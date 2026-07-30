import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location("llm_client_n4", ROOT / "scripts" / "llm_client.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["llm_client_n4"] = mod
spec.loader.exec_module(mod)


def test_load_providers_reads_yaml():
    prov = mod.load_providers()  # 读取真实 config/providers.yaml
    assert "ollama" in prov
    assert prov["ollama"]["local"] is True
    assert prov["ollama"]["api_key"] == ""
    for builtin in ("friday", "sub2api", "nvidia", "agnes"):
        assert builtin in prov


def test_build_providers_extends_and_overrides():
    defaults = {"friday": {"api_key": "x", "base_url": "u"}}
    yaml_p = {"ollama": {"local": True, "api_key": ""}, "friday": {"api_key": "y"}}
    merged = mod.build_providers(defaults, yaml_p)
    assert "ollama" in merged
    assert merged["ollama"]["local"] is True
    assert merged["friday"]["api_key"] == "y"   # YAML 覆盖
    assert merged["friday"]["base_url"] == "u"  # 默认值保留


def test_failover_allows_local_provider():
    fake_chain = ["friday", "ollama", "noprov"]
    fake_providers = {
        "friday": {"api_key": "k"},
        "ollama": {"local": True, "api_key": ""},
        "noprov": {"api_key": ""},
    }
    with mock.patch.object(mod, "FAILOVER_CHAIN", fake_chain), \
         mock.patch.dict(mod.PROVIDERS, fake_providers, clear=False):
        cands = mod._get_failover_candidates("friday")
    # 本地 provider（无 key）应进入候选；远程空 key provider 应被排除
    assert cands == ["ollama"]


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        mod.get_provider_config("does-not-exist")


def test_runtime_providers_has_ollama():
    # 模块级 PROVIDERS 已在 import 时加载 config/providers.yaml
    assert "ollama" in mod.PROVIDERS
    assert mod.PROVIDERS["ollama"]["local"] is True


def test_local_provider_constructs_without_real_key():
    # N4 隐私模式（ollama）无真实 key 也必须能构造 LLMClient：
    # 此前因 OpenAI SDK 拒绝空串 api_key 而崩溃（'Missing credentials'）。
    cli = mod.LLMClient(provider="ollama")
    assert cli.provider_name == "ollama"
    assert str(cli.client.base_url).rstrip("/") == "http://localhost:11434/v1"
    assert cli.client.api_key  # 占位符已注入，非空
    # 显式 key 优先于占位符
    cli2 = mod.LLMClient(provider="ollama", api_key="real-local")
    assert cli2.client.api_key == "real-local"


def test_remote_provider_without_key_raises_clear_error():
    # 非本地 provider 缺 key：应抛清晰错误，而非静默构造后调用才暴露。
    # 用 mock 注入一个无 key 的远程 provider，与环境是否预置 key 解耦。
    fake = {"api_key": "", "base_url": "https://api.example.com/v1",
            "default_model": "x", "local": False}
    with mock.patch.dict(mod.PROVIDERS, {"nofrkey": fake}, clear=False):
        with pytest.raises(Exception):
            mod.LLMClient(provider="nofrkey")
