"""verify_output.py 合同化回归测试。

覆盖：
- 合法输入：通过且 counts 正确（real/fallback 区分）
- fallback 在 0~15% 区间：不失败但[W]警告必须显式暴露（不再静默通过）
- fallback > 15%：触发 [C12] 硬失败
- 顶层缺字段：触发 [C1]
- JSON 截断/损坏：load_results 优雅 FAIL [C0] 并退出码 1（不抛 traceback）
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_output.py"
spec = importlib.util.spec_from_file_location("verify_output", SCRIPT)
vo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vo)


def _item(job_id, title, score, tier, risks=None):
    return {"job_id": job_id, "title": title, "score": score, "tier": tier, "risks": risks or []}


def build(n_a=3, n_b=2, n_c=1, fallback_ids=None):
    fallback_ids = fallback_ids or set()
    items = []
    # 各档用独立基数，保证整体分数分布拉开（range >= 10，避免误触 C11），
    # 且 A 档最低分 >= 75（避免误触 C7）。
    i = 0
    for _ in range(n_a):
        rid = f"a{i}"
        risks = ["模型未返回该岗位评估"] if rid in fallback_ids else []
        items.append(_item(rid, f"AJob{i}", 85 + i, "A", risks))
        i += 1
    for _ in range(n_b):
        rid = f"b{i}"
        risks = ["模型未返回该岗位评估"] if rid in fallback_ids else []
        items.append(_item(rid, f"BJob{i}", 72 + i, "B", risks))
        i += 1
    for _ in range(n_c):
        rid = f"c{i}"
        risks = ["模型未返回该岗位评估"] if rid in fallback_ids else []
        items.append(_item(rid, f"CJob{i}", 68 + i, "C", risks))
        i += 1
    return {
        "pipeline": {s: {} for s in ["stage1", "stage1_5", "stage2", "stage2_5", "post_judge", "direction_anchor"]},
        "summary": {"tier_A": n_a, "tier_B": n_b, "tier_C": n_c},
        "recommendations": {
            "tier_A": [it for it in items if it["tier"] == "A"],
            "tier_B": [it for it in items if it["tier"] == "B"],
            "tier_C": [it for it in items if it["tier"] == "C"],
        },
    }


def test_valid_passes():
    data = build()
    failures, warnings, counts = vo.run_checks(data)
    assert failures == [], failures
    assert counts["total"] == 6
    assert counts["real"] == 6
    assert counts["fallback"] == 0


def test_fallback_low_ratio_warns_not_fails():
    # fallback 1/10 = 10% < 15% -> 不失败但必须显式警告；
    # A 档 2/10 = 20% ≤ 25% 上限，不误触新 C4（修复前固定 15 上限曾放过 50% A 档）。
    data = build(n_a=2, n_b=4, n_c=4, fallback_ids={"a0"})
    failures, warnings, counts = vo.run_checks(data)
    assert counts["fallback"] == 1, counts
    assert counts["real"] == 9, counts
    assert failures == [], failures
    assert any("fallback" in w for w in warnings), warnings


def test_fallback_high_ratio_fails():
    # 3/6 = 50% > 15% -> [C12] 硬失败
    data = build(n_a=3, n_b=2, n_c=1, fallback_ids={"a0", "a1", "a2"})
    failures, warnings, counts = vo.run_checks(data)
    assert any("[C12]" in f for f in failures), failures


def test_missing_top_key_fails_c1():
    data = build()
    del data["pipeline"]
    failures, warnings, counts = vo.run_checks(data)
    assert any("[C1]" in f for f in failures), failures


def test_json_decode_error_exits(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json ", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        vo.load_results(str(bad))
    assert e.value.code == 1
