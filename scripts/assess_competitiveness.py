#!/usr/bin/env python3
"""
assess_competitiveness.py — 对 A/B 档岗位进行竞争力评估

为每个推荐岗位评估"投递难度"，帮助用户制定投递策略。

评估维度：
  1. 经验匹配度：JD 要求的经验年限/学历 vs 候选人实际情况
  2. 方向契合度：核心方向是否精确对口（vs 相关但偏）
  3. 竞争激烈程度推断：根据岗位热度信号（大厂核心部门、热门方向等）

输出：为每个岗位标注 stretch/match/safe 三级投递定位：
  - stretch（冲刺）：方向匹配但有明显 gap（如经验不足、核心技能缺一个）
  - match（稳妥）：方向对口 + 能力覆盖 + 风险可控
  - safe（保底）：强匹配 + 竞争压力较小

使用方式：
    python3 assess_competitiveness.py \
        --scored scored_results.json \
        --profile boundary_profile.json \
        --summary candidate_summary.txt \
        --output decision_context.json \
        [--model gpt-4.1-mini]

输入：
  - scored_results.json: smart_score.py 的输出
  - boundary_profile.json: 候选人画像
  - candidate_summary.txt: 候选人摘要

输出：
  - decision_context.json: 含投递定位 + 竞争力分析 + 组合建议
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import Optional

# 共享 LLM 客户端
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from llm_client import LLMClient  # noqa: E402


ASSESSMENT_SYSTEM = """你是一位资深求职策略顾问，帮助候选人评估每个目标岗位的"投递难度"和"录用概率"。

## 你的任务

给定候选人画像和一个 A/B 档岗位（已确认方向匹配），你需要评估：

1. **投递定位**（三选一）：
   - `stretch`（冲刺）：方向匹配但有明显能力 gap。特征：JD 要求的核心技能候选人只有部分覆盖、要求的经验量级超出候选人实际、或岗位竞争极其激烈（大厂明星团队核心岗）
   - `match`（稳妥）：方向精确对口 + 核心能力覆盖 ≥ 70% + 风险可控。特征：候选人的实习经验直接对标 JD 核心职责、缺口在"加分项"而非"必须项"
   - `safe`（保底）：方向匹配 + 能力高度契合或竞争较小。特征：候选人经验覆盖 JD 大部分核心要求、或岗位在非热门部门/非热门城市、或匹配分数 ≥ 93 且风险极少

2. **关键 gap 分析**（1-3 个具体 gap，如"JD 要求搜索排序经验但候选人只有推荐经验"）

3. **面试预判**（一句话：面试中最可能被挑战的点）

4. **置信度**（0.0-1.0：你对这个投递定位判断的确信程度）

## 输出格式（JSON）
```json
{
  "positioning": "stretch/match/safe",
  "confidence": 0.8,
  "gaps": ["具体gap1", "具体gap2"],
  "interview_risk": "面试中最可能被问到的挑战点",
  "reasoning": "一句话解释为什么给这个定位"
}
```

## 判断原则
- 不要因为候选人是实习生就全标 stretch——实习岗本身对经验要求有限，候选人不需要"超配"才能获得 safe
- 重点看"核心职责覆盖"而不是"完美匹配所有要求"
- 大厂核心团队（如头部公司的搜索/配送/推荐等核心业务线）的热门方向岗天然比边缘部门更 stretch
- 如果 A 档评分 ≥ 93 且风险 ≤ 1 个，**必须给 match 或 safe**，不允许全部标 stretch
- 如果 A 档评分在 88-91 或风险 ≥ 2 个，倾向 stretch
- 全局约束：如果 A 档有 ≥ 5 个岗位，其中至少 1 个应为 safe 或 match，不允许全部为 stretch

只输出 JSON。"""


STRATEGY_SYSTEM = """你是一位求职策略顾问。给定候选人的所有推荐岗位及其投递定位（stretch/match/safe），生成一个投递组合建议。

## 原则

1. **风险分散**：不要全投 stretch（容易全军覆没），也不要全投 safe（浪费潜力）
2. **黄金比例**：理想组合约 30% stretch + 50% match + 20% safe（可根据实际岗位分布调整）
3. **时间管理**：推荐优先投递的顺序（考虑 DDL、面试准备重叠度）
4. **实操建议**：如果某个岗位需要特别准备什么、或有时间窗口限制

## 输出格式（JSON）
```json
{
  "strategy_summary": "一段话总结投递策略（50字以内）",
  "recommended_order": [
    {"title": "岗位标题", "positioning": "match", "priority": 1, "reason": "为什么先投这个"}
  ],
  "preparation_tips": [
    {"title": "岗位标题", "tip": "面试这个岗位需要额外准备什么"}
  ],
  "risk_note": "整体风险提示（如果有的话）"
}
```

只输出 JSON。"""


async def assess_single(client, candidate_summary: str, profile: dict,
                         job: dict) -> dict:
    """评估单个岗位的投递难度。

    Args:
        client: LLMClient 实例
        candidate_summary: 候选人摘要文本
        profile: boundary_profile 字典（需含 direction_anchors, hard_negatives）
        job: 单个岗位字典，预期字段：
            - title (str): 岗位标题
            - job_id (str): 岗位 ID（如 "JOB_1"）
            - department (str, optional): 部门
            - location (str, optional): 城市
            - score (float): 匹配分数
            - tier (str): 档位（A/B/C）
            - match_reasons (list[str]): 匹配理由
            - risks (list[str]): 风险标注
            - url (str, optional): 岗位来源链接

    Returns:
        含 positioning/confidence/gaps/interview_risk/reasoning 的评估字典，
        同时透传 job_id/title/tier/score/department/location。
    """
    hard_negatives = profile.get("hard_negatives", [])

    user_prompt = f"""## 候选人摘要
{candidate_summary}

## 候选人核心方向
{', '.join(profile.get('direction_anchors', []))}

## 待评估岗位
**标题**：{job['title']}
**部门**：{job.get('department', '')}
**城市**：{job.get('location', '')}
**匹配分数**：{job.get('score', 0):.0f}/100（{job.get('tier', '?')}档）
**匹配理由**：{', '.join(job.get('match_reasons', []))}
**已知风险**：{', '.join(job.get('risks', []))}

## 请评估投递难度，输出 JSON"""

    resp = await client.chat_raw(
        messages=[
            {"role": "system", "content": ASSESSMENT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_tokens=400,
    )

    content = (resp.choices[0].message.content or "").strip() if resp else ""

    # 解析 JSON
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:])
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            try:
                result = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                print(f"  ⚠ [{job['title'][:20]}] JSON 解析失败: {content[:100]}")
                result = {"positioning": "match", "confidence": 0.3,
                         "gaps": [], "interview_risk": "解析失败",
                         "reasoning": "模型输出无法解析"}
        else:
            print(f"  ⚠ [{job['title'][:20]}] 响应无 JSON 结构: {content[:100]}")
            result = {"positioning": "match", "confidence": 0.3,
                     "gaps": [], "interview_risk": "解析失败",
                     "reasoning": "模型输出无法解析"}

    return {
        "job_id": job.get("job_id", ""),
        "title": job["title"],
        "tier": job.get("tier", "?"),
        "score": job.get("score", 0),
        "department": job.get("department", ""),
        "location": job.get("location", ""),
        **result,
    }


async def generate_strategy(client, assessments: list[dict],
                             candidate_summary: str) -> dict:
    """生成投递组合策略"""
    # 构建岗位列表摘要（精简信息避免输入过长）
    no_gap = "无"
    jobs_text = "\n".join(
        f"- {a['title']}（{a['tier']}档 {a['score']:.0f}分）→ 定位: {a['positioning']}，主 gap: {(a.get('gaps', []) or [no_gap])[0]}"
        for a in assessments
    )

    user_prompt = f"""## 候选人摘要
{candidate_summary[:500]}

## 所有推荐岗位及投递定位
{jobs_text}

## 统计
- stretch: {sum(1 for a in assessments if a['positioning'] == 'stretch')} 个
- match: {sum(1 for a in assessments if a['positioning'] == 'match')} 个
- safe: {sum(1 for a in assessments if a['positioning'] == 'safe')} 个

## 请生成投递组合建议，输出 JSON"""

    resp = await client.chat_raw(
        messages=[
            {"role": "system", "content": STRATEGY_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_tokens=1500,
    )

    content = (resp.choices[0].message.content or "").strip() if resp else ""
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:])
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                print(f"  ✗ 策略 JSON 解析失败，原始响应前200字符: {content[:200]}")
        else:
            print(f"  ✗ 策略响应中未找到 JSON 结构，原始响应前200字符: {content[:200]}")
        return {"strategy_summary": "策略生成失败", "recommended_order": [],
                "preparation_tips": [], "risk_note": ""}


async def run(args):
    print("=" * 60)
    print("Decision Advisor — 投递策略分析")
    print("=" * 60)

    # 加载数据
    scored = json.loads(Path(args.scored).read_text(encoding="utf-8"))
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    candidate_summary = Path(args.summary).read_text(encoding="utf-8")

    # 只评估 A 档 + B 档（C 档迁移较远，无需策略分析）
    tier_a = scored.get("recommendations", {}).get("tier_A", [])
    tier_b = scored.get("recommendations", {}).get("tier_B", [])
    target_jobs = tier_a + tier_b[:10]  # B 档最多取前 10

    if not target_jobs:
        print("没有 A/B 档岗位，无需策略分析。")
        return

    print(f"\n目标岗位: A档 {len(tier_a)} + B档 {min(len(tier_b), 10)} = {len(target_jobs)}")

    # 初始化客户端（带重试 + 并发控制）
    client = LLMClient(model=args.model, max_concurrent=3, provider=args.provider)

    # 并发评估每个岗位（并发由 LLMClient.semaphore 控制）
    print(f"\n[1/2] 竞争力评估中... | 模型: {args.model}")

    async def assess_with_client(job):
        return await assess_single(client, candidate_summary, profile, job)

    assessments = await asyncio.gather(
        *[assess_with_client(j) for j in target_jobs],
        return_exceptions=True
    )
    assessments = [a for a in assessments if not isinstance(a, Exception)]

    # 统计
    stretch_count = sum(1 for a in assessments if a.get("positioning") == "stretch")
    match_count = sum(1 for a in assessments if a.get("positioning") == "match")
    safe_count = sum(1 for a in assessments if a.get("positioning") == "safe")
    print(f"  完成: stretch={stretch_count} | match={match_count} | safe={safe_count}")

    # 分布异常告警
    total = stretch_count + match_count + safe_count
    if total > 0 and safe_count == 0 and len(tier_a) >= 3:
        print(f"\n  ⚠ 分布告警: safe=0 但 A 档有 {len(tier_a)} 个岗位。")
        print(f"    可能原因: safe 定义对当前候选人过于严苛。建议检查 A 档高分岗的 gaps 是否仅为加分项缺失。")
    if total > 0 and stretch_count / total > 0.8:
        print(f"\n  ⚠ 分布告警: stretch 占比 {stretch_count/total:.0%}，分布严重偏斜。")
        print(f"    建议人工复核 A 档高分岗位是否合理标为 stretch。")

    # 生成策略
    print(f"\n[2/2] 生成投递策略...")
    strategy = await generate_strategy(client, assessments, candidate_summary)
    print(f"  策略: {strategy.get('strategy_summary', '?')}")

    # 组装输出
    output = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "assessments": assessments,
        "positioning_summary": {
            "stretch": stretch_count,
            "match": match_count,
            "safe": safe_count,
        },
        "strategy": strategy,
    }

    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 决策上下文已保存: {output_path}")

    # 打印摘要
    print(f"\n{'='*60}")
    print("投递策略摘要")
    print(f"{'='*60}")
    print(f"\n{strategy.get('strategy_summary', '')}")

    if strategy.get("recommended_order"):
        print(f"\n推荐投递顺序：")
        for item in strategy["recommended_order"][:8]:
            pos_emoji = {"stretch": "🔴", "match": "🟢", "safe": "🔵"}.get(
                item.get("positioning", ""), "⚪")
            print(f"  {item.get('priority', '?')}. {pos_emoji} {item.get('title', '?')}")
            if item.get("reason"):
                print(f"     → {item['reason']}")

    if strategy.get("risk_note"):
        print(f"\n⚠ 风险提示: {strategy['risk_note']}")


def main():
    parser = argparse.ArgumentParser(description="投递策略分析")
    parser.add_argument("--scored", required=True, help="scored_results.json 路径")
    parser.add_argument("--profile", required=True, help="boundary_profile.json 路径")
    parser.add_argument("--summary", required=True, help="candidate_summary.txt 路径")
    parser.add_argument("--output", required=True, help="输出 decision_context.json 路径")
    parser.add_argument("--model", default="gpt-4.1-mini", help="使用的模型")
    parser.add_argument("--provider", default=None, help="LLM provider: internal 或 external（默认读环境变量 LLM_PROVIDER）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
