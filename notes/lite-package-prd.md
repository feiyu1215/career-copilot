<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# Lite 包 PRD（minor · 运行时无关可粘贴段）

> 依据 `notes/archive/skilllens_upgrade_plan.archived.md` 的 minor 项（原 P1-3 运行时无关包，已降级 + 诚实标签）。
> 开发规范：scholar-dev-process（Grill→To-Spec→To-Tickets→Implement(TDD)→Review→Ship）。
> EVIDENCE_TIER：本任务纯文档产物 + 离线解析测试 = **SYNTHETIC-MECHANISM**（无 live key）。

## Problem（问题）
主 skill 强依赖 `scripts/`（fetch_jobs / smart_score / verify_*）与运行时上下文，无法在「纯 ChatGPT / 通用 LLM」里直接复用其核心求职契约。用户需要一份可手动粘贴、零依赖的「核心契约 + lens」段，用于轻量咨询（单 JD 评估、方向性建议）。

## Solution（方案）
新增 `references/chatgpt-lite.md`：从 SKILL.md 抽出 4 条核心契约（① 前提来源标注 ② 单源外部红线 ③ 改稿熔断 ④ Over-Claim 镜面）+ lens 不分回合规则 + 红线，写成给任意 LLM 的 system/prompt 段。**强制声明「无机制保证」**：本段只有 prompt 级约束，无 verify 脚本校验，弱模型可能失效，且缺失全部 scripts 能力（fetch_jobs / smart_score / 简历改写等）。

## User Stories（长列表）
- 作为 ChatGPT 用户，我想粘贴一段求职契约提示词，让模型默认给我打来源标签、不编造单源数字、不偷换论题，而不必部署整套 skill。
- 作为 skill 作者，我想分发一份诚实标注「无机制保证」的精简版，避免用户误以为它等同完整 skill（撞 Anti-pattern：与 P0 机制化自相矛盾）。

## Implementation Decisions（含 seam 草拟）
- **Seam（实现）** = 文档文件 `references/chatgpt-lite.md`。
- **Seam（测试）** = `tests/test_skill_doc_contracts.py` 离线解析该文件（复用既有 `_read_skill` 模式，新增 `_read_lite`）。
- 不修改主 `SKILL.md` / 不新增 `/命令` / 不接入运行时（Scope Drift 红线）。
- 内容硬约束：含强制「无机制保证」声明 + 4 契约关键词（前提来源标注 / 单源 / 熔断 / Over-Claim）。
- 哲学护栏：保留软路由语义（非硬命令），不钝化灵活性。

## Testing Decisions
- TDD：先写测试断言「文件存在 + 含『无机制保证』+ 含 4 契约关键词」（red→green）。
- SYNTHETIC-MECHANISM：离线文本解析，无需 live key；fresh 证据 = `pytest` 刚跑绿。

## Out of Scope（不做）
- 不把 lite 包接入主 skill 路由；不写分发流水线；不加任何 verify 机制（那会重新引入 P0 矛盾）。
- 不重述 Pipeline / 面试 / 记忆等需要 scripts 的能力。
- 不做 BOOTSTRAP 身份设定（独立待办）。
