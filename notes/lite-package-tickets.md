<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# Lite 包 Tickets（垂直切片 / tracer-bullet）

> 对应 PRD：`notes/lite-package-prd.md`。两票垂直切片，各自带 acceptance criteria。
> 开发规范：scholar-dev-process → Implement(TDD 在预约定 seam) → Review(双轴+置信度门+Scope Drift) → Ship(DoD)。

## Slice 1（tracer-bullet）：chatgpt-lite.md + 契约测试
- **改动**：`references/chatgpt-lite.md`（新）+ `tests/test_skill_doc_contracts.py`（+3 测试）
- **blocking edges**：无（独立新文件，不依赖其他切片）
- **acceptance criteria**：
  - `references/chatgpt-lite.md` 存在
  - 含强制「无机制保证」声明
  - 含 4 契约关键词：`前提来源标注` / `单源` / `熔断` / `Over-Claim`
  - `pytest tests/test_skill_doc_contracts.py` 全绿（red→green）

## Slice 2：FILE_GUIDE 登记 + bus factor 表
- **改动**：`FILE_GUIDE.md`（references 段加 chatgpt-lite 条目 + bus-factor 表 references 11→12 加行）
- **blocking edges**：依赖 Slice 1（文件先存在才能登记）
- **acceptance criteria**：
  - `references/` 段含 `chatgpt-lite.md` 条目，注明「无机制保证 / 可粘贴段 / 零 scripts 依赖」
  - bus factor 表 references 计数 `11`→`12`，含新行（owner/节律/复杂度/核实）
  - 无 doc rot（与磁盘一致）
