import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "behavior_fit.py"
spec = importlib.util.spec_from_file_location("behavior_fit", SCRIPT)
bf = importlib.util.module_from_spec(spec)
sys.modules["behavior_fit"] = bf
spec.loader.exec_module(bf)


def test_neutral_when_no_keywords():
    r = bf.compute_behavior_fit("这是一个关于猫咪的JD", None)
    assert r["score"] == 0.5
    assert r["implied_dims"] == []


def test_strong_match_high_score():
    profile = {"high": ["D", "I"]}
    jd = "负责主导项目，驱动结果，需要沟通表达和跨团队协调"
    r = bf.compute_behavior_fit(jd, profile)
    assert r["score"] > 0.8
    assert "负责" in r["matched"]


def test_gap_lowers_score():
    profile = {"low": ["D", "I"]}
    jd = "负责主导项目，驱动结果，需要沟通表达"
    r = bf.compute_behavior_fit(jd, profile)
    assert r["score"] < 0.3
    assert r["gaps"]


def test_styles_profile_full_match():
    profile = {"styles": {"D": 1.0, "I": 1.0, "S": 0.0, "C": 0.0}}
    jd = "负责主导，沟通表达"
    r = bf.compute_behavior_fit(jd, profile)
    assert r["score"] == 1.0


def test_load_missing_returns_empty():
    assert bf.load_behavioral_profile("/no/such/file.json") == {}
