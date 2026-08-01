#!/usr/bin/env python3
"""T11 —— 版本间回归对比（version-to-version regression compare）。

管线任何改动（prompt 外置 / 模型切换 / 代码重构）都可能**静默改变打分结果**。
本工具在固定输入上对比「当前版本」与「已存基线快照」，量化漂移，把
"分数变了但没人发现"变成可门禁的硬信号。

用法：
    python evals/run_regression_compare.py --demo
        # 框架自检：用确定性合成漂移演示指标 + 门禁（无需 LLM key，CI 友好）
    python evals/run_regression_compare.py --snapshot
        # 跑 golden 生成 evals/regression/baseline.json（需 LLM key）
    python evals/run_regression_compare.py --baseline baseline.json --snapshot-current
        # 生成 current 并直接与 baseline 对比（需 LLM key）
    python evals/run_regression_compare.py --baseline baseline.json --current scored.json
        # 对比两份已存 scored JSON（无需 key）

门控（默认，均可用 --xxx-gate 覆盖）：
    MAE(total_score) ≤ 5
    Cohen's κ(tier) ≥ 0.8
    Tier 翻转数 ≤ 2（且不得出现 A↔D 跳变）
    Outlier 率（|Δtotal| > 10 的 job 占比）≤ 10%
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = Path(__file__).resolve().parent
REGRESSION_DIR = EVALS_DIR / "regression"

# 默认门禁
GATE_MAE = 5.0
GATE_KAPPA = 0.8
GATE_MAX_FLIPS = 2
GATE_OUTLIER_RATE = 0.10
OUTLIER_THRESHOLD = 10  # |Δtotal| 超过此值算 outlier


def _tier_from_score(score: float) -> str:
    # 与 run_accuracy_eval.score_to_tier 保持一致（A≥85 / B≥72 / 否则 C）
    try:
        from run_accuracy_eval import score_to_tier  # noqa: F401
        return score_to_tier(score)
    except Exception:
        if score >= 85:
            return "A"
        if score >= 72:
            return "B"
        return "C"


def mae(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """两两 Cohen's κ（tier 标签一致性）。完全随机或全一致均安全返回。"""
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


def load_scored(path: Path) -> dict:
    """加载 scored JSON → {job_id: {"total_score": float, "tier": str}}。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for item in data.get("scored", []):
        out[item["job_id"]] = {
            "total_score": float(item["total_score"]),
            "tier": item.get("tier") or _tier_from_score(float(item["total_score"])),
        }
    return out


def compute_regression(baseline: dict, current: dict) -> dict:
    """逐 job_id 对齐，计算漂移指标。"""
    ids = sorted(set(baseline) & set(current))
    if not ids:
        raise ValueError("baseline 与 current 无交集 job_id，无法对齐对比")
    b_scores = [baseline[i]["total_score"] for i in ids]
    c_scores = [current[i]["total_score"] for i in ids]
    b_tiers = [baseline[i]["tier"] for i in ids]
    c_tiers = [current[i]["tier"] for i in ids]

    mae_val = mae(b_scores, c_scores)
    tier_agree = sum(1 for x, y in zip(b_tiers, c_tiers) if x == y) / len(ids)
    kappa = cohen_kappa(b_tiers, c_tiers)

    flips = []
    a_d_jump = False
    for i, bt, ct in zip(ids, b_tiers, c_tiers):
        if bt != ct:
            flips.append({"job_id": i, "from": bt, "to": ct})
            if {bt, ct} == {"A", "D"}:
                a_d_jump = True
    outlier_rate = sum(
        1 for x, y in zip(b_scores, c_scores) if abs(x - y) > OUTLIER_THRESHOLD
    ) / len(ids)

    return {
        "n": len(ids),
        "mae": round(mae_val, 3),
        "tier_agreement": round(tier_agree, 4),
        "cohen_kappa": round(kappa, 4),
        "flips": flips,
        "flip_count": len(flips),
        "a_d_jump": a_d_jump,
        "outlier_rate": round(outlier_rate, 4),
    }


def check_regression_gates(metrics: dict, gates: dict) -> tuple[bool, list[str]]:
    failures = []
    if metrics["mae"] > gates["mae"]:
        failures.append(f"MAE {metrics['mae']} > {gates['mae']}")
    if metrics["cohen_kappa"] < gates["kappa"]:
        failures.append(f"Cohen's κ {metrics['cohen_kappa']} < {gates['kappa']}")
    if metrics["flip_count"] > gates["max_flips"]:
        failures.append(f"Tier 翻转 {metrics['flip_count']} > {gates['max_flips']}")
    if metrics["a_d_jump"]:
        failures.append("出现 A↔D 档位跳变（高风险回归）")
    if metrics["outlier_rate"] > gates["outlier_rate"]:
        failures.append(f"Outlier 率 {metrics['outlier_rate']} > {gates['outlier_rate']}")
    return len(failures) == 0, failures


def _snapshot_from_golden(provider: str, model: str, skip_on_error: bool) -> dict:
    """跑 golden cases 生成 scored 快照（需 LLM key）。"""
    sys.path.insert(0, str(REPO_ROOT))
    from run_accuracy_eval import load_golden_cases, predict_case  # noqa: E402

    cases = load_golden_cases()
    if not cases:
        print("ERROR: evals/golden/ 下无 case", file=sys.stderr)
        sys.exit(1)
    scored = []
    for case in cases:
        pred = predict_case(case, provider, model, skip_on_error)
        if pred is None:
            continue
        scored.append({
            "job_id": case.get("id", "case"),
            "total_score": round(pred, 2),
            "tier": _tier_from_score(pred),
        })
    return {
        "version": "snapshot",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scored": scored,
    }


def _demo_pair() -> tuple[dict, dict]:
    """确定性合成基线 + 当前（小幅漂移，演示指标/门禁，无需 key）。"""
    base_scores = {
        "golden_001": 84.0, "golden_002": 72.0, "golden_003": 61.0,
        "golden_004": 90.0, "golden_005": 55.0, "golden_006": 78.0,
        "golden_007": 68.0, "golden_008": 88.0,
    }
    # 当前：整体 +1 微调；golden_003 下修 6（仍 <10 阈值，不触发 outlier）；无档位跳变
    drift = {"golden_001": 1, "golden_002": 1, "golden_003": -6, "golden_004": 0,
             "golden_005": 1, "golden_006": 2, "golden_007": 1, "golden_008": -1}
    cur_scores = {k: base_scores[k] + d for k, d in drift.items()}

    def to_dict(scores: dict) -> dict:
        return {jid: {"total_score": v, "tier": _tier_from_score(v)}
                for jid, v in scores.items()}

    return to_dict(base_scores), to_dict(cur_scores)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true",
                        help="框架自检：确定性合成漂移演示指标+门禁（无需 key）")
    parser.add_argument("--snapshot", action="store_true",
                        help="跑 golden 生成 baseline.json（需 LLM key）")
    parser.add_argument("--snapshot-current", action="store_true",
                        help="生成 current 并直接与 --baseline 对比（需 LLM key）")
    parser.add_argument("--baseline", default=None, help="基线 scored JSON 路径")
    parser.add_argument("--current", default=None, help="当前 scored JSON 路径")
    parser.add_argument("--provider", default="agnes")
    parser.add_argument("--stage1-model", default="gpt-4o-mini")
    parser.add_argument("--skip-on-error", action="store_true")
    parser.add_argument("--mae-gate", type=float, default=GATE_MAE)
    parser.add_argument("--kappa-gate", type=float, default=GATE_KAPPA)
    parser.add_argument("--max-flips", type=int, default=GATE_MAX_FLIPS)
    parser.add_argument("--outlier-gate", type=float, default=GATE_OUTLIER_RATE)
    args = parser.parse_args()

    gates = {"mae": args.mae_gate, "kappa": args.kappa_gate,
             "max_flips": args.max_flips, "outlier_rate": args.outlier_gate}

    if args.demo:
        baseline, current = _demo_pair()
        metrics = compute_regression(baseline, current)
        passed, failures = check_regression_gates(metrics, gates)
        _print_regression(metrics, gates, passed, failures)
        sys.exit(0 if passed else 1)

    if args.snapshot:
        REGRESSION_DIR.mkdir(parents=True, exist_ok=True)
        snap = _snapshot_from_golden(args.provider, args.stage1_model, args.skip_on_error)
        out = REGRESSION_DIR / "baseline.json"
        out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 基线快照写入 {out}（{len(snap['scored'])} 个 job）")
        sys.exit(0)

    if args.snapshot_current:
        if not args.baseline:
            print("ERROR: --snapshot-current 需要配合 --baseline", file=sys.stderr)
            sys.exit(1)
        baseline = load_scored(args.baseline)
        snap = _snapshot_from_golden(args.provider, args.stage1_model, args.skip_on_error)
        current = {item["job_id"]: {"total_score": item["total_score"], "tier": item["tier"]}
                   for item in snap["scored"]}
        metrics = compute_regression(baseline, current)
        passed, failures = check_regression_gates(metrics, gates)
        _print_regression(metrics, gates, passed, failures)
        sys.exit(0 if passed else 1)

    if args.baseline and args.current:
        baseline = load_scored(args.baseline)
        current = load_scored(args.current)
        metrics = compute_regression(baseline, current)
        passed, failures = check_regression_gates(metrics, gates)
        _print_regression(metrics, gates, passed, failures)
        sys.exit(0 if passed else 1)

    print("ERROR: 需要 --demo / --snapshot / --snapshot-current / "
          "--baseline+--current 之一", file=sys.stderr)
    sys.exit(2)


def _print_regression(metrics: dict, gates: dict, passed: bool, failures: list):
    print("\n=== T11 版本回归对比 ===")
    print(f"对齐 job 数: {metrics['n']}")
    print(f"MAE(total): {metrics['mae']}  (门禁 ≤ {gates['mae']})")
    print(f"Tier 一致率: {metrics['tier_agreement']}")
    print(f"Cohen's κ: {metrics['cohen_kappa']}  (门禁 ≥ {gates['kappa']})")
    print(f"Tier 翻转数: {metrics['flip_count']}  (门禁 ≤ {gates['max_flips']})")
    print(f"Outlier 率: {metrics['outlier_rate']}  (门禁 ≤ {gates['outlier_rate']})")
    if metrics["flips"]:
        print("  翻转明细:")
        for f in metrics["flips"]:
            print(f"    - {f['job_id']}: {f['from']} → {f['to']}")
    if passed:
        print("\n✅ 回归门禁通过（漂移在可接受范围内）")
    else:
        print("\n❌ 回归门禁失败:")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
