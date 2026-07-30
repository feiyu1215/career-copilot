#!/usr/bin/env python3
"""
llm_client.py — 共享 LLM 客户端（多 Provider 支持）

支持的 Provider：
  - friday:   Friday 平台（内部 OpenAI 兼容接口）
  - sub2api:  Sub2API 第三方代理（OpenAI 兼容接口，支持 GPT-5.4 等模型）
  - nvidia:   NVIDIA NvAPI（OpenAI 兼容，托管 DeepSeek 等开源模型）
  - agnes:    Agnes AI（OpenAI 兼容，外部可达，agnes-2.0-flash）

Provider 选择优先级：
  1. 代码中显式指定 provider 参数
  2. 环境变量 LLM_PROVIDER（可选值：friday / sub2api / nvidia / agnes）
  3. 默认使用 friday

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

from cache import default_cache, SemanticCache  # T13：语义缓存
from openai import AsyncOpenAI  # 模块级导入，便于测试时 monkeypatch

import yaml


# ============================================================
# 统一失败语义（T2：替代返回空字符串/None 的静默失败）
# ============================================================

class LLMCallFailed(Exception):
    """所有重试耗尽后抛出。替代返回空字符串/None 的静默失败。"""
    def __init__(self, provider: str, model: str, attempts: int, last_error: Exception):
        self.provider = provider
        self.model = model
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"[{provider}/{model}] {attempts} 次重试均失败，最后错误: "
            f"{type(last_error).__name__}: {last_error}"
        )


# ============================================================
# Provider 配置
# ============================================================

# Provider A（内部平台，通过环境变量配置）
FRIDAY_BASE_URL = os.environ.get("LLM_BASE_URL", "")
FRIDAY_APP_ID = os.environ.get("FRIDAY_APP_ID", "")

# Provider B（外部 API 代理，通过环境变量配置）
SUB2API_BASE_URL = os.environ.get("SUB2API_BASE_URL", "")
SUB2API_API_KEY = os.environ.get("SUB2API_API_KEY", "")

# Provider C（NVIDIA NvAPI，OpenAI 兼容接口，可托管 DeepSeek 等模型）
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")

# Provider D（Agnes AI，OpenAI 兼容接口，外部可达，沙箱可用）
AGNES_BASE_URL = os.environ.get("AGNES_BASE_URL", "")
AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "")

# 默认 Provider
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "friday")

# Provider 配置注册表
# 内置 4 个 provider 由环境变量驱动；扩展 provider（含本地 ollama）走 config/providers.yaml，
# 通过 build_providers 合并，新增后端无需改代码。
DEFAULT_PROVIDERS = {
    "friday": {
        "base_url": FRIDAY_BASE_URL,
        "api_key": FRIDAY_APP_ID,
        "default_model": "gpt-4o-mini",
        "description": "Friday 平台（内部 OpenAI 兼容接口）",
    },
    "sub2api": {
        "base_url": SUB2API_BASE_URL,
        "api_key": SUB2API_API_KEY,
        "default_model": "gpt-5.4",
        "description": "Sub2API 代理（GPT-5.4/5.4-mini/5.3-codex）",
        "available_models": [
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
        ],
    },
    "nvidia": {
        "base_url": NVIDIA_BASE_URL,
        "api_key": NVIDIA_API_KEY,
        "default_model": "deepseek-ai/deepseek-v4-flash",
        "description": "NVIDIA NvAPI（OpenAI 兼容，托管 DeepSeek 等开源模型）",
        "available_models": [
            "deepseek-ai/deepseek-v4-flash",
            "deepseek-ai/deepseek-v4-pro",
            "deepseek-ai/deepseek-coder-6.7b-instruct",
        ],
        "note": "v4-pro 在 NVIDIA 侧偶发冷启动/排队导致超时，默认用更稳定快速的 v4-flash；需要更强推理时显式 model='deepseek-ai/deepseek-v4-pro' 并放宽超时。",
    },
    "agnes": {
        "base_url": AGNES_BASE_URL,
        "api_key": AGNES_API_KEY,
        "default_model": "agnes-2.0-flash",
        "description": "Agnes AI（OpenAI 兼容，外部可达，agnes-2.0-flash）",
    },
}


def build_providers(defaults: dict, yaml_providers: dict | None = None) -> dict:
    """合并默认 provider 与 YAML 扩展（YAML 可新增 / 覆盖 provider，无需改代码）。"""
    merged = {k: dict(v) for k, v in defaults.items()}
    for name, cfg in (yaml_providers or {}).items():
        base = dict(merged.get(name, {}))
        base.update(cfg or {})
        merged[name] = base
    return merged


def load_providers(path=None) -> dict:
    """从 config/providers.yaml（可选）加载扩展 provider，叠加在内置默认之上。"""
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "providers.yaml",
        )
    yaml_providers: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            yaml_providers = (data.get("providers") if isinstance(data, dict) else {}) or {}
        except Exception:
            yaml_providers = {}
    return build_providers(DEFAULT_PROVIDERS, yaml_providers)


# 运行时注册表：内置 4 个 + YAML 扩展（含本地 ollama 等）
PROVIDERS = load_providers()


def get_provider_config(provider: str | None = None) -> dict:
    """获取指定 provider 的配置，未指定则使用默认。"""
    provider = provider or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise ValueError(
            f"未知 provider: {provider}。支持的 provider: {list(PROVIDERS.keys())}"
        )
    return PROVIDERS[provider]


def _resolve_api_key(config: dict, explicit: str | None = None) -> str | None:
    """解析可用的 api_key。

    OpenAI SDK 拒绝空串/None，因此 local/隐私 provider（如 ollama，本就不需真实 key）
    缺 key 时返回占位符 'sk-noauth' 使其能正常构造；非本地 provider 缺 key 时返回 None，
    让构造阶段抛出清晰的配置缺失错误，而非在调用时才暴露。
    """
    ak = explicit if explicit is not None else config.get("api_key")
    if not ak:
        ak = "sk-noauth" if config.get("local") else None
    return ak


# ============================================================
# Provider 降级链（T2 补全：主 Provider 不可用时自动切换）
# ============================================================

import time as _time

# 降级顺序：从主力到兜底。可通过环境变量 LLM_FAILOVER_CHAIN 覆盖（逗号分隔）。
FAILOVER_CHAIN: list[str] = os.environ.get(
    "LLM_FAILOVER_CHAIN", "friday,sub2api,nvidia,agnes"
).split(",")

# Provider 冷却时间（秒）：失败后这段时间内跳过该 Provider
PROVIDER_COOLDOWN_SECONDS = int(os.environ.get("LLM_PROVIDER_COOLDOWN", "60"))

# 模块级冷却追踪器：{provider_name: 冷却到期时间戳}
_provider_cooldowns: dict[str, float] = {}


def _is_provider_cooled(provider: str) -> bool:
    """检查 provider 是否在冷却期内。"""
    deadline = _provider_cooldowns.get(provider)
    if deadline is None:
        return False
    if _time.time() >= deadline:
        del _provider_cooldowns[provider]
        return False
    return True


def _cool_provider(provider: str) -> None:
    """将 provider 放入冷却期。"""
    _provider_cooldowns[provider] = _time.time() + PROVIDER_COOLDOWN_SECONDS


def _get_failover_candidates(primary: str) -> list[str]:
    """获取降级候选列表（从 primary 之后开始，跳过冷却中的）。"""
    candidates = []
    # 从 chain 中 primary 之后开始
    try:
        start_idx = FAILOVER_CHAIN.index(primary) + 1
    except ValueError:
        start_idx = 0
    for p in FAILOVER_CHAIN[start_idx:]:
        p = p.strip()
        if p in PROVIDERS and p != primary and not _is_provider_cooled(p):
            # 本地 provider（local: true）无需 api_key；远程 provider 需非空 key
            cfg = PROVIDERS[p]
            if cfg.get("local", False) or cfg.get("api_key"):
                candidates.append(p)
    return candidates


# ============================================================
# LLM 客户端
# ============================================================

class LLMClient:
    """轻量级异步 LLM 客户端，带并发控制、重试和语义缓存。

    支持多 Provider 切换。

    Usage:
        # 使用默认 provider（由环境变量或 friday 决定）
        client = LLMClient(model="gpt-4o-mini", max_concurrent=5)

        # 显式指定 sub2api provider
        client = LLMClient(model="gpt-5.4", provider="sub2api", max_concurrent=5)

        # 关闭语义缓存（等价于 CLI --no-cache）
        client = LLMClient(model="gpt-4o-mini", use_cache=False)

        text = await client.chat(system="...", user="...", max_tokens=500)
    """

    def __init__(self, model: str | None = None, max_concurrent: int = 5,
                 provider: str | None = None, timeout: int = 120,
                 api_key: str | None = None, base_url: str | None = None,
                 use_cache: bool = True, cache=None):
        config = get_provider_config(provider)
        self.provider_name = provider or DEFAULT_PROVIDER
        self.model = model or config["default_model"]
        self.timeout = timeout

        # T13：语义缓存开关。环境变量 LLM_NO_CACHE 可全局禁用（等价 --no-cache）。
        self.use_cache = use_cache and os.environ.get("LLM_NO_CACHE") is None
        self.cache = cache if cache is not None else default_cache()
        self.cache_hits = 0

        # api_key/base_url 可被调用方显式覆盖：llm_client 在 import 时快照环境变量，
        # 若调用方在 import 之后才注入 env（如运行时读 .env），快照会为空。
        # 显式传参可彻底规避「import 顺序导致 key 丢失」这一脆弱点。
        ak = _resolve_api_key(config, api_key)
        if ak is None:
            # 非本地 provider 缺 key：在构造阶段即抛出清晰、可操作的错误，
            # 而不是把 OpenAI SDK 的原生 'Missing credentials' 异常甩给用户。
            raise ValueError(
                f"Provider '{self.provider_name}' 缺少 API 密钥：config 中 api_key 为空且未传入显式 key。"
                f"请在 .env 设置 {self.provider_name.upper()}_API_KEY，"
                f"或将 LLM_PROVIDER 指向已配置的 provider（如 agnes）。"
            )
        bu = base_url if base_url is not None else config["base_url"]
        self.client = AsyncOpenAI(
            api_key=ak,
            base_url=bu,
            timeout=timeout,
        )
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # 降级显式标注所需：记录实际服务的 provider（默认即请求的主 provider，
        # 一旦走 failover 命中其它 provider 则更新，避免「静默 fallback」）。
        self.requested_provider = self.provider_name
        self.last_served_by = self.provider_name
        self.last_served_model = self.model
        self.last_served_via_failover = False
        self.last_served_is_local = False

    async def chat(self, system: str, user: str, temperature: float = 0.0,
                   max_tokens: int = 500, retries: int = 5,
                   annotate_fallback: bool = False) -> str:
        """单次调用，返回内容文本。带智能重试 + Provider 降级 + 语义缓存。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        # T13：命中缓存直接返回（不消耗 token、不触发重试；延迟 < 10ms）
        if self.use_cache:
            cached = self.cache.get(self.model, messages)
            if cached is not None:
                self.cache_hits += 1
                self.total_calls += 1
                return cached

        last_error = None
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
                value = resp.choices[0].message.content or ""
                if self.use_cache:
                    self.cache.put(self.model, messages, value)
                return value
            except Exception as e:
                last_error = e
                wait = self._compute_retry_wait(e, attempt, retries)
                if wait is None:
                    break  # 不可重试错误，跳出进入降级
                print(f"  [重试 {attempt+1}] [{self.provider_name}] {type(e).__name__}: {e}, 等待{wait}s",
                      file=sys.stderr)
                await asyncio.sleep(wait)

        # 主 Provider 重试耗尽：冷却并尝试降级链
        _cool_provider(self.provider_name)
        failover_result = await self._failover_chat(messages, temperature, max_tokens)
        if failover_result is not None:
            # 显式标注降级来源（默认不改动文本，避免破坏 JSON；调用方主动开启才前置标注）
            if annotate_fallback:
                note = self.served_note()
                if note:
                    failover_result = note + "\n" + failover_result
            return failover_result

        # 所有 Provider 均失败
        raise LLMCallFailed(
            provider=self.provider_name,
            model=self.model,
            attempts=retries,
            last_error=last_error or RuntimeError("unknown error"),
        )

    async def _failover_chat(self, messages: list[dict], temperature: float,
                             max_tokens: int, fallback_retries: int = 2) -> str | None:
        """尝试降级链中的后续 Provider。成功返回文本，全部失败返回 None。"""
        candidates = _get_failover_candidates(self.provider_name)
        for provider_name in candidates:
            config = PROVIDERS[provider_name]
            fallback_model = config["default_model"]
            print(f"  [降级] {self.provider_name} → {provider_name}/{fallback_model}",
                  file=sys.stderr)
            fallback_client = AsyncOpenAI(
                api_key=_resolve_api_key(config),
                base_url=config["base_url"],
                timeout=self.timeout,
            )
            for attempt in range(fallback_retries):
                try:
                    async with self.semaphore:
                        resp = await fallback_client.chat.completions.create(
                            model=fallback_model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                    self.total_calls += 1
                    if resp.usage:
                        self.total_input_tokens += resp.usage.prompt_tokens
                        self.total_output_tokens += resp.usage.completion_tokens
                    value = resp.choices[0].message.content or ""
                    if self.use_cache:
                        self.cache.put(self.model, messages, value)
                    print(f"  [降级成功] {provider_name}/{fallback_model} 响应正常",
                          file=sys.stderr)
                    self._mark_served(provider_name, fallback_model, config)
                    return value
                except Exception as e:
                    wait = self._compute_retry_wait(e, attempt, fallback_retries)
                    if wait is None:
                        break
                    print(f"  [降级重试 {attempt+1}] [{provider_name}] {type(e).__name__}: {e}",
                          file=sys.stderr)
                    await asyncio.sleep(wait)
            # 该候选也失败，冷却后继续下一个
            _cool_provider(provider_name)
        return None

    async def chat_raw(self, messages: list[dict], temperature: float = 0.0,
                       max_tokens: int = 500, retries: int = 5):
        """原始调用，接受完整 messages 列表，返回 response 对象。

        用于需要访问 response 元数据或自定义消息格式的场景。
        带 Provider 降级：主 Provider 失败后自动尝试降级链。
        """
        last_error = None
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
                last_error = e
                wait = self._compute_retry_wait(e, attempt, retries)
                if wait is None:
                    break  # 不可重试错误，跳出进入降级
                print(f"  [重试 {attempt+1}] [{self.provider_name}] {type(e).__name__}: {e}, 等待{wait}s",
                      file=sys.stderr)
                await asyncio.sleep(wait)

        # 主 Provider 重试耗尽：冷却并尝试降级链
        _cool_provider(self.provider_name)
        failover_resp = await self._failover_chat_raw(messages, temperature, max_tokens)
        if failover_resp is not None:
            return failover_resp

        # 所有 Provider 均失败
        raise LLMCallFailed(
            provider=self.provider_name,
            model=self.model,
            attempts=retries,
            last_error=last_error or RuntimeError("unknown error"),
        )

    async def _failover_chat_raw(self, messages: list[dict], temperature: float,
                                  max_tokens: int, fallback_retries: int = 2):
        """尝试降级链中的后续 Provider（返回 response 对象）。全部失败返回 None。"""
        candidates = _get_failover_candidates(self.provider_name)
        for provider_name in candidates:
            config = PROVIDERS[provider_name]
            fallback_model = config["default_model"]
            print(f"  [降级] {self.provider_name} → {provider_name}/{fallback_model}",
                  file=sys.stderr)
            fallback_client = AsyncOpenAI(
                api_key=_resolve_api_key(config),
                base_url=config["base_url"],
                timeout=self.timeout,
            )
            for attempt in range(fallback_retries):
                try:
                    async with self.semaphore:
                        resp = await fallback_client.chat.completions.create(
                            model=fallback_model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                    self.total_calls += 1
                    if resp.usage:
                        self.total_input_tokens += resp.usage.prompt_tokens
                        self.total_output_tokens += resp.usage.completion_tokens
                    print(f"  [降级成功] {provider_name}/{fallback_model} 响应正常",
                          file=sys.stderr)
                    self._mark_served(provider_name, fallback_model, config)
                    resp._served_by = provider_name
                    resp._served_via_failover = True
                    resp._served_is_local = bool(config.get("local"))
                    return resp
                except Exception as e:
                    wait = self._compute_retry_wait(e, attempt, fallback_retries)
                    if wait is None:
                        break
                    print(f"  [降级重试 {attempt+1}] [{provider_name}] {type(e).__name__}: {e}",
                          file=sys.stderr)
                    await asyncio.sleep(wait)
            _cool_provider(provider_name)
        return None

    def _compute_retry_wait(self, error: Exception, attempt: int, max_retries: int) -> float | None:
        """根据错误类型计算等待时间（含 jitter）。返回 None 表示不重试直接抛出。"""
        import random
        try:
            import openai
        except ImportError:
            # 没有 openai 包的详细异常类型，走通用逻辑
            if attempt == max_retries - 1:
                return None
            # 其他错误：指数退避 + jitter（±50%）
            return 2 ** (attempt + 1) * random.uniform(0.5, 1.5)

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
            base = 2
        # Rate Limit：尊重 retry-after header 或较长退避
        elif isinstance(error, openai.RateLimitError):
            retry_after = None
            if hasattr(error, 'response') and error.response is not None:
                retry_after = error.response.headers.get("retry-after")
            if retry_after:
                base = max(int(retry_after), 2 ** (attempt + 1))
            else:
                base = max(30, 2 ** (attempt + 1))
        # 其他错误：指数退避
        else:
            base = 2 ** (attempt + 1)
        # 加 jitter：±50% 随机化，防止并发重试 thundering herd
        return base * random.uniform(0.5, 1.5)

    def _mark_served(self, provider_name: str, model: str, config: dict) -> None:
        """记录实际服务的 provider（用于降级显式标注，避免静默 fallback）。"""
        self.last_served_by = provider_name
        self.last_served_model = model
        self.last_served_via_failover = True
        self.last_served_is_local = bool(config.get("local"))
        if config.get("local"):
            print(f"  [降级·WARNING] 原始 provider={self.requested_provider} 不可用，"
                  f"本次响应来自【本地隐私模型】{provider_name}/{model}，"
                  f"非远程模型结果，仅供参考", file=sys.stderr)

    def served_note(self) -> str:
        """若本次响应来自降级（尤其本地隐私模型），返回需显式标注的提示；否则返回空串。"""
        if not self.last_served_via_failover:
            return ""
        if self.last_served_is_local:
            return (f"[降级·本地隐私模型] 原始 provider={self.requested_provider} 不可用，"
                    f"本次响应来自本地 {self.last_served_by}/{self.last_served_model}，"
                    f"非远程模型结果，仅供参考")
        return (f"[降级] 原始 provider={self.requested_provider} 不可用，"
                f"本次响应来自 {self.last_served_by}/{self.last_served_model}")

    def stats(self) -> dict:
        """返回调用统计"""
        return {
            "provider": self.provider_name,
            "model": self.model,
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "served_by": self.last_served_by,
            "served_via_failover": self.last_served_via_failover,
            "served_is_local": self.last_served_is_local,
        }
