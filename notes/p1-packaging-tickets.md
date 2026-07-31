<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P1 文档层 · Tickets（垂直切片）

> 父 PRD：`notes/p1-packaging-prd.md`。每个 ticket 独立可测、独立 ship。

## Ticket P1-1：SKILL.md 加 30 秒速览（TL;DR）
- **垂直切片**：在「权衡声明」与「红线」之间插入「## 30 秒速览（TL;DR）」段。
- **内容**：一句话定位（匹配→面试→简历→记忆闭环）+ 「单岗匹配 3 步走」+ 快路径提示。
- **Acceptance**：`tests/test_skill_doc_contracts.py::test_skill_has_tldr` 通过（SKILL.md 含 `30 秒速览` + `单岗匹配` + `3 步走`）。
- **Blocking edges**：无。独立可 ship。
- **Out of scope**：不引命令、不改红线、不重复既有内容。

## Ticket P1-3：决策路由正式命名「lite 模式」
- **垂直切片**：改「决策路由」表 L117-118 的「纯推理」→「纯推理（lite 模式）」，路由段后补一行定义。
- **内容**：定义 lite 模式 = 不跑脚本、prompt 级 lens 自检覆盖、适用单 JD/JD≤5/快速评估。
- **Acceptance**：`tests/test_skill_doc_contracts.py::test_lite_mode_named_in_routing` 通过（SKILL.md 含 `纯推理（lite 模式）`）。
- **Blocking edges**：无。独立可 ship。
- **Out of scope**：不改写其余「纯推理」措辞（L154/L219/L223 已含 lite 语义，保持避免噪声）。

## 执行顺序
P1-1 → P1-3（均独立，顺序无关，依 PRD 列出顺序）。每票走 TDD：先红测试 → 改 SKILL.md → 绿 → 双轴 review → ship。
