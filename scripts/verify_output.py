#!/usr/bin/env python3
"""
verify_output.py — scored_results.json 确定性断言检查

跑完 smart_score.py 后执行，验证输出结构和分布没有 regress。
全部是确定性检查（无 LLM），1 秒内完成。

使用方式：
    python3 verify_output.py --input ./scored_results.json

退出码：
    0 = 全部通过
    1 = 存在失败断言（详情打印到 stdout，含契约号 [C#]）
"""

import json
import sys
import argparse
from pathlib import Path

# 关键约束以 config/constraints.yaml 为单一事实源（见 scripts/config_loader.py）
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from config_loader import load_constraints

_CONSTRAINTS = load_constraints()


def load_results(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"FAIL [C0]: 文件不存在: {path}")
        sys.exit(1)
    if p.stat().st_size < 100:
        print(f"FAIL [C0]: 文件过小 ({p.stat().st_size} bytes)，可能是空输出")
        sys.exit(1)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"FAIL [C0]: JSON 解析失败（文件可能截断/格式损坏）: {path}")
        print(f"       {e}")
        sys.exit(1)


def run_checks(data: dict) -> tuple[list[str], list[str], dict]:
    """返回 (failures, warnings, counts)。
    - failures: 结构化失败消息（带契约号 [C#]），非空 = 退出码 1。
    - warnings: 非致命但必须显式暴露（如 fallback 真实计数），契合"隐蔽 fallback 更危险"。
    - counts: 真实评估数 / fallback 数，供摘要与测试断言使用。
    """
    failures = []
    warnings = []

    # === C1. 顶层结构完整 ===
    required_keys = ["pipeline", "summary", "recommendations"]
    for k in required_keys:
        if k not in data:
            failures.append(f"[C1] 顶层缺少必需字段: {k}")

    if failures:
        return failures, warnings, {}

    pipeline = data["pipeline"]
    summary = data["summary"]
    recs = data["recommendations"]

    # === C2. Pipeline 元数据完整（6 阶段） ===
    expected_stages = ["stage1", "stage1_5", "stage2", "stage2_5", "post_judge", "direction_anchor"]
    for stage in expected_stages:
        if stage not in pipeline:
            failures.append(f"[C2] pipeline 缺少阶段: {stage}")

    # === C3. 推荐分档结构 ===
    for tier in ["tier_A", "tier_B", "tier_C"]:
        if tier not in recs:
            failures.append(f"[C3] recommendations 缺少: {tier}")
        elif not isinstance(recs[tier], list):
            failures.append(f"[C3] recommendations.{tier} 不是数组")

    if failures:
        return failures, warnings, {}

    tier_a = recs["tier_A"]
    tier_b = recs["tier_B"]
    tier_c = recs["tier_C"]
    all_items = tier_a + tier_b + tier_c

    # === C4. A 档数量约束（单一事实源：config/constraints.yaml → a_tier_cap） ===
    # 与 scripts/post_judge.py 的 enforce_distribution 完全一致，避免「约束器放行、校验器判死」。
    a_cap = _CONSTRAINTS["a_tier_cap"]
    a_tier_max = max(a_cap["min_floor"], int(len(all_items) * a_cap["max_ratio"]))
    if len(tier_a) > a_tier_max:
        failures.append(
            f"[C4] A 档数量 = {len(tier_a)}，超过上限 {a_tier_max}（= max({a_cap['min_floor']}, "
            f"int(total*{a_cap['max_ratio']}))，分布约束失效）"
        )

    # === C5. 总输出非空 ===
    if len(all_items) == 0:
        failures.append("[C5] 推荐结果为空（A+B+C = 0）")
        return failures, warnings, {}

    # === C6. 每个 item 必需字段完整 ===
    item_required = ["job_id", "title", "score", "tier"]
    for i, item in enumerate(all_items):
        missing = [k for k in item_required if k not in item]
        if missing:
            failures.append(f"[C6] item[{i}] ({item.get('title', '?')}) 缺少字段: {missing}")
            if len(failures) > 5:
                failures.append("[C6] ...（过多字段缺失，截断）")
                break

    # === C7. 分数区间合理 ===
    # A 档: 应 >= 80（历史数据最低 85，留余量）；检查下限即 80，低于即判异常
    # 全部: 应在 0-100 范围内
    for item in all_items:
        score = item.get("score")
        if score is not None:
            if not (0 <= score <= 100):
                failures.append(f"[C7] 分数越界: {item.get('title', '?')} = {score}")

    if tier_a:
        min_a = min(item["score"] for item in tier_a if "score" in item)
        if min_a < 80:
            failures.append(f"[C7] A 档最低分 = {min_a}，低于 80（可能分档逻辑异常）")

    # === C8. 无重复 job_id ===
    job_ids = [item.get("job_id") for item in all_items if item.get("job_id")]
    if len(job_ids) != len(set(job_ids)):
        seen = set()
        dupes = [jid for jid in job_ids if jid in seen or seen.add(jid)]
        failures.append(f"[C8] 存在重复 job_id: {dupes[:5]}")

    # === C9. Post-Judge 实际生效（语义以 config/constraints.yaml → post_judge_check 为准） ===
    # 历史：penalties==0 且批量大时直接判 FAILURE。但干净批次（JD 无英语/核心团队/技术
    # 信号）本就 0 penalties，属正常结果，原逻辑会误杀（false positive）。按配置降级为 WARNING，
    # 仅当 penalties_applied 字段结构缺失（暗示后处理未运行）才判 FAILURE；
    # zero_penalty_mode=warning 时由配置决定处置（当前为 WARNING）。
    c9 = _CONSTRAINTS["post_judge_check"]
    pj = pipeline.get("post_judge", {})
    penalties = pj.get("penalties_applied", None)
    if penalties is None:
        warnings.append(
            "[W] pipeline.post_judge.penalties_applied 未产出（结构提示，请确认后处理已运行）"
        )
    elif not isinstance(penalties, int):
        failures.append(
            "[C9] pipeline.post_judge.penalties_applied 非整数（后处理阶段结构损坏）"
        )
    elif penalties == 0 and len(all_items) > c9["min_items_for_check"]:
        note = (
            f"[W] Post-Judge penalties = 0（{len(all_items)} 个岗位中无一触发规则；"
            "若这批 JD 均无英语/核心团队/技术信号则属正常，否则检查 full_text 是否传递）"
        )
        if c9.get("zero_penalty_mode", "warning") == "failure":
            failures.append("[C9] " + note)
        else:
            warnings.append(note)

    # === C10. Summary 与实际数据一致 ===
    if summary.get("tier_A") != len(tier_a):
        failures.append(f"[C10] summary.tier_A={summary.get('tier_A')} 与实际 A 档数量 {len(tier_a)} 不一致")
    if summary.get("tier_B") != len(tier_b):
        failures.append(f"[C10] summary.tier_B={summary.get('tier_B')} 与实际 B 档数量 {len(tier_b)} 不一致")
    if summary.get("tier_C") != len(tier_c):
        failures.append(f"[C10] summary.tier_C={summary.get('tier_C')} 与实际 C 档数量 {len(tier_c)} 不一致")

    # === C11. 分数分布不极端收窄 ===
    all_scores = [item["score"] for item in all_items if "score" in item]
    if all_scores:
        score_range = max(all_scores) - min(all_scores)
        if score_range < 10:
            failures.append(
                f"[C11] 全部分数分布极窄: max-min = {score_range:.1f}（区分度不足）"
            )

    # === C12. Stage 2 fallback 比例检查（硬失败阈值 > 15%） ===
    fallback_items = [
        item for item in all_items
        if any("模型未返回该岗位评估" in r for r in item.get("risks", []))
    ]
    real_count = len(all_items) - len(fallback_items)
    if len(all_items) > 0:
        fallback_ratio = len(fallback_items) / len(all_items)
        if fallback_ratio > 0.15:
            failures.append(
                f"[C12] Stage 2 fallback 过多: {len(fallback_items)}/{len(all_items)} "
                f"({fallback_ratio:.0%}) 个岗位为 fallback 分数（非真实评估），"
                "考虑降低 --concurrency 或检查网络"
            )
        elif fallback_items:
            # 非致命，但必须显式暴露——0~15% 区间不再静默通过
            warnings.append(
                f"[W] Stage 2 fallback 存在 {len(fallback_items)}/{len(all_items)} "
                f"({fallback_ratio:.0%}) 个岗位为 fallback 分数（非真实评估），"
                f"标题：{', '.join(i.get('title', '?') for i in fallback_items)}"
            )

    counts = {"total": len(all_items), "real": real_count, "fallback": len(fallback_items)}
    return failures, warnings, counts


def main():
    parser = argparse.ArgumentParser(
        description="scored_results.json 确定性回归检查（合同化 + 真实计数）"
    )
    parser.add_argument("--input", required=True, help="scored_results.json 路径")
    args = parser.parse_args()

    data = load_results(args.input)
    failures, warnings, counts = run_checks(data)

    if not failures:
        recs = data["recommendations"]
        total = len(recs["tier_A"]) + len(recs["tier_B"]) + len(recs["tier_C"])
        pj = data["pipeline"].get("post_judge", {})
        print(f"✅ 全部通过 (12 项契约检查)")
        print(f"   A={len(recs['tier_A'])} B={len(recs['tier_B'])} C={len(recs['tier_C'])} "
              f"Total={total} Penalties={pj.get('penalties_applied', '?')}")
        print(f"   真实评估={counts.get('real', '?')} fallback={counts.get('fallback', '?')} "
              f"（fallback 为非真实评估分数，需警惕）")
        if warnings:
            print("\n⚠️ 警告（非致命，但已显式暴露）：")
            for w in warnings:
                print(f"  {w}")
        sys.exit(0)
    else:
        print(f"❌ {len(failures)} 项契约检查失败:\n")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")
        if warnings:
            print("\n⚠️ 同时存在的警告：")
            for w in warnings:
                print(f"  {w}")
        sys.exit(1)


if __name__ == "__main__":
    main()
