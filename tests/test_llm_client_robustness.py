"""T2 验收测试：LLM Client 健壮性"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from llm_client import LLMCallFailed
from provider_chain import ProviderChain


class TestLLMCallFailed:
    def test_exception_message_contains_provider(self):
        err = LLMCallFailed("friday", "gpt-4o-mini", 5, TimeoutError("timeout"))
        assert "friday" in str(err)
        assert "gpt-4o-mini" in str(err)
        assert "5" in str(err)

    def test_is_exception_subclass(self):
        err = LLMCallFailed("x", "y", 1, ValueError("v"))
        assert isinstance(err, Exception)


class TestProviderChain:
    def test_initial_all_available(self):
        chain = ProviderChain(["friday", "agnes", "sub2api"])
        assert chain.get_available() == ["friday", "agnes", "sub2api"]

    def test_cooldown_after_max_failures(self):
        chain = ProviderChain(["friday", "agnes"], max_consecutive_failures=3)
        chain.record_failure("friday")
        chain.record_failure("friday")
        assert "friday" in chain.get_available()  # 2 次还没到
        chain.record_failure("friday")
        assert "friday" not in chain.get_available()  # 3 次，进入冷却
        assert "agnes" in chain.get_available()

    def test_success_resets_counter(self):
        chain = ProviderChain(["friday", "agnes"], max_consecutive_failures=3)
        chain.record_failure("friday")
        chain.record_failure("friday")
        chain.record_success("friday")
        chain.record_failure("friday")
        # 重置后只有 1 次失败，不应进入冷却
        assert "friday" in chain.get_available()
