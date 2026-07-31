<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P1 体验与分发（文档层）· PRD

> 来源：本里程碑是 `notes/archive/skilllens_upgrade_plan.archived.md` P1 段的剩余未做项（跨模型回归已完成）。立项依据同升级计划：(A) 降冷启动成本 / 提升可用性；(B) 无。哲学合规：不引 /命令、不拆 skill、不钝化灵活性。
> 开发纪律：`scholar-dev-process`（Grill→To-Spec→To-Tickets→Implement(tdd)→Review→Ship）。本 PRD 即 To-Spec 产出。

## Problem
- SKILL.md 顶部只有「权衡声明」就直接进「红线」，新用户/首次加载没有 30 秒速览，冷启动成本高。
- 「纯推理」路径在多处提及（决策路由 L117-118、Stop Conditions、绝对不要 L154、犯错想法表 L219/223），但**从未被正式命名为「lite 模式」**——读者无法把分散的「纯推理」认作同一个可复用模式，也难在文档/README 里统一指代。

## Solution
1. **P1-1（TL;DR）**：在「权衡声明」后插入「30 秒速览」段——一句话定位 + 「单岗匹配 3 步走」+ 快路径提示。不引入命令、不重复红线。
2. **P1-3（lite 模式命名）**：把决策路由里的「纯推理」正式命名为「纯推理（lite 模式）」，并在路由段补一行定义（不跑脚本、prompt 级 lens 自检覆盖、适用场景）。其余「纯推理」措辞保持（已含 lite 语义），不改写避免噪声。

## User Stories
- 作为首次使用者，打开 SKILL.md 30 秒内知道这 skill 干啥、单岗匹配怎么走。
- 作为维护者/读者，看到「lite 模式」能立刻对应到「纯推理路径」的全部既有规则。

## Implementation Decisions
- **Seam**：SKILL.md 是契约文档，可测 seam = 结构化文本约定。测试用 `tests/test_skill_doc_contracts.py` 解析 SKILL.md 断言：
  - TL;DR 段存在：含 `30 秒速览`（或 `TL;DR`）+ `单岗匹配` + `3 步走`。
  - lite 模式在决策路由正式命名：含 `纯推理（lite 模式）`。
- **不碰**：红线 / 绝对不要 / 会话生命周期 / 脚本 / .env。纯内容增改。
- **插入位置**：TL;DR 插在「权衡声明」(L8-10) 与「红线」(L12) 之间；lite 命名改「决策路由」表 (L117-118) + 路由段后补定义行。

## Testing Decisions
- TDD：先写 `tests/test_skill_doc_contracts.py`（红），再改 SKILL.md（绿），重跑（绿）。
- 不引入新依赖；用标准库 `re` 解析。

## Out of Scope
- P1-4 持续 eval 门禁（需 Makefile/CI + API，独立垂直切片，本轮不做）。
- minor 运行时无关 lite 包（分发，独立切片）。
- P2 全部（PII/安全、维护性、代理评测、自评偏见）——优先级低于 P1。
- 任何契约/行为变更（本里程碑纯文档体验层）。

## Evidence Tier
- 文档契约检查 = SYNTHETIC-MECHANISM（离线解析，sandbox 可全验，无需 live key）。
