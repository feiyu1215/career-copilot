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

import os
import sys
import json
import time
import math
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

# 添加 scripts 目录到路径（复用 job_parser + 共享模块）
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from llm_client import LLMClient  # noqa: E402


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
        text = blocks[i + 1].strip()
        if not text:
            continue

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
        })

    return jobs


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


def _parse_json_array(text: str) -> list[dict]:
    """从 LLM 输出中提取 JSON 数组。供 Stage 2 Listwise 使用。"""
    import re
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

    return profile.get("role_type", "AI产品")


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

def build_stage1_system(direction_anchor: str) -> str:
    return f"""你是一位资深求职匹配顾问。评估候选人与岗位的匹配度。

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
- 表面关键词相似但方向不同的岗位应该低分"""


async def stage1(client: LLMClient, candidate_summary: str,
                 direction_anchor: str, jobs: list[dict],
                 progress_callback=None) -> list[dict]:
    """Stage 1: 全量评分"""
    system_prompt = build_stage1_system(direction_anchor)

    async def eval_one(job: dict) -> dict:
        user_prompt = f"""{candidate_summary}

---
## 待评估岗位
**标题**：{job['title']}
**部门**：{job['department']} | **城市**：{job['location']}
**描述**：
{job['full_text'][:1500]}
---
评分并返回 JSON：{{"score": <0-100整数，避免整十数>, "reasoning": "<30字以内理由>"}}
只返回 JSON。"""

        content = await client.chat(system_prompt, user_prompt,
                                    temperature=0.0, max_tokens=150)
        result = _parse_json(content)
        is_fallback = result is None or "score" not in result
        score = result.get("score", 30) if result else 30
        reasoning = result.get("reasoning", "") if result else ""
        if is_fallback:
            print(f"  [WARN] JD '{job.get('title', '?')[:20]}' 评分解析失败，使用默认分 30",
                  file=sys.stderr)
        return {**job, "stage1_score": float(score), "stage1_reasoning": reasoning,
                "is_fallback": is_fallback}

    scored = []
    batch_size = 25
    for i in range(0, len(jobs), batch_size):
        batch = [eval_one(jobs[j]) for j in range(i, min(i + batch_size, len(jobs)))]
        results = await asyncio.gather(*batch, return_exceptions=True)
        for r in results:
            if not isinstance(r, Exception):
                scored.append(r)
        if progress_callback:
            progress_callback(min(i + batch_size, len(jobs)), len(jobs))

    scored.sort(key=lambda x: x["stage1_score"], reverse=True)
    return scored


# ============================================================
# Stage 1.5: 动态辨别知识生成（针对 Top K 的具体 JD）
# ============================================================

CALIBRATION_SYSTEM = """你是一位资深行业分析师。给定候选人的能力边界画像和一批通过初筛的岗位标题，你需要生成"辨别知识"——帮助后续精排模型区分哪些岗位是真匹配、哪些是表面相似但实际不同。

## 输出格式
输出一段文字（200-400字），包含：
1. 具体的"≠"判断（如：火山方舟的RAG产品 ≠ 业务侧RAG优化，前者是平台infra）
2. 容易混淆的岗位标题及其真实含义
3. 需要特别注意的业务线/部门差异

不需要覆盖所有岗位，只写最容易误判的 5-10 个case。直接输出文字，不需要JSON。"""


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

    return f"""你是一位资深行业猎头，对各大互联网公司的业务线非常熟悉。

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
4. score：0-100（组内排名第1的可以是 90-97，最后一名不应超过 75）
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

输出 JSON 数组，按 rank 排列。只返回 JSON。"""


async def stage2(client: LLMClient, candidate_summary: str,
                 domain_knowledge: str, calibration_knowledge: str,
                 profile: dict, top_jobs: list[dict],
                 progress_callback=None) -> list[dict]:
    """Stage 2: Listwise 分组精排 + 风险标注"""
    GROUP_SIZE = 6  # 每组 6 个岗位，模型可以有效对比

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
{job['full_text'][:1800]}
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

        content = await client.chat(system_prompt, user_prompt,
                                    temperature=0.0, max_tokens=2000)

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
                print(f"  [警告] 一组评估失败: {r}", file=sys.stderr)
        if progress_callback:
            done = min((i + concurrent_groups) * GROUP_SIZE, len(top_jobs))
            progress_callback(done, len(top_jobs))

    # 全局排序：先按 tier，再按 score
    tier_order = {"A": 0, "B": 1, "C": 2}
    all_analyzed.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x["score"]))
    return all_analyzed


# ============================================================
# Stage 2.5: 全局重排（解决组间分数不可比问题）
# ============================================================

GLOBAL_RERANK_SYSTEM = """你是一位资深行业猎头，需要对候选人与多个岗位的匹配度做**全局排序**。

## 核心任务

你将看到一批已经通过初步筛选的高匹配岗位。你需要将它们从"最适合候选人"到"相对没那么适合"做一个**严格的全局排序**。

## 排序标准（按优先级）

1. **经验迁移距离**：候选人已有经验到岗位核心职责的迁移距离越短，排名越高
2. **职责覆盖度**：候选人能覆盖 JD 中列出的核心职责的比例越高越好
3. **信号词精确匹配**：JD 中出现候选人精确信号词（而非泛化关键词）的密度越高越好
4. **方向契合度**：岗位方向与候选人核心方向的重叠程度

## 强制规则

1. **绝对不允许并列**：每个岗位必须有唯一的排名，不能有两个岗位排名相同
2. **必须拉开分差**：排名第 1 和排名最后的分数差距必须 ≥ 20 分
3. **分数必须唯一**：每个岗位的分数必须不同（至少差 1 分）
4. **分数区间**：排名第 1 给 97 分，最后一名不超过 72 分，中间线性分布
5. **你的排序就是最终排序**，请慎重考虑每一个位置

## 输出格式

JSON 数组，按 rank 从 1 到 N 排列：
[
  {"job_id": "JOB_X", "rank": 1, "score": 97, "one_line_reason": "一句话说明为什么排第一"},
  {"job_id": "JOB_Y", "rank": 2, "score": 95, "one_line_reason": "..."},
  ...
]

只返回 JSON 数组，不要其他内容。"""


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

        content = await client.chat(GLOBAL_RERANK_SYSTEM, user_prompt,
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
            mid_score = (score_high + score_low) / 2
            for i, mid in enumerate(missing_ids):
                returned_map[mid] = {"rank": 50 + i, "score": mid_score - i * 0.5, "reason": ""}

        return returned_map

    if len(candidates) <= 15:
        # 单次全局重排
        rank_map = await rerank_batch(candidates, 97, 55)
    else:
        # 分层重排：按 Stage 2 原始 tier 分三层，每层独立排序
        tier_a_jobs = [j for j in candidates if j["tier"] == "A"]
        tier_b_jobs = [j for j in candidates if j["tier"] == "B"]
        tier_c_jobs = [j for j in candidates if j["tier"] == "C"]

        print(f"    分层重排: A={len(tier_a_jobs)} | B={len(tier_b_jobs)} | C={len(tier_c_jobs)}")

        # 并发执行三层重排（只对非空层）
        layer_configs = [
            (tier_a_jobs, 97, 85),  # A 层
            (tier_b_jobs, 84, 72),  # B 层
            (tier_c_jobs, 71, 55),  # C 层
        ]

        tasks = [rerank_batch(jobs, hi, lo) for jobs, hi, lo in layer_configs if jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并所有层结果
        rank_map = {}
        for r in results:
            if isinstance(r, dict):
                rank_map.update(r)

    # 应用全局重排结果
    for job in candidates:
        jid = job["job_id"]
        if jid in rank_map:
            job["global_rank"] = rank_map[jid]["rank"]
            job["score"] = rank_map[jid]["score"]  # 覆盖组内分数
            job["rerank_reason"] = rank_map[jid].get("reason", "")
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
        print(f"  [checkpoint] 已清理")


async def run_pipeline(args) -> dict:
    """执行完整的六阶段评分 pipeline"""
    print("=" * 60)
    print("Smart Score — 六阶段智能评分 Pipeline")
    print("=" * 60)

    # 加载输入
    candidate_summary = Path(args.summary).read_text(encoding="utf-8")
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    jobs = parse_jobs_raw(args.jobs)
    print(f"\n输入: {len(jobs)} 个 JD | Profile: {profile.get('role_type', 'unknown')}")

    # 自动生成 prompts
    direction_anchor = build_direction_anchor(profile)
    domain_knowledge = build_domain_knowledge(profile)
    print(f"方向锚定: {direction_anchor}")

    top_k = args.top_k

    # Pre-Filter: 确定性预过滤（在花 token 之前排除明显不匹配的 JD）
    print(f"\n[Pre-Filter] 确定性预过滤")
    from pre_filter import pre_filter
    filter_config = {
        "include_intern": getattr(args, "include_intern", False),
        "include_outsource": getattr(args, "include_outsource", False),
        "max_year_requirement": getattr(args, "max_year_requirement", 10),
    }
    jobs, prefilter_stats = pre_filter(jobs, profile, exclude_english_hard=True, config=filter_config)
    print(f"  过滤后: {len(jobs)} 个 JD 进入 Stage 1")

    # Stage 1: 全量粗筛（支持 checkpoint 恢复）
    provider = getattr(args, 'provider', None)
    resume = getattr(args, 'resume', False)
    stage1_ckpt = _load_checkpoint(args.output, "stage1") if resume else None

    if stage1_ckpt:
        print(f"\n[Stage 1] ⏩ 从 checkpoint 恢复（跳过）")
        all_scored = stage1_ckpt["all_scored"]
        top_jobs = stage1_ckpt["top_jobs"]
        wall1 = stage1_ckpt.get("wall_time", 0)
    else:
        print(f"\n[Stage 1] 全量评分 | {args.stage1_model} | 并发={args.concurrency} | provider={provider or 'default'}")
        client1 = LLMClient(model=args.stage1_model, max_concurrent=args.concurrency, provider=provider)
        start = time.time()

        def progress1(done, total):
            print(f"  进度: {done}/{total}")

        all_scored = await stage1(client1, candidate_summary, direction_anchor, jobs, progress1)
        wall1 = time.time() - start

        # 分数分布
        scores = [j["stage1_score"] for j in all_scored]
        from collections import Counter
        score_dist = Counter(scores)
        print(f"\n  Stage 1 完成: {wall1:.1f}s")
        print(f"  分数范围: {min(scores):.0f} - {max(scores):.0f} | 不同分值: {len(score_dist)}")
        print(f"  Tokens: {client1.total_input_tokens} in / {client1.total_output_tokens} out")

        # 取 Top K（并列分数时用 direction_score 做 tiebreaker，
        # 确保与候选人方向高匹配的 JD 优先进入 Stage 2）
        for j in all_scored:
            j["_tiebreaker"] = j.get("pre_filter_meta", {}).get("direction_score", 0)
        all_scored.sort(key=lambda x: (x["stage1_score"], x["_tiebreaker"]), reverse=True)
        top_jobs = all_scored[:top_k]
        print(f"\n  进入 Stage 2: Top {min(top_k, len(all_scored))} (截断分≥{top_jobs[-1]['stage1_score']:.0f})")

        # 保存 Stage 1 checkpoint
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

    def progress2(done, total):
        print(f"  进度: {done}/{total}")

    analyzed = await stage2(client2, candidate_summary, domain_knowledge,
                           calibration_knowledge, profile, top_jobs, progress2)
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
                if j["score"] >= 85:
                    j["tier"] = "A"
                elif j["score"] >= 72:
                    j["tier"] = "B"
                else:
                    j["tier"] = "C"
    else:
        print(f"\n[Stage 2.5] 跳过全局重排（候选数不足: {len(analyzed)}）")
        wall_rerank = 0

    # Post-Judge: 确定性后处理
    print(f"\n[Post-Judge] 确定性后处理（英语/核心团队/技术依赖/分布约束）")
    from post_judge import post_judge
    analyzed = post_judge(analyzed, profile)

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
                      "mode": "listwise", "group_size": 6},
            "stage2_5": {"model": args.stage2_model,
                        "reranked": rerank_count,
                        "wall_time": round(wall_rerank, 1) if rerank_count else 0},
            "post_judge": {
                "penalties_applied": sum(1 for j in analyzed if j.get("post_penalties")),
                "rules": ["english_gate", "core_team_edu", "tech_dependency", "distribution"]
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

    # Pre-Filter 预估
    from pre_filter import pre_filter
    filter_config = {
        "include_intern": getattr(args, "include_intern", False),
        "include_outsource": getattr(args, "include_outsource", False),
        "max_year_requirement": getattr(args, "max_year_requirement", 10),
    }
    filtered, stats = pre_filter(jobs, profile, exclude_english_hard=True, config=filter_config)
    after_filter = len(filtered)

    top_k = min(args.top_k, after_filter)
    stage2_groups = math.ceil(top_k / 6)

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
    print(f"Pre-Filter:")
    print(f"  输入 {total_jobs} → 过滤后 {after_filter} 条进入 Stage 1")
    print(f"  排除: 实习={stats['excluded_intern']} 外包={stats['excluded_outsource']} "
          f"英语={stats['excluded_english']} 年限={stats['excluded_experience']}")
    print(f"\nStage 1 (全量粗筛):")
    print(f"  模型: {args.stage1_model} | 并发: {args.concurrency}")
    print(f"  调用次数: {after_filter} | 预估 tokens: ~{s1_total:,}")
    print(f"  预估耗时: ~{s1_time}s")
    print(f"\nStage 1.5 (辨别知识):")
    print(f"  模型: {args.stage2_model} | 预估 tokens: ~{s15_tokens:,}")
    print(f"\nStage 2 (精排):")
    print(f"  模型: {args.stage2_model} | 组并发: {s2_concurrency}")
    print(f"  Top-K: {top_k} → {stage2_groups} 组 × 6 个/组")
    print(f"  预估 tokens: ~{s2_total:,} | 预估耗时: ~{s2_time}s")
    print(f"\nStage 2.5 (全局重排):")
    print(f"  预估 tokens: ~{s25_tokens:,} | 预估耗时: ~{s25_time}s")
    print(f"\n{'─' * 50}")
    print(f"总预估:")
    print(f"  Tokens: ~{total_tokens:,}")
    print(f"  耗时:   ~{total_time}s ({total_time // 60}分{total_time % 60}秒)")
    print(f"  成本:   ~¥{total_cost:.2f} (按 gpt-4o-mini/gpt-4.1-mini 公价估算)")
    print(f"\n提示: 实际调用请去掉 --dry-run 参数")


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
    parser.add_argument("--provider", default=None, help="LLM provider (internal/external)，默认从环境变量 LLM_PROVIDER 读取")
    parser.add_argument("--resume", action="store_true", help="从 checkpoint 恢复（跳过已完成的阶段）")
    parser.add_argument("--stage2-concurrency", type=int, default=2, help="Stage 2 分组并发数（默认2）")
    parser.add_argument("--include-intern", action="store_true", help="保留实习岗（默认排除）")
    parser.add_argument("--include-outsource", action="store_true", help="保留外包岗（默认排除）")
    parser.add_argument("--max-year-requirement", type=int, default=10, help="超过此年限要求的 JD 才被排除（默认10）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式：只打印预估成本和耗时，不实际调用 LLM")

    args = parser.parse_args()
    if args.dry_run:
        dry_run(args)
    else:
        asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
