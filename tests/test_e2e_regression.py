#!/usr/bin/env python3
"""
test_e2e_regression.py — Phase 3.3 端到端回归测试（离线、无网络依赖）

设计目标
--------
本测试用**确定性 mock LLM** 跑真实的六阶段 `run_pipeline`，对以下“代码/逻辑层”做回归护栏：

1. 评分分布（tier_A/B/C 计数）—— 防止 post_judge / 分档阈值 / 重排逻辑被悄悄改坏；
2. top-3 推荐排序 —— 防止装配逻辑（stage1→stage2→rerank→post_judge）退化；
3. post_judge 惩罚项 —— 防止英语门槛 / 核心团队 / 技术依赖等确定性规则被误关。

与 3.1（Golden Cases 准确性评测）的分工（务必看清，避免误读护栏边界）：
- 3.1 用**真实 LLM** 验证「模型打分 vs 人工真值」的对齐度（ρ/R@10 门控，需 agnes/deepseek-v4-flash）。
- 本测试**离线**验证「管线代码逻辑」稳定。因为 mock 忽略提示词语义，所以它**故意对 prompts.yaml 的措辞改动鲁棒**
  —— 即：改文案不应让 CI 红。提示词→评分分布的语义漂移，由 3.1 准确性评测负责（需联网跑真 LLM）。
- 若未来改动确实要让分布变化（合理优化），应同步审慎更新 `regression_baseline.json` 快照，并在 MR 说明。

用法
----
    pytest tests/test_e2e_regression.py -q
    REGRESSION_RECORD=1 pytest tests/test_e2e_regression.py -q   # 重新录制快照基线
"""
import asyncio
import hashlib
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import smart_score  # noqa: E402

FIX = REPO / "tests" / "fixtures"
BASELINE_PATH = FIX / "regression_baseline.json"


def _score_for(title: str) -> int:
    """确定性、跨进程稳定（不依赖 PYTHONHASHSEED）的伪评分。

    同一 title 在 stage1 / stage2 / rerank 三处都调用，保证分数锚定一致，
    最终分 = stage1_score 被 rerank 钳制在 ±20 内（见 smart_score.global_rerank），
    因此最终 tier 由 _score_for(title) 稳定决定。
    """
    h = int.from_bytes(hashlib.md5(title.encode("utf-8")).digest()[:4], "big")
    return 40 + (h % 60)  # 40..99，覆盖 B/C 与部分 A


class _Sem:
    def __init__(self, v):
        self._value = v


class _DeterministicClient:
    """行为确定、无网络的 LLMClient 替身。

    按 user 文案路由到对应 stage，返回符合各 stage 解析合约的 JSON。
    关键点：所有分数都来自 _score_for(title)，与真实管线解耦但保持稳定。
    """

    def __init__(self, *a, **k):
        self.provider_name = "mock"
        self.model = k.get("model", "mock")
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.semaphore = _Sem(k.get("max_concurrent", 4))

    async def chat(self, system, user, temperature=0.0, max_tokens=150):
        self.total_input_tokens += len(system) + len(user)
        # 路由顺序很关键：
        # 1) rerank 的 user 含「请严格排出/全局顺序」——必须最先判，因为 rerank 的
        #    system 提示词也含「行业猎头」，若先判 system 会把 rerank 误送进 stage2，
        #    导致 rerank 解析失败、全部岗位落入 missing_ids 的 set 迭代分支（跨进程非确定）。
        # 2) stage1 由 system「求职匹配顾问」区分；3) stage2 由 system「行业猎头」区分；
        # 4) 校准（Stage 1.5）由 user「通过初筛」区分。
        if "请严格排出" in user or "全局顺序" in user:
            resp = self._rerank(user)
        elif "求职匹配顾问" in system:
            resp = self._stage1(user)
        elif "行业猎头" in system:
            resp = self._stage2(user)
        elif "通过初筛" in user:  # Stage 1.5 辨别知识
            resp = "calibration_knowledge"
        else:
            resp = "calibration_knowledge"
        self.total_output_tokens += len(resp)
        return resp

    def _stage1(self, user):
        m = re.search(r"\*\*标题\*\*：(.+)", user)
        title = m.group(1).strip() if m else "unknown"
        return json.dumps({"score": _score_for(title), "reasoning": "确定性回归"})

    def _stage2(self, user):
        rows = re.findall(r"### 岗位 \d+（(JOB_\d+)）\s*\*\*标题\*\*：(.+)", user)
        scored = sorted(rows, key=lambda r: -_score_for(r[1]))
        out = []
        for rank, (jid, title) in enumerate(scored, 1):
            s = _score_for(title)
            tier = "A" if s >= 90 else ("B" if s >= 75 else "C")
            out.append({
                "job_id": jid, "rank": rank, "tier": tier, "score": float(s),
                "match_reasons": ["匹配"], "risks": [], "advice": "",
            })
        return json.dumps(out, ensure_ascii=False)

    def _rerank(self, user):
        rows = re.findall(r"### \d+\. (.+)（(JOB_\d+)）", user)
        scored = sorted(rows, key=lambda r: -_score_for(r[0]))
        out = []
        for rank, (title, jid) in enumerate(scored, 1):
            out.append({
                "job_id": jid, "rank": rank,
                "score": float(_score_for(title)),
                "one_line_reason": "确定性回归",
            })
        return json.dumps(out, ensure_ascii=False)


def _build_args(tmp_path: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        summary=str(FIX / "regression_summary.txt"),
        profile=str(FIX / "regression_profile.json"),
        jobs=str(FIX / "regression_jobs.txt"),
        top_k=8,
        stage1_model="mock",
        stage2_model="mock",
        concurrency=4,
        provider=None,
        resume=False,
        output=str(tmp_path / "out.json"),
        include_intern=False,
        include_outsource=False,
        max_year_requirement=20,
        jd_trust_report=False,
        stage2_concurrency=2,
        suppress_summary_notify=True,
        behavior_profile=None,
        wecom=None,
    )


def _run(tmp_path: Path) -> dict:
    smart_score.LLMClient = lambda *a, **k: _DeterministicClient(*a, **k)
    return asyncio.run(smart_score.run_pipeline(_build_args(tmp_path)))


def _extract_top3(output: dict) -> list:
    recs = output["recommendations"]
    ordered = recs["tier_A"] + recs["tier_B"] + recs["tier_C"]
    return [j["job_id"] for j in ordered[:3]]


def test_e2e_regression_score_pipeline(tmp_path):
    output = _run(tmp_path)
    summary = output["summary"]
    pj = output["pipeline"]["post_judge"]
    top3 = _extract_top3(output)

    # ---- 结构性不变量（对合理改动鲁棒，对回归敏感）----
    total = summary["tier_A"] + summary["tier_B"] + summary["tier_C"]
    assert total == 8, f"应分析 8 个岗位，实际 {total}"

    c_ids = {j["job_id"] for j in output["recommendations"]["tier_C"]}
    assert not (set(top3) & c_ids), f"top3 不应含 C 档：{top3}"

    # fixture 刻意构造了「英语偏好(候选 basic)」+「核心团队(学历 medium)」两条惩罚
    assert pj["penalties_applied"] >= 2, \
        f"post_judge 惩罚数应≥2（英语偏好+核心团队），实际 {pj['penalties_applied']}"

    all_recs = (output["recommendations"]["tier_A"]
                + output["recommendations"]["tier_B"]
                + output["recommendations"]["tier_C"])
    assert all(j.get("job_id") for j in all_recs), "推荐项缺失 job_id"

    # ---- 快照基线（精确，需审慎更新）----
    baseline = {
        "tier_A": summary["tier_A"],
        "tier_B": summary["tier_B"],
        "tier_C": summary["tier_C"],
        "penalties_applied": pj["penalties_applied"],
        "top3": top3,
    }
    if os.environ.get("REGRESSION_RECORD"):
        BASELINE_PATH.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
        pytest.skip("已重新录制基线，请复核 regression_baseline.json 后重跑")

    assert BASELINE_PATH.exists(), \
        "基线文件缺失，请先 REGRESSION_RECORD=1 录制快照"
    expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline == expected, f"回归漂移：{baseline} != {expected}"
