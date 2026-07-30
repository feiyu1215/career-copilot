# -*- coding: utf-8 -*-
"""T11 —— 版本间回归对比的单元测试 + 框架 CLI 自检。"""
import os
import sys
import subprocess

import pytest

EVALS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "evals"))
if EVALS_DIR not in sys.path:
    sys.path.insert(0, EVALS_DIR)

import run_regression_compare as T11  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_mae_at_known_value():
    assert T11.mae([80.0, 60.0], [85.0, 60.0]) == pytest.approx(2.5)


def test_cohen_kappa_identical_is_one():
    a = ["A", "B", "C", "A"]
    assert T11.cohen_kappa(a, a) == pytest.approx(1.0)


def test_cohen_kappa_known_negative():
    # 完全不吻合（observed=0，chance=0.5）→ κ = -1.0
    a = ["A", "A", "B", "B"]
    b = ["B", "B", "A", "A"]
    assert T11.cohen_kappa(a, b) == pytest.approx(-1.0)


def test_compute_regression_known_metrics():
    baseline = {
        "j1": {"total_score": 80.0, "tier": "B"},
        "j2": {"total_score": 60.0, "tier": "C"},
    }
    current = {
        "j1": {"total_score": 85.0, "tier": "A"},
        "j2": {"total_score": 60.0, "tier": "C"},
    }
    m = T11.compute_regression(baseline, current)
    assert m["n"] == 2
    assert m["mae"] == pytest.approx(2.5)
    assert m["tier_agreement"] == pytest.approx(0.5)
    assert m["cohen_kappa"] == pytest.approx(0.333, abs=0.01)
    assert m["flip_count"] == 1
    assert m["a_d_jump"] is False
    assert m["outlier_rate"] == pytest.approx(0.0)


def test_compute_regression_a_d_jump_flagged():
    baseline = {"x": {"total_score": 90.0, "tier": "A"}}
    current = {"x": {"total_score": 40.0, "tier": "D"}}
    m = T11.compute_regression(baseline, current)
    assert m["a_d_jump"] is True
    assert m["flip_count"] == 1


def test_regression_gate_passes_on_identical():
    baseline = {"j1": {"total_score": 84.0, "tier": "B"}}
    current = dict(baseline)
    m = T11.compute_regression(baseline, current)
    gates = {"mae": 5.0, "kappa": 0.8, "max_flips": 2, "outlier_rate": 0.10}
    passed, failures = T11.check_regression_gates(m, gates)
    assert passed is True
    assert failures == []


def test_regression_gate_fails_on_low_kappa():
    baseline = {
        "j1": {"total_score": 80.0, "tier": "B"},
        "j2": {"total_score": 60.0, "tier": "C"},
    }
    current = {
        "j1": {"total_score": 85.0, "tier": "A"},
        "j2": {"total_score": 60.0, "tier": "C"},
    }
    m = T11.compute_regression(baseline, current)
    gates = {"mae": 5.0, "kappa": 0.8, "max_flips": 2, "outlier_rate": 0.10}
    passed, failures = T11.check_regression_gates(m, gates)
    assert passed is False
    assert any("κ" in f for f in failures)


def test_cli_demo_runs_without_key():
    """框架自检：--demo 不应依赖 LLM key，且退出码 0（满足计划 VERIFY）。"""
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = ""
    env["AGNES_API_KEY"] = ""
    cp = subprocess.run(
        [sys.executable, "run_regression_compare.py", "--demo"],
        cwd=EVALS_DIR, capture_output=True, text=True, env=env,
    )
    assert cp.returncode == 0, cp.stderr
    assert "T11" in cp.stdout
