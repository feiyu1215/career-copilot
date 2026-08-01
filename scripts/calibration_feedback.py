#!/usr/bin/env python3
"""
calibration_feedback.py — 投递结果反馈 → 评分校准 (Phase 6.1)

核心目的：
    把真实投递结果（job_tracker.json 的历史生命周期数据）反哺回评分体系，
    检测「分档与实际转化脱节」的异常，并产出可执行的校准建议 / 阈值微调提议。

设计原则：
    - 确定性、可离线、零 LLM：纯 Python 统计 + 规则推理。
    - 不擅自改写管线配置：阈值微调只「提议」，写入独立的 *.suggested.yaml，
      必须人工 review 后再合并回 pipeline.yaml（plan 要求「需人工确认」）。
    - 样本不足时明确提示「样本不足，建议继续积累投递」，不编造结论。

数据契约（来自 job_tracker.json，已在 Phase 5.1 落地）：
    每个 application 含 tier(str: A/B/C/D/''), score(float|None),
    status(planned/applied/screening/interview/offer/rejected/withdrawn),
    applied_at(str|None), outcome(str|None)。

使用方式：
    # 计算漏斗 + 异常检测 + 校准建议（人类可读）
    python3 calibration_feedback.py --store job_tracker.json

    # 输出 JSON（便于其它工具消费 / 测试）
    python3 calibration_feedback.py --store job_tracker.json --json

    # 同时把阈值微调提议写到独立文件（默认 calibrate/YYYYMMDD.suggested.yaml）
    python3 calibration_feedback.py --store job_tracker.json --suggest

    # 指定最少有效样本（默认 10，低于则只给结论不评估异常）
    python3 calibration_feedback.py --store job_tracker.json --min-samples 20
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 允许以脚本方式直接导入同目录模块（job_tracker）
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from job_tracker import _load, _now  # noqa: E402

# ============================================================
# 数据加载
# ============================================================

# 视为「已投递」的终态/中间态（有 applied_at 即做过投递动作）
_APPLIED_STATES = {"applied", "screening", "interview", "offer", "rejected", "withdrawn"}
# 视为「拿到面试」的状态
_INTERVIEW_STATES = {"interview", "offer"}
# 视为「拿到 offer」的状态
_OFFER_STATES = {"offer"}
# 视为「被拒」的状态（与拿到 offer 互斥的负面终态）
_REJECTED_STATES = {"rejected"}


def load_applications(store: str) -> list[dict]:
    """读取 job_tracker.json 并返回 applications 列表（空存储返回 []）。"""
    data = _load(store)
    return data.get("applications", [])


# ============================================================
# 漏斗计算
# ============================================================

def compute_tier_funnel(applications: list[dict]) -> dict:
    """按 tier 计算投递转化漏斗。

    每个 tier 的指标：
        n          该档总建档数
        reached    曾投递（applied_at 非空 / 状态在 _APPLIED_STATES）
        interview  走到面试的岗位数
        offer      拿到 offer 的岗位数
        rejected   被拒的岗位数
        applied_rate     reached / n
        interview_rate   interview / reached   （reached>0）
        offer_rate       offer / reached       （reached>0）
        offer_rate_overall  offer / n
    """
    tiers_order = ["A", "B", "C", "D"]
    funnel: dict[str, dict] = {}
    for tier in tiers_order:
        funnel[tier] = {
            "tier": tier,
            "n": 0, "reached": 0, "interview": 0, "offer": 0, "rejected": 0,
            "applied_rate": 0.0, "interview_rate": 0.0,
            "offer_rate": 0.0, "offer_rate_overall": 0.0,
        }
    # 未分档 / 其它档归到 '' 便于排查
    other = {
        "tier": "", "n": 0, "reached": 0, "interview": 0, "offer": 0,
        "rejected": 0, "applied_rate": 0.0, "interview_rate": 0.0,
        "offer_rate": 0.0, "offer_rate_overall": 0.0,
    }

    for app in applications:
        tier = app.get("tier") or ""
        bucket = funnel.get(tier, other)
        bucket["n"] += 1
        status = app.get("status", "")
        applied_at = app.get("applied_at")
        if applied_at or status in _APPLIED_STATES:
            bucket["reached"] += 1
        if status in _INTERVIEW_STATES:
            bucket["interview"] += 1
        if status in _OFFER_STATES:
            bucket["offer"] += 1
        if status in _REJECTED_STATES:
            bucket["rejected"] += 1

    for bucket in list(funnel.values()) + [other]:
        n = bucket["n"]
        reached = bucket["reached"]
        bucket["applied_rate"] = round(reached / n, 4) if n else 0.0
        bucket["interview_rate"] = round(bucket["interview"] / reached, 4) if reached else 0.0
        bucket["offer_rate"] = round(bucket["offer"] / reached, 4) if reached else 0.0
        bucket["offer_rate_overall"] = round(bucket["offer"] / n, 4) if n else 0.0
        # 清理空桶的零值噪音
        if n == 0:
            for k in ("applied_rate", "interview_rate", "offer_rate", "offer_rate_overall"):
                bucket[k] = 0.0

    rows = [funnel[t] for t in tiers_order if funnel[t]["n"] > 0]
    if other["n"] > 0:
        rows.append(other)

    total_reached = sum(b["reached"] for b in funnel.values()) + other["reached"]
    total_offer = sum(b["offer"] for b in funnel.values()) + other["offer"]
    return {
        "rows": rows,
        "total_records": len(applications),
        "total_reached": total_reached,
        "total_offer": total_offer,
        "overall_offer_rate": round(total_offer / total_reached, 4) if total_reached else 0.0,
        "by_tier": funnel,
    }


# ============================================================
# 异常检测
# ============================================================

def _rate(bucket: dict, key: str) -> float:
    return float(bucket.get(key, 0.0) or 0.0)


def detect_anomalies(funnel: dict, min_samples: int = 10) -> list[dict]:
    """检测分档与实际转化脱节的异常。

    仅在有效样本足够时评估（reached 总数 >= min_samples），否则返回空。
    返回异常列表，每条含 type / severity / detail。
    """
    by_tier = funnel["by_tier"]
    total_reached = funnel["total_reached"]
    if total_reached < min_samples:
        return []

    anomalies: list[dict] = []

    a = by_tier.get("A")
    b = by_tier.get("B")

    # --- 异常 1：Tier A 转化 <= Tier B（典型过排名） ---
    if a and b and a["reached"] >= 3 and b["reached"] >= 3:
        a_offer = _rate(a, "offer_rate")
        b_offer = _rate(b, "offer_rate")
        if a_offer <= b_offer and (b_offer > 0 or a_offer == 0):
            anomalies.append({
                "type": "A_le_B_offer",
                "severity": "high" if a_offer == 0 else "medium",
                "detail": (
                    f"Tier A offer 转化率 {a_offer:.0%} ≤ Tier B {b_offer:.0%}，"
                    f"高分档未带来更高转化，疑似评分过排名或英语/核心团队/技术门槛漏判。"
                ),
            })

    # --- 异常 2：Tier A 大量投递却极少面试（高 reach 低 interview） ---
    if a and a["reached"] >= 3:
        a_iv = _rate(a, "interview_rate")
        if a_iv < 0.10:
            anomalies.append({
                "type": "A_low_interview",
                "severity": "medium",
                "detail": (
                    f"Tier A 曾投递 {a['reached']} 个，仅 {a['interview']} 个进入面试"
                    f"（面试率 {a_iv:.0%}）。A 档岗位「看起来匹配」却难推进，"
                    f"建议收紧 A 档门槛或加强英语/核心团队/技术依赖硬约束。"
                ),
            })

    # --- 异常 3：Tier A 能面试但拿不到 offer（区分度差） ---
    if a and a["interview"] >= 2:
        a_offer = _rate(a, "offer_rate")
        a_iv = _rate(a, "interview_rate")
        if a_iv > 0 and a_offer / a_iv < 0.25:
            anomalies.append({
                "type": "A_win_interview_lose_offer",
                "severity": "medium",
                "detail": (
                    f"Tier A 面试率 {a_iv:.0%} 尚可，但 offer 率仅 {a_offer:.0%}"
                    f"（面试→offer {a_offer / a_iv:.0%}）。A 档内部区分度不足，"
                    f"建议提高 A 档分数阈值（tiers.A）或降低 A 档比例上限"
                    f"（config/constraints.yaml → a_tier_cap.max_ratio）。"
                ),
            })

    # --- 异常 4：Tier B/C 转化反超 Tier A（反向过排名） ---
    for lower, lbl in (("B", "B"), ("C", "C")):
        lo = by_tier.get(lower)
        if a and lo and lo["reached"] >= 3 and a["reached"] >= 3:
            lo_offer = _rate(lo, "offer_rate")
            a_offer = _rate(a, "offer_rate")
            if lo_offer > a_offer and lo_offer > 0:
                anomalies.append({
                    "type": f"{lower}_over_A_offer",
                    "severity": "low",
                    "detail": (
                        f"Tier {lbl} offer 转化率 {lo_offer:.0%} > Tier A {a_offer:.0%}。"
                        f"低分档反而更出 offer，说明 A 档锚点偏松或 B/C 档被低估，"
                        f"可适度下调 score_high / score_mid 以释放被压制的优质岗。"
                    ),
                })

    return anomalies


# ============================================================
# 校准建议（从异常 → 具体可执行的配置改动）
# ============================================================

def generate_calibration_suggestions(funnel: dict, anomalies: list[dict]) -> list[dict]:
    """把异常映射为针对具体配置项的校准建议。"""
    if not anomalies:
        return []

    # 汇总异常类型，去重同一配置项建议
    seen = set()
    suggestions: list[dict] = []

    def add(key, title, rationale, config_ref):
        if key in seen:
            return
        seen.add(key)
        suggestions.append({
            "id": key,
            "title": title,
            "rationale": rationale,
            "config_ref": config_ref,
        })

    types = {a["type"] for a in anomalies}

    if "A_le_B_offer" in types:
        add("tighten_post_judge",
            "加强确定性后处理约束（post_judge）",
            "A 档转化不高于 B 档，常见根因是英语/核心团队/技术依赖门槛未正确封顶，"
            "导致不匹配岗位滞留高分区。",
            "config/pipeline.yaml → post_judge.english_fluent_cap / core_team_*_cap / tech_dependency_penalty")
        add("raise_a_threshold",
            "提高 A 档准入分数阈值",
            "高分档未带来更高转化，A 档整体偏松，应抬高准入线。",
            "config/pipeline.yaml → tiers.A（默认 85）")

    if "A_low_interview" in types:
        add("tighten_distribution",
            "收紧 A 档比例上限",
            "A 档投递多但面试少，说明 A 档被过度填充，应降低 A 档占比上限以浓缩质量。",
            "config/constraints.yaml → a_tier_cap.max_ratio")
        add("raise_a_threshold",
            "提高 A 档准入分数阈值",
            "同上，A 档准入线偏低导致大量弱匹配进入高分区。",
            "config/pipeline.yaml → tiers.A（默认 85）")

    if "A_win_interview_lose_offer" in types:
        add("raise_a_threshold",
            "提高 A 档准入分数阈值",
            "A 档能面试但拿不到 offer，内部区分度不足，抬高准入线可提升 A 档纯度。",
            "config/pipeline.yaml → tiers.A 与 output.score_high")
        add("tighten_distribution",
            "收紧 A 档比例上限",
            "A 档内部质量方差大，降低占比上限可迫使更优岗位胜出。",
            "config/constraints.yaml → a_tier_cap.max_ratio")

    if "B_over_A_offer" in types or "C_over_A_offer" in types:
        add("lower_score_high",
            "适度下调 score_high / score_mid",
            "低分档转化反超 A 档，B/C 档被压制，应释放被低估的优质岗位。",
            "config/pipeline.yaml → output.score_high（默认 97）/ output.score_mid（默认 72）")

    return suggestions


def propose_threshold_adjustments(funnel: dict, anomalies: list[dict],
                                  pipeline_config: Optional[dict] = None) -> dict:
    """基于异常给出 pipeline.yaml 阈值微调提议（仅提议，不写入管线文件）。

    返回形如 {"tiers": {"A": 88}, "output": {"score_high": 95}} 的增量覆盖。
    pipeline_config 可选，用于读取当前阈值（否则用默认）。
    """
    if not anomalies:
        return {}

    types = {a["type"] for a in anomalies}
    defaults = {
        "tiers": {"A": 85, "B": 72},
        "output": {"score_high": 97, "score_mid": 72, "score_mid_high": 85},
    }
    cfg = pipeline_config or {}
    tiers = cfg.get("tiers", defaults["tiers"])
    output = cfg.get("output", defaults["output"])

    cur_a = float(tiers.get("A", defaults["tiers"]["A"]))
    cur_high = float(output.get("score_high", defaults["output"]["score_high"]))
    cur_mid = float(output.get("score_mid", defaults["output"]["score_mid"]))

    proposed: dict = {}

    # 过排名类异常 → 抬高 A 档阈值（每次 +3，封顶 92）
    if {"A_le_B_offer", "A_low_interview", "A_win_interview_lose_offer"} & types:
        new_a = min(92.0, cur_a + 3.0)
        if new_a != cur_a:
            proposed.setdefault("tiers", {})["A"] = new_a

    # 反向过排名（低分档反超）→ 下调 score_high / score_mid
    if {"B_over_A_offer", "C_over_A_offer"} & types:
        new_high = max(90.0, cur_high - 2.0)
        new_mid = max(68.0, cur_mid - 3.0)
        if new_high != cur_high:
            proposed.setdefault("output", {})["score_high"] = new_high
        if new_mid != cur_mid:
            proposed.setdefault("output", {})["score_mid"] = new_mid

    return proposed


# ============================================================
# 报告装配
# ============================================================

def build_report(store: str, min_samples: int = 10,
                 pipeline_config: Optional[dict] = None) -> dict:
    """一站式装配校准反馈报告。"""
    applications = load_applications(store)
    funnel = compute_tier_funnel(applications)
    anomalies = detect_anomalies(funnel, min_samples=min_samples)
    suggestions = generate_calibration_suggestions(funnel, anomalies)
    proposed = propose_threshold_adjustments(funnel, anomalies, pipeline_config)

    sufficient = funnel["total_reached"] >= min_samples
    return {
        "generated_at": _now(),
        "store": store,
        "min_samples": min_samples,
        "sample_sufficient": sufficient,
        "total_records": funnel["total_records"],
        "total_reached": funnel["total_reached"],
        "total_offer": funnel["total_offer"],
        "overall_offer_rate": funnel["overall_offer_rate"],
        "funnel": funnel["rows"],
        "anomalies": anomalies,
        "suggestions": suggestions,
        "proposed_thresholds": proposed,
        "conclusion": _conclusion(funnel, anomalies, sufficient, min_samples),
    }


def _conclusion(funnel: dict, anomalies: list[dict], sufficient: bool,
                min_samples: int) -> str:
    if not sufficient:
        return (
            f"样本不足：有效投递 {funnel['total_reached']} 条 < 最少 {min_samples} 条，"
            f"暂不做异常评估。建议继续积累真实投递数据（≥{min_samples} 条）后再运行本工具。"
        )
    if not anomalies:
        return (
            "当前各档转化未检出明显异常，评分体系与实际投递结果基本自洽。"
            "建议每积累 ≥10 条新投递后定期复跑，持续观测。"
        )
    return (
        f"检出 {len(anomalies)} 项分档与实际转化脱节异常，"
        f"建议按下方校准建议逐步复核（先收紧 A 档，再复盘确定性后处理规则）。"
    )


# ============================================================
# 人类可读渲染
# ============================================================

def render_human(report: dict) -> str:
    lines = []
    lines.append("=" * 56)
    lines.append(" 投递结果反馈 → 评分校准 (Phase 6.1)")
    lines.append("=" * 56)
    lines.append(f" 数据来源 : {report['store']}")
    lines.append(f" 生成时间 : {report['generated_at'][:19]}")
    lines.append(f" 建档总数 : {report['total_records']} | 有效投递 : {report['total_reached']} "
                 f"| 总 offer : {report['total_offer']} | 整体 offer 率 : {report['overall_offer_rate']:.1%}")
    lines.append(f" 样本充分 : {'是' if report['sample_sufficient'] else f'否 (需 ≥{report['min_samples']} 条有效投递)'}")
    lines.append("")

    lines.append("-- 各档转化漏斗 --")
    header = f"  {'Tier':<5}{'建档':>6}{'投递':>6}{'面试':>6}{'offer':>6}{'投递率':>9}{'面试率':>9}{'offer率':>9}"
    lines.append(header)
    lines.append("  " + "-" * 52)
    for r in report["funnel"]:
        t = r["tier"] or "—"
        lines.append(
            f"  {t:<5}{r['n']:>6}{r['reached']:>6}{r['interview']:>6}{r['offer']:>6}"
            f"{r['applied_rate']:>8.0%}{r['interview_rate']:>8.0%}{r['offer_rate']:>8.0%}"
        )
    lines.append("")

    if not report["sample_sufficient"]:
        lines.append(f"⚠ {report['conclusion']}")
        lines.append("")
        return "\n".join(lines)

    if report["anomalies"]:
        lines.append(f"-- 检出异常 ({len(report['anomalies'])}) --")
        for i, a in enumerate(report["anomalies"], 1):
            sev = {"high": "严重", "medium": "中等", "low": "轻微"}.get(a["severity"], a["severity"])
            lines.append(f"  {i}. [{sev}] {a['type']}")
            lines.append(f"     {a['detail']}")
        lines.append("")

        lines.append(f"-- 校准建议 ({len(report['suggestions'])}) --")
        for s in report["suggestions"]:
            lines.append(f"  ▸ {s['title']}")
            lines.append(f"    依据: {s['rationale']}")
            lines.append(f"    配置: {s['config_ref']}")
        lines.append("")

        if report["proposed_thresholds"]:
            lines.append("-- 阈值微调提议 (需人工确认后合并) --")
            lines.append("  " + json.dumps(report["proposed_thresholds"], ensure_ascii=False))
            lines.append("  （仅提议，未改动 pipeline.yaml；可用 --suggest 落盘到 *.suggested.yaml）")
            lines.append("")
    else:
        lines.append("✓ 各档转化未检出异常，评分体系与实际结果基本自洽。")
        lines.append("")

    lines.append(f"结论: {report['conclusion']}")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _maybe_load_pipeline_config(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        import yaml
    except ImportError:
        # 没有 PyYAML 时退化为 None（propose 会用默认值，不影响主流程）
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("pipeline", data)
    except Exception:
        return None


def _write_suggested(report: dict, out_path: Optional[str]) -> str:
    if not report["proposed_thresholds"]:
        return ""
    out = Path(out_path) if out_path else (
        Path("calibrate") / f"{datetime.now().strftime('%Y%m%d')}.suggested.yaml"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"# Phase 6.1 阈值微调提议（自动生成，需人工确认后合并回 config/pipeline.yaml）\n"
        f"# 生成时间: {report['generated_at']}\n"
        f"# 数据来源: {report['store']}\n"
        f"# 异常: {', '.join(a['type'] for a in report['anomalies']) or '无'}\n"
    )
    # 仅写出增量覆盖段，便于人工 review
    import yaml
    content += yaml.safe_dump(report["proposed_thresholds"], allow_unicode=True, sort_keys=False)
    out.write_text(content, encoding="utf-8")
    return str(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="投递结果反馈 → 评分校准 (Phase 6.1)")
    parser.add_argument("--store", required=True, help="job_tracker.json 路径")
    parser.add_argument("--min-samples", type=int, default=10,
                        help="最少有效投递样本数（默认 10），低于则只给结论不评估异常")
    parser.add_argument("--pipeline-config", default=None,
                        help="config/pipeline.yaml 路径（可选，用于读取当前阈值做微调提议）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非人类可读文本")
    parser.add_argument("--suggest", action="store_true",
                        help="把阈值微调提议写到 calibrate/YYYYMMDD.suggested.yaml")
    parser.add_argument("--suggest-out", default=None,
                        help="--suggest 的目标文件路径（默认 calibrate/YYYYMMDD.suggested.yaml）")
    args = parser.parse_args(argv)

    store = Path(args.store)
    if not store.exists():
        print(f"✗ 数据文件不存在: {store}", file=sys.stderr)
        print("  请先运行 job_tracker.py 积累投递记录", file=sys.stderr)
        return 1

    pipeline_config = _maybe_load_pipeline_config(args.pipeline_config)
    report = build_report(str(store), min_samples=args.min_samples,
                          pipeline_config=pipeline_config)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))

    if args.suggest:
        written = _write_suggested(report, args.suggest_out)
        if written:
            print(f"\n✓ 阈值微调提议已写入: {written}")
        else:
            print("\n(无异常，未生成阈值微调提议)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
