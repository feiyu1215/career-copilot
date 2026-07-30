# Career Copilot — CLI 入口（AGENTS / 通用 agent）

本仓库的完整能力定义与全部指令位于 **`SKILL.md`**（单一事实源）。请直接读取 `SKILL.md` 获得身份设定、红线、思考框架、各模块用法与 `--help`。

- 所有脚本均为 **CLI 无关的纯 Python**，位于 `scripts/`，由 `SKILL.md` 各模块章节描述调用方式。
- 本文件是给 AGENTS 类 host CLI 的**薄入口**：**不在此重复指令**（no-op 守卫，避免上下文重复加载）。

跨 CLI 入口同套：`CODEX.md` / `GEMINI.md` / `OPENCODE.md` / `.agents/skills/career-copilot/SKILL.md`，均指向同一 `SKILL.md`。
