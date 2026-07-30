#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_pipeline.py（2.1 Orchestrator）的离线测试。

全部用 mock 替代 LLM / 抓取，验证：
- dry-run 只跑 fetch+score 预览，不产出简历；
- 全链路产出 drafts / pdfs / report，并写入 job_tracker；
- 单岗位 draft 失败被隔离，不影响其余岗位与整体；
- --resume-from compile 复用已落盘草稿重编译，不重跑 draft。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS))

import run_pipeline  # noqa: E402
import generate_report  # noqa: E402

JOBS_RAW = """\
--- JOB 1 ---
[URL]https://example.com/j1[/URL]
字节跳动 - 推荐算法工程师
我们是字节，招聘推荐算法工程师，要求机器学习经验。

--- JOB 2 ---
[URL]https://example.com/j2[/URL]
腾讯 - 后端开发
腾讯招聘后端开发，要求分布式系统经验。
"""

CANNED_SCORED = {
    "recommendations": {
        "tier_A": [
            {"job_id": "JOB_1", "title": "字节跳动 - 推荐算法工程师",
             "score": 0.9, "reasons": ["匹配度高"], "risks": [],
             "url": "https://example.com/j1"},
            {"job_id": "JOB_2", "title": "腾讯 - 后端开发",
             "score": 0.8, "reasons": ["尚可"], "risks": ["竞争激烈"],
             "url": "https://example.com/j2"},
        ],
        "tier_B": [],
    }
}


def _opts(tmp_path, **kw):
    base = dict(
        summary=str(tmp_path / "summary.json"),
        profile=None,
        jobs=None,
        query=None,
        portals="config/portals.yaml",
        pages=3, max_jobs=0, seen=None,
        output=str(tmp_path / "out"),
        scored=None,
        template="cn-professional",
        name="张三", email="z@x.com", phone="13800000000",
        max_cv=3, top_k=20,
        stage1_model="gpt-4.1", stage2_model="gpt-4.1", provider="openai",
        concurrency=4, stage2_concurrency=2,
        webhook=None, report=None, store=None, source="pipeline",
        track=False, dry_run=False, resume_from=None, force=False,
        summary_only=False, jd_trust_report=None, no_calibration=False,
        max_year_requirement=None, include_intern=False, include_outsource=False,
        no_behavior_fit=False, bf_log=None, include_risk_levels=True,
    )
    base.update(kw)
    # summary / profile 文件需存在（dry-run / score 会读取）
    Path(base["summary"]).write_text(json.dumps({"role": "swe"}), encoding="utf-8")
    prof = base.get("profile") or str(tmp_path / "profile.json")
    base["profile"] = prof
    Path(prof).write_text(json.dumps({"name": "张三", "title": "SDE"}), encoding="utf-8")
    return SimpleNamespace(**base)


def _mock_deps(fail_draft_jid=None, draft_raises_on_call=False, fail_cover=False):
    calls = {"draft": 0, "build": 0, "cover_draft": 0, "build_cover": 0, "track": 0}

    async def fetch(opts, jobs_raw):
        Path(jobs_raw).write_text(JOBS_RAW, encoding="utf-8")
        return jobs_raw

    async def score(opts, jobs_raw, scored_out, tracer):
        # 动态按 jobs_raw 内容产出 scored（增量模式下只含新增岗位）
        jobs = run_pipeline._parse_jobs(Path(jobs_raw))
        rec = {"tier_A": [], "tier_B": []}
        for j in jobs:
            rec["tier_A"].append({
                "job_id": j["job_id"], "title": j.get("title", ""),
                "score": 0.9, "reasons": ["匹配"], "risks": [],
                "url": j.get("url", ""),
            })
        scored = {"recommendations": rec}
        scored_out = Path(scored_out)
        scored_out.parent.mkdir(parents=True, exist_ok=True)
        scored_out.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
        return scored

    async def draft(profile, jd_text, provider, job_id):
        calls["draft"] += 1
        if draft_raises_on_call:
            raise AssertionError("draft 不应在 resume 阶段被调用")
        if fail_draft_jid and job_id == fail_draft_jid:
            raise RuntimeError("mock draft failure")
        return {"draft": "\\section{教育背景}\n测试正文\n",
                "report": {"note": "ok"}}

    async def cover_draft(profile, jd_text, provider, job_id):
        calls["cover_draft"] += 1
        if fail_cover:
            raise RuntimeError("mock cover failure")
        return "尊敬的招聘负责人：\n第一段。\n第二段。\n第三段。\n此致 / 敬礼"

    def build(tex_path, pdf_path, template, name, email, phone):
        calls["build"] += 1
        Path(pdf_path).write_text("FAKE PDF", encoding="utf-8")
        return {"pdf": str(pdf_path), "engine": "lualatex",
                "failures": [], "warnings": [], "visual_issues": []}

    def build_cover(cover_path, pdf_path, name, email, phone):
        calls["build_cover"] += 1
        Path(pdf_path).write_text("FAKE COVER PDF", encoding="utf-8")
        return {"pdf": str(pdf_path), "engine": "lualatex",
                "failures": [], "warnings": [], "visual_issues": []}

    def track(store, meta, opts):
        calls["track"] += 1
        return calls["track"]

    def notify(title, message, webhook):
        return bool(webhook)

    def report(scored, profile, out_html, opts=None):
        Path(out_html).write_text("<html>report</html>", encoding="utf-8")
        return out_html

    return {"fetch": fetch, "score": score, "draft": draft, "build": build,
            "cover_draft": cover_draft, "build_cover": build_cover,
            "track": track, "notify": notify, "report": report, "_calls": calls}


def test_dry_run_only_fetch_and_score(tmp_path):
    deps = _mock_deps()
    opts = _opts(tmp_path, dry_run=True)
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    assert result["dry_run"] is True
    # dry-run 不产出任何简历
    assert result["drafts"] == {}
    assert result["selected"] == []
    # jobs_raw 已落盘，scored 预览不写文件
    assert Path(result["jobs_raw"]).exists()


def test_full_pipeline_produces_cv_and_report(tmp_path):
    deps = _mock_deps()
    opts = _opts(tmp_path, track=True, webhook="fakekey")
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    assert set(result["selected"]) == {"JOB_1", "JOB_2"}
    assert len(result["drafts"]) == 2
    for jid in ("JOB_1", "JOB_2"):
        d = result["drafts"][jid]
        assert d.get("pdf") and Path(d["pdf"]).exists(), f"{jid} 应有 PDF"
        assert not d.get("error")
    # 报告已生成
    assert result["report_html"] and Path(result["report_html"]).exists()
    # 两个岗位均入库
    assert len(result["tracked"]) == 2
    # 草稿 .tex 落盘
    assert (Path(result["jobs_raw"]).parent / "drafts" / "JOB_1.tex").exists()


def test_error_isolation_one_job_fails(tmp_path):
    deps = _mock_deps(fail_draft_jid="JOB_2")
    opts = _opts(tmp_path, track=True)
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    # JOB_1 成功
    assert result["drafts"]["JOB_1"].get("pdf") and not result["drafts"]["JOB_1"].get("error")
    # JOB_2 被隔离：记录错误、无 PDF、不入库
    assert "draft" in (result["drafts"]["JOB_2"].get("error") or "")
    assert not result["drafts"]["JOB_2"].get("pdf")
    # 仅 JOB_1 入库
    assert result["tracked"] == [1]


def test_resume_from_compile_reuses_drafts(tmp_path):
    # 第一次：正常跑完，产出草稿 + PDF
    deps = _mock_deps()
    opts = _opts(tmp_path)
    first = asyncio.run(run_pipeline.run_pipeline(opts, deps))
    assert len(first["drafts"]) == 2

    # 删掉 PDF，模拟"改模板后只重编译"
    cv_dir = Path(first["jobs_raw"]).parent / "cv"
    for p in cv_dir.glob("*.pdf"):
        p.unlink()

    # 第二次用会抛错的 draft 依赖，证明 resume 阶段未重跑 draft
    deps2 = _mock_deps(draft_raises_on_call=True)
    opts2 = _opts(tmp_path, resume_from="compile")
    second = asyncio.run(run_pipeline.run_pipeline(opts2, deps2))
    # 两个 PDF 均由已落盘草稿重编译生成
    assert (cv_dir / "JOB_1.pdf").exists() and (cv_dir / "JOB_2.pdf").exists()
    assert second["drafts"]["JOB_1"].get("pdf") and second["drafts"]["JOB_2"].get("pdf")


def test_resume_without_scored_raises(tmp_path):
    # 没有任何 scored_results.json 且 resume 早于 score → 应报错
    opts = _opts(tmp_path, resume_from="compile")
    with pytest.raises(RuntimeError):
        asyncio.run(run_pipeline.run_pipeline(opts, _mock_deps()))


# ---------------------------------------------------------------------------
# 1.2 求职信（cover letter）
# ---------------------------------------------------------------------------

def test_cover_letter_one_click(tmp_path):
    deps = _mock_deps()
    opts = _opts(tmp_path, cover_letter=True)
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    # 简历 + 求职信均产出
    assert deps["_calls"]["cover_draft"] == 2
    assert deps["_calls"]["build_cover"] == 2
    for jid in ("JOB_1", "JOB_2"):
        cl = result["cover_letters"][jid]
        assert cl["tex"] and Path(cl["tex"]).exists(), f"{jid} 求职信草稿应存在"
        assert cl["pdf"] and Path(cl["pdf"]).exists(), f"{jid} 求职信 PDF 应存在"
    # 草稿与 PDF 落盘命名
    assert (Path(result["jobs_raw"]).parent / "drafts" / "JOB_1.cover.tex").exists()
    assert (Path(result["jobs_raw"]).parent / "cv" / "JOB_1.cover.pdf").exists()


def test_cover_letter_failure_isolated(tmp_path):
    deps = _mock_deps(fail_cover=True)
    opts = _opts(tmp_path, cover_letter=True)
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    # 简历不受求职信失败影响
    assert result["drafts"]["JOB_1"].get("pdf") and not result["drafts"]["JOB_1"].get("error")
    # 求职信失败被隔离：记录错误、无 PDF
    cl = result["cover_letters"]["JOB_1"]
    assert cl["error"] and "cover" in cl["error"].lower()
    assert not cl.get("pdf")


# ---------------------------------------------------------------------------
# 2.2 增量模式（incremental）
# ---------------------------------------------------------------------------

BASELINE_JOBS_RAW = """\
--- JOB 1 ---
[URL]https://example.com/j1[/URL]
字节跳动 - 推荐算法工程师
我们是字节，招聘推荐算法工程师，要求机器学习经验。
"""


def test_incremental_only_processes_new_jobs(tmp_path):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE_JOBS_RAW, encoding="utf-8")  # 仅 JOB_1
    deps = _mock_deps()
    opts = _opts(tmp_path, incremental=True, baseline=str(baseline))
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    # 仅 JOB_2 为新增
    assert result["new_job_ids"] == ["JOB_2"]
    assert result["selected"] == ["JOB_2"]
    # draft/compile 只跑了新岗位
    assert deps["_calls"]["draft"] == 1
    assert deps["_calls"]["build"] == 1
    # baseline 已刷新为全量（JOB_1 + JOB_2）
    refreshed = run_pipeline._parse_jobs(baseline)
    assert {j["job_id"] for j in refreshed} == {"JOB_1", "JOB_2"}


def test_incremental_no_new_reuses_accumulated(tmp_path):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(JOBS_RAW, encoding="utf-8")  # 与 fetch 产出相同
    # 先全量跑一次，建立累计 scored
    first = asyncio.run(run_pipeline.run_pipeline(_opts(tmp_path), _mock_deps()))
    assert set(first["selected"]) == {"JOB_1", "JOB_2"}
    # 再增量跑（baseline == current，无新增）
    deps2 = _mock_deps()
    opts2 = _opts(tmp_path, incremental=True, baseline=str(baseline))
    second = asyncio.run(run_pipeline.run_pipeline(opts2, deps2))
    assert second["new_job_ids"] == []
    # 跳过 score/draft/compile
    assert deps2["_calls"]["draft"] == 0
    assert deps2["_calls"]["build"] == 0
    # 累计 scored 仍可用
    assert set(second["selected"]) == {"JOB_1", "JOB_2"}


# ---------------------------------------------------------------------------
# Phase 9.2：周报贯通三智能段（竞争力 / 趋势 / 漏斗）
# ---------------------------------------------------------------------------

def test_report_stage_threads_three_intelligence_sections(tmp_path, monkeypatch):
    """默认 report dep 应在给定 store 时把三智能段透传给 generate_html。"""
    captured = {}

    def fake_generate_html(data, profile, decision_context=None, history_funnel=None,
                           trend_html=None, now=None, comp_html=None):
        captured["history_funnel"] = history_funnel
        captured["trend_html"] = trend_html
        captured["comp_html"] = comp_html
        return "<html>report</html>"

    monkeypatch.setattr(generate_report, "generate_html", fake_generate_html)
    # 竞争力段用 patch 后的渲染（避免真实 store 读取）
    monkeypatch.setattr(generate_report, "render_competitiveness_section",
                        lambda store, cl=None, provider=None: "<div>comp</div>")

    # 懒加载的三段 loader 用假模块顶替
    import types
    fake_cal = types.ModuleType("calibration_feedback")
    fake_cal.compute_tier_funnel = lambda apps: {"rows": [], "total_reached": 0}
    fake_cal.load_applications = lambda p: []
    monkeypatch.setitem(sys.modules, "calibration_feedback", fake_cal)

    fake_trend = types.ModuleType("trend_analyzer")
    fake_trend.load_store = lambda p: {}
    fake_trend.analyze_trend = lambda s: {}
    fake_trend.render_trend_html = lambda t: "<div>trend</div>"
    monkeypatch.setitem(sys.modules, "trend_analyzer", fake_trend)

    deps = run_pipeline._default_deps()
    opts = SimpleNamespace(
        competitiveness_store="c.json", trend_store="t.json", history_store="h.json",
        competitiveness_provider="agnes",
    )
    scored = {"recommendations": {"tier_A": [], "tier_B": []},
              "summary": {}, "pipeline": {}, "generated_at": ""}
    out = str(tmp_path / "report.html")
    deps["report"](scored, {}, out, opts)

    assert captured["history_funnel"] is not None
    assert captured["trend_html"] is not None
    assert captured["comp_html"] is not None


def test_report_stage_no_stores_keeps_compat(tmp_path, monkeypatch):
    """不传任何 store 时，report dep 行为与旧版一致（三段均为 None，不报错）。"""
    captured = {}

    def fake_generate_html(data, profile, decision_context=None, history_funnel=None,
                           trend_html=None, now=None, comp_html=None):
        captured["history_funnel"] = history_funnel
        captured["trend_html"] = trend_html
        captured["comp_html"] = comp_html
        return "<html>report</html>"

    monkeypatch.setattr(generate_report, "generate_html", fake_generate_html)
    deps = run_pipeline._default_deps()
    opts = SimpleNamespace()
    scored = {"recommendations": {"tier_A": [], "tier_B": []},
              "summary": {}, "pipeline": {}, "generated_at": ""}
    out = str(tmp_path / "report.html")
    deps["report"](scored, {}, out, opts)

    assert captured["history_funnel"] is None
    assert captured["trend_html"] is None
    assert captured["comp_html"] is None


def test_incremental_marks_is_new_and_merges(tmp_path):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE_JOBS_RAW, encoding="utf-8")  # 仅 JOB_1
    deps = _mock_deps()
    opts = _opts(tmp_path, incremental=True, baseline=str(baseline))
    result = asyncio.run(run_pipeline.run_pipeline(opts, deps))

    scored = run_pipeline._load_json(result["scored"])
    ids = {j["job_id"]: j for j in scored["recommendations"]["tier_A"]}
    assert "JOB_2" in ids
    assert ids["JOB_2"].get("is_new") is True
