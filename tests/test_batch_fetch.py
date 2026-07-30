import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("batch_fetch", ROOT / "scripts" / "batch_fetch.py")
bf = importlib.util.module_from_spec(spec)
sys.modules["batch_fetch"] = bf
spec.loader.exec_module(bf)

SAMPLE = {
    "boss": [
        {"title": "后端工程师", "company": "A", "url": "http://a/1", "salary": "", "location": "", "raw": ""},
        {"title": "前端工程师", "company": "B", "url": "http://b/1", "salary": "", "location": "", "raw": ""},
    ],
    "linkedin": [
        {"title": "后端工程师", "company": "A", "url": "http://a/1", "salary": "", "location": "", "raw": ""},
        {"title": "算法工程师", "company": "C", "url": "http://c/1", "salary": "", "location": "", "raw": ""},
    ],
}


def _fake_portals():
    return {
        "portals": {
            "boss": {"enabled": True, "kind": "boss", "backend": "fetch_boss.py"},
            "linkedin": {"enabled": True, "kind": "linkedin", "backend": "fetch_jobs_linkedin.py"},
            "catdesk": {"enabled": True, "kind": "catdesk", "backend": "fetch_jobs.py"},  # 缺 base_url/preset → 跳过
        }
    }


def _fake_run_factory(fail_backend=None):
    def fake_run(cmd, *a, **k):
        out = cmd[cmd.index("--output") + 1]
        if fail_backend and fail_backend in cmd[1]:
            return subprocess.CompletedProcess(cmd, 2, "", "boom")
        key = "boss" if "fetch_boss" in cmd[1] else "linkedin" if "linkedin" in cmd[1] else "boss"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(SAMPLE.get(key, []), fh, ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return fake_run


def test_merge_and_dedup(tmp_path):
    out = tmp_path / "batch.json"
    with mock.patch.object(bf, "load_portals", return_value=_fake_portals()), \
         mock.patch.object(bf.subprocess, "run", _fake_run_factory()):
        jobs = bf.batch_fetch("后端", None, str(out), seen_path=str(tmp_path / "seen.json"))
    data = bf.load_jobs_format(str(out))
    assert len(data) == 3  # boss 2 + linkedin 2，其中 1 条 url 重复 → 3 条
    assert len(jobs) == 3


def test_missing_param_portal_skipped(tmp_path):
    # catdesk 缺 base_url/preset，应被优雅跳过，不报错
    out = tmp_path / "batch.json"
    with mock.patch.object(bf, "load_portals", return_value=_fake_portals()), \
         mock.patch.object(bf.subprocess, "run", _fake_run_factory()):
        jobs = bf.batch_fetch("后端", None, str(out), seen_path=str(tmp_path / "seen.json"))
    assert len(jobs) == 3  # 仅 boss + linkedin 贡献


def test_backend_failure_skipped(tmp_path):
    out = tmp_path / "batch.json"
    with mock.patch.object(bf, "load_portals", return_value=_fake_portals()), \
         mock.patch.object(bf.subprocess, "run", _fake_run_factory(fail_backend="linkedin")):
        jobs = bf.batch_fetch("后端", None, str(out), seen_path=str(tmp_path / "seen.json"))
    assert len(jobs) == 2  # 仅 boss 成功，linkedin 退出码 2 被跳过


def test_backend_command_shapes():
    q, p, m, o = "后端", 3, 0, "/tmp/x.json"
    assert bf._backend_command("boss", {"backend": "fetch_boss.py"}, q, p, m, o)[0:3] == [
        sys.executable, mock.ANY, "search"]
    assert bf._backend_command("linkedin", {"backend": "fetch_jobs_linkedin.py"}, q, p, m, o)[1].endswith("fetch_jobs_linkedin.py")
    assert bf._backend_command("catdesk", {"backend": "fetch_jobs.py"}, q, p, m, o) is None  # 缺 base_url+preset
    assert bf._backend_command("feishu", {"backend": "fetch_jobs_feishu.py"}, q, p, m, o) is None  # 缺 url
    assert bf._backend_command("catdesk", {"backend": "fetch_jobs.py", "base_url": "U", "preset": "generic"}, q, p, m, o) is not None
    # nowcoder：无 search 子命令，但带 --query/--pages/--max-jobs
    nc = bf._backend_command("nowcoder", {"backend": "fetch_jobs_nowcoder.py"}, q, p, m, o)
    assert "search" not in nc
    assert "--query" in nc and "--pages" in nc and "--max-jobs" in nc


def test_backend_command_no_search_for_linkedin_shixiseng():
    # 回归：linkedin/shixiseng 后端无子命令，命令里绝不能出现 "search"（否则子进程报
    # unrecognized 被静默跳过）。boss 有 search 子命令，保持不变。
    q, p, m, o = "后端", 3, 0, "/tmp/x.json"
    linkedin_cmd = bf._backend_command("linkedin", {"backend": "fetch_jobs_linkedin.py"}, q, p, m, o)
    shixiseng_cmd = bf._backend_command("shixiseng", {"backend": "fetch_jobs_shixiseng.py"}, q, p, m, o)
    nowcoder_cmd = bf._backend_command("nowcoder", {"backend": "fetch_jobs_nowcoder.py"}, q, p, m, o)
    assert "search" not in linkedin_cmd
    assert "search" not in shixiseng_cmd
    assert "search" not in nowcoder_cmd
    assert "search" in bf._backend_command("boss", {"backend": "fetch_boss.py"}, q, p, m, o)


def test_read_backend_output_json_and_text(tmp_path):
    # 回归：_read_backend_output 必须兼容 JSON（boss）与 v1 文本（其余后端）
    jf = tmp_path / "j.json"
    jf.write_text(json.dumps([{"title": "J", "url": "u", "company": "C"}], ensure_ascii=False), encoding="utf-8")
    jobs = bf._read_backend_output(str(jf))
    assert len(jobs) == 1 and jobs[0]["title"] == "J" and jobs[0]["_block"]

    tf = tmp_path / "t.txt"
    tf.write_text("--- JOB 1 ---\nT岗位\n[URL]http://t/1[/URL]\nCompany: Y\n", encoding="utf-8")
    jobs2 = bf._read_backend_output(str(tf))
    assert len(jobs2) == 1 and jobs2[0]["title"] == "T岗位" and jobs2[0]["url"] == "http://t/1"


def test_batch_fetch_reads_text_backend_end_to_end(tmp_path):
    # 最强回归：用一个「输出 v1 文本」的假 linkedin 后端，验证整链不静默丢数据。
    # 旧实现用 json.load 读取文本后端会异常 → 该门户 jobs 被丢弃。
    fake = tmp_path / "fake_linkedin.py"
    fake.write_text(
        "import argparse\n"
        "ap=argparse.ArgumentParser()\n"
        "ap.add_argument('--query',required=True);"
        "ap.add_argument('--output',required=True);"
        "ap.add_argument('--pages',type=int,default=1);"
        "ap.add_argument('--mode',default='auto')\n"
        "a=ap.parse_args()\n"
        "open(a.output,'w',encoding='utf-8').write('--- JOB 1 ---\\n假岗位A\\n[URL]http://x/9[/URL]\\nCompany: X\\nJD: 测试\\n')\n",
        encoding="utf-8",
    )
    portals = {"portals": {"li": {"enabled": True, "kind": "linkedin", "backend": str(fake)}}}
    out = tmp_path / "batch.txt"
    with mock.patch.object(bf, "load_portals", return_value=portals):
        jobs = bf.batch_fetch("测试", None, str(out), seen_path=str(tmp_path / "seen.json"))
    assert len(jobs) == 1, jobs
    blocks = bf.load_jobs_format(str(out))
    assert blocks and "假岗位A" in blocks[0]
