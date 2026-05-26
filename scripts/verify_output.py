#!/usr/bin/env python3
"""
verify_output.py — scored_results.json 确定性断言检查

跑完 smart_score.py 后执行，验证输出结构和分布没有 regress。
全部是确定性检查（无 LLM），1 秒内完成。

使用方式：
    python3 verify_output.py --input ./scored_results.json

退出码：
    0 = 全部通过
    1 = 存在失败断言（详情打印到 stdout）
"""

import json
import sys
import argparse
from pathlib import Path


def load_results(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"FAIL: 文件不存在: {path}")
        sys.exit(1)
    if p.stat().st_size < 100:
        print(f"FAIL: 文件过小 ({p.stat().st_size} bytes)，可能是空输出")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def run_checks(data: dict) -> list[str]:
    """返回失败消息列表。空列表 = 全部通过。"""
    failures = []

    # === 1. 顶层结构完整 ===
    required_keys = ["pipeline", "summary", "recommendations"]
    for k in required_keys:
        if k not in data:
            failures.append(f"顶层缺少必需字段: {k}")

    if failures:
        return failures  # 结构都不完整，后续检查无意义

    pipeline = data["pipeline"]
    summary = data["summary"]
    recs = data["recommendations"]

    # === 2. Pipeline 元数据完整（6 阶段） ===
    expected_stages = ["stage1", "stage1_5", "stage2", "stage2_5", "post_judge", "direction_anchor"]
    for stage in expected_stages:
        if stage not in pipeline:
            failures.append(f"pipeline 缺少阶段: {stage}")

    # === 3. 推荐分档结构 ===
    for tier in ["tier_A", "tier_B", "tier_C"]:
        if tier not in recs:
            failures.append(f"recommendations 缺少: {tier}")
        elif not isinstance(recs[tier], list):
            failures.append(f"recommendations.{tier} 不是数组")

    if failures:
        return failures

    tier_a = recs["tier_A"]
    tier_b = recs["tier_B"]
    tier_c = recs["tier_C"]
    all_items = tier_a + tier_b + tier_c

    # === 4. A 档数量约束（≤ 15） ===
    if len(tier_a) > 15:
        failures.append(f"A 档数量 = {len(tier_a)}，超过上限 15（分布约束失效）")

    # === 5. 总输出非空 ===
    if len(all_items) == 0:
        failures.append("推荐结果为空（A+B+C = 0）")
        return failures

    # === 6. 每个 item 必需字段完整 ===
    item_required = ["job_id", "title", "score", "tier"]
    for i, item in enumerate(all_items):
        missing = [k for k in item_required if k not in item]
        if missing:
            failures.append(f"item[{i}] ({item.get('title', '?')}) 缺少字段: {missing}")
            if len(failures) > 5:
                failures.append("...（过多字段缺失，截断）")
                break

    # === 7. 分数区间合理 ===
    # A 档: 应 >= 80（历史数据最低 85，留余量）
    # 全部: 应在 0-100 范围内
    for item in all_items:
        score = item.get("score")
        if score is not None:
            if not (0 <= score <= 100):
                failures.append(f"分数越界: {item.get('title', '?')} = {score}")

    if tier_a:
        min_a = min(item["score"] for item in tier_a if "score" in item)
        if min_a < 75:
            failures.append(f"A 档最低分 = {min_a}，低于 75（可能分档逻辑异常）")

    # === 8. 无重复 job_id ===
    job_ids = [item.get("job_id") for item in all_items if item.get("job_id")]
    if len(job_ids) != len(set(job_ids)):
        seen = set()
        dupes = [jid for jid in job_ids if jid in seen or seen.add(jid)]
        failures.append(f"存在重复 job_id: {dupes[:5]}")

    # === 9. Post-Judge 实际生效 ===
    pj = pipeline.get("post_judge", {})
    penalties = pj.get("penalties_applied", 0)
    if penalties == 0 and len(all_items) > 20:
        failures.append(
            f"Post-Judge penalties = 0（{len(all_items)} 个岗位中无一触发规则，"
            "可能 full_text 未传递或规则逻辑失效）"
        )

    # === 10. Summary 与实际数据一致 ===
    if summary.get("tier_A") != len(tier_a):
        failures.append(f"summary.tier_A={summary.get('tier_A')} 与实际 A 档数量 {len(tier_a)} 不一致")
    if summary.get("tier_B") != len(tier_b):
        failures.append(f"summary.tier_B={summary.get('tier_B')} 与实际 B 档数量 {len(tier_b)} 不一致")
    if summary.get("tier_C") != len(tier_c):
        failures.append(f"summary.tier_C={summary.get('tier_C')} 与实际 C 档数量 {len(tier_c)} 不一致")

    # === 11. 分数分布不极端收窄 ===
    all_scores = [item["score"] for item in all_items if "score" in item]
    if all_scores:
        score_range = max(all_scores) - min(all_scores)
        if score_range < 10:
            failures.append(
                f"全部分数分布极窄: max-min = {score_range:.1f}（区分度不足）"
            )

    # === 12. Stage 2 fallback 比例检查 ===
    fallback_items = [
        item for item in all_items
        if any("模型未返回该岗位评估" in r for r in item.get("risks", []))
    ]
    if len(all_items) > 0:
        fallback_ratio = len(fallback_items) / len(all_items)
        if fallback_ratio > 0.15:
            failures.append(
                f"Stage 2 fallback 过多: {len(fallback_items)}/{len(all_items)} "
                f"({fallback_ratio:.0%}) 个岗位为 fallback 分数（非真实评估），"
                "考虑降低 --concurrency 或检查网络"
            )

    return failures


def main():
    parser = argparse.ArgumentParser(
        description="scored_results.json 确定性回归检查"
    )
    parser.add_argument("--input", required=True, help="scored_results.json 路径")
    args = parser.parse_args()

    data = load_results(args.input)
    failures = run_checks(data)

    if not failures:
        # 打印摘要
        recs = data["recommendations"]
        total = len(recs["tier_A"]) + len(recs["tier_B"]) + len(recs["tier_C"])
        pj = data["pipeline"].get("post_judge", {})
        print(f"✅ 全部通过 (12 项检查)")
        print(f"   A={len(recs['tier_A'])} B={len(recs['tier_B'])} C={len(recs['tier_C'])} "
              f"Total={total} Penalties={pj.get('penalties_applied', '?')}")
        sys.exit(0)
    else:
        print(f"❌ {len(failures)} 项检查失败:\n")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
