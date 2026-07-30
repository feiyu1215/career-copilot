"""m5 回归测试：verify_output C7 的 A 档最低分下限应为 80（与注释「应 >= 80」一致）。

阈值原为 75，与注释矛盾；现统一为 80。
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_output.py"
spec = importlib.util.spec_from_file_location("verify_output_c7", SCRIPT)
vo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vo)


def _item(job_id, title, score, tier, risks=None):
    return {"job_id": job_id, "title": title, "score": score, "tier": tier, "risks": risks or []}


def _build(a_scores):
    a = [_item(f"a{i}", f"A{i}", s, "A") for i, s in enumerate(a_scores)]
    b = [_item("b0", "B0", 72, "B"), _item("b1", "B1", 73, "B")]
    c = [_item("c0", "C0", 68, "C")]
    items = a + b + c
    return {
        "pipeline": {s: {} for s in ["stage1", "stage1_5", "stage2", "stage2_5", "post_judge", "direction_anchor"]},
        "summary": {"tier_A": len(a), "tier_B": len(b), "tier_C": len(c)},
        "recommendations": {"tier_A": a, "tier_B": b, "tier_C": c},
    }


def test_c7_a_floor_80_passes_at_80():
    data = _build([80])
    failures, warnings, counts = vo.run_checks(data)
    assert failures == [], failures


def test_c7_a_floor_80_fails_below_80():
    data = _build([78])
    failures, warnings, counts = vo.run_checks(data)
    assert any("[C7]" in f for f in failures), failures
