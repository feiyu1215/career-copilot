# ADR-002: llm_client.py 多 Provider 架构与 Failover 机制

- 状态：已采纳
- 日期：2026-07-23
- 决策者：闫飞宇

## 背景

项目依赖 LLM API 完成评分 pipeline 的全部推理工作。单一 Provider 存在可用性风险（限流、宕机、API key 过期），且不同 Provider 的模型能力和成本差异显著。需要在保证可用性的同时，让调用方（smart_score.py 等）不感知底层 Provider 切换。

## 决策

### 多 Provider 注册表

`PROVIDERS` 字典注册所有可用 Provider（friday / sub2api / nvidia / agnes），每个包含 `base_url`、`api_key`（从环境变量读取）、`default_model`、`available_models`。调用方通过 `--provider` 参数或 `LLM_PROVIDER` 环境变量选择，默认 friday。

### 重试策略（按错误类型分级）

| 错误类型 | 策略 | 理由 |
|----------|------|------|
| AuthenticationError / NotFoundError | 不重试，立即抛出 | 配置错误，重试无意义 |
| APITimeoutError | 快速重试（2s 间隔） | 瞬态网络问题 |
| RateLimitError | 尊重 `retry-after` 头 | 限流需要等待 |
| 其他 | 指数退避（最多 5 次） | 通用容错 |

### Failover 机制

主 Provider 重试耗尽后，不直接抛异常，而是：

1. **冷却主 Provider**：记录失败时间，`PROVIDER_COOLDOWN_SECONDS`（默认 60s）内不再尝试
2. **沿 Failover 链路尝试**：`FAILOVER_CHAIN`（默认 `friday,sub2api,nvidia,agnes`，可通过 `LLM_FAILOVER_CHAIN` 环境变量覆盖），依次尝试下一个未冷却的 Provider
3. **每个候选 Provider 独立重试**：2 次重试，失败则冷却并继续下一个
4. **全部失败才抛 `LLMCallFailed`**

`chat()` 和 `chat_raw()` 均支持 failover（`_failover_chat` / `_failover_chat_raw`）。

### 设计取舍

**为什么用冷却而非永久标记不可用？** Provider 故障通常是瞬态的（限流、短暂宕机），60s 冷却后自动恢复，不需要人工干预。

**为什么 Failover 链路用环境变量而非配置文件？** 链路是部署级配置（不同环境可用 Provider 不同），环境变量更适合容器化部署。

**为什么不在 LLMClient 初始化时就检测 Provider 可用性？** 初始化时检测会增加启动延迟，且 Provider 状态随时可能变化。按需检测（调用失败时触发 failover）更实际。

## 后果

- 正面：单 Provider 故障不影响 pipeline 执行，自动切换
- 正面：调用方（smart_score.py 等）完全无感知，不需要处理 Provider 切换逻辑
- 正面：冷却机制避免在不可用 Provider 上浪费重试
- 负面：Failover 时创建临时 AsyncOpenAI 客户端，有少量额外开销
- 负面：如果所有 Provider 都不可用，failover 会延长总等待时间（每个 Provider 2 次重试 × 4 个 Provider）
- 约束：所有 Provider 必须兼容 OpenAI API 格式（`openai.AsyncOpenAI` 客户端）
