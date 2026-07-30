"""Phase 7.2 — 抓取合规：portals.yaml rate_limit 主动节流（token bucket）测试。

离线、确定性、纯 stdlib。验证：
  - parse_rate_limit 多格式解析与不节流（off/None/非法）
  - RateLimiter token bucket 语义（注入假时钟/睡眠，断言不真正 sleep）
  - make_portal_limiter 从配置构造
  - acquire_portal_throttle 在 fetch 脚本请求前被调用（接线）
  - 真实 config/portals.yaml 每个 portal 都含可解析的 rate_limit
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from job_common import (
    parse_rate_limit, RateLimiter, make_portal_limiter,
    acquire_portal_throttle, reset_portal_throttles,
)


def test_parse_rate_limit_formats():
    assert parse_rate_limit("30 req/min") == (30.0, 60.0)
    assert parse_rate_limit("10 req/min") == (10.0, 60.0)
    assert parse_rate_limit("1 req/sec") == (1.0, 1.0)
    assert parse_rate_limit("5 req/3min") == (5.0, 180.0)
    assert parse_rate_limit("20") == (20.0, 60.0)  # 纯数字容错：默认每分钟


def test_parse_rate_limit_off_and_invalid():
    assert parse_rate_limit(None) is None
    assert parse_rate_limit("") is None
    assert parse_rate_limit("off") is None
    assert parse_rate_limit("none") is None
    assert parse_rate_limit("0") is None
    assert parse_rate_limit("garbage") is None
    assert parse_rate_limit("999 req/lemon") is None


def test_rate_limiter_within_limit_no_block():
    sleeps = []
    clk = [0.0]
    lim = RateLimiter(30, 60, _time=lambda: clk[0], _sleep=lambda s: sleeps.append(s))
    # 前 30 次立即可取，不应 sleep
    for _ in range(30):
        assert lim.acquire() is True
    assert sleeps == []


def test_rate_limiter_blocks_when_exhausted():
    sleeps = []
    clk = [0.0]
    lim = RateLimiter(1, 60, _time=lambda: clk[0], _sleep=lambda s: sleeps.append(s))
    assert lim.acquire() is True          # 第 1 个令牌
    clk[0] = 10.0                          # 推进时间，但还不到 60s
    blocked = lim.acquire(block=False)    # 非阻塞：应返回 False，不 sleep
    assert blocked is False
    assert sleeps == []
    # 阻塞模式：应睡眠到下一个令牌可用（还需 50s）
    lim.acquire(block=True)
    assert sleeps == [50.0]


def test_make_portal_limiter_from_config():
    portals = {"portals": {"boss": {"rate_limit": "30 req/min"}}}
    lim = make_portal_limiter("boss", portals=portals)
    assert isinstance(lim, RateLimiter)
    assert lim.max == 30.0 and lim.period == 60.0
    # 无 rate_limit → None
    assert make_portal_limiter("boss", portals={"portals": {"boss": {}}}) is None
    # off → None
    assert make_portal_limiter("boss", portals={"portals": {"boss": {"rate_limit": "off"}}}) is None


def test_acquire_portal_throttle_wires_limiter(monkeypatch):
    calls = []
    class FakeLimiter:
        def __init__(self, *a, **k):
            calls.append(("build", a, k))
        def acquire(self, block=True):
            calls.append(("acquire", block))
            return True
    monkeypatch.setattr("job_common.RateLimiter", FakeLimiter)
    reset_portal_throttles()
    acquire_portal_throttle("boss")
    acquire_portal_throttle("boss")
    # 两次请求都应消耗令牌，且 limiter 只构建一次（缓存）
    assert calls[0][0] == "build"
    acquires = [c for c in calls if c[0] == "acquire"]
    assert len(acquires) == 2
    builds = [c for c in calls if c[0] == "build"]
    assert len(builds) == 1
    # 构造参数来自 boss 的 "30 req/min"
    assert builds[0][1][0] == 30.0 and builds[0][1][1] == 60.0


def test_acquire_portal_throttle_off_is_noop(monkeypatch):
    builds = []
    class FakeLimiter:
        def __init__(self, *a, **k):
            builds.append(1)
        def acquire(self, block=True):
            builds.append(1)
            return True
    monkeypatch.setattr("job_common.RateLimiter", FakeLimiter)
    reset_portal_throttles()
    # 注入一个关掉节流的配置
    fake_portals = {"portals": {"boss": {"rate_limit": "off"}}}
    acquire_portal_throttle("boss", portals=fake_portals)
    assert builds == []  # 不应构建/调用 limiter


def test_real_portals_yaml_all_have_rate_limit():
    import yaml
    p = Path(__file__).resolve().parent.parent / "config" / "portals.yaml"
    assert p.exists(), "config/portals.yaml 缺失"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    portals = data.get("portals") or {}
    assert portals, "portals.yaml 无 portals"
    for name, cfg in portals.items():
        spec = (cfg or {}).get("rate_limit")
        parsed = parse_rate_limit(spec)
        assert parsed is not None, f"门户 {name} 缺少可解析的 rate_limit（当前：{spec!r}）"
