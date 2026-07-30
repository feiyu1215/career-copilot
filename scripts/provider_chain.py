"""Provider 自动降级链。当主 Provider 连续失败时自动切换到备用。"""
import time
import sys
from dataclasses import dataclass, field


@dataclass
class ProviderState:
    name: str
    consecutive_failures: int = 0
    cooldown_until: float = 0.0  # unix timestamp

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def record_failure(self):
        self.consecutive_failures += 1

    def record_success(self):
        self.consecutive_failures = 0

    def enter_cooldown(self, seconds: float = 300):
        self.cooldown_until = time.time() + seconds
        print(f"  [降级] Provider {self.name} 进入 {seconds}s 冷却期", file=sys.stderr)


class ProviderChain:
    """按优先级管理多个 Provider，自动降级。

    用法：
        chain = ProviderChain(["friday", "agnes", "sub2api"])
        client = await chain.get_client()  # 返回第一个可用的 LLMClient
    """

    def __init__(self, provider_names: list[str],
                 max_consecutive_failures: int = 3,
                 cooldown_seconds: float = 300):
        self.states = {name: ProviderState(name) for name in provider_names}
        self.order = provider_names  # 优先级顺序
        self.max_failures = max_consecutive_failures
        self.cooldown = cooldown_seconds

    def get_available(self) -> list[str]:
        """返回当前可用的 provider 列表（按优先级）"""
        return [name for name in self.order
                if not self.states[name].is_in_cooldown()]

    def record_failure(self, provider_name: str):
        state = self.states[provider_name]
        state.record_failure()
        if state.consecutive_failures >= self.max_failures:
            state.enter_cooldown(self.cooldown)

    def record_success(self, provider_name: str):
        self.states[provider_name].record_success()
