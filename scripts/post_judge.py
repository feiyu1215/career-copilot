#!/usr/bin/env python3
"""
post_judge.py — 确定性后处理模块

核心原则：模型负责判断力，代码负责约束力。

本模块在 Stage 2 (listwise) 之后执行，用代码逻辑对分数做确定性修正：
1. 英语门槛：JD 有英语要求 + 候选人英语不达标 → 硬降分/封顶
2. 核心团队降级：JD 属于核心团队 + 候选人学历不足 → 封顶
3. 分布检查：A 档过多时强制降档
4. 技术依赖检测：JD 强调技术能力但候选人无技术背景 → 降分

使用方式：
    from post_judge import post_judge
    results = post_judge(analyzed_jobs, profile)
"""

from __future__ import annotations

import re
import sys
import json
from typing import Optional
from pathlib import Path

# 关键约束以 config/constraints.yaml 为单一事实源（见 scripts/config_loader.py）
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from config_loader import load_constraints


# ============================================================
# 可配置参数（默认值 = 当前硬编码行为，可通过 pipeline.yaml 覆盖）
# ============================================================

DEFAULT_CONFIG = {
    # 英语惩罚
    "english_fluent_cap": 40,          # JD要求fluent + 候选人非fluent → 封顶
    "english_preferred_penalty": 15,   # JD偏好英语 + 候选人basic/unknown → 降分
    "english_preferred_cap": 70,       # 同上 → 封顶
    "english_implicit_basic_penalty": 8,   # 隐含信号 + basic → 降分
    "english_implicit_basic_cap": 80,      # 同上 → 封顶
    "english_implicit_unknown_penalty": 5, # 隐含信号 + unknown → 降分
    "english_implicit_unknown_cap": 85,    # 同上 → 封顶
    # 核心团队
    "core_team_weak_cap": 60,          # 核心团队 + weak学历 → 封顶
    "core_team_medium_cap": 75,        # 核心团队 + medium学历 → 封顶
    # 技术依赖
    "tech_dependency_penalty": 10,     # JD强调技术 + 候选人无技术背景 → 降分
    # 分布约束（A 档比例）已迁移至 config/constraints.yaml → a_tier_cap，
    # 由 post_judge() 注入 cfg，此处不再保留，避免与 verify_output / pipeline.yaml 漂移。
}


# ============================================================
# 英语相关检测
# ============================================================

# JD 中的英语要求信号（三级）
ENGLISH_SIGNALS = {
    "fluent": [
        "fluent in english", "native english", "english as working language",
        "全英文工作环境", "英语作为工作语言", "英语流利", "流利的英语",
        "excellent english", "proficient in english",
    ],
    "preferred": [
        "english preferred", "good english", "英语优先", "良好的英语",
        "CET-6", "六级", "英语读写能力", "英文沟通能力",
        "english communication", "bilingual",
    ],
    "implicit": [
        "global team", "international", "cross-border", "海外", "出海",
        "globalization", "国际化", "跨境", "全球化",
        "Singapore", "San Jose", "London", "Tokyo",
        # 产品/部门级信号（这些业务本身国际化属性强，匹配时已做 lower）
        "tiktok", "lark", "byteplus", "pico",
        "global e-commerce", "全球电商",
        "international e-commerce", "跨境电商",
    ],
}


def detect_english_requirement(jd_text: str) -> Optional[str]:
    """检测 JD 中的英语要求等级，返回 fluent/preferred/implicit/None"""
    text_lower = jd_text.lower()

    for signal in ENGLISH_SIGNALS["fluent"]:
        if signal.lower() in text_lower:
            return "fluent"

    for signal in ENGLISH_SIGNALS["preferred"]:
        if signal.lower() in text_lower:
            return "preferred"

    for signal in ENGLISH_SIGNALS["implicit"]:
        if signal.lower() in text_lower:
            return "implicit"

    return None


def apply_english_penalty(job: dict, candidate_english: str,
                          jd_english_req: str, cfg: dict) -> dict:
    """根据英语匹配情况调整分数

    规则（参考 v1 的 must-hit rules）：
    - JD要求fluent + 候选人非fluent → 封顶
    - JD要求preferred + 候选人basic/unknown → 降分且封顶
    - JD有implicit信号 + 候选人basic/unknown → 降分且封顶
    """
    score = job["score"]
    penalties = []

    if jd_english_req == "fluent":
        if candidate_english not in ("fluent",):
            cap = cfg["english_fluent_cap"]
            score = min(score, cap)
            penalties.append(f"英语硬门槛: JD要求流利英语, 候选人{candidate_english}, 封顶{cap}")
    elif jd_english_req == "preferred":
        if candidate_english in ("basic", "unknown"):
            penalty = cfg["english_preferred_penalty"]
            cap = cfg["english_preferred_cap"]
            score = min(score - penalty, cap)
            penalties.append(f"英语偏好: JD偏好英语, 候选人{candidate_english}, -{penalty}且封顶{cap}")
    elif jd_english_req == "implicit":
        if candidate_english == "basic":
            penalty = cfg["english_implicit_basic_penalty"]
            cap = cfg["english_implicit_basic_cap"]
            score = min(score - penalty, cap)
            penalties.append(f"隐含英语: JD有国际化信号(TikTok/海外等), 候选人英语basic, -{penalty}且封顶{cap}")
        elif candidate_english == "unknown":
            penalty = cfg["english_implicit_unknown_penalty"]
            cap = cfg["english_implicit_unknown_cap"]
            score = min(score - penalty, cap)
            penalties.append(f"隐含英语: JD有国际化信号(TikTok/海外等), 候选人无英语证据, -{penalty}且封顶{cap}")

    if penalties:
        job = {**job, "score": max(score, 0)}
        job.setdefault("post_penalties", [])
        job["post_penalties"].extend(penalties)
        # 英语硬降可能需要降档
        if job["score"] <= 40:
            job["tier"] = "C"
        elif job["score"] <= 80 and job["tier"] == "A":
            job["tier"] = "B"

    return job


# ============================================================
# 核心团队 + 学历降级
# ============================================================

# 通用核心团队信号（不依赖特定公司，适用于所有用户）
GENERIC_CORE_SIGNALS = [
    "核心团队", "S级", "重点项目", "战略级", "一号位",
    "核心业务", "基础架构", "中台核心", "基础研发",
]


def detect_core_team(jd_text: str, profile: dict | None = None) -> bool:
    """检测 JD 是否属于核心团队

    信号来源：
    1. GENERIC_CORE_SIGNALS: 通用信号词（适用所有用户）
    2. profile["core_team_signals"]: 用户特定的目标公司核心业务线关键词
       （由 gen_profile 根据目标公司生成，如 ["豆包", "火山方舟", "Coze"]）
    """
    custom_signals = []
    if profile:
        custom_signals = profile.get("core_team_signals", [])
    all_signals = GENERIC_CORE_SIGNALS + custom_signals
    for signal in all_signals:
        if signal in jd_text:
            return True
    return False


def apply_core_team_penalty(job: dict, education_tier: str,
                            is_core_team: bool, cfg: dict) -> dict:
    """核心团队 + 学历不匹配时降级

    规则（对齐 v1/v2 step_b_core.py）：
    - 核心团队 + weak学历 → 封顶，降到 C 档
    - 核心团队 + medium学历 → 封顶，A档降到 B 档
    - 核心团队 + strong学历 → 不降
    """
    if not is_core_team:
        return job

    score = job["score"]
    penalties = []

    if education_tier == "weak":
        cap = cfg["core_team_weak_cap"]
        score = min(score, cap)
        penalties.append(f"核心团队+weak学历: 封顶{cap}, 降C档")
        job = {**job, "tier": "C"}
    elif education_tier == "medium":
        cap = cfg["core_team_medium_cap"]
        score = min(score, cap)
        penalties.append(f"核心团队+medium学历: 封顶{cap}")
        if job["tier"] == "A":
            job = {**job, "tier": "B"}
    # strong: 不降

    if penalties:
        job = {**job, "score": score}
        job.setdefault("post_penalties", [])
        job["post_penalties"].extend(penalties)

    return job


# ============================================================
# 技术依赖检测
# ============================================================

TECH_STRONG_SIGNALS = [
    "技术背景优先", "有开发经验", "代码能力", "编程能力",
    "需要写代码", "technical background", "coding ability",
    "Python/SQL", "具备编程", "技术产品经理",
]


def detect_tech_strong(jd_text: str) -> bool:
    """检测 JD 是否强依赖技术能力"""
    for signal in TECH_STRONG_SIGNALS:
        if signal.lower() in jd_text.lower():
            return True
    return False


def apply_tech_penalty(job: dict, has_tech: bool, is_tech_strong: bool,
                       cfg: dict) -> dict:
    """JD 强依赖技术但候选人无技术背景 → 降分

    规则（参考 v1 sort_score: tech_strong × -N）
    """
    if not is_tech_strong or has_tech:
        return job

    penalty = cfg["tech_dependency_penalty"]
    score = job["score"] - penalty
    job = {**job, "score": max(score, 0)}
    job.setdefault("post_penalties", [])
    job["post_penalties"].append(f"技术依赖: JD强调技术能力, 候选人无明确技术背景, -{penalty}")
    return job


# ============================================================
# 分布检查 & 强制降档
# ============================================================

def enforce_distribution(jobs: list[dict], cfg: Optional[dict] = None) -> list[dict]:
    """强制 A 档比例不超过阈值

    如果 A 档占比超过 max_a_ratio，将分数最低的 A 档岗位降为 B 档。
    这是代码层面的硬约束，确保推荐质量。A 档比例以 config/constraints.yaml
    → a_tier_cap 为单一事实源（不依赖调用方传入，避免漂移）。
    """
    a_cap = load_constraints()["a_tier_cap"]
    max_a_ratio = a_cap["max_ratio"]
    min_floor = a_cap["min_floor"]
    tier_a = [j for j in jobs if j["tier"] == "A"]
    max_a_count = max(min_floor, int(len(jobs) * max_a_ratio))

    if len(tier_a) <= max_a_count:
        return jobs

    # 按分数排序，把尾部的 A 档降为 B
    tier_a.sort(key=lambda x: x["score"], reverse=True)
    demote_count = len(tier_a) - max_a_count

    demote_ids = {j["job_id"] for j in tier_a[-demote_count:]}

    result = []
    for j in jobs:
        if j["job_id"] in demote_ids:
            j = {**j, "tier": "B"}
            j.setdefault("post_penalties", [])
            j["post_penalties"].append(f"分布约束: A档超额, 降为B档")
        result.append(j)

    return result


# ============================================================
# 主函数
# ============================================================

def post_judge(analyzed_jobs: list[dict], profile: dict,
               config: dict | None = None) -> list[dict]:
    """对 Stage 2 输出做确定性后处理

    Args:
        analyzed_jobs: Stage 2 的输出列表
        profile: boundary_profile.json 的内容
        config: 可选配置覆盖（来自 pipeline.yaml 的 post_judge 段）

    Returns:
        修正后的岗位列表（增加了 post_penalties 字段）
    """
    # 合并配置：DEFAULT_CONFIG ← 外部覆盖（pipeline.yaml 的 post_judge 段）
    cfg = {**DEFAULT_CONFIG}
    if config:
        cfg.update(config)
    # 注：A 档比例约束由 enforce_distribution 直接从 config/constraints.yaml
    # （a_tier_cap）读取，作为单一事实源；此处无需注入，避免重复定义。

    # 提取候选人信息
    eng_info = profile.get("english_evidence", {})
    candidate_english = eng_info.get("level", "unknown")

    edu_info = profile.get("education", {})
    education_tier = edu_info.get("tier", "medium")

    # 判断候选人是否有技术背景（从 profile 中推断）
    has_tech = False
    for exp in profile.get("core_experiences", []):
        signal_words = exp.get("signal_words", [])
        what = exp.get("what_i_did", "")
        combined = " ".join(signal_words) + " " + what
        tech_keywords = ["开发", "代码", "编程", "Python", "SQL", "Java",
                        "算法", "模型训练", "工程化", "API", "SDK"]
        if any(kw.lower() in combined.lower() for kw in tech_keywords):
            has_tech = True
            break

    # 逐个岗位应用规则
    results = []
    for job in analyzed_jobs:
        job = {**job}  # 浅拷贝
        job["post_penalties"] = job.get("post_penalties", [])

        jd_text = job.get("full_text", "") or ""

        # Rule 1: 英语门槛
        eng_req = detect_english_requirement(jd_text)
        if eng_req:
            job["english_requirement"] = eng_req  # 写入结构化字段供报告渲染
            job = apply_english_penalty(job, candidate_english, eng_req, cfg)

        # Rule 2: 核心团队 + 学历
        is_core = detect_core_team(jd_text, profile)
        if is_core:
            job["is_core_team"] = True  # 写入结构化字段供报告渲染
            job = apply_core_team_penalty(job, education_tier, is_core, cfg)

        # Rule 3: 技术依赖
        is_tech_strong = detect_tech_strong(jd_text)
        if is_tech_strong:
            job["is_tech_strong"] = True  # 写入结构化字段供报告渲染
            job = apply_tech_penalty(job, has_tech, is_tech_strong, cfg)

        results.append(job)

    # Rule 4: 分布约束
    results = enforce_distribution(results, cfg)

    # 重新排序
    tier_order = {"A": 0, "B": 1, "C": 2}
    results.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x["score"]))

    # 统计
    penalties_applied = sum(1 for j in results if j.get("post_penalties"))
    tier_a = sum(1 for j in results if j["tier"] == "A")
    tier_b = sum(1 for j in results if j["tier"] == "B")
    tier_c = sum(1 for j in results if j["tier"] == "C")

    print(f"  [Post-Judge] 应用惩罚: {penalties_applied}/{len(results)} 个岗位")
    print(f"  [Post-Judge] 最终分档: A={tier_a} | B={tier_b} | C={tier_c}")

    return results


# ============================================================
# CLI 入口（独立测试用）
# ============================================================

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="确定性后处理")
    parser.add_argument("--results", required=True, help="Stage 2 输出 JSON")
    parser.add_argument("--profile", required=True, help="boundary_profile.json")
    parser.add_argument("--output", required=True, help="输出路径")
    args = parser.parse_args()

    # 加载
    with open(args.results, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 兼容两种格式：直接列表 or scored_results.json 的嵌套结构
    if isinstance(data, list):
        jobs = data
    elif "recommendations" in data:
        jobs = []
        for tier_list in data["recommendations"].values():
            jobs.extend(tier_list)
    else:
        jobs = data

    with open(args.profile, "r", encoding="utf-8") as f:
        profile = json.load(f)

    # 执行
    results = post_judge(jobs, profile)

    # 保存
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存: {args.output}")
