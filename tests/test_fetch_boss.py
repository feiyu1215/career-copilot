"""fetch_boss.py 合同化回归测试（离线可跑，不依赖真实 BOSS 抓取）。

覆盖：
- normalize_job：解析含 [URL] 的 BOSS 卡片 → 各字段正确；缺 URL 时 url=""
- parse_boss_search_html：从搜索结果 HTML 解析 /job_detail/ 链接 → 字段 + 去重
- shortlist：按关键词筛选；空条件返回全部
- 可插拔注册表含 boss-cli（默认首选）+ bsk；未知后端抛 BackendUnavailable
- BossCliBackend：search 解析 JSON 信封 → 字段映射 + 去重 + 分页终止；
  available() 按 status 信封判断；detail 从 URL 抽取 security_id；
  CLI 缺失 / status 非 ok 时优雅降级
- 优雅降级：bsk 缺失时 available()==False、search() 抛 BackendUnavailable
- 刹车：FakeBackend 返回 100 条，search_jobs(max_jobs=10) 截断 ≤10，max_jobs=0 不限制
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_boss.py"
# fetch_boss 不再依赖 fetch_jobs；只需把 scripts/ 加入路径以 import
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("fetch_boss", SCRIPT)
fb = importlib.util.module_from_spec(spec)
# 注册进 sys.modules，否则 @dataclass 解析字符串注解时 sys.modules.get 为 None
sys.modules["fetch_boss"] = fb
spec.loader.exec_module(fb)


def test_normalize_parses_boss_card_with_url():
    raw = (
        "[URL]https://www.zhipin.com/job_detail/abc.html[/URL]\n"
        "推荐系统后端开发\n字节跳动\n20-40K·13薪\n北京·3-5年·本科\n负责推荐策略"
    )
    job = fb.normalize_job(raw)
    assert job.url == "https://www.zhipin.com/job_detail/abc.html"
    assert job.title == "推荐系统后端开发"
    assert job.company == "字节跳动"
    assert job.salary == "20-40K·13薪"
    assert job.location == "北京·3-5年·本科"


def test_normalize_handles_missing_url():
    raw = "前端开发\n某公司\n15K\n上海"
    job = fb.normalize_job(raw)
    assert job.url == ""
    assert job.title == "前端开发"
    assert job.raw == raw


FAKE_HTML = """
<div class="job-card-wrapper">
  <a class="job-card-left" href="/job_detail/abc123.html">
    <span class="job-name">推荐系统后端开发</span>
    <span class="company-name">字节跳动</span>
    <span class="salary">20-40K·13薪</span>
    <span class="job_area">北京·3-5年·本科</span>
  </a>
</div>
<div class="job-card-wrapper">
  <a class="job-card-left" href="/job_detail/def456.html">
    <span class="job-name">风控策略专家</span>
    <span class="company-name">美团</span>
    <span class="salary">30-50K</span>
  </a>
</div>
<!-- 重复链接应去重 -->
<div class="job-card-wrapper">
  <a class="job-card-left" href="/job_detail/abc123.html">重复</a>
</div>
"""


def test_parse_boss_search_html_extracts_and_dedupes():
    jobs = fb.parse_boss_search_html(FAKE_HTML)
    urls = [j.url for j in jobs]
    assert "https://www.zhipin.com/job_detail/abc123.html" in urls
    assert "https://www.zhipin.com/job_detail/def456.html" in urls
    # 去重：abc123 只出现一次
    assert urls.count("https://www.zhipin.com/job_detail/abc123.html") == 1
    by_url = {j.url: j for j in jobs}
    a = by_url["https://www.zhipin.com/job_detail/abc123.html"]
    assert a.title == "推荐系统后端开发"
    assert a.company == "字节跳动"
    assert a.salary == "20-40K·13薪"
    assert a.location == "北京·3-5年·本科"
    d = by_url["https://www.zhipin.com/job_detail/def456.html"]
    assert d.title == "风控策略专家"
    assert d.company == "美团"


def test_shortlist_filters_by_criteria():
    jobs = [fb.Job(title="Python 后端"), fb.Job(title="前端开发"), fb.Job(title="风控策略")]
    res = fb.BaseBackend().shortlist(jobs, "风控")
    assert [j.title for j in res] == ["风控策略"]


def test_shortlist_empty_criteria_returns_all():
    jobs = [fb.Job(title="a"), fb.Job(title="b")]
    assert len(fb.BaseBackend().shortlist(jobs, "")) == 2


def test_pluggable_backend_registry_has_boss_cli_and_bsk():
    assert "boss-cli" in fb.BACKENDS
    assert "bsk" in fb.BACKENDS
    assert isinstance(fb.get_backend("boss-cli"), fb.BossCliBackend)
    assert isinstance(fb.get_backend("bsk"), fb.BskBackend)


def test_default_backend_is_boss_cli():
    b = fb.get_backend()
    assert isinstance(b, fb.BossCliBackend)


def test_unknown_backend_raises():
    with pytest.raises(fb.BackendUnavailable):
        fb.get_backend("nonexistent")


def test_graceful_degradation_when_bsk_missing(monkeypatch):
    monkeypatch.setattr(fb.BskBackend, "_find_bsk", staticmethod(lambda: "/no/such/bsk"))
    b = fb.BskBackend()
    assert b.available() is False
    with pytest.raises(fb.BackendUnavailable):
        b.search("推荐系统", 1, 1.0)


def test_max_jobs_brake():
    class FakeBackend(fb.BaseBackend):
        name = "fake"

        def available(self):
            return True

        def search(self, query, pages, delay):
            return [fb.Job(title=f"job{i}") for i in range(100)]

        def detail(self, url):
            return "jd"

    fb.BACKENDS["fake"] = FakeBackend
    try:
        capped = fb.search_jobs("q", backend_name="fake", pages=1, delay=0, max_jobs=10)
        assert len(capped) <= 10
        uncapped = fb.search_jobs("q", backend_name="fake", pages=1, delay=0, max_jobs=0)
        assert len(uncapped) == 100
    finally:
        del fb.BACKENDS["fake"]


# ---- BossCliBackend（首选后端）离线测试 ----


def _boss_status_ok():
    return fb.subprocess.CompletedProcess(
        args=(), returncode=0,
        stdout='{"ok":true,"command":"status","data":{"logged_in":true,"auth_state":"complete"},"error":null}',
        stderr="",
    )


def _boss_search_envelope():
    data = [
        {
            "title": "推荐系统后端开发", "company": "字节跳动", "salary": "20-40K·13薪",
            "city": "北京", "experience": "3-5年", "education": "本科",
            "security_id": "abc123", "description": "负责推荐策略",
        },
        {
            "jobName": "风控策略专家", "brandName": "美团", "salaryDesc": "30-50K",
            "cityName": "上海", "security_id": "def456",
        },
        {"title": "重复项", "security_id": "abc123"},  # 应被去重
    ]
    return fb.subprocess.CompletedProcess(
        args=(), returncode=0,
        stdout='{"ok":true,"command":"search","data":' + __import__("json").dumps(data, ensure_ascii=False)
        + ',"pagination":{"has_more":false,"page":1},"error":null}',
        stderr="",
    )


def _boss_detail_envelope():
    return fb.subprocess.CompletedProcess(
        args=(), returncode=0,
        stdout='{"ok":true,"command":"detail","data":{"description":"完整职位描述..."},"error":null}',
        stderr="",
    )


def test_boss_cli_search_maps_and_dedupes(monkeypatch):
    b = fb.BossCliBackend()
    monkeypatch.setattr(b, "_run", lambda *a, timeout=120: _boss_search_envelope())
    jobs = b.search("推荐系统", pages=3, delay=0)
    urls = [j.url for j in jobs]
    assert "https://www.zhipin.com/job_detail/abc123.html" in urls
    assert "https://www.zhipin.com/job_detail/def456.html" in urls
    assert urls.count("https://www.zhipin.com/job_detail/abc123.html") == 1  # 去重
    by_url = {j.url: j for j in jobs}
    a = by_url["https://www.zhipin.com/job_detail/abc123.html"]
    assert a.title == "推荐系统后端开发" and a.company == "字节跳动"
    assert a.location == "北京" and a.salary == "20-40K·13薪"
    d = by_url["https://www.zhipin.com/job_detail/def456.html"]
    assert d.title == "风控策略专家" and d.company == "美团" and d.location == "上海"


def test_boss_cli_search_stops_on_has_more_false(monkeypatch):
    b = fb.BossCliBackend()
    monkeypatch.setattr(b, "_run", lambda *a, timeout=120: _boss_search_envelope())
    # pagination.has_more=false → 只跑 1 页（即便 pages=5），不重复请求
    jobs = b.search("推荐系统", pages=5, delay=0)
    assert len(jobs) == 2  # 去重后 2 条


def test_boss_cli_available_true_and_false(monkeypatch):
    b = fb.BossCliBackend()
    monkeypatch.setattr(b, "_run", lambda *a, timeout=20: _boss_status_ok())
    assert b.available() is True

    bad = fb.subprocess.CompletedProcess(args=(), returncode=0,
        stdout='{"ok":false,"data":null,"error":{"code":"AUTH_REQUIRED","message":"未登录"}}', stderr="")
    monkeypatch.setattr(b, "_run", lambda *a, timeout=20: bad)
    assert b.available() is False


def test_boss_cli_graceful_when_cli_missing(monkeypatch):
    monkeypatch.setattr(fb.BossCliBackend, "_find_boss_cli", staticmethod(lambda: "/no/such/boss"))
    b = fb.BossCliBackend()
    assert b.available() is False
    with pytest.raises(fb.BackendUnavailable):
        b.search("推荐系统", 1, 1.0)


def test_boss_cli_detail_extracts_security_id(monkeypatch):
    b = fb.BossCliBackend()
    monkeypatch.setattr(b, "_run", lambda *a, timeout=60: _boss_detail_envelope())
    # 传完整 URL 也能从路径抽取 security_id 并取到 description
    assert b.detail("https://www.zhipin.com/job_detail/xyz789.html") == "完整职位描述..."


# --- Phase 4.1：限流自愈 / 登录态分级 -------------------------------------

def _fake_res(returncode=0, stdout="", stderr=""):
    return fb.subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


def test_detect_rate_limit_markers():
    # 强信号触发
    assert fb.detect_rate_limit("访问过于频繁，请稍后再试") is True
    assert fb.detect_rate_limit("请完成安全验证 滑动验证") is True
    assert fb.detect_rate_limit("HTTP 429 Too Many Requests") is True
    assert fb.detect_rate_limit("verify you are human") is True
    # 正常 JD 文案不误伤（含「验证」但非验证码）
    assert fb.detect_rate_limit("负责推荐策略的技术验证与线上验证") is False
    assert fb.detect_rate_limit("") is False


def test_backoff_delay_exponential_no_jitter():
    # jitter=0 时序列确定性：5, 10, 20
    assert fb._backoff_delay(1, 5.0, 0.0) == 5.0
    assert fb._backoff_delay(2, 5.0, 0.0) == 10.0
    assert fb._backoff_delay(3, 5.0, 0.0) == 20.0


def test_with_rate_limit_retry_succeeds_after_retries():
    sleeps = []
    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        if calls["n"] <= 2:
            return ("partial", True)  # 限流，需重试
        return ("ok", False)

    res = fb.with_rate_limit_retry(attempt, sleep=lambda s: sleeps.append(s))
    assert res == "ok"
    assert calls["n"] == 3  # 2 次限流 + 1 次成功
    assert len(sleeps) == 2  # 每次重试前各睡一次


def test_with_rate_limit_retry_exhausted_raises_rate_limited():
    def attempt():
        return ("x", True)

    with pytest.raises(fb.RateLimited) as exc:
        fb.with_rate_limit_retry(attempt, sleep=lambda s: None)
    assert isinstance(exc.value, fb.BackendUnavailable)  # 仍是优雅降级信号


def test_boss_cli_search_retries_on_rate_limit(monkeypatch):
    b = fb.BossCliBackend()
    monkeypatch.setattr(b, "available", lambda: True)
    monkeypatch.setattr(fb.time, "sleep", lambda s: None)  # 跳过真实退避
    calls = {"search": 0}

    def fake_run(*args, timeout=120):
        if args and args[0] == "search":
            calls["search"] += 1
            if calls["search"] <= 2:
                return _fake_res(0, '{"ok":false,"error":{"code":"RATE_LIMITED","message":"频率过快"}}')
            data = [{"title": "后端开发", "company": "A", "security_id": "x1", "salary": "20K", "city": "北京"}]
            return _fake_res(0, '{"ok":true,"data":' + __import__("json").dumps(data, ensure_ascii=False)
                              + ',"pagination":{"has_more":false},"error":null}')
        return _fake_res(0, '{"ok":true}')  # status 等其它命令

    monkeypatch.setattr(b, "_run", fake_run)
    jobs = b.search("python", pages=3, delay=0)
    assert len(jobs) == 1
    assert calls["search"] == 3  # 2 限流 + 1 成功（自愈后拿到数据）


def test_boss_cli_search_auth_expired_message(monkeypatch):
    b = fb.BossCliBackend()
    monkeypatch.setattr(b, "available", lambda: True)
    monkeypatch.setattr(b, "_run", lambda *a, timeout=120: _fake_res(
        0, '{"ok":false,"error":{"code":"SESSION_EXPIRED","message":"登录失效"}}'))
    with pytest.raises(fb.BackendUnavailable) as exc:
        b.search("python", pages=1, delay=0)
    assert "boss login" in str(exc.value)  # 显式「重新登录」提示


def test_bsk_search_retries_on_rate_limit(monkeypatch):
    monkeypatch.setattr(fb.BskBackend, "_find_bsk", staticmethod(lambda: "bsk"))
    b = fb.BskBackend()
    b.delay = 0
    monkeypatch.setattr(b, "available", lambda: True)
    monkeypatch.setattr(b, "_ensure_session", lambda: "sess")
    monkeypatch.setattr(b, "_is_login_wall", lambda s: False)
    monkeypatch.setattr(fb.time, "sleep", lambda s: None)
    get_html = {"n": 0}
    # 解析器要求相对路径 href="/job_detail/..."（非完整 URL）
    real_html = (
        '<div class="job-card"><a href="/job_detail/abc.html">'
        '<span class="job-name">后端开发</span></a></div>'
    )

    def fake_run(*args, timeout=30):
        if args and args[0] == "navigate":
            return _fake_res(0, "")
        if args and args[0] == "get-html":
            get_html["n"] += 1
            if get_html["n"] <= 2:
                return _fake_res(0, "<html>请完成安全验证 滑动验证</html>")  # 风控页
            return _fake_res(0, real_html)
        return _fake_res(0, "")

    monkeypatch.setattr(b, "_run", fake_run)
    jobs = b.search("python", pages=1, delay=0)
    assert len(jobs) == 1
    assert jobs[0].url == "https://www.zhipin.com/job_detail/abc.html"
    assert get_html["n"] == 3  # 2 风控页 + 1 真实页（自愈）
