#!/usr/bin/env python3
"""
llm_client.py — 共享 LLM 客户端（多 Provider 支持）

支持的 Provider：
  - internal: 内部 OpenAI 兼容接口
  - external: 外部 API 代理（OpenAI 兼容接口，支持 GPT-5.4 等模型）

Provider 选择优先级：
  1. 代码中显式指定 provider 参数
  2. 环境变量 LLM_PROVIDER（值为 "internal" 或 "external"）
  3. 默认使用 internal

提供：
  - 多 Provider 配置管理
  - LLMClient：带并发控制 + 指数退避重试的异步客户端

所有需要调用 LLM 的脚本统一 import 此模块，避免：
  1. 重试逻辑重复实现 / 遗漏
  2. 配置分散在多处
"""

from __future__ import annotations

import os
import sys
import asyncio

# ============================================================
# Provider 配置
# ============================================================

# Provider A（内部平台，通过环境变量配置）
INTERNAL_BASE_URL = os.environ.get("LLM_BASE_URL", "")
INTERNAL_API_KEY = os.environ.get("LLM_API_KEY", "")

# Provider B（外部 API 代理，通过环境变量配置）
EXTERNAL_BASE_URL = os.environ.get("EXTERNAL_BASE_URL", "")
EXTERNAL_API_KEY = os.environ.get("EXTERNAL_API_KEY", "")

# 默认 Provider
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "internal")

# Provider 配置注册表
PROVIDERS = {
    "internal": {
        "base_url": INTERNAL_BASE_URL,
        "api_key": INTERNAL_API_KEY,
        "default_model": "gpt-4o-mini",
        "description": "内部 OpenAI 兼容接口",
    },
    "external": {
        "base_url": EXTERNAL_BASE_URL,
        "api_key": EXTERNAL_API_KEY,
        "default_model": "gpt-5.4",
        "description": "外部 API 代理（GPT-5.4/5.4-mini/5.3-codex）",
        "available_models": [
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
        ],
    },
}


def get_provider_config(provider: str | None = None) -> dict:
    """获取指定 provider 的配置，未指定则使用默认。"""
    provider = provider or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise ValueError(
            f"未知 provider: {provider}。支持的 provider: {list(PROVIDERS.keys())}"
        )
    return PROVIDERS[provider]


# ============================================================
# LLM 客户端
# ============================================================

class LLMClient:
    """轻量级异步 LLM 客户端，带并发控制和重试。

    支持多 Provider 切换。

    Usage:
        # 使用默认 provider（由环境变量或 internal 决定）
        client = LLMClient(model="gpt-4o-mini", max_concurrent=5)

        # 显式指定 external provider
        client = LLMClient(model="gpt-5.4", provider="external", max_concurrent=5)

        text = await client.chat(system="...", user="...", max_tokens=500)
    """

    def __init__(self, model: str | None = None, max_concurrent: int = 5,
                 provider: str | None = None, timeout: int = 120):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        config = get_provider_config(provider)
        self.provider_name = provider or DEFAULT_PROVIDER
        self.model = model or config["default_model"]
        self.timeout = timeout

        self.client = AsyncOpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"],
            timeout=timeout,
        )
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def chat(self, system: str, user: str, temperature: float = 0.0,
                   max_tokens: int = 500, retries: int = 5) -> str:
        """单次调用，返回内容文本。带智能重试（区分错误类型）。"""
        for attempt in range(retries):
            try:
                async with self.semaphore:
                    resp = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                self.total_calls += 1
                if resp.usage:
                    self.total_input_tokens += resp.usage.prompt_tokens
                    self.total_output_tokens += resp.usage.completion_tokens
                return resp.choices[0].message.content or ""
            except Exception as e:
                wait = self._compute_retry_wait(e, attempt, retries)
                if wait is None:
                    raise
                print(f"  [重试 {attempt+1}] [{self.provider_name}] {type(e).__name__}: {e}, 等待{wait}s",
                      file=sys.stderr)
                await asyncio.sleep(wait)
        return ""

    async def chat_raw(self, messages: list[dict], temperature: float = 0.0,
                       max_tokens: int = 500, retries: int = 5):
        """原始调用，接受完整 messages 列表，返回 response 对象。

        用于需要访问 response 元数据或自定义消息格式的场景。
        """
        for attempt in range(retries):
            try:
                async with self.semaphore:
                    resp = await self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                self.total_calls += 1
                if resp.usage:
                    self.total_input_tokens += resp.usage.prompt_tokens
                    self.total_output_tokens += resp.usage.completion_tokens
                return resp
            except Exception as e:
                wait = self._compute_retry_wait(e, attempt, retries)
                if wait is None:
                    raise
                print(f"  [重试 {attempt+1}] [{self.provider_name}] {type(e).__name__}: {e}, 等待{wait}s",
                      file=sys.stderr)
                await asyncio.sleep(wait)
        return None

    def _compute_retry_wait(self, error: Exception, attempt: int, max_retries: int) -> float | None:
        """根据错误类型计算等待时间。返回 None 表示不重试直接抛出。"""
        try:
            import openai
        except ImportError:
            # 没有 openai 包的详细异常类型，走通用逻辑
            if attempt == max_retries - 1:
                return None
            return 2 ** (attempt + 1)

        # 认证错误：不重试
        if isinstance(error, openai.AuthenticationError):
            return None
        # 模型不存在等请求错误：不重试
        if isinstance(error, openai.NotFoundError):
            return None
        # 最后一次尝试：不重试
        if attempt == max_retries - 1:
            return None
        # 超时：快速重试（2s）
        if isinstance(error, (openai.APITimeoutError, asyncio.TimeoutError)):
            return 2
        # Rate Limit：尊重 retry-after header 或较长退避
        if isinstance(error, openai.RateLimitError):
            retry_after = None
            if hasattr(error, 'response') and error.response is not None:
                retry_after = error.response.headers.get("retry-after")
            if retry_after:
                return max(int(retry_after), 2 ** (attempt + 1))
            return max(30, 2 ** (attempt + 1))
        # 其他错误：指数退避
        return 2 ** (attempt + 1)

    def stats(self) -> dict:
        """返回调用统计"""
        return {
            "provider": self.provider_name,
            "model": self.model,
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }
