#!/usr/bin/env python3
"""P1-4 eval 门禁测试：compute_summary 纯函数（SYNTHETIC-MECHANISM，fixtures 离线，无需 live key）。

Seam：`evals/run_dynamic_eval.compute_summary(results) -> summary`（含 gate）。
对应 PRD：`notes/p1-eval-gate-prd.md`；Tickets：`notes/p1-eval-gate-tickets.md`。
"""
import os
import sys

EVALS_DIR = os.path.join(os.path.dirname(__file__), "..", "evals")
if EVALS_DIR not in sys.path:
    sys.path.insert(0, EVALS_DIR)

from run_dynamic_eval import compute_summary  # noqa: E402


def _r(eid, passed, known=False, stable=None):
    return {
        "eval_id": eid,
        "known_variance": known,
        "verdict": {"passed": passed, "stable": stable},
    }


def test_gate_pass_when_core_all_pass_and_kv_stable():
    res = [_r(11, True), _r(12, True), _r(13, True), _r(14, True, known=True, stable=True)]
    s = compute_summary(res)
    assert s["gate"] == "PASS"


def test_gate_fail_when_core_fails():
    res = [_r(11, True), _r(12, False), _r(13, True), _r(14, True, known=True, stable=True)]
    assert compute_summary(res)["gate"] == "FAIL"


def test_gate_fail_when_kv_unstable():
    res = [_r(11, True), _r(12, True), _r(13, True), _r(14, True, known=True, stable=False)]
    assert compute_summary(res)["gate"] == "FAIL"


def test_gate_pass_when_kv_unverified():
    # known_variance 用例 stable=None（agnes 毛刺，未验证）→ 不阻断
    res = [_r(11, True), _r(12, True), _r(13, True), _r(14, None, known=True, stable=None)]
    s = compute_summary(res)
    assert s["gate"] == "PASS"
    assert s["known_variance"]["unverified"] == 1


def test_gate_core_count_and_kv_count():
    res = [_r(11, True), _r(12, True), _r(13, True), _r(14, True, known=True, stable=True)]
    s = compute_summary(res)
    assert s["core"]["total"] == 3
    assert s["core"]["passed"] == 3
    assert s["known_variance"]["total"] == 1
    assert s["known_variance"]["stable"] == 1
