# -*- coding: utf-8 -*-
"""Golden Cases（3.1）结构与覆盖矩阵自检（离线，无 LLM）。"""
from pathlib import Path
import json
import pytest

GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "golden"
CASES = sorted(GOLDEN.glob("case_*.json"))

REQUIRED_TOP = {"id", "profile", "jd_text", "expected_score",
                "expected_tier", "key_reasons", "annotator", "meta"}
REQUIRED_META = {"track", "role_family", "transition", "career_stage", "match_band"}


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_ten_cases_present():
    assert len(CASES) == 10, f"应有 10 个 case，实际 {len(CASES)}"


@pytest.mark.parametrize("case_path", CASES, ids=lambda p: p.name)
def test_case_schema(case_path):
    data = _load(case_path)
    missing = REQUIRED_TOP - set(data)
    assert not missing, f"{case_path.name} 缺字段 {missing}"
    assert isinstance(data["expected_score"], (int, float)) and 0 <= data["expected_score"] <= 100
    assert data["expected_tier"] in {"A", "B", "C"}
    meta = data.get("meta", {})
    assert REQUIRED_META <= set(meta), f"{case_path.name} meta 缺 {REQUIRED_META - set(meta)}"


def test_coverage_matrix():
    counts = {"tech": 0, "non_tech": 0, "transition": 0,
              "campus_intern": 0, "high": 0, "low": 0}
    for p in CASES:
        m = _load(p).get("meta", {})
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
    assert not gaps, f"覆盖矩阵缺口：{gaps}"
