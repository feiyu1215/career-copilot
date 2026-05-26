#!/usr/bin/env python3
"""
pre_filter.py — Stage 1 之前的确定性预过滤

核心原则：在花费 LLM token 之前，用代码规则排除明显不匹配的 JD。

本模块在 Stage 1 之前执行，提供：
1. 方向词检测：JD 标题/内容是否包含候选人方向的关键词
2. 硬门槛过滤：JD 有明确英语硬要求 + 候选人完全不达标 → 直接排除
3. 惩罚标记：不完全排除，但标记 penalty 供 Stage 1 参考

使用方式：
    from pre_filter import pre_filter
    filtered_jobs, stats = pre_filter(jobs, profile)
"""

from __future__ import annotations

import re
from typing import Optional


# ============================================================
# 方向词检测
# ============================================================

def extract_direction_keywords(profile: dict) -> tuple[list[str], list[str]]:
    """从 profile 中提取正向方向词和负向方向词

    Returns:
        (positive_keywords, negative_keywords)
    """
    positive = []
    negative = []

    # 从 direction_anchors 提取正向关键词（完整词组，不拆分）
    for anchor in profile.get("direction_anchors", []):
        positive.append(anchor)

    # 从 core_experiences 的 signal_words 提取（这是最精确的信号源）
    for exp in profile.get("core_experiences", []):
        for sw in exp.get("signal_words", []):
            positive.append(sw)
        # scenario 也作为正向词
        scenario = exp.get("scenario", "")
        if scenario and len(scenario) >= 2:
            positive.append(scenario)

    # 从 transferable_to 提取
    for exp in profile.get("core_experiences", []):
        for t in exp.get("transferable_to", [])[:3]:
            if len(t) >= 2:
                positive.append(t)

    # 从 hard_negatives 提取负向词
    for neg in profile.get("hard_negatives", []):
        negative.append(neg)

    # 从 NOT_transferable_to 提取负向词
    for exp in profile.get("core_experiences", []):
        for nt in exp.get("NOT_transferable_to", []):
            if len(nt) >= 2:
                negative.append(nt)

    # 去重并过滤太短的词
    positive = list(set(w for w in positive if len(w) >= 2))
    negative = list(set(w for w in negative if len(w) >= 2))

    return positive, negative


def compute_direction_score(jd_text: str, positive_keywords: list[str],
                            negative_keywords: list[str]) -> tuple[float, list[str], list[str]]:
    """计算 JD 与候选人方向的匹配度

    Returns:
        (score 0-1, matched_positive, matched_negative)
    """
    text_lower = jd_text.lower()

    matched_pos = [kw for kw in positive_keywords if kw.lower() in text_lower]
    matched_neg = [kw for kw in negative_keywords if kw.lower() in text_lower]

    if not positive_keywords:
        return 0.5, matched_pos, matched_neg

    # 正向命中率
    pos_rate = len(matched_pos) / len(positive_keywords)

    # 如果有负向命中，降低得分
    neg_penalty = min(len(matched_neg) * 0.15, 0.5)

    score = max(0, min(1, pos_rate - neg_penalty))
    return score, matched_pos, matched_neg


# ============================================================
# 英语硬门槛预过滤
# ============================================================

ENGLISH_HARD_GATE_SIGNALS = [
    "fluent in english", "native english", "english as working language",
    "全英文工作环境", "英语作为工作语言", "英语流利必备",
    "must be fluent", "native-level english",
]


def has_english_hard_gate(jd_text: str) -> bool:
    """检测 JD 是否有不可商量的英语硬门槛"""
    text_lower = jd_text.lower()
    return any(signal.lower() in text_lower for signal in ENGLISH_HARD_GATE_SIGNALS)


# ============================================================
# 年限/学历硬门槛
# ============================================================

def detect_experience_requirement(jd_text: str) -> Optional[int]:
    """从 JD 中提取最低工作年限要求"""
    patterns = [
        r"(\d+)\s*年以上.*(?:工作|经验|经历)",
        r"(\d+)\+?\s*years?\s*(?:of\s+)?experience",
        r"至少(\d+)年",
        r"(\d+)年及以上",
    ]
    for pattern in patterns:
        match = re.search(pattern, jd_text)
        if match:
            return int(match.group(1))
    return None


# ============================================================
# 主函数
# ============================================================

# 默认配置
DEFAULT_FILTER_CONFIG = {
    "include_intern": False,       # 是否保留实习岗
    "include_outsource": False,    # 是否保留外包岗
    "max_year_requirement": 10,    # 超过此年限要求的 JD 才被排除
}

# 实习/外包关键词
_INTERN_SIGNALS = ["实习", "实习生", "intern", "internship"]
_OUTSOURCE_SIGNALS = ["外包", "外协", "劳务派遣", "outsource", "contractor"]


def pre_filter(jobs: list[dict], profile: dict,
               exclude_english_hard: bool = True,
               min_direction_score: float = 0.0,
               config: dict | None = None) -> tuple[list[dict], dict]:
    """对 JD 列表做预过滤

    Args:
        jobs: 原始 JD 列表（每个 dict 含 title, full_text 等）
        profile: boundary_profile.json
        exclude_english_hard: 是否排除英语硬门槛不达标的 JD
        min_direction_score: 方向分最低阈值（0 = 不过滤）
        config: 过滤配置字典，支持 include_intern / include_outsource / max_year_requirement

    Returns:
        (filtered_jobs, stats)
        - filtered_jobs: 通过过滤的 JD（增加了 pre_filter_meta 字段）
        - stats: 过滤统计
    """
    cfg = {**DEFAULT_FILTER_CONFIG, **(config or {})}
    candidate_english = profile.get("english_evidence", {}).get("level", "unknown")
    positive_kw, negative_kw = extract_direction_keywords(profile)

    passed = []
    excluded_english = 0
    excluded_direction = 0
    excluded_intern = 0
    excluded_outsource = 0
    excluded_experience = 0
    total = len(jobs)

    for job in jobs:
        jd_text = job.get("full_text", "")
        title = job.get("title", "")
        search_text = (title + " " + jd_text).lower()
        meta = {}

        # Rule 0a: 实习过滤
        if not cfg["include_intern"]:
            if any(sig in search_text for sig in _INTERN_SIGNALS):
                excluded_intern += 1
                continue

        # Rule 0b: 外包过滤
        if not cfg["include_outsource"]:
            if any(sig in search_text for sig in _OUTSOURCE_SIGNALS):
                excluded_outsource += 1
                continue

        # Rule 1: 英语硬门槛
        if exclude_english_hard and candidate_english in ("basic", "unknown"):
            if has_english_hard_gate(jd_text):
                excluded_english += 1
                continue

        # Rule 1b: 年限硬门槛
        year_req = detect_experience_requirement(jd_text)
        if year_req is not None and year_req > cfg["max_year_requirement"]:
            excluded_experience += 1
            continue

        # Rule 2: 方向词匹配度
        dir_score, matched_pos, matched_neg = compute_direction_score(
            jd_text, positive_kw, negative_kw)
        meta["direction_score"] = round(dir_score, 3)
        meta["matched_positive"] = matched_pos[:5]
        meta["matched_negative"] = matched_neg[:3]

        if dir_score < min_direction_score:
            excluded_direction += 1
            continue

        # 标记 penalty（不排除，但后续 Stage 1 可以参考）
        penalties = []
        if matched_neg:
            penalties.append(f"方向负信号: {', '.join(matched_neg[:3])}")
        if dir_score < 0.1 and positive_kw:
            penalties.append("方向词零命中")

        meta["penalties"] = penalties
        job_with_meta = {**job, "pre_filter_meta": meta}
        passed.append(job_with_meta)

    stats = {
        "total_input": total,
        "passed": len(passed),
        "excluded_english": excluded_english,
        "excluded_direction": excluded_direction,
        "excluded_intern": excluded_intern,
        "excluded_outsource": excluded_outsource,
        "excluded_experience": excluded_experience,
        "positive_keywords_used": len(positive_kw),
        "negative_keywords_used": len(negative_kw),
    }

    print(f"  [Pre-Filter] 输入: {total} | 通过: {len(passed)} | "
          f"英语排除: {excluded_english} | 方向排除: {excluded_direction} | "
          f"实习排除: {excluded_intern} | 外包排除: {excluded_outsource} | "
          f"年限排除: {excluded_experience}")

    return passed, stats


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import json
    import argparse
    import sys
    from pathlib import Path

    # 复用 smart_score.py 的 JD 解析
    sys.path.insert(0, str(Path(__file__).parent))
    from smart_score import parse_jobs_raw

    parser = argparse.ArgumentParser(description="Stage 1 前预过滤")
    parser.add_argument("--jobs", required=True, help="jobs_raw.txt")
    parser.add_argument("--profile", required=True, help="boundary_profile.json")
    parser.add_argument("--output", help="输出过滤后的 JD JSON（可选）")
    parser.add_argument("--min-direction", type=float, default=0.0,
                       help="方向分最低阈值（0-1，默认0不过滤）")
    parser.add_argument("--include-intern", action="store_true", help="保留实习岗")
    parser.add_argument("--include-outsource", action="store_true", help="保留外包岗")
    parser.add_argument("--max-year-requirement", type=int, default=10,
                       help="超过此年限要求的 JD 才被排除（默认10）")
    args = parser.parse_args()

    jobs = parse_jobs_raw(args.jobs)
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))

    cli_config = {
        "include_intern": args.include_intern,
        "include_outsource": args.include_outsource,
        "max_year_requirement": args.max_year_requirement,
    }
    filtered, stats = pre_filter(jobs, profile,
                                  min_direction_score=args.min_direction,
                                  config=cli_config)

    print(f"\n过滤统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已保存: {args.output}")
