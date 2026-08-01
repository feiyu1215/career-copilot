#!/usr/bin/env python3
"""
smart_score.py — 六阶段智能评分 pipeline

核心原理（来自 S16 实验，ρ=0.76, R@10=86%）：
  1. 连续分(0-100)替代整数(1-10) → 避免分数扎堆
  2. 方向锚定 + 行业知识注入 → 解决模型的行业理解缺陷
  3. 分层架构 → 成本与效果的最优解
  4. Stage 2.5 全局重排 → 解决组内排序有效但组间不可比的问题

使用方式：
    python3 smart_score.py \
        --jobs /path/to/jobs_raw.txt \
        --profile /path/to/boundary_profile.json \
        --summary /path/to/candidate_summary.txt \
        --output /path/to/scored_results.json \
        [--top-k 50] \
        [--stage1-model gpt-4o-mini] \
        [--stage2-model gpt-4.1-mini] \
        [--concurrency 5]

输入：
  - jobs_raw.txt: 抓取的JD文本（--- JOB N --- 分隔格式）
    每条 JD 可选带 [URL]...[/URL] 前缀（由 fetch_jobs.py 注入的岗位来源链接）
  - boundary_profile.json: 候选人边界画像（由 gen_profile.py 生成）
  - candidate_summary.txt: 候选人摘要（由 gen_profile.py 生成）

输出：
  - scored_results.json: 三档推荐结果（A/B/C + 风险标注）
    每个岗位 item 含 "url" 字段（来源链接，若无则为空字符串），供下游报告生成可点击链接
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

import yaml


class PipelineAbortError(Exception):
    """管线因失败率过高或超时而中止"""
    pass


class StageStats:
    """单阶段执行统计"""
    def __init__(self, total: int = 0, succeeded: int = 0, failed: int = 0,
                 fallback: int = 0, wall_seconds: float = 0.0):
        self.total = total
        self.succeeded = succeeded
        self.failed = failed
        self.fallback = fallback
        self.wall_seconds = wall_seconds

    @property
    def failure_rate(self) -> float:
        """全量失败率（failed/total），用于最终统计输出。"""
        return self.failed / self.total if self.total > 0 else 0.0

    @property
    def processed_failure_rate(self) -> float:
        """已处理样本的失败率（failed/processed），用于熔断判断。"""
        processed = self.succeeded + self.failed
        return self.failed / processed if processed > 0 else 0.0

# 添加 scripts 目录到路径（复用 job_parser + 共享模块）
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from trace import ExecutionTracer  # noqa: E402

from behavior_fit import compute_behavior_fit, load_behavioral_profile  # noqa: E402
from llm_client import LLMClient  # noqa: E402

DEFAULT_BEHAVIOR_PROFILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "behavioral_profile.json")


# ============================================================
# Pipeline 配置化（T5）：所有数值型参数从 config/pipeline.yaml 读取
# 优先级：CLI 参数 > YAML 文件 > 代码默认值
# ============================================================

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pipeline.yaml"


def load_config(config_path: str | None = None) -> dict:
    """加载管线配置。优先级：CLI 参数 > YAML 文件 > 代码默认值。"""
    defaults: dict[str, Any] = {
        "pipeline": {"timeout_seconds": 1800, "checkpoint_dir": ".checkpoint", "version": "3.0.0"},
        "stage1": {"model": "gpt-4o-mini", "batch_size": 25, "max_concurrent": 8,
                   "truncation_chars": 1500, "circuit_breaker_threshold": 0.30, "circuit_min_samples": 5},
        "stage1_5_calibration": {"model": "gpt-4.1-mini", "top_k": 15},
        "stage2": {"model": "gpt-4.1-mini", "group_size": 6, "truncation_chars": 1800, "max_concurrent": 4, "top_score_low": 90, "top_score_high": 97, "bottom_cap": 75},
        "stage2_5_rerank": {"model": "gpt-4.1-mini", "layer_threshold": 15},
        "post_judge": {
            "english_fluent_cap": 40, "english_preferred_penalty": 15, "english_preferred_cap": 70,
            "english_implicit_basic_penalty": 8, "english_implicit_basic_cap": 80,
            "english_implicit_unknown_penalty": 5, "english_implicit_unknown_cap": 85,
            "core_team_weak_cap": 60, "core_team_medium_cap": 75,
            "tech_dependency_penalty": 10, "a_tier_max_ratio": 0.25,
        },
        "tiers": {"A": 85, "B": 72},
        "output": {"score_high": 97, "score_mid_high": 85, "score_mid": 72, "score_low": 55},
        # N5 行为×ATS 拟合：默认关闭，开启后按权重微调 score（±5 分内）
        "behavior_fit": {"enabled": False, "weight": 0.10},
        # Phase 6.2 面试复盘 → 匹配模型修正：默认关闭，仅 --history 显式传入时启用。
        # 复盘数据（career_log.jsonl）中的「被高频追问/被指出短板」方向 → 加权；
        # 「面试通过率低」方向 → 降权 + 风险提示。仅微调 stage1_score，不改动 LLM 行为。
        "history_calibration": {
            "boost_per_hit": 4.0,        # 命中的一个复盘强化方向 +4 分
            "max_boost": 12.0,           # 正向调整上限
            "penalty": 8.0,              # 命中一个低通过率方向 -8 分
            "max_penalty": 12.0,         # 负向调整上限
            "min_interviews_for_penalty": 2,  # 某方向面试数 ≥ 此值才统计通过率
            "pass_results": ["pass", "通过", "passed", "offer"],
            "fail_results": ["fail", "未通过", "reject", "no_offer", "failed"],
        },
    }

    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path, encoding="utf-8") as f:
            file_cfg = yaml.safe_load(f) or {}
        # 深度合并：file_cfg 覆盖 defaults
        for section, values in file_cfg.items():
            if section in defaults and isinstance(values, dict):
                defaults[section].update(values)
            else:
                defaults[section] = values

    return defaults


# 模块级配置（main 中可按 --config / CLI 参数覆盖）
PIPELINE_CFG = load_config()


# ============================================================
# T8: 外部化提示词（config/prompts.yaml 为单一可信源）
# 设计：YAML 模板经 .format() 注入动态字段；_DEFAULT_PROMPTS 内联默认作为兜底，
# 即使 prompts.yaml 缺失/解析失败，行为仍与改造前完全一致（无回归）。
# ============================================================

DEFAULT_PROMPTS_PATH = Path(__file__).parent.parent / "config" / "prompts.yaml"


def load_prompts(config_path: str | None = None) -> dict:
    """加载外部化提示词模板。文件缺失或解析失败返回空 dict（回退内联默认）。"""
    path = Path(config_path) if config_path else DEFAULT_PROMPTS_PATH
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# 内联默认（与 config/prompts.yaml 文本内容一致），作为 YAML 缺失时的兜底
_DEFAULT_PROMPTS = {
    "stage1_system": """你是一位资深求职匹配顾问。评估候选人与岗位的匹配度。

评分标准（0-100 连续分，请给出精确到个位数的分数）：
- 85-100: 核心方向完全一致 + 核心职责有直接经验
- 70-84: 方向高度相关 + 大部分职责可覆盖
- 55-69: 方向相关但有距离 + 部分职责匹配
- 40-54: 方向有关联但差距明显
- 0-39: 方向基本不相关

评分维度权重：
- 方向匹配 40%（候选人的 {direction_anchor} vs 岗位方向）
- 职责覆盖 35%（核心职责是否有直接或可迁移经验）
- 能力迁移 15%（通用能力是否适用）
- 成长性 10%（团队/业务对职业发展价值）

重要提示：
- 请给出精确分数，如 73、81、56，避免给整十数（70、80、90）
- 不同岗位之间应该有明显的分数差异
- 表面关键词相似但方向不同的岗位应该低分""",

    # 严格变体：适配强模型（frontier），强制硬负向惩罚、锚点分、禁止扎堆高分
    "stage1_system_strict": """你是一位资深求职匹配顾问，以"保守、精确、可追溯"为评分原则。评估候选人与岗位的匹配度。

评分标准（0-100 连续分，精确到个位数）：
- 90-100: 核心方向完全一致 + 核心职责有可直接复用的经验 + JD 出现候选人精确信号词
- 78-89: 方向高度相关 + 大部分核心职责可覆盖
- 65-77: 方向相关 + 部分职责匹配，但存在明显能力缺口
- 50-64: 方向有关联但差距明显，仅个别职责可迁移
- 35-49: 方向弱相关，主要靠可迁移通用能力
- 0-34: 方向基本不相关

评分维度权重：
- 方向匹配 40%（候选人的 {direction_anchor} vs 岗位方向）
- 职责覆盖 35%（核心职责是否有直接或可迁移经验）
- 能力迁移 15%（通用能力是否适用）
- 成长性 10%（团队/业务对职业发展价值）

硬负向强制规则（重要）：
- 若岗位方向属于候选人的硬负向（明确不匹配方向），最高不得超过 55 分，且 reasoning 必须说明方向不符。
- 表面关键词相似但实质方向不同的岗位，必须低分（≤60），不得因关键词命中而抬分。
- 仅"方向相关"但无直接职责的岗位，不得超过 77 分。

输出纪律：
- 给出精确个位数分数（如 73、81、56），禁止给整十数（70、80、90）。
- 不同岗位之间必须有 ≥10 分差异，禁止扎堆在 85-95。
- 先想清"这个岗位为什么不是更高分"，再给分；reasoning 必须指出具体命中或缺失的 JD 职责。""",

    # 宽松变体：适配思考模型（reasoning），抵消其过度挑刺/压分倾向，识别真实匹配
    "stage1_system_lenient": """你是一位鼓励型求职匹配顾问，以"看到真实匹配、不过度挑刺"为评分原则。评估候选人与岗位的匹配度。

评分标准（0-100 连续分，精确到个位数）：
- 85-100: 核心方向一致，或方向高度相关且候选人能力可覆盖核心职责
- 70-84: 方向相关，核心职责大部分可迁移覆盖
- 55-69: 方向有关联，部分职责匹配
- 40-54: 方向弱相关但存在可迁移点
- 0-39: 方向基本不相关

评分维度权重：
- 方向匹配 40%（候选人的 {direction_anchor} vs 岗位方向）
- 职责覆盖 35%（核心职责是否有直接或可迁移经验）
- 能力迁移 15%（通用能力是否适用）
- 成长性 10%（团队/业务对职业发展价值）

宽容评分原则（重要）：
- 候选人的经验往往能迁移到看似不完全一致的职责，请优先识别"能覆盖"的部分，不要因个别缺失职责而大幅扣分。
- 只要方向相关且候选人具备可迁移能力，就应给出反映真实潜力的分数，避免一味求严。
- 区分"暂时未做过的职责"与"完全无法迁移"——前者不应成为低分理由。

输出纪律：
- 给出精确个位数分数（如 73、81、56），禁止给整十数。
- 不同岗位之间应有合理差异，但允许方向相关的岗位处于中高分区间。
- reasoning 控制在 30 字以内，指出主要匹配点即可。""",

    "stage2_system": """你是一位资深行业猎头，对各大互联网公司的业务线非常熟悉。

你需要对候选人（{role_type}）与一组岗位的匹配做**对比式深度分析**。

## 核心视角（极其重要！）

你的视角是“候选人去匹配岗位”，而非“岗位来匹配候选人”。具体来说：
- ✅ 正确：“候选人的XX经验能迁移到这个岗位的YY职责”
- ❌ 错误：“这个岗位不在候选人核心方向”“非候选人核心技术平台方向”
- 候选人可能想拓展方向，也可能只想做某一部分。不要因为岗位不在候选人“核心方向”就否定它。
- 评价标准是：候选人的经验“能否胜任”和“迁移距离多远”，而不是“是否在候选人开心的方向”。

{domain_knowledge}

## 针对本批岗位的辨别知识（重要！）
{calibration_knowledge}

## 核心规则：Listwise 强制排序

你将收到一组 {group_size} 个岗位。你必须：
1. **先排名，再打分**：先确定这 {group_size} 个岗位从最匹配到最不匹配的排序
2. **强制拉开分差**：排名第1和排名最后的分数差距必须 ≥15 分
3. **不允许并列**：每个岗位必须有不同的分数（允许相邻岗位差 1-2 分，但不允许完全相同）
4. **组内相对定位**：分数反映的是"在这组里谁更适合候选人"，而非绝对匹配度

## 输出要求（JSON 数组，按排名从高到低排列）

对每个岗位给出：
1. job_id：岗位ID
2. rank：在本组中的排名（1 = 最匹配）
3. tier：A（强烈推荐）/ B（可以考虑）/ C（迁移距离较远）
4. score：0-100（组内排名第1的可以是 {stage2_top_low}-{stage2_top_high}，最后一名不应超过 {stage2_bottom_cap}）
5. match_reasons：2-3句具体理由，指出 JD 中哪些职责与候选人经验对应
6. risks：1-3个具体迁移风险点（视角：候选人的已有经验迁移到这个岗位时，哪些路径较远。不要说"缺乏XX经验"，而要说"候选人的YY经验迁移到岗位要求的ZZ需要跨越什么距离"——像职业教练看迁移路径，而非面试官挑毛病）
7. advice：一句话建议

## 分档标准
- A档：候选人经验可直接胜任核心职责（L2/L3级别） + JD 中出现候选人的精确信号词 + 迁移距离极短
- B档：候选人经验可迁移但需要适应 / 仅有 L1 级经验 / 部分职责能覆盖
- C档：候选人经验迁移到该岗位距离较远，需要较多新学习和适应（但仍然比未进入精排的岗位强）

## 评分锚点
- 95-97：方向 + 职责 + 信号词全部精确命中，几乎完美匹配
- 88-94：方向精确，主要职责匹配，个别次要职责缺乏
- 78-87：方向相关，部分核心职责可迁移
- 68-77：有关联但差距明显，仅个别职责相关
- ≤65：表面相似但实质不同

输出 JSON 数组，按 rank 排列。只返回 JSON。""",

    "calibration_system": """你是一位资深行业分析师。给定候选人的能力边界画像和一批通过初筛的岗位标题，你需要生成"辨别知识"——帮助后续精排模型区分哪些岗位是真匹配、哪些是表面相似但实际不同。

## 输出格式
输出一段文字（200-400字），包含：
1. 具体的"≠"判断（如：火山方舟的RAG产品 ≠ 业务侧RAG优化，前者是平台infra）
2. 容易混淆的岗位标题及其真实含义
3. 需要特别注意的业务线/部门差异

不需要覆盖所有岗位，只写最容易误判的 5-10 个case。直接输出文字，不需要JSON。""",

    "global_rerank_system": """你是一位资深行业猎头，需要对候选人与多个岗位的匹配度做**全局排序**。

## 核心任务

你将看到一批已经通过初步筛选的高匹配岗位。你需要将它们从"最适合候选人"到"相对没那么适合"做一个**严格的全局排序**。

## 排序标准（按优先级）

1. **经验迁移距离**：候选人已有经验到岗位核心职责的迁移距离越短，排名越高
2. **职责覆盖度**：候选人能覆盖 JD 中列出的核心职责的比例越高越好
3. **信号词精确匹配**：JD 中出现候选人精确信号词（而非泛化关键词）的密度越高越好
4. **方向契合度**：岗位方向与候选人核心方向的重叠程度

## 强制规则

1. **绝对不允许并列**：每个岗位必须有唯一的排名，不能有两个岗位排名相同
2. **必须拉开分差**：排名第 1 和排名最后的分数差距必须 ≥ {rerank_min_gap} 分
3. **分数必须唯一**：每个岗位的分数必须不同（至少差 1 分）
4. **分数区间**：排名第 1 给 {rerank_top_score} 分，最后一名不超过 {rerank_bottom_score} 分，中间线性分布
5. **你的排序就是最终排序**，请慎重考虑每一个位置

## 输出格式

JSON 数组，按 rank 从 1 到 N 排列：
[
  {{"job_id": "JOB_X", "rank": 1, "score": {rerank_top_score}, "one_line_reason": "一句话说明为什么排第一"}},
  {{"job_id": "JOB_Y", "rank": 2, "score": {rerank_top_score_minus_2}, "one_line_reason": "..."}},
  ...
]

只返回 JSON 数组，不要其他内容。""",
}

# YAML 覆盖内联默认（key 相同则 YAML 生效；YAML 缺失则保留内联默认）
_PROMPTS = {**_DEFAULT_PROMPTS, **load_prompts()}


# ============================================================
# JD 解析（兼容 job-matcher 的 jobs_raw.txt 格式）
# ============================================================

def parse_jobs_raw(filepath: str) -> list[dict]:
    """解析 jobs_raw.txt 为结构化列表"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 跳过版本头
    if content.startswith("# JOB_MATCHER_FORMAT"):
        content = content.split("\n", 1)[1] if "\n" in content else ""

    import re
    blocks = re.split(r"---\s*JOB\s+(\d+)\s*---", content)
    jobs = []
    # blocks: ['', '1', 'text1', '2', 'text2', ...]
    for i in range(1, len(blocks) - 1, 2):
        idx = int(blocks[i])
        raw = blocks[i + 1].strip()
        if not raw:
            continue

        # P5 接线：所有外部 JD 视为不可信，统一经过零信任清洗（剥离注入指令）
        from jd_guard import sanitize_jd
        text, rep = sanitize_jd(raw)
        if rep.injection_detected:
            print(f"  [JD-TRUST] JOB_{idx} 命中注入信号(high={rep.high_severity_count},"
                  f" total={len(rep.hits)})，已剥离清洗", file=sys.stderr)
        if not text:
            # 清洗后无任何正文（整条都是注入）→ 丢弃该岗位
            continue
        job_trust = {
            "injection_detected": rep.injection_detected,
            "high_severity_count": rep.high_severity_count,
            "hits": [
                {"kind": h.group, "severity": h.severity, "snippet": h.snippet[:80]}
                for h in rep.hits
            ],
            "summary": rep.summary(),
        }

        # 提取 URL（如果存在 [URL]...[/URL] 标记）
        url = ""
        url_match = re.match(r"^\[URL\](.*?)\[/URL\]\n?", text)
        if url_match:
            url = url_match.group(1).strip()
            text = text[url_match.end():].strip()

        # 提取标题（第一行）
        lines = text.split("\n")
        title = lines[0].strip() if lines else f"JOB_{idx}"

        # 提取部门（标题行中 - 后面的部分）
        department = ""
        if "-" in title:
            parts = title.rsplit("-", 1)
            if len(parts) == 2:
                department = parts[1].strip()

        # 提取城市
        location = ""
        location_keywords = ["北京", "上海", "深圳", "杭州", "成都", "广州",
                           "武汉", "南京", "西安", "珠海", "Singapore", "San Jose"]
        for loc in location_keywords:
            if loc in text[:200]:
                location = loc
                break

        jobs.append({
            "job_id": f"JOB_{idx}",
            "title": title,
            "department": department,
            "location": location,
            "url": url,
            "full_text": text,
            "_jd_trust": job_trust,
        })

    return jobs


def _print_jd_trust_report(jobs: list[dict]) -> None:
    """P5: 打印每条 JD 的零信任扫描摘要（消费前已 sanitize）"""
    print("\n[JD-TRUST] 零信任扫描报告（每条 JD 消费前已 sanitize）")
    suspicious = 0
    for j in jobs:
        t = j.get("_jd_trust", {})
        if t.get("injection_detected"):
            suspicious += 1
            kinds = ", ".join(h.get("kind", "?") for h in t.get("hits", []))
            sev = (t.get("hits", [{}])[0].get("severity", "?") if t.get("hits") else "?")
            print(f"  - {j.get('job_id')} [{sev}] 命中: {kinds} → 已剥离(sanitized)")
        else:
            print(f"  - {j.get('job_id')} [clean]")
    print(f"  [JD-TRUST] 共 {len(jobs)} 条，可疑 {suspicious} 条")


# ============================================================
# JSON 解析工具
# ============================================================

def _clean_json_str(s: str) -> str:
    """清理 JSON 字符串中的非法控制字符（保留 \\n \\r \\t）"""
    import re
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)


def _strip_markdown_fence(text: str) -> str:
    """去掉 markdown code fence 包裹"""
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    return text


def _fix_common_json_errors(text: str) -> str:
    """修复 LLM 常见的 JSON 格式错误"""
    import re
    # trailing commas: ,} or ,]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # single quotes → double quotes (简单情况)
    # 只在明确不含嵌套引号时处理
    if "'" in text and '"' not in text.replace('\\"', ''):
        text = text.replace("'", '"')
    return text


def _parse_json(text: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON 对象（dict）。四层恢复策略。"""
    import re
    text = _strip_markdown_fence(text)
    text = _clean_json_str(text)

    # Layer 1: 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Layer 2: 找 { } 边界
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Layer 3: 修复常见错误后重试
    fixed = _fix_common_json_errors(text[start:end + 1] if start != -1 else text)
    try:
        result = json.loads(fixed)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Layer 4: regex 提取 score 字段作为兜底
    score_match = re.search(r'"score"\s*:\s*(\d+)', text)
    if score_match:
        return {"score": int(score_match.group(1)), "reasoning": "", "is_fallback": True}

    return None


def _classify_parse(result: Optional[dict]) -> tuple[bool, float, str]:
    """由 _parse_json 结果判定是否回退分，并取出分数/理由（M2：正确透传 is_fallback）。

    _parse_json 的 Layer-4 正则兜底会返回 {"score": int, "reasoning": "", "is_fallback": True}，
    其 dict 含 "score" 键；若仅用 ``"score" not in result`` 判断回退，会把兜底分数误判为真分。
    这里同时检查 result.get("is_fallback")，确保兜底分被显式标记为回退。
    """
    if result is None:
        return True, 30, ""
    is_fallback = bool(result.get("is_fallback")) or "score" not in result
    return is_fallback, float(result.get("score", 30)), result.get("reasoning", "")


def _parse_json_array(text: str) -> list[dict]:
    """从 LLM 输出中提取 JSON 数组。供 Stage 2 Listwise 使用。"""
    text = _strip_markdown_fence(text)
    text = _clean_json_str(text)

    # Layer 1: 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Layer 2: 找 [ ] 边界
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Layer 3: 修复常见错误后重试
    fixed = _fix_common_json_errors(text[start:end + 1] if start != -1 else text)
    try:
        result = json.loads(fixed)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    return []


# ============================================================
# 从 boundary_profile 自动生成 Prompts
# ============================================================

def build_direction_anchor(profile: dict) -> str:
    """从 boundary_profile 提取方向锚定短语（用于 Stage 1）

    优先使用 profile 中的 direction_anchors 字段（由 gen_profile.py 生成）。
    如果不存在，回退到从 core_experiences 的 scenario 截取。
    """
    # 优先：profile 中已有预生成的方向锚定
    anchors = profile.get("direction_anchors", [])
    if anchors:
        return "/".join(anchors[:4])

    # 回退：从 scenario 提取（适用于旧版 profile）
    scenarios = [exp["scenario"] for exp in profile.get("core_experiences", [])]
    if scenarios:
        # 取每个 scenario 的前 8 个字作为锚点
        return "/".join(s[:8] for s in scenarios[:4])

    return cast(str, profile.get("role_type", "AI产品"))


def build_domain_knowledge(profile: dict) -> str:
    """从 boundary_profile 自动生成行业知识注入内容"""
    lines = ["## 行业知识（评估时必须考虑）\n"]

    # Part 1: 候选人核心方向精确定义（含证据层级）
    lines.append("### 候选人核心方向精确定义")
    for exp in profile.get("core_experiences", []):
        scenario = exp["scenario"]
        evidence_level = exp.get("evidence_level", "L2")
        not_transferable = exp.get("NOT_transferable_to", [])
        boundary = exp.get("boundary_explanation", "")

        lines.append(f"- **{scenario}** [{evidence_level}]")
        if boundary:
            lines.append(f"  - 边界说明：{boundary}")
        for neg in not_transferable[:3]:
            lines.append(f"  - ≠ {neg}")
        lines.append("")

    # Part 2: 精确信号词（用于 JD 匹配验证）
    lines.append("### 精确匹配信号词（JD 中出现这些词才算真匹配）")
    for exp in profile.get("core_experiences", []):
        signal_words = exp.get("signal_words", [])
        if signal_words:
            lines.append(f"- {exp['scenario']}: {', '.join(signal_words)}")
    lines.append("")

    # Part 3: 硬负面（整体不匹配的方向）
    hard_negatives = profile.get("hard_negatives", [])
    if hard_negatives:
        lines.append("### 整体不匹配的方向（需要降分）")
        for neg in hard_negatives:
            lines.append(f"- {neg}")
        lines.append("")

    # Part 4: 相邻但不同的角色
    adjacent = profile.get("adjacent_but_different", [])
    if adjacent:
        lines.append("### 相邻但不同的角色类型（容易误判）")
        for adj in adjacent:
            lines.append(f"- {adj}")
        lines.append("")

    # Part 5: 强匹配信号（可迁移方向）
    lines.append("### 强匹配信号")
    for exp in profile.get("core_experiences", []):
        transferable = exp.get("transferable_to", [])[:3]
        for t in transferable:
            lines.append(f"- JD涉及「{t}」→ 加分")
    lines.append("")

    # Part 6: 候选人英语 & 学历信息（供后处理使用）
    eng = profile.get("english_evidence", {})
    edu = profile.get("education", {})
    if eng or edu:
        lines.append("### 候选人基本条件")
        if eng:
            lines.append(f"- 英语水平: {eng.get('level', 'unknown')}")
            signals = eng.get("signals", [])
            if signals:
                lines.append(f"  - 证据: {'; '.join(signals[:3])}")
        if edu:
            lines.append(f"- 学历: {edu.get('degree', '?')} / {edu.get('school', '?')} [{edu.get('tier', '?')}]")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# Stage 1: 全量粗筛（便宜模型 + 连续分 + 方向锚定）
# ============================================================

_STAGE1_VARIANTS = ("general", "strict", "lenient")


def build_stage1_system(direction_anchor: str, variant: str = "general") -> str:
    """构建 Stage1 system 提示词。

    variant 适配不同模型族：
    - general: 平衡版（默认），适配一般模型（如 gpt-4o-mini / llama-70b）
    - strict : 严格版，强制硬负向惩罚与锚点分，适配强模型（frontier，如 gpt-4.1 / claude）
    - lenient: 宽松版，抵消思考模型过度挑刺倾向，适配思考模型（如 deepseek-r1 / o1）
    """
    # T8: 外部化提示词（config/prompts.yaml 覆盖内联默认）
    key = "stage1_system"
    if variant == "strict":
        key = "stage1_system_strict"
    elif variant == "lenient":
        key = "stage1_system_lenient"
    # 回退：变体缺失时退到通用版，保证无回归
    if key not in _PROMPTS:
        key = "stage1_system"
    return cast(str, _PROMPTS[key].format(direction_anchor=direction_anchor))


async def stage1(client: LLMClient, candidate_summary: str,
                 direction_anchor: str, jobs: list[dict],
                 progress_callback=None, tracer: "ExecutionTracer | None" = None,
                 prompt_variant: str = "general") -> tuple[list[dict], StageStats]:
    """Stage 1: 全量评分

    prompt_variant: 提示词变体（general/strict/lenient），适配不同模型族。
    """
    system_prompt = build_stage1_system(direction_anchor, prompt_variant)

    async def eval_one(job: dict) -> dict:
        user_prompt = f"""{candidate_summary}

---
## 待评估岗位
**标题**：{job['title']}
**部门**：{job['department']} | **城市**：{job['location']}
**描述**：
{job['full_text'][:PIPELINE_CFG["stage1"]["truncation_chars"]]}
---
评分并返回 JSON：{{"score": <0-100整数，避免整十数>, "reasoning": "<30字以内理由>"}}
只返回 JSON。"""

        t0 = time.time()
        in_before = client.total_input_tokens
        out_before = client.total_output_tokens
        content = await client.chat(system_prompt, user_prompt,
                                    temperature=0.0, max_tokens=150)
        in_after = client.total_input_tokens
        out_after = client.total_output_tokens
        latency_ms = int((time.time() - t0) * 1000)
        result = _parse_json(content)
        is_fallback, score, reasoning = _classify_parse(result)
        if tracer:
            tracer.record_call(
                "stage1", client.provider_name, client.model,
                in_after - in_before, out_after - out_before,
                latency_ms,
                job_ids=[job.get("job_id", "")],
                is_fallback=is_fallback,
            )
        if is_fallback:
            print(f"  [WARN] JD '{job.get('title', '?')[:20]}' 评分解析失败，使用默认分 30",
                  file=sys.stderr)
        return {**job, "stage1_score": float(score), "stage1_reasoning": reasoning,
                "is_fallback": is_fallback}

    scored = []
    batch_size = PIPELINE_CFG["stage1"]["batch_size"]
    stage_stats = StageStats(total=len(jobs))
    circuit_threshold = PIPELINE_CFG["stage1"]["circuit_breaker_threshold"]  # 失败率触发熔断
    circuit_min_samples = PIPELINE_CFG["stage1"]["circuit_min_samples"]   # 至少 N 个样本才判断

    for i in range(0, len(jobs), batch_size):
        batch = [eval_one(jobs[j]) for j in range(i, min(i + batch_size, len(jobs)))]
        results = await asyncio.gather(*batch, return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                stage_stats.failed += 1
            else:
                stage_stats.succeeded += 1
                scored.append(r)
                if r.get("is_fallback"):
                    stage_stats.fallback += 1

        # 熔断检查（用已处理样本的失败率，而非全量失败率）
        processed = stage_stats.succeeded + stage_stats.failed
        if (processed >= circuit_min_samples
                and stage_stats.processed_failure_rate > circuit_threshold):
            raise PipelineAbortError(
                f"Stage 1 熔断：{stage_stats.failed}/{processed} 调用失败 "
                f"({stage_stats.processed_failure_rate:.0%})，超过阈值 {circuit_threshold:.0%}。"
                f"已完成 {len(scored)}/{len(jobs)} 个 JD。"
            )

        if progress_callback:
            progress_callback(min(i + batch_size, len(jobs)), len(jobs))

    # 警告但不中止的情况
    if stage_stats.failed > 0:
        print(f"  [警告] Stage 1 有 {stage_stats.failed}/{stage_stats.total} 个调用失败 "
              f"(失败率 {stage_stats.failure_rate:.0%})", file=sys.stderr)

    scored.sort(key=lambda x: x["stage1_score"], reverse=True)
    return scored, stage_stats


# ============================================================
# Stage 1.5: 动态辨别知识生成（针对 Top K 的具体 JD）
# ============================================================

# T8: 外部化提示词（config/prompts.yaml 覆盖内联默认，_DEFAULT_PROMPTS 兜底）
CALIBRATION_SYSTEM = _PROMPTS["calibration_system"]


async def generate_calibration_knowledge(client: LLMClient, profile: dict,
                                          top_titles: list[str]) -> str:
    """Stage 1.5: 根据 Top K 的具体岗位标题，动态生成辨别知识"""
    # 准备 profile 摘要
    core_scenarios = [exp["scenario"] for exp in profile.get("core_experiences", [])]
    not_transferable_all = []
    for exp in profile.get("core_experiences", []):
        not_transferable_all.extend(exp.get("NOT_transferable_to", []))

    user_prompt = f"""## 候选人核心方向
{chr(10).join(f"- {s}" for s in core_scenarios)}

## 候选人方向边界（以下不适合）
{chr(10).join(f"- {n}" for n in not_transferable_all[:8])}

## 通过初筛的岗位标题（共{len(top_titles)}个，需要你帮助辨别）
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(top_titles))}

请针对上面这批具体岗位，写出辨别知识。重点关注：
- 哪些标题中的关键词与候选人方向"看着像但不同"？
- 哪些部门/业务线的岗位虽然标题匹配但实际做的事情不一样？
- 哪些是真正精准匹配候选人方向的？"""

    return await client.chat(CALIBRATION_SYSTEM, user_prompt,
                            temperature=0.0, max_tokens=800)


# ============================================================
# Stage 2: Top K 精排（强模型 + 行业知识 + 风险标注）
# ============================================================

def build_stage2_system(domain_knowledge: str, calibration_knowledge: str,
                        profile: dict, group_size: int) -> str:
    role_type = profile.get("role_type", "产品经理")
    # T8: 外部化提示词（config/prompts.yaml 覆盖内联默认）
    s2_cfg = PIPELINE_CFG["stage2"]
    return cast(str, _PROMPTS["stage2_system"].format(
        role_type=role_type,
        domain_knowledge=domain_knowledge,
        calibration_knowledge=calibration_knowledge,
        group_size=group_size,
        stage2_top_low=s2_cfg.get("top_score_low", 90),
        stage2_top_high=s2_cfg.get("top_score_high", 97),
        stage2_bottom_cap=s2_cfg.get("bottom_cap", 75),
    ))


async def stage2(client: LLMClient, candidate_summary: str,
                 domain_knowledge: str, calibration_knowledge: str,
                 profile: dict, top_jobs: list[dict],
                 progress_callback=None, tracer: "ExecutionTracer | None" = None) -> tuple[list[dict], int]:
    """Stage 2: Listwise 分组精排 + 风险标注"""
    stage2_failures = 0
    GROUP_SIZE = PIPELINE_CFG["stage2"]["group_size"]  # 每组岗位数，模型可有效对比

    hard_negatives = profile.get("hard_negatives", [])
    negatives_text = "\n".join(f"- {n}" for n in hard_negatives[:5])

    # 将 top_jobs 分组
    groups = []
    for i in range(0, len(top_jobs), GROUP_SIZE):
        groups.append(top_jobs[i:i + GROUP_SIZE])

    system_prompt = build_stage2_system(domain_knowledge, calibration_knowledge,
                                       profile, GROUP_SIZE)

    async def eval_group(group: list[dict]) -> list[dict]:
        """对一组岗位做 listwise 排序"""
        jobs_text = ""
        for idx, job in enumerate(group, 1):
            jobs_text += f"""
---
### 岗位 {idx}（{job['job_id']}）
**标题**：{job['title']}
**部门**：{job['department']} | **城市**：{job['location']}
**Stage 1 初筛分**：{job['stage1_score']:.0f}/100
**完整JD**：
{job['full_text'][:PIPELINE_CFG["stage2"]["truncation_chars"]]}
"""

        user_prompt = f"""## 候选人画像
{candidate_summary}

## 候选人边界（以下方向不适合）
{negatives_text}

## 本组待排序岗位（共{len(group)}个）
{jobs_text}

## 请对以上 {len(group)} 个岗位进行排序和评分

输出 JSON 数组，包含 {len(group)} 个对象，按 rank 从 1（最匹配）到 {len(group)}（最不匹配）排列：
[
  {{"job_id": "JOB_X", "rank": 1, "tier": "A", "score": 95, "match_reasons": ["..."], "risks": ["..."], "advice": "..."}},
  ...
]
只返回 JSON 数组。"""

        in_before = client.total_input_tokens
        out_before = client.total_output_tokens
        t0 = time.time()
        content = await client.chat(system_prompt, user_prompt,
                                    temperature=0.0, max_tokens=2000)
        if tracer:
            in_after = client.total_input_tokens
            out_after = client.total_output_tokens
            tracer.record_call(
                "stage2", client.provider_name, client.model,
                in_after - in_before, out_after - out_before,
                int((time.time() - t0) * 1000),
                job_ids=[job["job_id"] for job in group],
            )

        # 解析 JSON 数组（复用统一的解析函数）
        results = _parse_json_array(content)

        # 构建 job_id → job 映射
        job_map = {job["job_id"]: job for job in group}

        analyzed = []
        for r in results:
            job_id = r.get("job_id", "")
            if job_id in job_map:
                job = job_map[job_id]
                analyzed.append({
                    "job_id": job_id,
                    "title": job["title"],
                    "department": job.get("department", ""),
                    "location": job.get("location", ""),
                    "url": job.get("url", ""),
                    "full_text": job.get("full_text", ""),  # 传递给 post_judge 做规则检测
                    "stage1_score": job["stage1_score"],
                    "rank_in_group": r.get("rank", 99),
                    "tier": r.get("tier", "C"),
                    "score": float(r.get("score", 50)),
                    "match_reasons": r.get("match_reasons", []),
                    "risks": r.get("risks", []),
                    "advice": r.get("advice", ""),
                })

        # 如果有岗位没被模型返回，补默认值
        returned_ids = {a["job_id"] for a in analyzed}
        for job in group:
            if job["job_id"] not in returned_ids:
                analyzed.append({
                    "job_id": job["job_id"],
                    "title": job["title"],
                    "department": job.get("department", ""),
                    "location": job.get("location", ""),
                    "url": job.get("url", ""),
                    "full_text": job.get("full_text", ""),  # 传递给 post_judge 做规则检测
                    "stage1_score": job["stage1_score"],
                    "rank_in_group": 99,
                    "tier": "C",
                    "score": job["stage1_score"] * 0.7,
                    "match_reasons": [],
                    "risks": ["模型未返回该岗位评估"],
                    "advice": "",
                })

        return analyzed

    # 并发处理所有组（并发度由调用方通过 client.semaphore 控制）
    all_analyzed = []
    concurrent_groups = min(client.semaphore._value, len(groups))
    for i in range(0, len(groups), concurrent_groups):
        batch = [eval_group(groups[j]) for j in range(i, min(i + concurrent_groups, len(groups)))]
        results = await asyncio.gather(*batch, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_analyzed.extend(r)
            elif isinstance(r, Exception):
                stage2_failures += 1
                print(f"  [警告] 一组评估失败 ({stage2_failures} 累计): {r}", file=sys.stderr)
        if progress_callback:
            done = min((i + concurrent_groups) * GROUP_SIZE, len(top_jobs))
            progress_callback(done, len(top_jobs))

    # 全局排序：先按 tier，再按 score
    tier_order = {"A": 0, "B": 1, "C": 2}
    all_analyzed.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x["score"]))

    if stage2_failures > 0:
        print(f"  [警告] Stage 2 共 {stage2_failures} 组失败，"
              f"丢失约 {stage2_failures * GROUP_SIZE} 个 JD 的精排结果", file=sys.stderr)

    return all_analyzed, stage2_failures


# ============================================================
# Stage 2.5: 全局重排（解决组间分数不可比问题）
# ============================================================

# T8: 外部化提示词（config/prompts.yaml 覆盖内联默认，_DEFAULT_PROMPTS 兜底）
_GLOBAL_RERANK_TEMPLATE = _PROMPTS["global_rerank_system"]


def _build_rerank_system() -> str:
    """格式化全局重排 system prompt，注入配置中的分数带参数。"""
    score_high = PIPELINE_CFG["output"]["score_high"]
    score_mid = PIPELINE_CFG["output"]["score_mid"]
    return cast(str, _GLOBAL_RERANK_TEMPLATE.format(
        rerank_top_score=score_high,
        rerank_bottom_score=score_mid,
        rerank_min_gap=20,
        rerank_top_score_minus_2=score_high - 2,
    ))


async def global_rerank(client: LLMClient, candidate_summary: str,
                        calibration_knowledge: str, profile: dict,
                        candidates: list[dict]) -> list[dict]:
    """Stage 2.5: 对全部 Stage 2 输出做全局重排，解决组间分数不可比问题。

    策略：
    - ≤ 15 个：一次调用搞定
    - > 15 个：按 Stage 2 分档分层重排
      - A 档（或 Stage 2 top 25%）做一次全局重排 → 输出 97→85
      - B 档（中间 40%）做一次全局重排 → 输出 84→72
      - C 档（剩余）做一次全局重排 → 输出 71→55
      每层独立排序，层间分数天然不重叠
    """
    if len(candidates) <= 1:
        return candidates

    hard_negatives = profile.get("hard_negatives", [])
    negatives_text = "\n".join(f"- {n}" for n in hard_negatives[:5])

    async def rerank_batch(batch: list[dict], score_high: int, score_low: int) -> dict:
        """对一批岗位做全局排序，返回 {job_id: {rank, score, reason}}

        分数从 score_high（rank=1）到 score_low（rank=N）线性递减。
        """
        if not batch:
            return {}

        jobs_text = ""
        for idx, job in enumerate(batch, 1):
            jobs_text += f"\n---\n### {idx}. {job['title']}（{job['job_id']}）\n"
            jobs_text += f"部门：{job.get('department', '')} | 城市：{job.get('location', '')}\n"
            jd_text = job.get("full_text", "")
            jobs_text += f"JD摘要：{jd_text[:500]}\n"

        user_prompt = f"""## 候选人画像
{candidate_summary}

## 候选人边界（以下方向不适合）
{negatives_text}

## 辨别知识
{calibration_knowledge[:400]}

## 待排序岗位（共 {len(batch)} 个，请严格排出 1→{len(batch)} 的全局顺序）
{jobs_text}

请输出 JSON 数组，包含 {len(batch)} 个对象，按 rank 从 1（最匹配）到 {len(batch)}（最不匹配）排列。
分数从 {score_high}（rank=1）线性递减到 {score_low}（rank={len(batch)}），每个分数必须唯一。
只返回 JSON 数组。"""

        content = await client.chat(_build_rerank_system(), user_prompt,
                                    temperature=0.0, max_tokens=4000)

        # 解析
        content = content.strip()
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        if content.startswith("json"):
            content = content[4:].strip()

        content = _clean_json_str(content)
        try:
            results = json.loads(content)
        except json.JSONDecodeError:
            start_idx = content.find("[")
            end_idx = content.rfind("]")
            if start_idx != -1 and end_idx != -1:
                try:
                    results = json.loads(content[start_idx:end_idx + 1])
                except json.JSONDecodeError:
                    results = []
            else:
                results = []

        # 如果模型返回不完整，对未返回的岗位按原 score 插入
        returned_map = {}
        for r in results:
            if "job_id" in r:
                returned_map[r["job_id"]] = {
                    "rank": r.get("rank", 99),
                    "score": float(r.get("score", (score_high + score_low) / 2)),
                    "reason": r.get("one_line_reason", "")
                }

        # 对未返回的岗位分配中间分数
        batch_ids = {j["job_id"] for j in batch}
        missing_ids = batch_ids - set(returned_map.keys())
        if missing_ids:
            # 必须 sorted 后再枚举：set 迭代顺序受 PYTHONHASHSEED 影响，直接 enumerate
            # 会在不同进程给出不同的兜底分数，导致 CI / 复跑结果抖动（回归测试会误报）。
            mid_score = (score_high + score_low) / 2
            for i, mid in enumerate(sorted(missing_ids)):
                returned_map[mid] = {"rank": 50 + i, "score": mid_score - i * 0.5, "reason": ""}

        return returned_map

    # 从配置读取分数带和分层阈值
    layer_threshold = PIPELINE_CFG["stage2_5_rerank"]["layer_threshold"]
    score_high = PIPELINE_CFG["output"]["score_high"]
    score_mid_high = PIPELINE_CFG["output"]["score_mid_high"]
    score_mid = PIPELINE_CFG["output"]["score_mid"]
    score_low = PIPELINE_CFG["output"]["score_low"]

    if len(candidates) <= layer_threshold:
        # 单次全局重排
        rank_map = await rerank_batch(candidates, score_high, score_low)
    else:
        # 分层重排：按 Stage 2 原始 tier 分三层，每层独立排序
        tier_a_jobs = [j for j in candidates if j["tier"] == "A"]
        tier_b_jobs = [j for j in candidates if j["tier"] == "B"]
        tier_c_jobs = [j for j in candidates if j["tier"] == "C"]

        print(f"    分层重排: A={len(tier_a_jobs)} | B={len(tier_b_jobs)} | C={len(tier_c_jobs)}")

        # 并发执行三层重排（只对非空层）
        layer_configs = [
            (tier_a_jobs, score_high, score_mid_high),      # A 层: 97→85
            (tier_b_jobs, score_mid_high - 1, score_mid),   # B 层: 84→72
            (tier_c_jobs, score_mid - 1, score_low),        # C 层: 71→55
        ]

        tasks = [rerank_batch(jobs, hi, lo) for jobs, hi, lo in layer_configs if jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并所有层结果
        rank_map = {}
        for r in results:
            if isinstance(r, dict):
                rank_map.update(r)

    # 应用全局重排结果（带 stage1 锚定约束，防止 rerank 分数膨胀）
    RERANK_MAX_DEVIATION = 20  # rerank 分不得偏离 stage1 超过此值
    for job in candidates:
        jid = job["job_id"]
        if jid in rank_map:
            job["global_rank"] = rank_map[jid]["rank"]
            raw_rerank_score = rank_map[jid]["score"]
            # Clamp: 以 stage1_score 为锚，允许 ±RERANK_MAX_DEVIATION 的调整
            s1 = job.get("stage1_score", raw_rerank_score)
            clamped = max(s1 - RERANK_MAX_DEVIATION, min(s1 + RERANK_MAX_DEVIATION, raw_rerank_score))
            job["score"] = clamped
            job["rerank_reason"] = rank_map[jid].get("reason", "")
            if clamped != raw_rerank_score:
                job["rerank_clamped"] = True
        else:
            # 模型没返回的，保持原分但标记
            job["global_rank"] = 999

    # 按全局重排分数重新排序
    candidates.sort(key=lambda x: -x["score"])
    return candidates


# ============================================================
# 主流程
# ============================================================

def _checkpoint_dir(output_path: str) -> Path:
    """获取 checkpoint 目录路径（与输出文件同目录）"""
    return Path(output_path).parent / ".checkpoint"


def _save_checkpoint(output_path: str, stage: str, data) -> None:
    """保存 checkpoint 文件"""
    ckpt_dir = _checkpoint_dir(output_path)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt_file = ckpt_dir / f"{stage}.json"
    ckpt_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [checkpoint] 已保存: {stage}")


def _load_checkpoint(output_path: str, stage: str):
    """加载 checkpoint 文件，不存在返回 None"""
    ckpt_file = _checkpoint_dir(output_path) / f"{stage}.json"
    if ckpt_file.exists():
        return json.loads(ckpt_file.read_text(encoding="utf-8"))
    return None


def _clean_checkpoints(output_path: str) -> None:
    """Pipeline 成功后清理 checkpoint 目录"""
    import shutil
    ckpt_dir = _checkpoint_dir(output_path)
    if ckpt_dir.exists():
        shutil.rmtree(ckpt_dir)
        print("  [checkpoint] 已清理")


# ============================================================
# Phase 6.2 面试复盘 → 匹配模型修正（Stage 1.5 mixer 输入）
# 默认关闭：仅当显式传入 --history <career_log.jsonl> 时启用；
# 不传则 stage1_score 完全不变（向后兼容）。确定性、离线、零 LLM。
# ============================================================

def _read_career_jsonl(path: str) -> list[dict]:
    """逐行解析 career_log.jsonl（容错：跳过空行/非法 JSON）。"""
    events: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return events


def analyze_career_history(history_path: str, config: dict | None = None) -> dict:
    """把 career_log.jsonl 复盘数据解析为可执行的校准信号。

    返回：
        boost_terms         被高频追问/被指出短板/复盘学到的方向关键词（去重、按频次降序）
        low_pass_directions 面试通过率偏低的「方向」（≥ min_interviews_for_penalty 且 < 0.5）
        n_interviews        有效面试复盘事件数
        stats               调试用统计
    """
    cfg = config or PIPELINE_CFG.get("history_calibration", {})
    min_n = int(cfg.get("min_interviews_for_penalty", 2))
    pass_set = {str(x).lower() for x in cfg.get("pass_results", ["pass"])}
    fail_set = {str(x).lower() for x in cfg.get("fail_results", ["fail"])}

    boost_counter: dict[str, int] = {}
    direction_results: dict[str, list[str]] = {}
    n_interviews = 0

    for ev in _read_career_jsonl(history_path):
        etype = ev.get("type", "")
        if etype == "interview_done":
            n_interviews += 1
            for key in ("strong_points", "weak_points", "learnings"):
                for term in (ev.get(key) or []):
                    if isinstance(term, str) and term.strip():
                        boost_counter[term.strip()] = boost_counter.get(term.strip(), 0) + 1
            # 方向通过率：以 role / direction 归一为 key
            direction = ev.get("role") or ev.get("direction") or ev.get("company")
            if direction:
                direction = str(direction).strip()
                res = str(ev.get("result", "")).lower()
                bucket = direction_results.setdefault(direction, [])
                if res in pass_set:
                    bucket.append("pass")
                elif res in fail_set:
                    bucket.append("fail")
        elif etype == "match_round":
            # match_round 主要沉淀匹配理由，方向信号以 interview_done 为准
            pass

    boost_terms = [t for t, _ in sorted(boost_counter.items(),
                                        key=lambda kv: (-kv[1], kv[0]))]
    low_pass_directions = []
    for d, results in direction_results.items():
        total = len(results)
        if total >= min_n:
            passes = results.count("pass")
            if passes / total < 0.5:
                low_pass_directions.append(d)

    return {
        "boost_terms": boost_terms,
        "low_pass_directions": low_pass_directions,
        "n_interviews": n_interviews,
        "stats": {
            "boost_term_count": len(boost_terms),
            "direction_results": {d: {"total": len(r), "pass": r.count("pass")}
                                  for d, r in direction_results.items()},
        },
    }


def compute_history_delta(job: dict, analysis: dict, config: dict | None = None) -> tuple[float, str]:
    """根据复盘信号计算单个岗位的 stage1_score 调整量（确定性）。

    命中的复盘强化方向 → 加分（封顶 max_boost）；
    命中的低通过率方向 → 扣分（封顶 max_penalty）；
    返回 (delta, reason)。
    """
    cfg = config or PIPELINE_CFG.get("history_calibration", {})
    boost_per_hit = float(cfg.get("boost_per_hit", 4.0))
    max_boost = float(cfg.get("max_boost", 12.0))
    penalty = float(cfg.get("penalty", 8.0))
    max_penalty = float(cfg.get("max_penalty", 12.0))

    title = (job.get("title") or "")
    dept = (job.get("department") or "")
    ftext = (job.get("full_text") or "")
    text = f"{title} {dept} {ftext}".lower()

    boost_total = 0.0
    reasons = []
    for term in analysis.get("boost_terms", []):
        if str(term).lower() in text:
            boost_total += boost_per_hit
            reasons.append(f"复盘强化:{term}")
    boost_total = min(boost_total, max_boost)

    penalty_total = 0.0
    for d in analysis.get("low_pass_directions", []):
        if str(d).lower() in text:
            penalty_total += penalty
            reasons.append(f"复盘低通过率:{d}")
    penalty_total = min(penalty_total, max_penalty)

    delta = round(boost_total - penalty_total, 2)
    return delta, "; ".join(reasons)


def _apply_history_calibration(all_scored: list, history_path: str) -> dict:
    """就地把复盘校准施加到 all_scored（修改 stage1_score + 附加 history_delta/signal）。

    返回 analysis 供输出元数据使用。仅当 --history 传入时调用。
    """
    cfg = PIPELINE_CFG.get("history_calibration", {})
    analysis = analyze_career_history(history_path, cfg)
    for j in all_scored:
        delta, reason = compute_history_delta(j, analysis, cfg)
        j["history_delta"] = delta
        j["history_signal"] = reason
        j["stage1_score"] = max(0.0, min(100.0, j["stage1_score"] + delta))
    print(f"  复盘校准：{analysis['n_interviews']} 条面试复盘 → "
          f"强化方向 {len(analysis['boost_terms'])} 个，"
          f"低通过率方向 {len(analysis['low_pass_directions'])} 个")
    return analysis


def _attach_behavior_fit(analyzed, args):
    """N5：计算每岗位 behavior_fit 并挂到 analyzed；enabled 时按权重微调 score。"""
    bf_cfg = PIPELINE_CFG.get("behavior_fit", {}) or {}
    bf_enabled = bool(bf_cfg.get("enabled", False))
    bf_weight = float(bf_cfg.get("weight", 0.10))
    bf_path = getattr(args, "behavior_profile", None) or DEFAULT_BEHAVIOR_PROFILE
    profile = load_behavioral_profile(bf_path)
    for job in analyzed:
        ft = job.get("full_text", "")
        bf = compute_behavior_fit(ft, profile)
        job["behavior_fit"] = bf
        if bf_enabled:
            delta = (bf["score"] - 0.5) * bf_weight * 100.0
            job["score"] = max(0.0, min(100.0, job["score"] + delta))
            bf["applied_delta"] = round(delta, 2)


def _maybe_notify_summary(output, args):
    """B2：评分完成后推送摘要（webhook 来自 --wecom 或 WECOM_WEBHOOK；空则跳过）。"""
    if getattr(args, "suppress_summary_notify", False):
        return
    wh = getattr(args, "wecom", None) or os.environ.get("WECOM_WEBHOOK")
    if not wh:
        return
    try:
        from notify_wecom import notify
    except ImportError:
        return
    recs = output.get("recommendations", {}) or {}
    total = sum(len(v) for v in recs.values() if isinstance(v, list))
    a = len(recs.get("tier_A", []) or [])
    b = len(recs.get("tier_B", []) or [])
    notify("smart_score", f"评分完成：{total} 岗（A {a} / B {b}）", wh)


async def run_pipeline(args, tracer: "ExecutionTracer | None" = None) -> dict:
    """执行完整的六阶段评分 pipeline"""
    print("=" * 60)
    print("Smart Score — 六阶段智能评分 Pipeline")
    print("=" * 60)

    # 加载输入
    candidate_summary = Path(args.summary).read_text(encoding="utf-8")
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    jobs = parse_jobs_raw(args.jobs)
    print(f"\n输入: {len(jobs)} 个 JD | Profile: {profile.get('role_type', 'unknown')}")
    if getattr(args, "jd_trust_report", False):
        _print_jd_trust_report(jobs)

    # 自动生成 prompts
    direction_anchor = build_direction_anchor(profile)
    domain_knowledge = build_domain_knowledge(profile)
    print(f"方向锚定: {direction_anchor}")

    top_k = args.top_k

    # Pre-Filter: 确定性预过滤（在花 token 之前排除明显不匹配的 JD）
    print("\n[Pre-Filter] 确定性预过滤")
    from pre_filter import pre_filter
    filter_config = {
        "include_intern": getattr(args, "include_intern", False),
        "include_outsource": getattr(args, "include_outsource", False),
        "max_year_requirement": getattr(args, "max_year_requirement", 10),
        # Phase 4.3：质量守门，正文过短（<100字）直接丢弃，不进 Stage 1 浪费 token
        "min_jd_chars": getattr(args, "min_jd_chars", 100),
    }
    jobs, prefilter_stats = pre_filter(jobs, profile, exclude_english_hard=True, config=filter_config)
    print(f"  过滤后: {len(jobs)} 个 JD 进入 Stage 1")

    # Stage 1: 全量粗筛（支持 checkpoint 恢复）
    provider = getattr(args, 'provider', None)
    resume = getattr(args, 'resume', False)
    stage1_ckpt = _load_checkpoint(args.output, "stage1") if resume else None
    stage1_stats = None  # T1: 由 stage1() 返回；从 checkpoint 恢复时不重建

    if stage1_ckpt:
        print("\n[Stage 1] ⏩ 从 checkpoint 恢复（跳过）")
        all_scored = stage1_ckpt["all_scored"]
        top_jobs = stage1_ckpt["top_jobs"]
        wall1 = stage1_ckpt.get("wall_time", 0)
    else:
        print(f"\n[Stage 1] 全量评分 | {args.stage1_model} | 并发={args.concurrency} | provider={provider or 'default'}")
        client1 = LLMClient(model=args.stage1_model, max_concurrent=args.concurrency, provider=provider)
        start = time.time()

        def progress1(done, total):
            print(f"  进度: {done}/{total}")

        all_scored, stage1_stats = await stage1(client1, candidate_summary, direction_anchor, jobs, progress1, tracer=tracer)
        wall1 = time.time() - start

        # 分数分布
        scores = [j["stage1_score"] for j in all_scored]
        from collections import Counter
        score_dist = Counter(scores)
        print(f"\n  Stage 1 完成: {wall1:.1f}s")
        if scores:
            print(f"  分数范围: {min(scores):.0f} - {max(scores):.0f} | 不同分值: {len(score_dist)}")
        else:
            print("  分数范围: 无有效岗位（全部被预过滤丢弃）")
        print(f"  Tokens: {client1.total_input_tokens} in / {client1.total_output_tokens} out")

    # 6.2 Stage 1.5 mixer 输入：接入 career_log 复盘（默认关闭，仅 --history 时启用）。
    # 不传 --history 时 stage1_score 完全不变（向后兼容）。
    history_analysis = None
    if getattr(args, "history", None):
        history_analysis = _apply_history_calibration(all_scored, args.history)

    # 取 Top K（统一，不论是否 resume；并列分数时用 direction_score 做 tiebreaker，
    # 确保与候选人方向高匹配的 JD 优先进入 Stage 2）
    for j in all_scored:
        j["_tiebreaker"] = j.get("pre_filter_meta", {}).get("direction_score", 0)
    all_scored.sort(key=lambda x: (x["stage1_score"], x["_tiebreaker"]), reverse=True)
    top_jobs = all_scored[:top_k]
    print(f"\n  进入 Stage 2: Top {min(top_k, len(all_scored))} (截断分≥{top_jobs[-1]['stage1_score']:.0f})")

    if not stage1_ckpt:
        # 保存 Stage 1 checkpoint（含复盘校准后的全量分数）
        _save_checkpoint(args.output, "stage1", {
            "all_scored": all_scored, "top_jobs": top_jobs, "wall_time": wall1
        })

    # Stage 1.5: 动态辨别知识生成
    print(f"\n[Stage 1.5] 动态辨别知识生成 | {args.stage2_model}")
    client_cal = LLMClient(model=args.stage2_model, max_concurrent=1, provider=provider)
    start = time.time()
    top_titles = [j["title"] for j in top_jobs]
    calibration_knowledge = await generate_calibration_knowledge(
        client_cal, profile, top_titles)
    wall_cal = time.time() - start
    print(f"  完成: {wall_cal:.1f}s | {len(calibration_knowledge)}字")
    print(f"  预览: {calibration_knowledge[:120]}...")

    # Stage 2: 精排
    s2_concurrency = getattr(args, 'stage2_concurrency', 2)
    print(f"\n[Stage 2] 精排 + 风险标注 | {args.stage2_model} | 组并发={s2_concurrency}")
    client2 = LLMClient(model=args.stage2_model, max_concurrent=s2_concurrency, provider=provider)
    start = time.time()
    stage2_failures = 0  # T1: 由 stage2() 返回

    def progress2(done, total):
        print(f"  进度: {done}/{total}")

    analyzed, stage2_failures = await stage2(client2, candidate_summary, domain_knowledge,
                           calibration_knowledge, profile, top_jobs, progress2, tracer=tracer)
    wall2 = time.time() - start

    # 统计（Stage 2 原始结果）
    s2_tier_a = sum(1 for j in analyzed if j["tier"] == "A")
    s2_tier_b = sum(1 for j in analyzed if j["tier"] == "B")
    s2_tier_c = sum(1 for j in analyzed if j["tier"] == "C")

    print(f"\n  Stage 2 完成: {wall2:.1f}s")
    print(f"  Stage 2 分档（后处理前）: A={s2_tier_a} | B={s2_tier_b} | C={s2_tier_c}")
    print(f"  Tokens: {client2.total_input_tokens} in / {client2.total_output_tokens} out")

    # Stage 2.5: 全局重排（解决组间分数不可比问题）
    # 对全部进入 Stage 2 的岗位做全局排序，不只是 A 档
    if len(analyzed) >= 3:
        print(f"\n[Stage 2.5] 全局重排 | {args.stage2_model} | {len(analyzed)} 个候选")
        client_rerank = LLMClient(model=args.stage2_model, max_concurrent=3, provider=provider)
        start_rerank = time.time()
        analyzed = await global_rerank(
            client_rerank, candidate_summary, calibration_knowledge,
            profile, analyzed)
        wall_rerank = time.time() - start_rerank
        print(f"  完成: {wall_rerank:.1f}s")
        print(f"  重排后分数范围: {analyzed[-1]['score']:.0f} - {analyzed[0]['score']:.0f}")
        # 根据全局重排的新分数重新分档
        for j in analyzed:
            if j.get("global_rank") and j["global_rank"] != 999:
                if j["score"] >= PIPELINE_CFG["tiers"]["A"]:
                    j["tier"] = "A"
                elif j["score"] >= PIPELINE_CFG["tiers"]["B"]:
                    j["tier"] = "B"
                else:
                    j["tier"] = "C"
    else:
        print(f"\n[Stage 2.5] 跳过全局重排（候选数不足: {len(analyzed)}）")
        wall_rerank = 0

    # Post-Judge: 确定性后处理
    print("\n[Post-Judge] 确定性后处理（英语/核心团队/技术依赖/分布约束）")
    from post_judge import post_judge
    analyzed = post_judge(analyzed, profile, config=PIPELINE_CFG.get("post_judge"))

    # N5 行为×ATS 拟合：诊断字段接入 +（可选）权重微调（须在 full_text 弹出前）
    _attach_behavior_fit(analyzed, args)

    # 清除 full_text（仅供 post_judge 检测使用，不写入最终输出）
    for j in analyzed:
        j.pop("full_text", None)

    # 最终统计
    tier_a = [j for j in analyzed if j["tier"] == "A"]
    tier_b = [j for j in analyzed if j["tier"] == "B"]
    tier_c = [j for j in analyzed if j["tier"] == "C"]

    # 组装输出
    rerank_count = len(analyzed) if wall_rerank > 0 else 0
    output = {
        "generated_at": datetime.now().isoformat(),
        "pipeline": {
            "stage1": {"model": args.stage1_model, "total_jobs": len(jobs),
                      "top_k": top_k, "wall_time": round(wall1, 1)},
            "stage1_5": {"model": args.stage2_model,
                        "wall_time": round(wall_cal, 1),
                        "calibration_knowledge_length": len(calibration_knowledge)},
            "stage2": {"model": args.stage2_model, "analyzed": len(analyzed),
                      "wall_time": round(wall2, 1),
                      "mode": "listwise", "group_size": PIPELINE_CFG["stage2"]["group_size"]},
            "stage2_5": {"model": args.stage2_model,
                        "reranked": rerank_count,
                        "wall_time": round(wall_rerank, 1) if rerank_count else 0},
            "post_judge": {
                "penalties_applied": sum(1 for j in analyzed if j.get("post_penalties")),
                "rules": ["english_gate", "core_team_edu", "tech_dependency", "distribution"]
            },
            # Phase 6.2 面试复盘 → 匹配模型修正（默认关闭，仅 --history 时启用）
            "history_calibration": {
                "enabled": history_analysis is not None,
                "history_path": getattr(args, "history", None),
                "n_interviews": history_analysis["n_interviews"] if history_analysis else 0,
                "boost_terms": history_analysis["boost_terms"] if history_analysis else [],
                "low_pass_directions": history_analysis["low_pass_directions"] if history_analysis else [],
            },
            "direction_anchor": direction_anchor,
        },
        "summary": {
            "tier_A": len(tier_a),
            "tier_B": len(tier_b),
            "tier_C": len(tier_c),
        },
        "recommendations": {
            "tier_A": tier_a,
            "tier_B": tier_b,
            "tier_C": tier_c,
        },
        # 保留全量 Stage 1 分数（供后续分析）
        "stage1_all_scores": [
            {"job_id": j["job_id"], "title": j["title"], "score": j["stage1_score"]}
            for j in all_scored
        ],
    }

    # T1.5: 管线降级/失败元信息（供下游报告与监控消费）
    output["metadata"] = {
        "stage1_stats": {
            "total": stage1_stats.total if stage1_stats else 0,
            "succeeded": stage1_stats.succeeded if stage1_stats else 0,
            "failed": stage1_stats.failed if stage1_stats else 0,
            "fallback": stage1_stats.fallback if stage1_stats else 0,
            "failure_rate": round(stage1_stats.failure_rate, 3) if stage1_stats else 0.0,
        },
        "degraded": (stage1_stats is not None and stage1_stats.failed > 0) or stage2_failures > 0,
        "pre_filter": {
            "total_input": prefilter_stats.get("total_input", 0),
            "passed": prefilter_stats.get("passed", 0),
            "filtered_short_count": prefilter_stats.get("filtered_short_count", 0),
            "filtered_spam_count": prefilter_stats.get("filtered_spam_count", 0),
        },
        "pipeline_version": "3.0.0",
        "timestamp": datetime.now().isoformat(),
    }

    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {output_path}")

    # 清理 checkpoint（Pipeline 成功完成）
    _clean_checkpoints(args.output)

    # 打印推荐摘要
    print(f"\n{'='*60}")
    print("推荐摘要")
    print(f"{'='*60}")

    if tier_a:
        print(f"\n🟢 A档 — 强烈推荐（{len(tier_a)}个）")
        for j in tier_a:
            print(f"  [{j['score']:.0f}] {j['title']}")
            if j["risks"]:
                print(f"      ⚠ {j['risks'][0]}")

    if tier_b:
        print(f"\n🟡 B档 — 可以考虑（{len(tier_b)}个）")
        for j in tier_b[:8]:
            print(f"  [{j['score']:.0f}] {j['title']}")

    print(f"\n⚪ C档: {len(tier_c)}个迁移较远")
    print(f"\n总耗时: {wall1 + wall_cal + wall2 + wall_rerank:.1f}s (S1={wall1:.0f}s + S1.5={wall_cal:.0f}s + S2={wall2:.0f}s + S2.5={wall_rerank:.0f}s)")

    # B2 企业微信推送（webhook 空则跳过，绝不中断主流程）
    _maybe_notify_summary(output, args)

    return output


def dry_run(args):
    """预览模式：计算预估成本和耗时，不调用 LLM"""
    print("=" * 60)
    print("Smart Score — Dry Run（预览模式，不消耗 token）")
    print("=" * 60)

    # 加载输入
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    jobs = parse_jobs_raw(args.jobs)
    total_jobs = len(jobs)
    print(f"\n输入: {total_jobs} 条 JD | Profile: {profile.get('role_type', 'unknown')}")
    if getattr(args, "jd_trust_report", False):
        _print_jd_trust_report(jobs)
    print(f"配置: group_size={PIPELINE_CFG['stage2']['group_size']} | "
          f"batch_size={PIPELINE_CFG['stage1']['batch_size']} | "
          f"truncation(stage1)={PIPELINE_CFG['stage1']['truncation_chars']} | "
          f"tier A/B={PIPELINE_CFG['tiers']['A']}/{PIPELINE_CFG['tiers']['B']}")

    # Pre-Filter 预估
    from pre_filter import pre_filter
    filter_config = {
        "include_intern": getattr(args, "include_intern", False),
        "include_outsource": getattr(args, "include_outsource", False),
        "max_year_requirement": getattr(args, "max_year_requirement", 10),
        # Phase 4.3：质量守门，正文过短（<100字）直接丢弃，不进 Stage 1 浪费 token
        "min_jd_chars": getattr(args, "min_jd_chars", 100),
    }
    filtered, stats = pre_filter(jobs, profile, exclude_english_hard=True, config=filter_config)
    after_filter = len(filtered)

    top_k = min(args.top_k, after_filter)
    stage2_groups = math.ceil(top_k / PIPELINE_CFG["stage2"]["group_size"])

    # Token 预估（基于历史数据的经验值）
    s1_input_per_job = 600   # system + user prompt 平均 tokens
    s1_output_per_job = 150  # JSON response
    s1_total = after_filter * (s1_input_per_job + s1_output_per_job)

    s15_tokens = 2000  # Stage 1.5 辨别知识

    s2_input_per_group = 4000   # system + 6 个 JD
    s2_output_per_group = 2000  # JSON array response
    s2_total = stage2_groups * (s2_input_per_group + s2_output_per_group)

    s25_tokens = top_k * 400  # 全局重排

    total_tokens = s1_total + s15_tokens + s2_total + s25_tokens

    # 耗时预估（基于并发度）
    s1_time = math.ceil(after_filter / args.concurrency) * 2  # 每批约 2 秒
    s2_concurrency = getattr(args, 'stage2_concurrency', 2)
    s2_time = math.ceil(stage2_groups / s2_concurrency) * 8  # 每批约 8 秒
    s25_time = 15 if top_k > 15 else 8
    total_time = s1_time + 5 + s2_time + s25_time  # +5 for Stage 1.5

    # 成本预估（粗略，gpt-4o-mini ~0.15/1M in, 0.6/1M out; gpt-4.1-mini ~0.4/1M in, 1.6/1M out）
    s1_cost = (after_filter * s1_input_per_job * 0.15 + after_filter * s1_output_per_job * 0.6) / 1_000_000
    s2_cost = (stage2_groups * s2_input_per_group * 0.4 + stage2_groups * s2_output_per_group * 1.6) / 1_000_000
    total_cost = s1_cost + s2_cost

    print(f"\n{'─' * 50}")
    print("Pre-Filter:")
    print(f"  输入 {total_jobs} → 过滤后 {after_filter} 条进入 Stage 1")
    print(f"  排除: 实习={stats['excluded_intern']} 外包={stats['excluded_outsource']} "
          f"英语={stats['excluded_english']} 年限={stats['excluded_experience']}")
    print("\nStage 1 (全量粗筛):")
    print(f"  模型: {args.stage1_model} | 并发: {args.concurrency}")
    print(f"  调用次数: {after_filter} | 预估 tokens: ~{s1_total:,}")
    print(f"  预估耗时: ~{s1_time}s")
    print("\nStage 1.5 (辨别知识):")
    print(f"  模型: {args.stage2_model} | 预估 tokens: ~{s15_tokens:,}")
    print("\nStage 2 (精排):")
    print(f"  模型: {args.stage2_model} | 组并发: {s2_concurrency}")
    print(f"  Top-K: {top_k} → {stage2_groups} 组 × {PIPELINE_CFG['stage2']['group_size']} 个/组")
    print(f"  预估 tokens: ~{s2_total:,} | 预估耗时: ~{s2_time}s")
    print("\nStage 2.5 (全局重排):")
    print(f"  预估 tokens: ~{s25_tokens:,} | 预估耗时: ~{s25_time}s")
    print(f"\n{'─' * 50}")
    print("总预估:")
    print(f"  Tokens: ~{total_tokens:,}")
    print(f"  耗时:   ~{total_time}s ({total_time // 60}分{total_time % 60}秒)")
    print(f"  成本:   ~¥{total_cost:.2f} (按 gpt-4o-mini/gpt-4.1-mini 公价估算)")
    print("\n提示: 实际调用请去掉 --dry-run 参数")


def _print_trace_summary(tracer: "ExecutionTracer"):
    """打印执行 Trace 摘要（T6 基础版；T7 增加成本行）。"""
    s = tracer.summary()
    print("\n" + "=" * 60)
    print("执行 Trace 摘要")
    print("=" * 60)
    print(f"  运行ID     : {s['run_id']}")
    print(f"  墙钟时间   : {s['wall_seconds']}s")
    print(f"  调用次数   : {s['total_calls']}")
    print(f"  失败次数   : {s['total_failures']}")
    print(f"  总 Token   : {s['total_input_tokens']} in / {s['total_output_tokens']} out")
    print(f"  预估成本   : ${s['estimated_cost_usd']:.6f} USD")
    print(f"  Trace 文件 : {s['trace_file']}")


def main():
    # 强制行缓冲，确保后台运行时日志实时输出
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, line_buffering=True)

    parser = argparse.ArgumentParser(description="六阶段智能评分 Pipeline")
    parser.add_argument("--jobs", required=True, help="jobs_raw.txt 路径")
    parser.add_argument("--profile", required=True, help="boundary_profile.json 路径")
    parser.add_argument("--summary", required=True, help="candidate_summary.txt 路径")
    parser.add_argument("--output", required=True, help="输出结果 JSON 路径")
    parser.add_argument("--top-k", type=int, default=50, help="Stage 1 → Stage 2 的数量（默认50）")
    parser.add_argument("--stage1-model", default="gpt-4o-mini", help="Stage 1 模型")
    parser.add_argument("--stage2-model", default="gpt-4.1-mini", help="Stage 2 模型")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数")
    parser.add_argument("--provider", default=None, help="LLM provider (friday/sub2api)，默认从环境变量 LLM_PROVIDER 读取")
    parser.add_argument("--behavior-profile", default=None,
                        help="候选行为画像 JSON（N5）；缺省读 config/behavioral_profile.json")
    parser.add_argument("--history", default=None,
                        help="career_log.jsonl 路径（Phase 6.2 面试复盘→匹配修正）；缺省关闭，向后兼容")
    parser.add_argument("--wecom", default=None,
                        help="企业微信群机器人 key（B2）；缺省读 WECOM_WEBHOOK；空则跳过")
    parser.add_argument("--resume", action="store_true", help="从 checkpoint 恢复（跳过已完成的阶段）")
    parser.add_argument("--stage2-concurrency", type=int, default=2, help="Stage 2 分组并发数（默认2）")
    parser.add_argument("--include-intern", action="store_true", help="保留实习岗（默认排除）")
    parser.add_argument("--include-outsource", action="store_true", help="保留外包岗（默认排除）")
    parser.add_argument("--max-year-requirement", type=int, default=10, help="超过此年限要求的 JD 才被排除（默认10）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式：只打印预估成本和耗时，不实际调用 LLM")
    parser.add_argument("--config", type=str, default=None,
                        help="管线配置文件路径（默认 config/pipeline.yaml）")
    parser.add_argument("--timeout", type=int, default=None,
                        help="管线整体超时（秒），默认取 config/pipeline.yaml 的 pipeline.timeout_seconds；显式指定则覆盖")
    parser.add_argument("--jd-trust-report", action="store_true",
                        help="P5: 打印每条 JD 的零信任扫描结果（注入信号/清洗动作），不消耗 token")

    args = parser.parse_args()

    # T5：加载配置，CLI 参数覆盖 YAML
    global PIPELINE_CFG
    cfg = load_config(args.config)
    if args.stage1_model:
        cfg["stage1"]["model"] = args.stage1_model
    if args.stage2_model:
        cfg["stage2"]["model"] = args.stage2_model
    PIPELINE_CFG = cfg  # 全局覆盖（模块函数通过 PIPELINE_CFG 读取）
    if args.timeout is None:
        args.timeout = cfg["pipeline"]["timeout_seconds"]

    # T6：执行 Trace —— 每次运行产生一个 JSONL trace 文件
    tracer = ExecutionTracer(output_dir=".traces")
    try:
        if args.dry_run:
            dry_run(args)
        else:
            asyncio.run(asyncio.wait_for(run_pipeline(args, tracer=tracer), timeout=args.timeout))
    except asyncio.TimeoutError:
        print(f"\n[错误] 管线超时（{args.timeout}s）。已保存 checkpoint，可用 --resume 继续。",
              file=sys.stderr)
        sys.exit(2)
    except PipelineAbortError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        sys.exit(3)
    finally:
        _print_trace_summary(tracer)


if __name__ == "__main__":
    main()
