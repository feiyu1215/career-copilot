"""job_tracker.py 离线测试（不依赖网络 / 真实 notes 目录）。

做法：用临时 JSON 存储（--store 覆盖默认路径）跑完整生命周期 + stats + export。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "job_tracker.py")


def run(*args, store):
    cmd = [sys.executable, SCRIPT, "--store", store, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class JobTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, "jt.json")

    def _add(self):
        rc, out, err = run(
            "add", "--company", "ACME", "--role", "MLE", "--source", "boss",
            "--tier", "A", "--score", "82",
            "--reasons", "匹配K8s,论文相关", "--risks", "缺Go经验",
            store=self.store,
        )
        self.assertEqual(rc, 0, err)
        return out.strip().split()[1].rstrip(":")  # "已建档 <id>: ..." -> id

    def test_add_creates_planned_record(self):
        app_id = self._add()
        with open(self.store, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["applications"]), 1)
        rec = data["applications"][0]
        self.assertEqual(rec["id"], app_id)
        self.assertEqual(rec["status"], "planned")
        self.assertEqual(rec["tier"], "A")
        self.assertEqual(rec["score"], 82)
        self.assertEqual(rec["top_reasons"], ["匹配K8s", "论文相关"])
        self.assertEqual(rec["top_risks"], ["缺Go经验"])

    def test_apply_sets_applied_and_timestamp(self):
        app_id = self._add()
        rc, out, err = run("apply", "--id", app_id, store=self.store)
        self.assertEqual(rc, 0, err)
        with open(self.store, encoding="utf-8") as fh:
            rec = json.load(fh)["applications"][0]
        self.assertEqual(rec["status"], "applied")
        self.assertIsNotNone(rec["applied_at"])
        self.assertEqual(rec["history"][-1]["status"], "applied")

    def test_update_terminal_locks_outcome(self):
        app_id = self._add()
        run("apply", "--id", app_id, store=self.store)
        rc, out, err = run("update", "--id", app_id, "--status", "interview",
                           "--note", "一面过", store=self.store)
        self.assertEqual(rc, 0, err)
        rc, out, err = run("update", "--id", app_id, "--status", "offer",
                           "--note", "oc", store=self.store)
        self.assertEqual(rc, 0, err)
        with open(self.store, encoding="utf-8") as fh:
            rec = json.load(fh)["applications"][0]
        self.assertEqual(rec["status"], "offer")
        self.assertEqual(rec["outcome"], "offer")
        # 终态不可再变更
        rc, out, err = run("update", "--id", app_id, "--status", "rejected", store=self.store)
        self.assertEqual(rc, 2)
        self.assertIn("终态", err)

    def test_apply_on_non_planned_fails(self):
        app_id = self._add()
        run("apply", "--id", app_id, store=self.store)
        rc, out, err = run("apply", "--id", app_id, store=self.store)
        self.assertEqual(rc, 2)
        self.assertIn("不是 planned", err)

    def test_update_invalid_status_fails(self):
        app_id = self._add()
        rc, out, err = run("update", "--id", app_id, "--status", "bogus", store=self.store)
        self.assertEqual(rc, 2)
        self.assertIn("非法状态", err)

    def test_find_by_company_role_returns_latest(self):
        self._add()
        rc, out, err = run("add", "--company", "ACME", "--role", "SDE", "--source", "linkedin",
                           store=self.store)
        self.assertEqual(rc, 0, err)
        rc, out, err = run("show", "--company", "ACME", "--role", "SDE", store=self.store)
        self.assertEqual(rc, 0, err)
        rec = json.loads(out)
        self.assertEqual(rec["role"], "SDE")

    def test_stats_funnel_and_feedback(self):
        self._add()
        # 第二条申请走到 offer
        rc, out, err = run("add", "--company", "Zeta", "--role", "DS", "--source", "referral",
                           "--tier", "B", "--score", "70", store=self.store)
        self.assertEqual(rc, 0, err)
        zid = out.strip().split()[1].rstrip(":")
        run("apply", "--id", zid, store=self.store)
        run("update", "--id", zid, "--status", "offer", store=self.store)
        rc, out, err = run("stats", store=self.store)
        self.assertEqual(rc, 0, err)
        self.assertIn("状态漏斗", out)
        self.assertIn("按 tier 转化", out)
        self.assertIn("反馈回路", out)
        self.assertIn("offer", out)

    def test_export_writes_markdown(self):
        self._add()
        out_md = os.path.join(self.tmp, "summary.md")
        rc, out, err = run("export", "--out", out_md, store=self.store)
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.exists(out_md))
        with open(out_md, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Job Tracker 汇总", content)
        self.assertIn("ACME", content)


if __name__ == "__main__":
    unittest.main()
