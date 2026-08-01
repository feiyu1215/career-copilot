"""T1–T15 审计回归测试：端到端跑通真实的 run_pipeline。

为什么需要这个测试（审计发现的 CRITICAL bug）：
  修复前 smart_score.run_pipeline 在 Stage1→Stage2 边界写的是
      all_scored = await stage1(...)        # stage1 返回 (scored, stats) 2 元组
  未解包，导致下一步 `for j in all_scored` 对 2 元组迭代直接 TypeError，
  且 stage1_stats 永远为 None（最终输出统计全 0、degraded 失真）。
  单 stage 测试全绿却漏掉它，正是因为没有任何测试组装并运行真实 run_pipeline。

本测试用 fake stage1/stage2/calibration/rerank 替换真实 LLM 调用，
但 run_pipeline 的**组装逻辑（含解包）完全走真实代码**，因此能直接守住该回归：
  - 修复前：run_pipeline 在 Stage1 之后崩溃 → 本测试失败；
  - 修复后：返回完整 output，且 metadata.stage1_stats 被正确捕获（非全 0）。
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "scripts")

import smart_score  # noqa: E402


def _make_args(tmp: Path) -> SimpleNamespace:
    summary = tmp / "summary.txt"
    summary.write_text("候选人：5 年 AI 产品经验，做过推荐系统与用户增长。", encoding="utf-8")

    profile = tmp / "profile.json"
    profile.write_text(json.dumps({
        "role_type": "AI 产品",
        "direction_anchors": ["推荐系统", "增长"],
    }, ensure_ascii=False), encoding="utf-8")

    jobs = tmp / "jobs_raw.txt"
    jobs.write_text(
        "--- JOB 1 ---\n"
        "[URL]https://example.com/j1[/URL]\n"
        "高级产品经理 - 推荐系统\n"
        "北京 负责推荐策略。负责推荐系统的产品规划与迭代，对接搜索与推荐算法团队，设计召回与排序策略优化方案，"
        "通过 AB 实验持续验证 CTR 与转化率提升，沉淀可复用的推荐策略方法论，推动核心场景业务增长。"
        "要求 3 年以上推荐或增长产品经验，熟悉机器学习排序基础者优先。\n"
        "--- JOB 2 ---\n"
        "增长产品经理 - 增长\n"
        "上海 负责用户增长。负责用户增长产品策略，设计拉新与留存闭环，搭建增长实验体系，"
        "通过数据驱动验证增长 ROI，主导过完整增长链路从 0 到 1 建设。要求 3 年以上增长产品经验，"
        "熟悉 AARRR 模型与 AB 实验方法论者优先，有社区或电商增长实战背景者优先。\n"
        "--- JOB 3 ---\n"
        "前端工程师 - 研发\n"
        "深圳 负责前端开发。负责 Web 前端业务页面与交互实现，参与大型 ToC 产品前端架构设计，"
        "主导性能优化与组件库建设，保障亿级流量页面首屏体验。要求 3 年以上前端经验，"
        "精通 React/Vue 与工程化体系者优先，有首屏加载与渲染性能调优经验者优先。\n",
        encoding="utf-8",
    )

    output = tmp / "out" / "scored_results.json"
    return SimpleNamespace(
        summary=str(summary),
        profile=str(profile),
        jobs=str(jobs),
        top_k=2,
        output=str(output),
        stage1_model="fake",
        stage2_model="fake",
        concurrency=2,
        stage2_concurrency=2,
        provider="ollama",  # 本地 provider：构造期注入占位 key，无需真实凭据（阶段已 monkeypatch）
        resume=False,
        include_intern=False,
        include_outsource=False,
        max_year_requirement=10,
    )


async def _fake_stage1(client, candidate_summary, direction_anchor, jobs, progress=None, tracer=None):
    scored = []
    for j in jobs:
        is_pm = "产品" in j.get("title", "")
        scored.append({
            "job_id": j["job_id"],
            "title": j["title"],
            "stage1_score": 80 if is_pm else 40,
            "pre_filter_meta": {"direction_score": 1.0 if is_pm else 0.0},
        })
    stats = SimpleNamespace(
        total=len(jobs), succeeded=len(jobs), failed=0, fallback=0, failure_rate=0.0
    )
    return scored, stats


async def _fake_stage2(client, candidate_summary, domain_knowledge, calibration, profile, top_jobs, progress=None, tracer=None):
    analyzed = []
    for j in top_jobs:
        score = j.get("stage1_score", 50)
        analyzed.append({
            "job_id": j["job_id"],
            "title": j["title"],
            "score": score,
            "tier": "A" if score >= 70 else "C",
            "match_reasons": ["匹配方向"],
            "risks": [],
            "advice": "",
            "english_requirement": "",
            "is_core_team": False,
            "is_tech_strong": False,
            "global_rank": 1,
        })
    return analyzed, 0


async def _fake_calibration(client, profile, top_titles):
    return "calibration knowledge"


async def _fake_rerank(client, candidate_summary, calibration, profile, analyzed):
    return analyzed


def test_run_pipeline_e2e_unpack_and_stats_captured(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        args = _make_args(tmp)
        monkeypatch.setattr(smart_score, "stage1", _fake_stage1)
        monkeypatch.setattr(smart_score, "stage2", _fake_stage2)
        monkeypatch.setattr(smart_score, "generate_calibration_knowledge", _fake_calibration)
        monkeypatch.setattr(smart_score, "global_rerank", _fake_rerank)

        output = asyncio.run(smart_score.run_pipeline(args))

        # 1) 结构完整
        assert "recommendations" in output
        assert "metadata" in output

        # 2) Stage1 统计被正确捕获（修复前 stage1_stats 恒为 None → total=0）
        s1 = output["metadata"]["stage1_stats"]
        assert s1["total"] > 0, "stage1_stats 未被捕获（疑似解包回归）"
        assert s1["failed"] == 0
        assert s1["total"] == s1["succeeded"]

        # 3) 推荐非空，且按 top_k 截断
        recs = output["recommendations"]
        total_recs = len(recs["tier_A"]) + len(recs["tier_B"]) + len(recs["tier_C"])
        assert total_recs > 0
        assert total_recs <= args.top_k + len(recs["tier_C"])  # top_jobs 限 top_k，C 档来自 top_jobs

        # 4) 输出文件已落盘
        assert Path(args.output).exists()
        assert json.loads(Path(args.output).read_text(encoding="utf-8"))["summary"]["tier_A"] >= 0
