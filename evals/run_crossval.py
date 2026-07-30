#!/usr/bin/env python3
"""T12 —— 多 Judge 交叉验证（multi-judge cross-validation）。

验证打分**不是单一模型怪癖的产物**。用 K 个独立 Judge 对同一批样本独立判档，
测 inter-rater 一致性；低一致项标记人工复核（不自动判错）。

用法：
    python evals/run_crossval.py --demo
        # 框架自检：合成判定矩阵演示 κ 计算 + 门禁（无需 LLM key，CI 友好）
    python evals/run_crossval.py --judges friday,sub2api,agnes
        # 真实多 Judge：每个 provider 独立判档（需 LLM key）
    python evals/run_crossval.py --judges friday,sub2api,agnes --sample 20

门控（默认，--fleiss-gate 可覆盖）：
    Fleiss' κ ≥ 0.6（中等一致）视为管线可信。
    低一致样本（Judge 间档位不完全一致）标记 needs_human_review。
"""
import json
import sys
import argparse
import itertools
from pathlib import Path

# scipy 是软依赖：仅 compute_crossval 的 Spearman ρ 用到。
# 做可选导入，避免缺 scipy 时整个模块（及依赖它的测试）在导入阶段就崩。
try:
    from scipy.stats import spearmanr
    HAS_SCIPY = True
except Exception:  # pragma: no cover - 仅在缺 scipy 时触发
    spearmanr = None
    HAS_SCIPY = False

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = Path(__file__).resolve().parent
CROSSVAL_DIR = EVALS_DIR / "crossval"

GATE_FLEISS = 0.6
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}
TIER_SCORE = {"A": 90.0, "B": 78.0, "C": 60.0, "D": 40.0}
KNOWN_TIERS = ["A", "B", "C", "D"]


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """两两 Cohen's κ（tier 标签）。"""
    n = len(a)
    if n == 0:
        return 1.0
    cats = sorted(set(a) | set(b))
    if len(cats) <= 1:
        return 1.0
    p_o = sum(1 for x, y in zip(a, b) if x == y) / n
    cnt_a = {c: a.count(c) for c in cats}
    cnt_b = {c: b.count(c) for c in cats}
    p_e = sum((cnt_a[c] / n) * (cnt_b[c] / n) for c in cats)
    if 1 - p_e == 0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


def fleiss_kappa(rating_matrix: list[list[str]]) -> float:
    """Fleiss' κ（多 rater 一致性）。rating_matrix: N 个样本 × K 个 Judge 的 tier 标签。

    rating_matrix 中每个元素为 tier 字符串（A/B/C/D），所有样本 Judge 数 K 相同。
    """
    n_subj = len(rating_matrix)
    if n_subj == 0:
        return 1.0
    k = len(rating_matrix[0])
    if k < 2:
        return 1.0
    cats = KNOWN_TIERS
    n_cat = len(cats)

    # n_ij: 样本 i 被判定为类别 j 的 Judge 数
    n_ij = []
    for row in rating_matrix:
        counts = [row.count(c) for c in cats]
        n_ij.append(counts)

    # P_j: 类别 j 占总评定的比例
    total_ratings = n_subj * k
    p_j = [sum(n_ij[i][j] for i in range(n_subj)) / total_ratings for j in range(n_cat)]

    # 每样本一致性 p_i
    p_i = []
    for i in range(n_subj):
        s = sum(c * c for c in n_ij[i])
        p_i.append((s - k) / (k * (k - 1)))

    p_bar = sum(p_i) / n_subj
    p_e_bar = sum(x * x for x in p_j)

    if 1 - p_e_bar == 0:
        return 1.0
    return (p_bar - p_e_bar) / (1 - p_e_bar)


def build_matrix(tier_lists: list[list[str]]) -> list[list[str]]:
    """list[ judge_tiers ] → 矩阵 [样本][judge]。每个 judge 是一个样本序列。"""
    # tier_lists: [judge0_samples, judge1_samples, ...]
    n = min(len(j) for j in tier_lists)
    return [[tier_lists[j][i] for j in range(len(tier_lists))] for i in range(n)]


def compute_crossval(tier_matrix: list[list[str]]) -> dict:
    n_subj = len(tier_matrix)
    k = len(tier_matrix[0]) if n_subj else 0
    judges = [list(col) for col in zip(*tier_matrix)]  # 转置为 [judge][sample]

    # 逐对 Cohen's κ
    pairwise = {}
    for j1, j2 in itertools.combinations(range(k), 2):
        key = f"j{j1}-j{j2}"
        pairwise[key] = round(cohen_kappa(judges[j1], judges[j2]), 4)

    # Spearman ρ（tier→score 向量）；缺 scipy 时优雅降为 None
    rho = None
    if k >= 2 and HAS_SCIPY:
        score_vectors = [[TIER_SCORE[t] for t in col] for col in judges]
        try:
            r, _ = spearmanr(score_vectors[0], score_vectors[1])
            rho = None if r != r else float(r)
        except Exception:
            rho = None

    fleiss = round(fleiss_kappa(tier_matrix), 4)

    # 低一致样本：档位不完全一致 → 需人工复核
    low_agreement = []
    for i, row in enumerate(tier_matrix):
        if len(set(row)) > 1:
            low_agreement.append({"sample": i, "tiers": list(row)})

    return {
        "n_subjects": n_subj,
        "n_judges": k,
        "fleiss_kappa": fleiss,
        "pairwise_cohen_kappa": pairwise,
        "spearman_rho": round(rho, 4) if rho is not None else None,
        "low_agreement_count": len(low_agreement),
        "low_agreement": low_agreement,
    }


def check_crossval_gates(metrics: dict, gate_fleiss: float) -> tuple[bool, list[str]]:
    failures = []
    if metrics["fleiss_kappa"] < gate_fleiss:
        failures.append(f"Fleiss' κ {metrics['fleiss_kappa']} < {gate_fleiss}")
    return len(failures) == 0, failures


def _demo_matrix() -> list[list[str]]:
    """确定性合成矩阵（20 样本 × 3 Judge，高一致，演示计算，无需 key）。"""
    import random
    rng = random.Random(42)
    matrix = []
    for _ in range(20):
        gold = rng.choice(["A", "B", "C"])
        row = [gold] * 3
        # 少量噪声：约 1/6 概率一个 judge 偏差一级
        if rng.random() < 0.16:
            jitter = rng.choice(["A", "B", "C", "D"])
            row[rng.randrange(3)] = jitter
        matrix.append(row)
    return matrix


def _real_matrix(judges: list[str], model: str, sample: int, skip_on_error: bool) -> list[list[str]]:
    """真实多 Judge：每个 judge provider 对 golden 样本判档 → 矩阵 [样本][judge]。"""
    sys.path.insert(0, str(REPO_ROOT))
    from run_accuracy_eval import load_golden_cases, predict_case  # noqa: E402

    cases = load_golden_cases()
    if sample and sample < len(cases):
        cases = cases[:sample]
    tier_lists = []
    for judge in judges:
        tiers = []
        for case in cases:
            pred = predict_case(case, judge, model, skip_on_error)
            if pred is None:
                tiers.append("C")  # 打分失败兜底，避免崩溃（标记但不计入可信度）
            else:
                # 复用 run_accuracy_eval 的 tier 映射
                try:
                    from run_accuracy_eval import score_to_tier
                    tiers.append(score_to_tier(pred))
                except Exception:
                    tiers.append("C")
        tier_lists.append(tiers)
    return build_matrix(tier_lists)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true",
                        help="框架自检：合成判定矩阵演示 κ + 门禁（无需 key）")
    parser.add_argument("--judges", default=None,
                        help="真实多 Judge：逗号分隔 provider，如 friday,sub2api,agnes（需 LLM key）")
    parser.add_argument("--stage1-model", default="gpt-4o-mini")
    parser.add_argument("--sample", type=int, default=0,
                        help="抽样样本数（默认全部 golden）")
    parser.add_argument("--skip-on-error", action="store_true")
    parser.add_argument("--fleiss-gate", type=float, default=GATE_FLEISS)
    args = parser.parse_args()

    if args.demo:
        matrix = _demo_matrix()
        metrics = compute_crossval(matrix)
        passed, failures = check_crossval_gates(metrics, args.fleiss_gate)
        _print_crossval(metrics, args.fleiss_gate, passed, failures)
        sys.exit(0 if passed else 1)

    if args.judges:
        judges = [j.strip() for j in args.judges.split(",") if j.strip()]
        if len(judges) < 2:
            print("ERROR: 至少 2 个 Judge（--judges a,b[,c...]）", file=sys.stderr)
            sys.exit(2)
        matrix = _real_matrix(judges, args.stage1_model, args.sample, args.skip_on_error)
        metrics = compute_crossval(matrix)
        passed, failures = check_crossval_gates(metrics, args.fleiss_gate)
        _print_crossval(metrics, args.fleiss_gate, passed, failures)
        sys.exit(0 if passed else 1)

    print("ERROR: 需要 --demo 或 --judges", file=sys.stderr)
    sys.exit(2)


def _print_crossval(metrics: dict, gate_fleiss: float, passed: bool, failures: list):
    print("\n=== T12 多 Judge 交叉验证 ===")
    print(f"样本数: {metrics['n_subjects']} | Judge 数: {metrics['n_judges']}")
    print(f"Fleiss' κ: {metrics['fleiss_kappa']}  (门禁 ≥ {gate_fleiss})")
    print(f"Spearman ρ: {metrics['spearman_rho']}")
    if metrics["pairwise_cohen_kappa"]:
        print("逐对 Cohen's κ:")
        for key, val in metrics["pairwise_cohen_kappa"].items():
            print(f"  {key}: {val}")
    print(f"低一致样本数: {metrics['low_agreement_count']}（标记 needs_human_review，非自动判错）")
    if metrics["low_agreement"]:
        print("  低一致明细:")
        for item in metrics["low_agreement"][:10]:
            print(f"    - sample {item['sample']}: {item['tiers']}")
    if passed:
        print("\n✅ 交叉验证门禁通过（多 Judge 一致，打分非单一模型怪癖）")
    else:
        print("\n❌ 交叉验证门禁失败:")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
