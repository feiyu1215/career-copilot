"""A 档上限一致性验收：post_judge.enforce_distribution 与 verify_output C4 必须同源。

背景：修复前 verify_output 用固定 15 硬上限，post_judge 用 25% 比例上限，两者在 n>60 时冲突
（约束器放行的输出被校验器判死）；且 FILE_GUIDE 曾误写 30%。

本测试断言：
1. 对任意 n∈{10,20,50,100}，post_judge 产出的 A 档数 = max(3, int(n*0.25))，且 verify C4 放行。
2. 一旦 A 档数 > max(3, int(n*0.25))，verify C4 判失败。
3. 干净大批量（penalties=0）不再触发 C9 硬失败（仅 WARNING）。

运行：uv run pytest tests/test_a_cap_consistency.py -q
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from config_loader import load_constraints  # noqa: E402

_A_TIER_CAP = load_constraints()["a_tier_cap"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vo = _load("verify_output")
pj = _load("post_judge")


def a_cap(n):
    return max(_A_TIER_CAP["min_floor"], int(n * _A_TIER_CAP["max_ratio"]))


def build_results(n_a, n_total, penalties=2):
    """构造 verify_output 期望的 scored_results 结构（分数落在各档合法区间，隔离 C4 测试）。"""
    items = []
    for i in range(n_a):
        items.append(
            {"job_id": f"A{i}", "title": f"Job{i}", "score": 85 + (i % 15), "tier": "A", "risks": []}
        )
    remaining = n_total - n_a
    for i in range(remaining):
        items.append(
            {"job_id": f"B{i}", "title": f"Job{n_a + i}", "score": 60 + (i % 19), "tier": "B", "risks": []}
        )
    pipeline = {s: {} for s in ["stage1", "stage1_5", "stage2", "stage2_5", "direction_anchor"]}
    pipeline["post_judge"] = {"penalties_applied": penalties}
    return {
        "pipeline": pipeline,
        "summary": {"tier_A": n_a, "tier_B": remaining, "tier_C": 0},
        "recommendations": {
            "tier_A": [it for it in items if it["tier"] == "A"],
            "tier_B": [it for it in items if it["tier"] == "B"],
            "tier_C": [],
        },
    }


class TestCapConsistency:
    def test_post_judge_cap_matches_verify_cap(self):
        for n in [10, 20, 50, 100]:
            cap = a_cap(n)
            # 全 A 输入，post_judge 应降至 cap 个 A
            jobs = [
                {"job_id": f"J{i}", "score": 90 - i, "tier": "A", "full_text": "普通岗位"}
                for i in range(n)
            ]
            result = pj.enforce_distribution(jobs, pj.DEFAULT_CONFIG)
            a_count = sum(1 for j in result if j["tier"] == "A")
            assert a_count == cap, f"n={n}: post_judge A 数 {a_count} != cap {cap}"
            # 该结果应被 verify C4 放行
            data = build_results(a_count, n, penalties=2)
            failures, warnings, counts = vo.run_checks(data)
            assert not any("[C4]" in f for f in failures), (n, failures)

    def test_verify_c4_fails_when_over_cap(self):
        n = 100
        cap = a_cap(n)
        data = build_results(cap + 1, n, penalties=2)
        failures, warnings, counts = vo.run_checks(data)
        assert any("[C4]" in f for f in failures), failures

    def test_clean_large_batch_no_failure(self):
        # 干净大批量：penalties=0 不应再触发 C9 硬失败
        n = 25
        data = build_results(a_cap(n), n, penalties=0)
        failures, warnings, counts = vo.run_checks(data)
        assert not any("[C9]" in f for f in failures), failures
        # 但应给出 WARNING 提示
        assert any("[W]" in w for w in warnings), warnings
