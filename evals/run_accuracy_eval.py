#!/usr/bin/env python3
"""评分准确度评估：管线输出 vs 人工标注 golden cases。

用法：
    python evals/run_accuracy_eval.py [--provider agnes] [--stage1-model gpt-4o-mini] \\
                                      [--skip-on-error] [--score] [--framework-only]

门控标准：
    MAE ≤ 8, Spearman ρ ≥ 0.85, Tier Accuracy ≥ 80%, Outlier Rate ≤ 10%

模式：
    - 默认（框架模式）：仅加载 cases 并做结构自检，exit 0。无需 LLM key，CI 友好。
    - --score：调用管线对每 case 真实打分，计算指标并门禁，exit 0/1（需 LLM key）。
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from scipy.stats import spearmanr

GOLDEN_DIR = Path(__file__).parent / "golden"
REPO_ROOT = Path(__file__).resolve().parent.parent

# 门控阈值
GATE_MAE = 8.0
GATE_RHO = 0.85
GATE_TIER_ACC = 0.80
GATE_OUTLIER_RATE = 0.10
OUTLIER_THRESHOLD = 15  # 偏差超过 15 分算 outlier

# 档位分档（与 README 标注指南一致）
TIER_A_MIN = 85
TIER_B_MIN = 72


def load_golden_cases() -> list[dict]:
    cases = []
    for f in sorted(GOLDEN_DIR.glob("case_*.json")):
        cases.append(json.loads(f.read_text(encoding="utf-8")))
    return cases


def check_coverage_matrix() -> tuple[dict, dict]:
    """校验 10 个 case 是否覆盖场景矩阵。返回 (counts, gaps)。"""
    cases = load_golden_cases()
    counts = {"tech": 0, "non_tech": 0, "transition": 0,
              "campus_intern": 0, "high": 0, "low": 0}
    for c in cases:
        m = c.get("meta", {})
        if m.get("track") == "tech":
            counts["tech"] += 1
        elif m.get("track") == "non-tech":
            counts["non_tech"] += 1
        if m.get("transition"):
            counts["transition"] += 1
        if m.get("career_stage") in ("campus", "intern"):
            counts["campus_intern"] += 1
        if m.get("match_band") == "high":
            counts["high"] += 1
        if m.get("match_band") == "low":
            counts["low"] += 1
    required = {"tech": 3, "non_tech": 2, "transition": 1,
                "campus_intern": 2, "high": 1, "low": 1}
    gaps = {k: (required[k], counts[k]) for k in required if counts[k] < required[k]}
    return counts, gaps


def validate_golden() -> list[str]:
    """结构自检：返回问题列表（空 = 全部通过）。覆盖 meta 与必填字段。"""
    issues = []
    required = ("id", "profile", "jd_text", "expected_score",
                "expected_tier", "key_reasons", "annotator", "meta")
    for f in sorted(GOLDEN_DIR.glob("case_*.json")):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            issues.append(f"{f.name}: JSON 解析失败 ({e})")
            continue
        for key in required:
            if key not in c:
                issues.append(f"{f.name}: 缺字段 {key}")
        meta = c.get("meta")
        if not isinstance(meta, dict):
            issues.append(f"{f.name}: 缺 meta")
        else:
            for mk in ("track", "role_family", "transition", "career_stage", "match_band"):
                if mk not in meta:
                    issues.append(f"{f.name}: meta 缺 {mk}")
        s = c.get("expected_score")
        if not isinstance(s, (int, float)) or not (0 <= s <= 100):
            issues.append(f"{f.name}: expected_score 越界 {s}")
        if c.get("expected_tier") not in ("A", "B", "C"):
            issues.append(f"{f.name}: expected_tier 非法 {c.get('expected_tier')}")
    return issues


def score_to_tier(score: float) -> str:
    if score >= TIER_A_MIN:
        return "A"
    if score >= TIER_B_MIN:
        return "B"
    return "C"


def compute_metrics(predicted: list[float], expected: list[float],
                    predicted_tiers: list[str], expected_tiers: list[str]) -> dict:
    n = len(predicted)
    errors = [abs(p - e) for p, e in zip(predicted, expected)]
    mae = sum(errors) / n
    rho, p_value = spearmanr(predicted, expected)
    rho = None if rho != rho else float(rho)          # NaN -> None
    p_value = None if p_value != p_value else float(p_value)
    tier_correct = sum(1 for p, e in zip(predicted_tiers, expected_tiers) if p == e)
    tier_acc = tier_correct / n
    outliers = sum(1 for e in errors if e > OUTLIER_THRESHOLD)
    outlier_rate = outliers / n

    return {
        "n": n,
        "mae": round(mae, 2),
        "spearman_rho": round(rho, 4) if rho is not None else None,
        "spearman_p": round(p_value, 4) if p_value is not None else None,
        "tier_accuracy": round(tier_acc, 4),
        "outlier_rate": round(outlier_rate, 4),
        "max_error": round(max(errors), 2),
    }


def check_gates(metrics: dict) -> tuple[bool, list[str]]:
    failures = []
    if metrics["mae"] > GATE_MAE:
        failures.append(f"MAE {metrics['mae']} > {GATE_MAE}")
    if metrics["spearman_rho"] is not None and metrics["spearman_rho"] < GATE_RHO:
        failures.append(f"ρ {metrics['spearman_rho']} < {GATE_RHO}")
    if metrics["tier_accuracy"] < GATE_TIER_ACC:
        failures.append(f"Tier Acc {metrics['tier_accuracy']} < {GATE_TIER_ACC}")
    if metrics["outlier_rate"] > GATE_OUTLIER_RATE:
        failures.append(f"Outlier Rate {metrics['outlier_rate']} > {GATE_OUTLIER_RATE}")
    return len(failures) == 0, failures


def _build_candidate_summary(profile: dict) -> str:
    anchors = profile.get("direction_anchors", [])
    skills = profile.get("skills", [])
    hard_neg = profile.get("hard_negatives", [])
    yrs = profile.get("years_experience", "")
    lines = []
    if anchors:
        lines.append("方向锚点: " + "、".join(anchors))
    if skills:
        lines.append("技能: " + "、".join(skills))
    if yrs != "":
        lines.append(f"经验年限: {yrs} 年")
    if hard_neg:
        lines.append("硬负向(不匹配方向): " + "、".join(hard_neg))
    return "\n".join(lines) if lines else "（无 profile 摘要）"


def predict_case(case: dict, provider: str, model: str, skip_on_error: bool,
                prompt_variant: str = "general"):
    """调用管线对单个 golden case 打分。无 LLM key / 失败时返回 None。"""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts.llm_client import LLMClient
        from scripts.smart_score import build_direction_anchor, stage1
    except Exception as e:  # noqa: BLE001
        if skip_on_error:
            print(f"  [SKIP] {case.get('id')}: 无法导入管线 ({e})", file=sys.stderr)
            return None
        raise

    profile = case.get("profile", {})
    candidate_summary = _build_candidate_summary(profile)
    direction_anchor = build_direction_anchor(profile)
    jobs = [{
        "job_id": case.get("id", "case"),
        "title": case.get("jd_title", "岗位"),
        "department": case.get("jd_department", ""),
        "location": case.get("jd_location", ""),
        "full_text": case.get("jd_text", ""),
    }]
    try:
        client = LLMClient(model=model, provider=provider)
        scored, _stats = asyncio.run(
            stage1(client, candidate_summary, direction_anchor, jobs,
                   progress_callback=None, tracer=None,
                   prompt_variant=prompt_variant)
        )
        return float(scored[0]["stage1_score"])
    except Exception as e:  # noqa: BLE001
        if skip_on_error:
            print(f"  [SKIP] {case.get('id')}: 打分失败 ({e})", file=sys.stderr)
            return None
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="agnes")
    parser.add_argument("--stage1-model", default="gpt-4o-mini")
    parser.add_argument("--stage1-prompt", default="general",
                        choices=["general", "strict", "lenient"],
                        help="Stage1 提示词变体：general=一般模型(默认), "
                             "strict=强模型(frontier), lenient=思考模型(reasoning)")
    parser.add_argument("--skip-on-error", action="store_true")
    parser.add_argument("--score", action="store_true",
                        help="调用管线真实打分并计算指标（需 LLM key）")
    parser.add_argument("--framework-only", action="store_true",
                        help="仅加载 cases 做结构自检（默认行为）")
    parser.add_argument("--check", action="store_true",
                        help="离线结构 + 覆盖矩阵自检（不调用 LLM），exit 非 0 = 有问题")
    args = parser.parse_args()

    cases = load_golden_cases()
    if not cases:
        print("ERROR: No golden cases found in evals/golden/")
        sys.exit(1)

    print(f"加载 {len(cases)} 个 golden cases")

    # 覆盖矩阵自检（始终打印，便于发现空缺）
    counts, gaps = check_coverage_matrix()
    print("覆盖矩阵: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if gaps:
        print(f"  ⚠️ 覆盖缺口: {gaps}")

    if args.check:
        issues = validate_golden()
        if issues:
            print(f"\n❌ 结构问题 {len(issues)} 项：")
            for i in issues:
                print(f"  - {i}")
        else:
            print("\n✅ 结构自检通过")
        if gaps or issues:
            sys.exit(1)
        print("✅ 覆盖矩阵与结构均通过")
        sys.exit(0)

    framework_mode = args.framework_only or not args.score
    if framework_mode:
        human = [c for c in cases if c.get("annotator") == "human"]
        draft = [c for c in cases if c.get("annotator") != "human"]
        print(f"  人工标注: {len(human)} | AI-draft(需人工复核): {len(draft)}")
        print("NOTE: 当前为框架模式。加 --score 调用管线真实打分（需 LLM key）。")
        print("门控标准: MAE≤8, ρ≥0.85, TierAcc≥80%, Outlier≤10%")
        sys.exit(0)

    # --score 模式：真实打分 + 指标 + 门禁
    predicted, expected, p_tiers, e_tiers = [], [], [], []
    skipped = 0
    for case in cases:
        pred = predict_case(case, args.provider, args.stage1_model,
                             args.skip_on_error, args.stage1_prompt)
        if pred is None:
            skipped += 1
            continue
        predicted.append(pred)
        expected.append(float(case["expected_score"]))
        p_tiers.append(score_to_tier(pred))
        e_tiers.append(case["expected_tier"])

    if len(predicted) < 2:
        print(f"ERROR: 有效预测不足 2 个（成功 {len(predicted)}，跳过 {skipped}），"
              f"无法计算 Spearman ρ")
        sys.exit(1)

    metrics = compute_metrics(predicted, expected, p_tiers, e_tiers)
    passed, failures = check_gates(metrics)

    print("\n=== 评分准确度评估 ===")
    print(f"有效样本: {metrics['n']} (跳过 {skipped})")
    print(f"MAE: {metrics['mae']}  (门禁 ≤ {GATE_MAE})")
    print(f"Spearman ρ: {metrics['spearman_rho']}  (门禁 ≥ {GATE_RHO})")
    print(f"Tier Accuracy: {metrics['tier_accuracy']}  (门禁 ≥ {GATE_TIER_ACC})")
    print(f"Outlier Rate: {metrics['outlier_rate']}  (门禁 ≤ {GATE_OUTLIER_RATE})")
    print(f"Max Error: {metrics['max_error']}")

    if passed:
        print("\n✅ 全部门禁通过")
        sys.exit(0)
    print("\n❌ 门禁失败:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)


if __name__ == "__main__":
    main()
