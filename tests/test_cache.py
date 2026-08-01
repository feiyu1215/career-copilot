"""T13 验收测试：语义缓存（cache.py + llm_client.chat 集成）"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import llm_client
from cache import SemanticCache, cache_key

# ──────────────────────────────────────────────
# 1) SemanticCache 纯逻辑
# ──────────────────────────────────────────────

def test_key_deterministic_and_content_sensitive(tmp_path):
    m = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    k1 = cache_key("gpt-4o-mini", m)
    k2 = cache_key("gpt-4o-mini", m)
    assert k1 == k2  # 相同输入稳定
    k3 = cache_key("gpt-4o-mini", [{"role": "user", "content": "u2"}])
    assert k3 != k1  # 不同输入不同键
    # 消息顺序对 LLM 有语义影响 → 列表顺序必须影响键（不强求顺序无关）
    m_swapped = [{"role": "user", "content": "u"}, {"role": "system", "content": "s"}]
    assert cache_key("gpt-4o-mini", m_swapped) != k1


def test_put_get_and_miss(tmp_path):
    c = SemanticCache(cache_dir=tmp_path / "llm", ttl_days=7)
    msgs = [{"role": "user", "content": "hello"}]
    assert c.get("m", msgs) is None  # miss
    c.put("m", msgs, "world")
    assert c.get("m", msgs) == "world"  # hit


def test_ttl_expiry(tmp_path):
    c = SemanticCache(cache_dir=tmp_path / "llm", ttl_days=7)
    msgs = [{"role": "user", "content": "x"}]
    c.put("m", msgs, "v")
    assert c.get("m", msgs) == "v"
    # 把 TTL 改到极短再查 → 过期
    c.ttl_seconds = -1
    assert c.get("m", msgs) is None


def test_stats_count(tmp_path):
    c = SemanticCache(cache_dir=tmp_path / "llm")
    msgs = [{"role": "user", "content": "x"}]
    c.put("m", msgs, "v")
    c.get("m", msgs)           # hit
    c.get("m-other", msgs)     # miss（不同键）
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1


# ──────────────────────────────────────────────
# 2) LLMClient.chat 集成缓存（fake OpenAI，不联网）
# ──────────────────────────────────────────────

class _FakeResp:
    def __init__(self):
        self.choices = [type("C", (), {"message": type("M", (), {"content": "LLM-result"})()})()]
        self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()


class _FakeClient:
    calls = 0  # 类级计数，测试间由 fixture 重置

    def __init__(self, *a, **k):
        pass

    class chat:
        class completions:
            @staticmethod
            async def create(**kwargs):
                _FakeClient.calls += 1
                return _FakeResp()


def _make_client(tmp_path, use_cache=True):
    llm_client.AsyncOpenAI = _FakeClient
    cache = SemanticCache(cache_dir=tmp_path / "llm")
    # 测试只验证缓存逻辑，网络已被 _FakeClient mock；显式给 dummy key，
    # 避免依赖「构造期不校验 key」的旧脆弱假设（真实缺 key 应在构造期清晰报错）。
    return llm_client.LLMClient(model="gpt-4o-mini", api_key="sk-test-dummy",
                                use_cache=use_cache, cache=cache)


def test_chat_cache_hit_skips_network(tmp_path):
    _FakeClient.calls = 0
    client = _make_client(tmp_path, use_cache=True)
    out1 = asyncio.run(client.chat(system="S", user="U"))
    out2 = asyncio.run(client.chat(system="S", user="U"))
    assert out1 == out2 == "LLM-result"
    assert _FakeClient.calls == 1, "第二次应命中缓存，不调用底层 API"
    assert client.cache_hits == 1


def test_chat_cache_hit_latency_under_10ms(tmp_path):
    _FakeClient.calls = 0
    client = _make_client(tmp_path, use_cache=True)
    asyncio.run(client.chat(system="S", user="U"))  # 预热（写缓存）
    t0 = time.perf_counter()
    asyncio.run(client.chat(system="S", user="U"))  # 命中
    dt = time.perf_counter() - t0
    assert dt < 0.01, f"缓存命中延迟 {dt*1000:.2f}ms 应 < 10ms"


def test_chat_no_cache_calls_network_twice(tmp_path):
    _FakeClient.calls = 0
    client = _make_client(tmp_path, use_cache=False)
    asyncio.run(client.chat(system="S", user="U"))
    asyncio.run(client.chat(system="S", user="U"))
    assert _FakeClient.calls == 2, "禁用缓存时应每次都调用底层 API"
    assert client.cache_hits == 0
