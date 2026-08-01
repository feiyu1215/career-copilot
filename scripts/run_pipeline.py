#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline.py — 2.1 端到端求职编排器（体验质变点）

把分散的单点脚本串成一条「可恢复 / 可预览 / 可容错」的流水线：

    fetch → score → draft → compile → verify → track → notify → report

设计要点（对齐升级计划 2.1）：
- 单岗位隔离：draft/compile 阶段每个岗位独立 try/except，单岗位失败不影响整体。
- --dry-run：仅跑 fetch + score（smart_score.dry_run 预览成本），不产出任何简历。
- --resume-from <stage>：从指定阶段续跑；前序产物已落盘（scored_results.json /
  drafts/*.tex / cv/*.pdf）可直接复用，幂等跳过已存在产物。
- 注入式 deps：score / draft / fetch / build / track / notify / report 均可被覆盖，
  便于离线测试（mock LLM / mock 抓取）而无需真实网关。
- 全程结构化 result 返回，供测试 / 监控消费；每阶段打印进度。

用法示例：
    python scripts/run_pipeline.py \\
        --summary config/boundary_profile.json \\
        --profile  config/career_profile.json \\
        --jobs     data/jobs_raw.txt \\
        --template cn-professional \\
        --name "张三" --email z@x.com --phone 13800000000 \\
        --max-cv 3 --output pipeline_out

    # 仅预览成本，不产出简历
    python scripts/run_pipeline.py --summary ... --profile ... --jobs ... --dry-run

    # 改了模板后只重编译
    python scripts/run_pipeline.py ... --resume-from compile --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from job_common import quality_gate  # Phase 4.3 抓取结果质量守门  # noqa: E402

# 复用 smart_score 既有的 trace 工具
try:
    from trace import ExecutionTracer
except Exception:  # pragma: no cover - 兜底，正常应走 trace 模块
    ExecutionTracer = None  # type: ignore

# 阶段顺序（也是 resume 的索引依据）
STAGES = ["fetch", "score", "draft", "compile", "verify", "track", "notify", "report"]


def _stage_index(name: str) -> int:
    if name not in STAGES:
        raise ValueError(f"未知阶段 {name!r}，可选：{', '.join(STAGES)}")
    return STAGES.index(name)


# ---------------------------------------------------------------------------
# 依赖注入（默认调用真实脚本；测试可整体覆盖）
# ---------------------------------------------------------------------------

def _build_score_args(opts, jobs_raw: Path, scored_out: Path) -> SimpleNamespace:
    """构造喂给 smart_score.run_pipeline 的 args 命名空间。"""
    return SimpleNamespace(
        summary=opts.summary,
        profile=opts.profile,
        jobs=str(jobs_raw),
        output=str(scored_out),
        top_k=getattr(opts, "top_k", 20),
        stage1_model=getattr(opts, "stage1_model", "gpt-4.1"),
        stage2_model=getattr(opts, "stage2_model", "gpt-4.1"),
        concurrency=getattr(opts, "concurrency", 4),
        stage2_concurrency=getattr(opts, "stage2_concurrency", 2),
        provider=getattr(opts, "provider", "openai"),
        summary_only=getattr(opts, "summary_only", False),
        jd_trust_report=getattr(opts, "jd_trust_report", None),
        no_calibration=getattr(opts, "no_calibration", False),
        max_year_requirement=getattr(opts, "max_year_requirement", None),
        include_intern=getattr(opts, "include_intern", False),
        include_outsource=getattr(opts, "include_outsource", False),
        behavior_fit=getattr(opts, "behavior_fit", True),
        no_behavior_fit=getattr(opts, "no_behavior_fit", False),
        bf_log=getattr(opts, "bf_log", None),
        webhook=getattr(opts, "webhook", None),
        include_risk_levels=getattr(opts, "include_risk_levels", True),
    )


def _default_deps():
    """返回默认（真实）依赖实现。"""
    import batch_fetch
    import build_cv
    import generate_report
    import job_tracker
    import notify_wecom
    import smart_score
    from drafter_reviewer import DrafterReviewer

    async def fetch(opts, jobs_raw: Path):
        if getattr(opts, "jobs", None):
            src = Path(opts.jobs).resolve()
            if src != jobs_raw.resolve():
                shutil.copy(src, jobs_raw)
            return jobs_raw
        # 真实抓取：按 portals.yaml 启用的源抓取并写出 jobs_raw 格式
        batch_fetch.batch_fetch(
            getattr(opts, "query", ""),
            getattr(opts, "portals", "config/portals.yaml"),
            str(jobs_raw),
            getattr(opts, "pages", 3),
            getattr(opts, "max_jobs", 0),
            getattr(opts, "concurrency", 4),
            getattr(opts, "seen", None),
            quality_gate_enabled=not getattr(opts, "no_quality_gate", False),
        )
        return jobs_raw

    async def score(opts, jobs_raw: Path, scored_out: Path, tracer):
        args = _build_score_args(opts, jobs_raw, scored_out)
        if tracer is None:
            tracer = ExecutionTracer(output_dir=str(Path(scored_out).parent / ".traces"))
        return await smart_score.run_pipeline(args, tracer)

    async def draft(profile: dict, jd_text: str, provider: str, job_id: str):
        return await DrafterReviewer(provider).revise(profile, jd_text)

    def build(draft_path: Path, pdf_path: Path, template, name, email, phone):
        return build_cv.build(
            str(draft_path), str(pdf_path),
            template=template, name=name, email=email, phone=phone,
        )

    async def cover_draft(profile: dict, jd_text: str, provider: str, job_id: str):
        return await DrafterReviewer(provider).cover_draft(profile, jd_text)

    def build_cover(cover_path: Path, pdf_path: Path, name, email, phone):
        return build_cv.build_cover(
            str(cover_path), str(pdf_path),
            name=name, email=email, phone=phone,
        )

    def track(store, job_meta: dict, opts):
        ns = SimpleNamespace(
            company=job_meta.get("company", ""),
            role=job_meta.get("role", ""),
            url=job_meta.get("url", ""),
            source=job_meta.get("source", "pipeline"),
            tier=job_meta.get("tier", ""),
            score=job_meta.get("score"),
            reasons=",".join(_as_list(job_meta.get("reasons"))),
            risks=",".join(_as_list(job_meta.get("risks"))),
            wecom=None,
        )
        return job_tracker.cmd_add(ns, store)

    def notify(title: str, message: str, webhook):
        return notify_wecom.notify(title, message, webhook)

    def report(scored: dict, profile: dict, out_html: Path, opts=None):
        # Phase 9.2：贯通三智能段。store 优先取显式参数，竞争力段缺省回退
        # CAREER_COMPETITIVENESS_STORE 环境变量；provider 缺省时若 LLM_PROVIDER=agnes 则自动启用。
        cs = getattr(opts, "competitiveness_store", None) or os.environ.get("CAREER_COMPETITIVENESS_STORE")
        ts = getattr(opts, "trend_store", None)
        hs = getattr(opts, "history_store", None)
        provider = getattr(opts, "competitiveness_provider", None)
        if not provider and os.environ.get("LLM_PROVIDER", "") == "agnes":
            provider = "agnes"
        history_funnel, trend_html, comp_html = generate_report.build_optional_sections(
            history_store=hs, trend_store=ts, competitiveness_store=cs,
            competitiveness_provider=provider, career_log_path=getattr(opts, "career_log", None),
            now=datetime.now())
        html = generate_report.generate_html(
            scored, profile, history_funnel=history_funnel, trend_html=trend_html,
            comp_html=comp_html, now=datetime.now())
        Path(out_html).write_text(html, encoding="utf-8")
        return out_html

    return {
        "fetch": fetch,
        "score": score,
        "draft": draft,
        "build": build,
        "cover_draft": cover_draft,
        "build_cover": build_cover,
        "track": track,
        "notify": notify,
        "report": report,
    }


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def _derive_company_role(job: dict):
    title = job.get("title", "") or ""
    if " - " in title:
        company, role = title.split(" - ", 1)
    else:
        company, role = "", title
    return company.strip(), role.strip()


# ---------------------------------------------------------------------------
# 阶段实现
# ---------------------------------------------------------------------------

def _selected_jobs(scored: dict, max_cv: int) -> list:
    rec = scored.get("recommendations", {}) or {}
    pool = list(rec.get("tier_A", []) or []) + list(rec.get("tier_B", []) or [])
    return pool[: max_cv]


async def _stage_fetch(opts, deps, state, start_idx):
    if _stage_index("fetch") < start_idx:
        print("[fetch] 跳过（resume）")
        return
    print("[fetch] 准备 jobs_raw ...")
    state["jobs_raw"] = await deps["fetch"](opts, state["jobs_raw"])
    print(f"[fetch] jobs_raw -> {state['jobs_raw']}")


async def _stage_score(opts, deps, state, start_idx, tracer, dry_run: bool):
    if _stage_index("score") < start_idx and state["scored"] is not None:
        print("[score] 跳过（resume，复用已有 scored_results.json）")
        return
    if dry_run:
        print("[score] dry-run 预览成本（不产出简历）...")
        import smart_score
        args = _build_score_args(opts, state["jobs_raw"], state["scored_out"])
        smart_score.dry_run(args)
        return
    print("[score] 运行 smart_score 主流程 ...")
    out = await deps["score"](opts, state["jobs_raw"], state["scored_out"], tracer)
    state["scored"] = out
    print(f"[score] 完成 -> {state['scored_out']} "
          f"(tier_A={len(out.get('recommendations', {}).get('tier_A', []))}, "
          f"tier_B={len(out.get('recommendations', {}).get('tier_B', []))})")


async def _stage_draft(opts, deps, state, start_idx):
    if _stage_index("draft") < start_idx:
        print("[draft] 跳过（resume）")
        return
    selected = state["selected"]
    lookup = state["jobs_lookup"]
    provider = getattr(opts, "provider", "openai")
    print(f"[draft] 为 {len(selected)} 个岗位生成定制简历 ...")
    for job in selected:
        jid = job.get("job_id")
        tex_path = state["draft_dir"] / f"{jid}.tex"
        entry = state["drafts"].setdefault(jid, {})
        if tex_path.exists() and not getattr(opts, "force", False):
            print(f"  - {jid}: 复用已有草稿 {tex_path.name}")
            entry["tex"] = str(tex_path)
            continue
        jd = lookup.get(jid)
        if not jd or not jd.get("full_text"):
            entry["error"] = "缺少 JD 文本（jobs_raw 中无该 job_id 或 full_text 为空）"
            print(f"  - {jid}: 跳过（{entry['error']}）")
            continue
        try:
            res = await deps["draft"](state["profile"], jd["full_text"], provider, jid)
            tex = res.get("draft", "")
            if not tex.strip():
                raise ValueError("drafter 返回空草稿")
            tex_path.write_text(tex, encoding="utf-8")
            entry["tex"] = str(tex_path)
            entry["draft_report"] = res.get("report")
            print(f"  - {jid}: 草稿 -> {tex_path.name}")
        except Exception as e:  # 单岗位隔离
            entry["error"] = f"draft 失败: {e}"
            print(f"  - {jid}: draft 失败: {e}")
            continue
        # 求职信（可选，独立错误隔离）
        if getattr(opts, "cover_letter", False) and "cover_draft" in deps:
            cover_path = state["draft_dir"] / f"{jid}.cover.tex"
            if cover_path.exists() and not getattr(opts, "force", False):
                print(f"  - {jid}: 复用已有求职信 {cover_path.name}")
                entry["cover_tex"] = str(cover_path)
                continue
            try:
                cover = await deps["cover_draft"](state["profile"], jd["full_text"], provider, jid)
                cover_path.write_text(cover, encoding="utf-8")
                entry["cover_tex"] = str(cover_path)
                # 字数检查（warning 级，不阻断）
                from drafter_reviewer import check_cover_letter_length
                cover_warns = check_cover_letter_length(cover)
                if cover_warns:
                    entry.setdefault("warnings", []).extend(cover_warns)
                    print(f"  - {jid}: 求职信提示: {'; '.join(cover_warns)}")
                else:
                    print(f"  - {jid}: 求职信 -> {cover_path.name}")
            except Exception as e:  # 求职信失败不影响简历
                entry["cover_error"] = f"cover_draft 失败: {e}"
                print(f"  - {jid}: cover_draft 失败（不影响简历）: {e}")


async def _stage_compile(opts, deps, state, start_idx):
    if _stage_index("compile") < start_idx:
        print("[compile] 跳过（resume）")
        return
    template = getattr(opts, "template", "cn-professional")
    name = getattr(opts, "name", None)
    email = getattr(opts, "email", None)
    phone = getattr(opts, "phone", None)
    print(f"[compile] 编译模板={template} ...")
    for jid, entry in state["drafts"].items():
        if entry.get("error"):
            continue
        tex_path = Path(entry["tex"])
        pdf_path = state["cv_dir"] / f"{jid}.pdf"
        if pdf_path.exists() and not getattr(opts, "force", False):
            print(f"  - {jid}: 复用已有 PDF {pdf_path.name}")
            entry["pdf"] = str(pdf_path)
            entry.setdefault("build", {"failures": [], "warnings": []})
            continue
        try:
            res = deps["build"](tex_path, pdf_path, template, name, email, phone)
            entry["pdf"] = str(pdf_path)
            entry["build"] = res
            fails = res.get("failures") or []
            warns = res.get("warnings") or []
            flag = "OK" if not fails else "FAIL"
            print(f"  - {jid}: {flag} (硬失败={len(fails)}, 视觉告警={len(warns)}) -> {pdf_path.name}")
        except Exception as e:  # 单岗位隔离
            entry["error"] = f"compile 失败: {e}"
            print(f"  - {jid}: compile 失败: {e}")
        # 求职信编译（若本岗位有 cover_tex）
        if getattr(opts, "cover_letter", False) and entry.get("cover_tex") \
                and "build_cover" in deps and not entry.get("error"):
            cover_tex = Path(entry["cover_tex"])
            cover_pdf = state["cv_dir"] / f"{jid}.cover.pdf"
            if cover_pdf.exists() and not getattr(opts, "force", False):
                entry["cover_pdf"] = str(cover_pdf)
                print(f"  - {jid}: 复用已有求职信 PDF {cover_pdf.name}")
                continue
            try:
                cres = deps["build_cover"](cover_tex, cover_pdf, name, email, phone)
                entry["cover_pdf"] = str(cover_pdf)
                entry["cover_build"] = cres
                cfails = cres.get("failures") or []
                cwarns = cres.get("warnings") or []
                cflag = "OK" if not cfails else "FAIL"
                print(f"  - {jid}: 求职信 {cflag} (硬失败={len(cfails)}, 告警={len(cwarns)}) -> {cover_pdf.name}")
            except Exception as e:  # 求职信失败不影响简历
                entry["cover_error"] = f"cover 编译失败: {e}"
                print(f"  - {jid}: cover 编译失败（不影响简历）: {e}")


async def _stage_verify(opts, deps, state, start_idx):
    # verify 已并入 compile（build_cv.build 返回 failures/warnings）
    if _stage_index("verify") < start_idx:
        return
    n_fail = sum(1 for e in state["drafts"].values()
                 if e.get("build") and (e["build"].get("failures")))
    n_warn = sum(1 for e in state["drafts"].values()
                 if e.get("build") and (e["build"].get("warnings")))
    print(f"[verify] 硬失败岗位数={n_fail}, 视觉告警岗位数={n_warn}")


async def _stage_track(opts, deps, state, start_idx):
    if _stage_index("track") < start_idx:
        return
    if not getattr(opts, "track", False):
        print("[track] 跳过（未启用 --track）")
        return
    import job_tracker as _jt
    store = getattr(opts, "store", None) or _jt.DEFAULT_STORE
    source = getattr(opts, "source", "pipeline")
    added = []
    for job in state["selected"]:
        jid = job.get("job_id")
        entry = state["drafts"].get(jid, {})
        if entry.get("error") or not entry.get("pdf"):
            continue  # 没产出简历就不入库
        company, role = _derive_company_role(job)
        meta = {
            "company": company,
            "role": role,
            "url": job.get("url", ""),
            "source": source,
            "tier": job.get("tier", "A"),
            "score": job.get("score"),
            "reasons": job.get("reasons", []),
            "risks": job.get("risks", []),
            "cv_pdf": entry.get("pdf"),
        }
        try:
            rid = deps["track"](store, meta, opts)
            added.append(rid)
            print(f"  - {jid}: 入库 job #{rid} ({company} / {role})")
        except Exception as e:
            print(f"  - {jid}: track 失败: {e}")
    state["tracked"] = added


async def _stage_notify(opts, deps, state, start_idx):
    if _stage_index("notify") < start_idx:
        return
    webhook = getattr(opts, "webhook", None)
    if not webhook:
        print("[notify] 跳过（无 --webhook）")
        return
    n_ok = sum(1 for e in state["drafts"].values() if e.get("pdf") and not e.get("error"))
    n_err = sum(1 for e in state["drafts"].values() if e.get("error"))
    msg = (f"产出简历 {n_ok} 份，失败 {n_err} 份；"
           f"报告：{state.get('report_html') or '(未生成)'}")
    ok = deps["notify"]("career-copilot 流水线完成", msg, webhook)
    print(f"[notify] {'已推送' if ok else '推送跳过/失败'}")


async def _stage_report(opts, deps, state, start_idx):
    if _stage_index("report") < start_idx:
        return
    if state["scored"] is None:
        print("[report] 跳过（无 scored 结果）")
        return
    out_html = state["report_html"]
    try:
        deps["report"](state["scored"], state["profile"], out_html, opts)
        state["report_html"] = str(out_html)
        print(f"[report] 生成 -> {out_html}")
    except Exception as e:
        print(f"[report] 失败: {e}")


# ---------------------------------------------------------------------------
# 主编排
# ---------------------------------------------------------------------------

async def run_pipeline(opts, deps=None) -> dict:
    deps = deps or _default_deps()
    dry_run = getattr(opts, "dry_run", False)
    resume_from = getattr(opts, "resume_from", None)
    start_idx = _stage_index(resume_from) if resume_from else 0

    out_dir = Path(getattr(opts, "output", "pipeline_out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_raw = out_dir / "jobs_raw.txt"
    scored_out = Path(opts.scored or str(out_dir / "scored_results.json"))
    draft_dir = out_dir / "drafts"
    cv_dir = out_dir / "cv"
    draft_dir.mkdir(exist_ok=True)
    cv_dir.mkdir(exist_ok=True)
    report_html = Path(opts.report or str(out_dir / "report.html"))

    # 读取 profile（draft 阶段需要）
    profile = _load_json(getattr(opts, "profile", None)) or {}

    # 复用已落盘产物（支持 resume）
    scored = None
    if scored_out.exists():
        try:
            scored = json.loads(scored_out.read_text(encoding="utf-8"))
        except Exception:
            scored = None
    jobs_lookup = {}
    if jobs_raw.exists():
        try:
            jobs_lookup = {j["job_id"]: j for j in _parse_jobs(jobs_raw)}
        except Exception:
            jobs_lookup = {}

    tracer = ExecutionTracer(output_dir=str(out_dir / ".traces")) if ExecutionTracer else None

    # 复用已落盘草稿/PDF（支持 --resume-from 跳过前序阶段）
    drafts_on_disk: dict[str, dict] = {}
    for p in draft_dir.glob("*.tex"):
        drafts_on_disk.setdefault(p.stem, {})["tex"] = str(p)
    for p in cv_dir.glob("*.pdf"):
        drafts_on_disk.setdefault(p.stem, {})["pdf"] = str(p)

    state = {
        "jobs_raw": jobs_raw,
        "full_jobs_raw": jobs_raw,
        "scored_out": scored_out,
        "scored": scored,
        "jobs_lookup": jobs_lookup,
        "profile": profile,
        "draft_dir": draft_dir,
        "cv_dir": cv_dir,
        "report_html": report_html,
        "selected": [],
        "drafts": drafts_on_disk,
        "tracked": [],
        "new_job_ids": set(),
        "no_new": False,
    }

    t0 = time.time()
    print(f"== career-copilot 流水线启动（dry_run={dry_run}, resume_from={resume_from or '开头'}）==")

    await _stage_fetch(opts, deps, state, start_idx)

    # fetch 之后才解析 jobs_raw（fetch 阶段才写出文件）
    if state["jobs_raw"].exists():
        try:
            state["jobs_lookup"] = {j["job_id"]: j for j in _parse_jobs(state["jobs_raw"])}
        except Exception:
            state["jobs_lookup"] = {}

    # Phase 8.3：记录本轮全量岗位首见时间（first_seen_at），供报告时机建议
    _record_first_seen(opts, state)

    # Phase 4.3 质量门禁：fetch 之后、score 之前断言抓取质量；
    # 未达门限则整批中止（不继续烧 LLM 评分预算）——CI 门禁语义。
    quality_gate_check(opts, state["jobs_raw"])

    # 增量模式：与 baseline 比对，仅处理新增岗位
    if getattr(opts, "incremental", False) and not dry_run:
        _incremental_setup(opts, state)

    if not dry_run:
        # score 阶段（dry_run 在 score 内特殊处理）
        if _stage_index("score") < start_idx and state["scored"] is None:
            raise RuntimeError("resume-from 早于 score，但 scored_results.json 不存在，无法续跑")

        if state.get("no_new"):
            # 增量且无新增：跳过 score/draft/compile，仅用累计 scored 出报告
            if state["scored"] is None and scored_out.exists():
                state["scored"] = json.loads(scored_out.read_text(encoding="utf-8"))
            state["scored"] = _strip_is_new(state["scored"])
            # Phase 8.3：注入首见时间（保留累计 scored 中已持久化的首见时间）
            if state.get("first_seen_map"):
                state["scored"] = _apply_first_seen(state["scored"], state["first_seen_map"])
            state["selected"] = _selected_jobs(state["scored"] or {}, getattr(opts, "max_cv", 3))
            print(f"[incremental] 无新增岗位，跳过 score/draft/compile（累计 {len(state['selected'])} 个）")
        else:
            prev_scored = state["scored"]  # 增量模式累计 scored（合并前）
            await _stage_score(opts, deps, state, start_idx, tracer, dry_run)
            # 增量合并：把本次新 scored 并入累计 scored，并打 is_new 标记
            if getattr(opts, "incremental", False):
                new_scored = state["scored"]
                merged = _merge_scored(prev_scored, new_scored, state.get("new_job_ids", set()))
                scored_out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
                state["scored"] = merged

            # 选取目标岗位
            if state["scored"] is None and scored_out.exists():
                state["scored"] = json.loads(scored_out.read_text(encoding="utf-8"))
            # Phase 8.3：注入首见时间到 scored
            if state.get("first_seen_map"):
                state["scored"] = _apply_first_seen(state["scored"], state["first_seen_map"])
            state["selected"] = _selected_jobs(state["scored"] or {}, getattr(opts, "max_cv", 3))
            print(f"[select] 选定 {len(state['selected'])} 个岗位（max_cv={getattr(opts, 'max_cv', 3)}）")

            await _stage_draft(opts, deps, state, start_idx)
            await _stage_compile(opts, deps, state, start_idx)
            await _stage_verify(opts, deps, state, start_idx)
            await _stage_track(opts, deps, state, start_idx)
            await _stage_notify(opts, deps, state, start_idx)
            await _stage_report(opts, deps, state, start_idx)
    else:
        # dry-run：仍跑 score 的预览（_stage_score 内部按 dry_run 分支）
        await _stage_score(opts, deps, state, start_idx, tracer, dry_run)

    # 增量模式：用本次全量 jobs_raw 刷新 baseline，供下次比对
    if getattr(opts, "incremental", False) and not dry_run and state.get("full_jobs_raw"):
        _update_baseline(opts, state)

    elapsed = round(time.time() - t0, 1)
    result = {
        "dry_run": dry_run,
        "resume_from": resume_from,
        "elapsed_seconds": elapsed,
        "jobs_raw": str(state["jobs_raw"]),
        "scored": str(state["scored_out"]),
        "selected": [j.get("job_id") for j in state["selected"]],
        "drafts": {jid: _json_safe_draft(e) for jid, e in state["drafts"].items()},
        "cover_letters": {
            jid: {"tex": e.get("cover_tex"), "pdf": e.get("cover_pdf"),
                  "error": e.get("cover_error")}
            for jid, e in state["drafts"].items()
            if e.get("cover_tex") or e.get("cover_pdf") or e.get("cover_error")
        },
        "new_job_ids": sorted(state.get("new_job_ids", set())),
        "tracked": state["tracked"],
        "report_html": str(state.get("report_html")) if state.get("report_html") else None,
    }
    print(f"== 流水线结束（耗时 {elapsed}s）==")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _json_safe_draft(e: dict) -> dict:
    """把单岗位草稿记录转换成可 JSON 序列化的字典（build 结果可能含 Path）。"""
    d = {k: v for k, v in e.items() if k != "draft_report"}
    if isinstance(d.get("pdf"), Path):
        d["pdf"] = str(d["pdf"])
    if isinstance(d.get("tex"), Path):
        d["tex"] = str(d["tex"])
    b = d.get("build")
    if isinstance(b, dict) and isinstance(b.get("pdf"), Path):
        b["pdf"] = str(b["pdf"])
    return d


def _load_json(path):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_jobs(jobs_raw: Path):
    import smart_score
    return smart_score.parse_jobs_raw(str(jobs_raw))


# ---------------------------------------------------------------------------
# Phase 4.3 抓取结果质量守门（跑批 / CI 门禁）
# ---------------------------------------------------------------------------

def _write_qg_report(path: str, gate_result: dict, source: str = "pipeline") -> None:
    """把质量守门报告写成 JSON（供 CI / 复盘读取）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({
            "source": source,
            "stats": gate_result["stats"],
            "rejected": [{"reason_codes": [r["code"] for r in it["reasons"]],
                          "record": {k: v for k, v in it["record"].items()
                                     if k != "_block"}}
                         for it in gate_result["rejected"]],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[quality-gate] 报告 → {path}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[quality-gate] 写出报告失败：{exc}", file=sys.stderr)


def quality_gate_check(opts, jobs_raw: Path) -> None:
    """fetch 之后、score 之前的质量门禁（观测 + 可选硬拦截）。

    默认「只报告不拦截」（report-only）：打印接受率/拦截项/软警告，写报告（若给定），
    便于跑批/CI 观测抓取质量趋势，但不影响流水线既有行为。

    要变成真正的 CI 门禁（未达门限即整批中止、不烧 LLM 评分预算），
    需显式传 --quality-gate-fail（hard 模式）：
      - 接受率 < --quality-gate-min-accept-rate → raise RuntimeError（main 据此 exit 1）
      - 软警告率 > --quality-gate-max-warning-rate 且 --quality-gate-warnings-fatal
        → 同样 raise

    注：权威的「硬过滤」在 batch_fetch 写出 jobs_raw 之前（已按完整字段契约
    require_company/require_identity 拦截废卡）。此处针对 run_pipeline 重解析后的
    jobs_raw（该形态下 company/url 常为空，仅 title 可靠），采用宽松契约
    （require_company=False, require_identity=False），只校验 title + URL 形态，
    避免对流水线既有数据形态产生误报。
    """
    if getattr(opts, "no_quality_gate", False):
        print("[quality-gate] 已跳过（--no-quality-gate）")
        return
    if not jobs_raw.exists():
        print("[quality-gate] jobs_raw 不存在，跳过")
        return
    try:
        records = _parse_jobs(jobs_raw)
    except Exception as e:
        print(f"[quality-gate] 解析 jobs_raw 失败（跳过门禁）：{e}", file=sys.stderr)
        return
    if not records:
        print("[quality-gate] jobs_raw 为空（0 条）；门禁不触发（由 health_check 负责）")
        return

    # 流水线重解析形态：仅 title 可靠，company/url 常空 → 宽松契约
    g = quality_gate(records, source=getattr(opts, "source", "pipeline"),
                     require_company=False, require_identity=False)
    st = g["stats"]
    min_rate = getattr(opts, "quality_gate_min_accept_rate", 0.5)
    hard = getattr(opts, "quality_gate_fail", False)
    print(f"[quality-gate] 总计 {st['total']} | 通过 {st['accepted']} | "
          f"拦截 {st['rejected']} | 接受率 {st['accept_rate']:.0%}"
          f"（门限 {min_rate:.0%}，hard={hard}）", file=sys.stderr)
    for code, cnt in st["by_code"].items():
        print(f"  [硬拦截] {code}: {cnt} 条", file=sys.stderr)
    if st["warnings"]:
        print(f"  [软警告] {st['warnings']}（告警率 {st['warning_rate']:.0%}）",
              file=sys.stderr)
    if getattr(opts, "quality_report", None):
        _write_qg_report(opts.quality_report, g,
                         source=getattr(opts, "source", "pipeline"))

    # 软警告阈值（可选致命；与 hard 模式独立）
    max_warn = getattr(opts, "quality_gate_max_warning_rate", None)
    if max_warn is not None:
        warn_rate = st["warning_rate"]
        if warn_rate > max_warn:
            msg = f"软警告率 {warn_rate:.0%} 超门限 {max_warn:.0%}：{st['warnings']}"
            if getattr(opts, "quality_gate_warnings_fatal", False):
                raise RuntimeError(msg)
            print(f"[quality-gate] 软警告超门限（非致命）：{msg}", file=sys.stderr)

    # 硬门禁（需 --quality-gate-fail）：接受率低于门限 → 整批中止
    if hard and st["accept_rate"] < min_rate:
        raise RuntimeError(
            f"抓取质量门禁未通过：接受率 {st['accept_rate']:.0%} < 门限 {min_rate:.0%}"
            f"（拦截 {st['rejected']} 条，契约 {st['by_code']}）")


# ---------------------------------------------------------------------------
# 增量模式（与 diff_watch 联动）
# ---------------------------------------------------------------------------

def _write_jobs_raw(jobs: list, path: Path) -> None:
    """把岗位列表写成 parse_jobs_raw 可解析的格式。

    关键：parse_jobs_raw 以 `--- JOB N ---` 的分块序号作为 job_id（JOB_N），
    不读任何显式 id。因此这里必须保留岗位在原始列表中的序号，否则重解析后
    id 错位（新增 JOB_2 会变成 JOB_1）。
    """
    lines = []
    for j in jobs:
        jid = j.get("job_id", "")
        m = re.match(r"JOB_(\d+)", jid)
        idx = m.group(1) if m else "1"
        lines.append(f"--- JOB {idx} ---")
        url = j.get("url", "")
        if url:
            lines.append(f"[URL]{url}[/URL]")
        title = j.get("title", "")
        if title:
            lines.append(title)
        ft = j.get("full_text", "")
        if ft:
            lines.append(ft)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _incremental_setup(opts, state: dict) -> None:
    """增量模式：与 baseline 比对，仅保留新增岗位；无新增则标记 no_new。"""
    import diff_watch

    baseline_path = Path(getattr(opts, "baseline", None)
                         or (state["full_jobs_raw"].parent / "jobs_raw.baseline.txt"))
    current = list(state["jobs_lookup"].values())
    baseline_jobs: list = []
    if baseline_path.exists():
        try:
            baseline_jobs = _parse_jobs(baseline_path)
        except Exception:
            baseline_jobs = []

    new_jobs = diff_watch.find_new_jobs(baseline_jobs, current)
    state["new_job_ids"] = {j["job_id"] for j in new_jobs}

    if not new_jobs:
        state["no_new"] = True
        print(f"[incremental] 无新增岗位（baseline={baseline_path.name}）")
        return

    # 写出仅含新岗位的 jobs_raw，后续 score/draft/compile 只跑新增
    filtered = state["full_jobs_raw"].parent / "new_jobs_raw.txt"
    _write_jobs_raw(new_jobs, filtered)
    state["jobs_raw"] = filtered
    state["jobs_lookup"] = {j["job_id"]: j for j in new_jobs}
    print(f"[incremental] 新增 {len(new_jobs)} 个岗位，仅处理新增：{sorted(state['new_job_ids'])}")


def _update_baseline(opts, state: dict) -> None:
    """用本次全量 jobs_raw 刷新 baseline，供下次增量比对。"""
    baseline_path = Path(getattr(opts, "baseline", None)
                         or (state["full_jobs_raw"].parent / "jobs_raw.baseline.txt"))
    try:
        baseline_path.write_text(state["full_jobs_raw"].read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[incremental] 已刷新 baseline: {baseline_path.name}")
    except Exception as e:
        print(f"[incremental] 刷新 baseline 失败: {e}")

    # Phase 8.1：本轮全量快照累积到 trend_store（与市场趋势分析联动）
    trend_store = getattr(opts, "trend_store", None)
    if trend_store:
        try:
            from trend_analyzer import append_snapshot, capture_snapshot
            snap = capture_snapshot(str(state["full_jobs_raw"]),
                                    date_str=getattr(opts, "date", None))
            store = append_snapshot(trend_store, snap)
            print(f"[trend] 已累积市场快照 {snap['date']}（{snap['total']} 岗，"
                  f"累计 {len(store['snapshots'])} 轮）→ {trend_store}")
        except Exception as e:
            print(f"[trend] 快照累积失败（跳过）: {e}")


def _merge_scored(acc, fresh, new_ids: set) -> dict:
    """把本次新 scored 并入累计 scored，并为每条打 is_new 标记。"""
    if not acc:
        acc = {"recommendations": {}}
    if not fresh:
        return acc
    a_rec = acc.get("recommendations") or {}
    f_rec = fresh.get("recommendations") or {}
    out = {}
    all_tiers = set(a_rec) | set(f_rec)
    for tier in all_tiers:
        a_items = {x.get("job_id"): dict(x) for x in a_rec.get(tier, [])}
        f_items = {x.get("job_id"): dict(x) for x in f_rec.get(tier, [])}
        merged = {}
        for jid, it in a_items.items():
            it["is_new"] = jid in new_ids
            merged[jid] = it
        for jid, it in f_items.items():
            it["is_new"] = jid in new_ids
            merged[jid] = it
        out[tier] = list(merged.values())
    result = dict(fresh)
    result["recommendations"] = out
    return result


def _strip_is_new(scored) -> dict:
    """清除累计 scored 中的 is_new 标记（增量无新增时避免陈旧高亮）。"""
    if not scored or "recommendations" not in scored:
        return scored
    out = dict(scored)
    rec = {}
    for tier, items in scored["recommendations"].items():
        rec[tier] = [{k: v for k, v in it.items() if k != "is_new"} for it in items]
    out["recommendations"] = rec
    return out


def _record_first_seen(opts, state: dict) -> None:
    """Phase 8.3：记录本轮全量岗位首见时间，构建 job_id -> first_seen_at 映射。"""
    store_path = getattr(opts, "first_seen_store", None)
    if not store_path:
        return
    try:
        from first_seen import load_store, record_first_seen, save_store
        jobs = list(state.get("jobs_lookup", {}).values())
        store = load_store(store_path)
        store, fs_map = record_first_seen(store, jobs)
        save_store(store_path, store)
        state["first_seen_map"] = fs_map
        print(f"[first_seen] 已记录 {len(fs_map)} 个岗位首见时间 → {store_path}")
    except Exception as e:
        print(f"[first_seen] 记录失败（跳过）: {e}")


def _apply_first_seen(scored: dict, fs_map: dict) -> dict:
    """将首见时间按 job_id 注入 scored 条目（已有则保留）。"""
    if not scored or not fs_map or "recommendations" not in scored:
        return scored
    out = dict(scored)
    rec = {}
    for tier, items in scored["recommendations"].items():
        rec[tier] = [
            {**it, "first_seen_at": fs_map.get(it.get("job_id", ""), it.get("first_seen_at"))}
            for it in items
        ]
    out["recommendations"] = rec
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="career-copilot 端到端求职编排器（fetch→score→draft→compile→track→report）",
    )
    ap.add_argument("--summary", help="边界画像（smart_score 输入，限制 LLM 行为边界）")
    ap.add_argument("--profile", help="求职画像（draft 阶段使用的求职人设 JSON）")
    ap.add_argument("--jobs", help="已抓取的 jobs_raw.txt（优先于 --query 抓取）")
    ap.add_argument("--query", help="抓取关键词（无 --jobs 时触发真实抓取）")
    ap.add_argument("--portals", default="config/portals.yaml", help="portals 配置")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--max-jobs", type=int, default=0)
    ap.add_argument("--seen", default=None, help="已见 JD 去重文件")
    ap.add_argument("--output", "-o", default="pipeline_out", help="产物输出目录")
    ap.add_argument("--scored", default=None, help="scored_results.json 路径（默认 <output>/scored_results.json）")
    ap.add_argument("--template", default="cn-professional", help="编译模板名")
    ap.add_argument("--name", default=None, help="求职人姓名（填入简历）")
    ap.add_argument("--email", default=None, help="求职人邮箱（填入简历）")
    ap.add_argument("--phone", default=None, help="求职人电话（填入简历）")
    ap.add_argument("--max-cv", type=int, default=3, help="最多为前 N 个岗位生成定制简历")
    ap.add_argument("--top-k", type=int, default=20, help="smart_score 评估房源数")
    ap.add_argument("--stage1-model", default="gpt-4.1")
    ap.add_argument("--stage2-model", default="gpt-4.1")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--stage2-concurrency", type=int, default=2)
    ap.add_argument("--webhook", default=None, help="企业微信推送 key（空则跳过）")
    ap.add_argument("--report", default=None, help="报告 HTML 路径（默认 <output>/report.html）")
    ap.add_argument("--store", default=None, help="job_tracker store 路径")
    ap.add_argument("--source", default="pipeline", help="入库来源标记")
    ap.add_argument("--track", action="store_true", help="将产出岗位写入 job_tracker")
    ap.add_argument("--dry-run", action="store_true", help="仅 fetch+score 预览成本，不产出简历")
    ap.add_argument("--resume-from", default=None, choices=STAGES, help="从指定阶段续跑")
    ap.add_argument("--force", action="store_true", help="强制重生成已存在的草稿/PDF")
    ap.add_argument("--cover-letter", dest="cover_letter", action="store_true",
                   help="同时产出求职信（草稿 cover.tex + 编译 cover.pdf）")
    ap.add_argument("--incremental", dest="incremental", action="store_true",
                   help="增量模式：仅处理相对 baseline 新增的岗位（需 --baseline）")
    ap.add_argument("--baseline", default=None,
                   help="增量模式基线 jobs_raw 路径（默认 <output>/jobs_raw.baseline.txt）")
    ap.add_argument("--trend-store", dest="trend_store", default=None,
                   help="Phase 8.1 市场趋势快照库 trend_store.json 路径（可选）")
    ap.add_argument("--history-store", dest="history_store", default=None,
                   help="Phase 6.1 历史转化漏斗 job_tracker.json 路径（可选，渲染历史转化漏斗）")
    ap.add_argument("--competitiveness-store", dest="competitiveness_store", default=None,
                   help="Phase 8.2 竞争力快照库 competitiveness_store.json 路径（可选；默认读 CAREER_COMPETITIVENESS_STORE）")
    ap.add_argument("--competitiveness-provider", dest="competitiveness_provider", default=None,
                   help="竞争力段接入 agnes 教练式叙述（可选，如 agnes；不给则纯确定性离线）")
    ap.add_argument("--career-log", dest="career_log", default=None,
                    help="职业日志路径（默认自动读取 career_log.LOG_FILE，用于竞争力 delta 的面试归因）；可选")
    ap.add_argument("--first-seen-store", dest="first_seen_store", default=None,
                   help="Phase 8.3 first_seen store 路径（可选，记录岗位首见时间）")
    ap.add_argument("--date", default=None, help="快照日期 YYYY-MM-DD（默认今天）")
    # Phase 4.3 质量门禁开关
    ap.add_argument("--no-quality-gate", dest="no_quality_gate", action="store_true",
                   help="关闭 Phase 4.3 抓取结果质量门禁（仅调试用）")
    ap.add_argument("--quality-gate-fail", dest="quality_gate_fail", action="store_true",
                   help="Phase 4.3 硬门禁：接受率低于门限则整批中止（否则仅报告）")
    ap.add_argument("--quality-gate-min-accept-rate", type=float, default=0.5,
                   dest="quality_gate_min_accept_rate",
                   help="质量门禁：接受率低于此值则整批中止（默认 0.5，需 --quality-gate-fail 生效）")
    ap.add_argument("--quality-gate-max-warning-rate", type=float, default=None,
                   dest="quality_gate_max_warning_rate",
                   help="软警告率上限；超过则告警（默认不限制）")
    ap.add_argument("--quality-gate-warnings-fatal", action="store_true",
                   dest="quality_gate_warnings_fatal",
                   help="软警告率超 --quality-gate-max-warning-rate 时一并判定失败")
    ap.add_argument("--quality-report", dest="quality_report", default=None,
                   help="写出质量门禁报告 JSON 的路径")
    # 透传给 smart_score 的开关
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--jd-trust-report", default=None)
    ap.add_argument("--no-calibration", action="store_true")
    ap.add_argument("--max-year-requirement", type=int, default=None)
    ap.add_argument("--include-intern", action="store_true")
    ap.add_argument("--include-outsource", action="store_true")
    ap.add_argument("--no-behavior-fit", action="store_true")
    ap.add_argument("--bf-log", default=None)
    ap.add_argument("--include-risk-levels", dest="include_risk_levels", action="store_true", default=True)
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        asyncio.run(run_pipeline(args))
    except Exception as e:
        print(f"[fatal] 流水线中止: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
