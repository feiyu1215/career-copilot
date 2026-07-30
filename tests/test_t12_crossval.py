# -*- coding: utf-8 -*-
"""T12 —— 多 Judge 交叉验证的单元测试 + 框架 CLI 自检。"""
import os
import sys
import subprocess

import pytest

EVALS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "evals"))
if EVALS_DIR not in sys.path:
    sys.path.insert(0, EVALS_DIR)

import run_crossval as T12  # noqa: E402


def test_fleiss_kappa_known_value():
    # 经典 3 样本 × 3 Judge 矩阵（Fleiss κ ≈ 0.550）
    matrix = [
        ["A", "A", "A"],
        ["B", "B", "B"],
        ["A", "B", "A"],
    ]
    assert T12.fleiss_kappa(matrix) == pytest.approx(0.550, abs=0.01)


def test_fleiss_kappa_perfect_agreement_is_one():
    matrix = [["A", "A"], ["B", "B"], ["C", "C"]]
    assert T12.fleiss_kappa(matrix) == pytest.approx(1.0)


def test_cohen_kappa_pairwise_identical():
    a = ["A", "B", "C"]
    assert T12.cohen_kappa(a, a) == pytest.approx(1.0)


def test_compute_crossval_low_agreement_flagged():
    # 3 样本 × 2 Judge；样本 1 两 judge 一致，样本 2 不一致
    matrix = [
        ["A", "A"],
        ["A", "B"],
        ["C", "C"],
    ]
    m = T12.compute_crossval(matrix)
    assert m["n_subjects"] == 3
    assert m["n_judges"] == 2
    assert m["low_agreement_count"] == 1
    assert m["low_agreement"][0]["sample"] == 1
    # 2 Judge 逐对 κ 应存在
    assert "j0-j1" in m["pairwise_cohen_kappa"]


def test_crossval_gate_passes_on_high_agreement():
    matrix = [["A", "A", "A"], ["B", "B", "B"], ["C", "C", "C"], ["A", "A", "A"]]
    m = T12.compute_crossval(matrix)
    passed, failures = T12.check_crossval_gates(m, 0.6)
    assert passed is True


def test_crossval_gate_fails_on_low_agreement():
    # 完全随机（全不一致）→ Fleiss κ 近 0
    matrix = [
        ["A", "B"],
        ["B", "A"],
        ["A", "B"],
        ["B", "A"],
    ]
    m = T12.compute_crossval(matrix)
    passed, failures = T12.check_crossval_gates(m, 0.6)
    assert passed is False
    assert any("κ" in f for f in failures)


def test_cli_demo_runs_without_key():
    """框架自检：--demo 不应依赖 LLM key，且退出码 0（满足计划 VERIFY）。"""
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = ""
    env["AGNES_API_KEY"] = ""
    cp = subprocess.run(
        [sys.executable, "run_crossval.py", "--demo"],
        cwd=EVALS_DIR, capture_output=True, text=True, env=env,
    )
    assert cp.returncode == 0, cp.stderr
    assert "T12" in cp.stdout
