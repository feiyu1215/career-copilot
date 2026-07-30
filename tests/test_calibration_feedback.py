"""calibration_feedback.py 离线测试（不依赖网络 / 真实 notes 目录）。

做法：用临时 JSON 存储构造合成投递记录，验证漏斗计算 / 异常检测 /
校准建议 / 阈值提议，以及 generate_report 的历史漏斗渲染。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "calibration_feedback.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from calibration_feedback import (  # noqa: E402
    compute_tier_funnel,
    detect_anomalies,
    generate_calibration_suggestions,
    propose_threshold_adjustments,
    build_report,
)
from generate_report import render_history_funnel  # noqa: E402


def _app(tid, tier, status, applied_at="2026-01-01T00:00:00+08:00"):
    return {
        "id": tid,
        "company": f"C{tid}",
        "role": "r",
        "source": "boss",
        "tier": tier,
        "score": 80,
        "status": status,
        "applied_at": applied_at,
        "outcome": "offer" if status == "offer" else None,
        "history": [],
        "created_at": applied_at,
        "top_reasons": [],
        "top_risks": [],
        "notes": "",
    }


def _write_store(tmp_path, apps):
    p = tmp_path / "jt.json"
    p.write_text(json.dumps({"applications": apps}, ensure_ascii=False), encoding="utf-8")
    return str(p)


class FunnelTest(unittest.TestCase):
    def test_funnel_counts_and_rates(self):
        apps = [
            _app("1", "A", "applied"),
            _app("2", "A", "interview"),
            _app("3", "A", "offer"),
            _app("4", "A", "planned", applied_at=None),  # 未投递，不计入 reached
            _app("5", "B", "applied"),
            _app("6", "B", "rejected"),
        ]
        f = compute_tier_funnel(apps)
        a = f["by_tier"]["A"]
        self.assertEqual(a["n"], 4)              # 含 1 条 planned（按 tier 计数）
        self.assertEqual(a["reached"], 3)        # planned 不计入；applied/interview/offer 计入
        self.assertEqual(a["interview"], 2)       # interview + offer 均计为「走到面试」
        self.assertEqual(a["offer"], 1)
        self.assertAlmostEqual(a["offer_rate"], 1 / 3, places=4)
        self.assertAlmostEqual(a["interview_rate"], 2 / 3, places=4)
        b = f["by_tier"]["B"]
        self.assertEqual(b["reached"], 2)        # applied + rejected
        self.assertEqual(b["offer"], 0)
        self.assertEqual(f["total_records"], 6)
        self.assertEqual(f["total_reached"], 5)

    def test_empty_store(self):
        f = compute_tier_funnel([])
        self.assertEqual(f["rows"], [])
        self.assertEqual(f["total_reached"], 0)
        self.assertEqual(f["overall_offer_rate"], 0.0)


class AnomalyTest(unittest.TestCase):
    def test_insufficient_sample_returns_empty(self):
        apps = [_app("1", "A", "applied"), _app("2", "B", "offer")]
        f = compute_tier_funnel(apps)
        self.assertEqual(detect_anomalies(f, min_samples=10), [])

    def test_a_le_b_offer_detected(self):
        # A 全灭，B 有转化 → 过排名（A 6 投递 + B 5 投递，共 11 ≥ 10）
        apps = [_app(str(i), "A", "applied") for i in range(1, 7)] + \
               [_app(str(i), "B", "interview") for i in range(7, 11)] + \
               [_app("11", "B", "offer")]
        f = compute_tier_funnel(apps)
        types = {a["type"] for a in detect_anomalies(f, min_samples=10)}
        self.assertIn("A_le_B_offer", types)
        self.assertIn("A_low_interview", types)
        self.assertIn("B_over_A_offer", types)

    def test_normal_no_anomaly(self):
        apps = (
            [_app(str(i), "A", "interview") for i in range(1, 4)]
            + [_app(str(i), "A", "offer") for i in range(4, 6)]
            + [_app(str(i), "B", "interview") for i in range(6, 8)]
            + [_app("8", "B", "offer")]
            + [_app(str(i), "B", "applied") for i in range(9, 12)]
        )
        f = compute_tier_funnel(apps)
        self.assertEqual(detect_anomalies(f, min_samples=10), [])

    def test_win_interview_lose_offer(self):
        # A 大量面试但零 offer（A 5 面试 + B 5 投递，共 10 ≥ 10）
        apps = [_app(str(i), "A", "interview") for i in range(1, 6)] + \
               [_app(str(i), "B", "applied") for i in range(6, 11)]  # B 无转化，避免反向噪声
        f = compute_tier_funnel(apps)
        types = {a["type"] for a in detect_anomalies(f, min_samples=10)}
        self.assertIn("A_win_interview_lose_offer", types)


class SuggestionTest(unittest.TestCase):
    def test_suggestions_generated_when_anomalies(self):
        # A 6 投递全灭 + B 4 面试 1 offer（共 11 ≥ 10）
        apps = [_app(str(i), "A", "applied") for i in range(1, 7)] + \
               [_app(str(i), "B", "interview") for i in range(7, 11)] + \
               [_app("11", "B", "offer")]
        f = compute_tier_funnel(apps)
        anoms = detect_anomalies(f, min_samples=10)
        suggs = generate_calibration_suggestions(f, anoms)
        self.assertTrue(suggs)
        ids = {s["id"] for s in suggs}
        self.assertIn("raise_a_threshold", ids)
        # 每个建议都指向具体配置项
        for s in suggs:
            self.assertTrue(s["config_ref"])

    def test_no_suggestions_when_clean(self):
        apps = [_app(str(i), "A", "offer") for i in range(1, 4)] + \
               [_app(str(i), "B", "interview") for i in range(4, 7)]
        f = compute_tier_funnel(apps)
        self.assertEqual(generate_calibration_suggestions(f, []), [])


class ThresholdProposalTest(unittest.TestCase):
    def test_overranking_raises_a_threshold(self):
        proposed = propose_threshold_adjustments(
            {}, [{"type": "A_le_B_offer"}], pipeline_config=None)
        self.assertEqual(proposed.get("tiers", {}).get("A"), 88)  # 85 + 3

    def test_reverse_overranking_lowers_score_high_mid(self):
        proposed = propose_threshold_adjustments(
            {}, [{"type": "B_over_A_offer"}], pipeline_config=None)
        self.assertEqual(proposed.get("output", {}).get("score_high"), 95)  # 97 - 2
        self.assertEqual(proposed.get("output", {}).get("score_mid"), 69)   # 72 - 3

    def test_clean_no_proposal(self):
        self.assertEqual(propose_threshold_adjustments({}, [], pipeline_config=None), {})


class ReportTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_insufficient_sample_report(self):
        store = _write_store(self.tmp, [_app("1", "A", "applied"),
                                        _app("2", "B", "offer")])
        rep = build_report(store, min_samples=10)
        self.assertFalse(rep["sample_sufficient"])
        self.assertEqual(rep["anomalies"], [])
        self.assertIn("样本不足", rep["conclusion"])

    def test_sufficient_anomaly_report(self):
        # A 6 投递全灭 + B 4 面试 1 offer（共 11 ≥ 10）
        apps = [_app(str(i), "A", "applied") for i in range(1, 7)] + \
               [_app(str(i), "B", "interview") for i in range(7, 11)] + \
               [_app("11", "B", "offer")]
        store = _write_store(self.tmp, apps)
        rep = build_report(store, min_samples=10)
        self.assertTrue(rep["sample_sufficient"])
        self.assertTrue(rep["anomalies"])
        self.assertTrue(rep["proposed_thresholds"])


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run(self, *args):
        cmd = [sys.executable, SCRIPT, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def test_cli_json_output(self):
        apps = [_app(str(i), "A", "applied") for i in range(1, 7)] + \
               [_app(str(i), "B", "interview") for i in range(7, 11)] + \
               [_app("11", "B", "offer")]
        store = _write_store(Path(self.tmp), apps)
        rc, out, err = self._run("--store", store, "--json")
        self.assertEqual(rc, 0, err)
        data = json.loads(out)
        self.assertTrue(data["sample_sufficient"])
        self.assertTrue(data["anomalies"])

    def test_cli_suggest_writes_file(self):
        apps = [_app(str(i), "A", "applied") for i in range(1, 7)] + \
               [_app(str(i), "B", "interview") for i in range(7, 11)] + \
               [_app("11", "B", "offer")]
        store = _write_store(Path(self.tmp), apps)
        out_yaml = os.path.join(self.tmp, "prop.suggested.yaml")
        rc, out, err = self._run("--store", store, "--suggest",
                                 "--suggest-out", out_yaml)
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.exists(out_yaml))
        with open(out_yaml, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("tiers", content)

    def test_cli_missing_store_fails(self):
        rc, out, err = self._run("--store", os.path.join(self.tmp, "nope.json"))
        self.assertEqual(rc, 1)


class ReportFunnelRenderTest(unittest.TestCase):
    def test_render_history_funnel_empty(self):
        self.assertEqual(render_history_funnel(None), "")
        self.assertEqual(render_history_funnel({"rows": []}), "")

    def test_render_history_funnel_html(self):
        f = compute_tier_funnel([
            _app("1", "A", "offer"),
            _app("2", "A", "applied"),
            _app("3", "B", "interview"),
        ])
        html = render_history_funnel(f)
        self.assertIn("历史转化漏斗", html)
        self.assertIn(">A<", html)
        self.assertIn("整体 offer 率", html)


if __name__ == "__main__":
    unittest.main()
