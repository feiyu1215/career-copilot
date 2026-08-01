"""agnes provider 的接线 / 真实环境端到端断言（收口用户需求 1 & 3 的「真实环境」验证）。

三个测试：
- test_agnes_provider_wiring：确定性接线断言。monkeypatch AsyncOpenAI，
  断言 LLMClient(provider="agnes") 把请求打到 AGNES_BASE_URL、使用 AGNES_API_KEY、
  默认模型 agnes-2.0-flash。无需真实网络，CI 可常跑。
- test_agnes_e2e_real_call：真实环境端到端。真实打 agnes（需 AGNES_API_KEY 在场，
  由 scholar .env 经 eval_env.load_provider_env 注入；缺失则 pytest.skip，不阻断无凭据环境）。
- test_agnes_missing_key_raises：用**真实** agnes provider 名断言缺凭据时构造期抛清晰
  ValueError（强化 test_provider_config 的「合成 provider」覆盖，闭合需求 3）。

注意：凭据只在进程内读取，绝不打印/落盘。
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "scripts")
sys.path.insert(0, "evals")
import eval_env  # noqa: E402
import llm_client  # noqa: E402
from llm_client import PROVIDERS, LLMClient  # noqa: E402

captured: dict = {}


def _inject_agnes_env():
    """注入 scholar .env 的 AGNES 凭据，并覆盖 llm_client 模块级/PROVIDERS 快照。

    必须在 import 顺序无关的前提下，保证 agnes provider 真正使用 AGNES_* 变量。
    """
    eval_env.load_provider_env()
    base = os.environ.get("AGNES_BASE_URL", "")
    key = os.environ.get("AGNES_API_KEY", "")
    llm_client.AGNES_BASE_URL = base
    llm_client.AGNES_API_KEY = key
    PROVIDERS["agnes"]["base_url"] = base
    PROVIDERS["agnes"]["api_key"] = key
    return base, key


class _FakeChoices:
    def __init__(self, content):
        self.message = SimpleNamespace(content=content)


class _FakeUsage:
    prompt_tokens = 1
    completion_tokens = 1


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoices(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    async def create(self, *args, **kwargs):
        return _FakeResp("agnes-wired-ok")


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeAsyncOpenAI:
    def __init__(self, api_key=None, base_url=None, timeout=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["timeout"] = timeout
        self.chat = _FakeChat()


def test_agnes_provider_wiring(monkeypatch):
    """agnes 必须把请求路由到 AGNES_BASE_URL，使用 AGNES_API_KEY，默认模型 agnes-2.0-flash。"""
    base, key = _inject_agnes_env()
    if not (base and key):
        pytest.skip("无 AGNES_BASE_URL/AGNES_API_KEY，跳过接线断言")

    captured.clear()
    monkeypatch.setattr(llm_client, "AsyncOpenAI", _FakeAsyncOpenAI)

    client = LLMClient(provider="agnes", use_cache=False)
    out = asyncio.run(client.chat(system="s", user="ping"))

    assert out == "agnes-wired-ok"
    assert captured["base_url"] == base, "agnes 未把请求打到 AGNES_BASE_URL"
    assert captured["api_key"] == key, "agnes 未使用 AGNES_API_KEY"
    assert client.model == "agnes-2.0-flash", "agnes 默认模型应为 agnes-2.0-flash"


def test_agnes_e2e_real_call():
    """真实环境端到端：真实打 agnes，返回非空。无凭据则跳过。"""
    base, key = _inject_agnes_env()
    if not (base and key):
        pytest.skip("无 AGNES_BASE_URL/AGNES_API_KEY，跳过真实环境端到端")

    client = LLMClient(provider="agnes", use_cache=False)
    out = asyncio.run(client.chat(
        system="You are a helpful assistant.",
        user="Reply with exactly the single word: pong",
        max_tokens=20,
    ))
    assert isinstance(out, str) and out.strip(), "agnes 真实调用返回为空"


def test_agnes_missing_key_raises_clear_error():
    """用真实 agnes provider 名断言：缺凭据时构造期抛清晰 ValueError，不触发任何网络。"""
    _inject_agnes_env()
    saved_key = PROVIDERS["agnes"].get("api_key")
    saved_env = os.environ.pop("AGNES_API_KEY", None)
    PROVIDERS["agnes"]["api_key"] = ""
    try:
        with pytest.raises(ValueError) as exc:
            LLMClient(provider="agnes")
        assert "AGNES_API_KEY" in str(exc.value), "报错信息应指明缺失 AGNES_API_KEY"
    finally:
        PROVIDERS["agnes"]["api_key"] = saved_key
        if saved_env is not None:
            os.environ["AGNES_API_KEY"] = saved_env
