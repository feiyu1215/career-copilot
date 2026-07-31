<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P0 PRD — 软契约机制化（verify_lens.py）

> 来源：`notes/archive/skilllens_upgrade_plan.archived.md` P0 项（已对齐 `notes/addition-criteria.md` 哲学）。
> 开发流程：scholar-dev-process（Grill→To-Spec→To-Tickets→Implement(tdd)→Review→Ship）。
> 证据层级（P7）：本脚本的确定性检查属 **SYNTHETIC-MECHANISM**（纯逻辑、无 LLM、可离线全测）；「弱模型 M4 回归」验收属 **LLM-REAL**，需 live API，沙箱外，列为 follow-up。

## Problem
①③④（前提来源标注 / 单源红线 / Over-Claim 镜面）目前仅 prompt 强制。M4 证明未硬化时 3/4 失效；核心安全机制依赖模型遵循度，弱模型或 prompt 漂移会回退。对 honesty-first 产品，这不可靠。

## Solution
新增 `scripts/verify_lens.py`，对**对白 transcript** 做确定性、**warning 模式**检查：
- `verify_output.py` 检 pipeline 的 `scored_results.json`（结构化产物）；本脚本检「对白回合」契约——二者互补，不重叠。
- 只做**标签存在性**检查（强断言/绝对保证是否带 `[事实]/[推测]/[脑补]/[来源]`），**绝不用正则判断「断言是否真的推测」**（那是判断，留给人/prompt）。
- 默认 WARNING（非阻断，保灵活性）；`--strict` 时 WARNING 升级为失败（可作 eval 门禁）。
- 显式暴露（契合「隐蔽 fallback 更危险」）。

## User Stories
- 作为评审者，我想把一段对白丢给检查器，立刻知道哪些回合违反了软契约 → WARNING 列出 turn 索引 + 命中契约。
- 作为维护者，我想在对抗用例（故意未标注强断言）上验证检查器必拦 → 单测覆盖。
- 作为门禁，我想在 `--strict` 下让违反直接失败 → 退出码 1。

## Implementation Decisions（seam 草拟）
- **公共 seam**：`run_checks(turns: list[dict]) -> (failures: list[str], warnings: list[str])`，与 `verify_output.run_checks` 同构；CLI `--input transcript.jsonl [--strict]`。
- **输入契约**：JSONL，每行 `{"role":"agent"|"user","text":"..."}`；仅检查 `role=="agent"` 回合。
- **三条检查（warning 码）**：
  - `LENS-W1` 强断言缺来源标签（命中 STRONG_MARKERS 且无 SOURCE_TAGS）。
  - `LENS-W2` 对外简历硬数字缺 `[事实]`（命中 RESUME_CTX + 数字且无 `[事实]`）。
  - `LENS-W3` 绝对化保证缺来源标签（命中 ABSOLUTE_MARKERS 且无 SOURCE_TAGS）。
- **退出码**：无 failures 且无 warnings → 0；仅 warnings → 0（或 `--strict`→1）；failures（如非法 JSONL/缺字段）→ 1。
- 风格：复刻 `verify_output.py` 的 `[L0]`/`[LENS-W*]` + 显式暴露约定。

## Testing Decisions
- `tests/test_verify_lens.py`：合法带标签→无 WARNING；W1/W2/W3 各自触发；带标签同类→不触发；user 回合不检查；非法 JSONL→`[L0]` 退出 1；`--strict`→WARNING 升级失败。
- 对抗 fixture：`tests/fixtures/lens_adversarial.jsonl`（故意未标注强断言）供手动回归 + 新鲜证据。

## Out of Scope（本票不做，列 follow-up）
- **自动采集 transcript**：让 agent 在 session 末落一份 transcript 供 verify_lens 吃（需动 session-start/end，更大改动）→ 单独票。
- **lens 回执（agent 自报）**：plan 提及的另一种数据源，本票以「离线扫 transcript」实现为主，回执留待定。
- **弱模型 M4 回归**：需 live LLM API（你本机跑），不在沙箱。

## Acceptance Criteria（DoD）
- [ ] `tests/test_verify_lens.py` 全绿（fresh evidence）。
- [ ] `verify_lens.py` 跑 `tests/fixtures/lens_adversarial.jsonl` 必出 WARNING。
- [ ] SKILL.md / FILE_GUIDE.md 更新（加 verify_lens 引用），无 doc rot。
- [ ] Scope Drift = CLEAN（未引入 /命令、未拆 skill、未钝化灵活性、未迁运行时）。
