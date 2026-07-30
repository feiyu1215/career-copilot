"""fetch_jobs_nowcoder.py 离线单测（纯 stdlib，无需真实网络 / bs4 / requests）。

覆盖：
- parse_jobs：字段提取 + URL 去重 + 退化链接扫描
- SPA 壳页（无卡片）优雅返回空（不崩溃，待本地微调）
- to_block：v1 块格式
- 限流/风控检测 + 退避确定性
- main：桩 HTTP 下写出 v1、限流停止、缺依赖 exit 2
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_jobs_nowcoder.py"
sys.path.insert(0, str(SCRIPT.parent))

spec_jc = importlib.util.spec_from_file_location(
    "job_common", SCRIPT.parent / "job_common.py")
jc = importlib.util.module_from_spec(spec_jc)
sys.modules["job_common"] = jc
spec_jc.loader.exec_module(jc)

spec = importlib.util.spec_from_file_location("fetch_jobs_nowcoder", SCRIPT)
fs = importlib.util.module_from_spec(spec)
sys.modules["fetch_jobs_nowcoder"] = fs
spec.loader.exec_module(fs)


SAMPLE = """
<html><body>
<div class="rec-job-card">
  <a href="/jobs/123">后端开发工程师</a>
  <span class="company-name">腾讯</span>
  <span class="job-city">深圳</span>
</div>
<div class="rec-job-card">
  <a href="/jobs/456">算法实习生</a>
  <span class="company-name">阿里</span>
</div>
<div class="rec-job-card">
  <a href="/jobs/123">重复条目</a>
</div>
</body></html>
"""


def test_parse_jobs_extracts_fields_and_dedups():
    jobs = fs.parse_jobs(SAMPLE)
    urls = [j["url"] for j in jobs]
    assert "https://www.nowcoder.com/jobs/123" in urls
    assert "https://www.nowcoder.com/jobs/456" in urls
    assert urls.count("https://www.nowcoder.com/jobs/123") == 1
    by = {j["url"]: j for j in jobs}
    a = by["https://www.nowcoder.com/jobs/123"]
    assert a["title"] == "后端开发工程师"
    assert a["company"] == "腾讯"
    assert a["location"] == "深圳"
    d = by["https://www.nowcoder.com/jobs/456"]
    assert d["title"] == "算法实习生" and d["company"] == "阿里"


def test_parse_jobs_spa_shell_returns_empty():
    # 牛客网 React SPA 壳页：无卡片、无职位链接 → 优雅返回空
    html = "<html><body><div id='root'></div><script>window.__INITIAL__={}</script></body></html>"
    assert fs.parse_jobs(html) == []


def test_parse_jobs_fallback_link_scan():
    html = ('<a href="/jobs/zzz">产品</a>'
            '<a href="/jobs/zzz">产品</a>'
            '<a href="/x">o</a>')
    jobs = fs.parse_jobs(html)
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://www.nowcoder.com/jobs/zzz"
    assert jobs[0]["title"] == "产品"


def test_to_block_format():
    block = fs.to_block({"title": "T", "url": "http://u", "company": "C",
                         "location": "L", "salary": "S", "description": ""})
    assert block.startswith("[URL]http://u[/URL]\nT")
    assert "C" in block and "L" in block and "S" in block


def test_is_rate_limit():
    assert fs._is_rate_limit("访问过于频繁，请稍后再试") is True
    assert fs._is_rate_limit("请完成安全验证") is True
    assert fs._is_rate_limit("校招提前批验证") is False


def test_backoff_deterministic_no_jitter():
    assert fs._backoff(1, 5.0, 0.0) == 5.0
    assert fs._backoff(2, 5.0, 0.0) == 10.0


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeHttp:
    @staticmethod
    def get(*a, **k):
        return _FakeResp(SAMPLE)


def test_main_writes_v1_with_stubbed_http(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fs, "_load_http", lambda: _FakeHttp)
    monkeypatch.setattr(fs.time, "sleep", lambda s: None)
    out = tmp_path / "jobs.txt"
    rc = fs.main(["--query", "算法", "--pages", "1", "--output", str(out)])
    assert rc == 0
    blocks = jc.load_jobs_format(str(out))
    assert len(blocks) == 2
    assert "后端开发工程师" in blocks[0]


def test_main_rate_limited_stops_and_empty(tmp_path, monkeypatch):
    class _RLResp:
        text = "访问过于频繁，请稍后再试"

        def raise_for_status(self):
            return None

    class _RLHttp:
        @staticmethod
        def get(*a, **k):
            return _RLResp()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fs, "_load_http", lambda: _RLHttp)
    monkeypatch.setattr(fs.time, "sleep", lambda s: None)
    out = tmp_path / "jobs.txt"
    rc = fs.main(["--query", "算法", "--pages", "2", "--output", str(out)])
    assert rc == 0
    assert jc.load_jobs_format(str(out)) == []


def test_main_missing_http_returns_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def _boom():
        raise RuntimeError("no requests")

    monkeypatch.setattr(fs, "_load_http", _boom)
    assert fs.main(["--query", "算法", "--output", "x.txt"]) == 2
