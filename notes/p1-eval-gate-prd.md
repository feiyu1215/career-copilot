<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P1-4 持续 eval 门禁 · PRD

> 来源：`notes/archive/skilllens_upgrade_plan.archived.md` P1 段最后一项。立项依据：(A) 防回退——把 G1/G2/A/B 的 eval 成果锁进可重复门禁，避免软契约在后续改动中悄悄退化；(B) 无。哲学合规：不引命令、不拆 skill、不钝化灵活性。
> 开发纪律：`scholar-dev-process`（Grill→To-Spec→To-Tickets→Implement(tdd)→Review→Ship）。

## Problem
- `run_dynamic_eval.py` 已能算出 `[gate] PASS/FAIL`，但**进程永远 exit 0**（除非抛未捕获异常）。CI / pre-commit 无法用它阻断回归。
- gate 逻辑内联在 `main()`（L209-225），无独立可单测 seam；想加测试只能整跑 eval（消耗 API）。
- 无 `Makefile` / CI 入口，开发者手敲长命令易出错。

## Solution
1. **提取纯函数 `compute_summary(results)`**：把 L209-225 的 gate 计算抽成可 import 的纯函数，返回 `summary` dict（含 `gate`）。`main()` 调用它。
2. **进程退出码**：`main()` 末尾 `sys.exit(0 if gate=="PASS" else 1)`。CI 直接靠退出码阻断。
3. **LLM 不可达 → --skip**：`__main__` 加 `EVAL_SKIP_ON_ERROR=1` 时，顶层运行异常（client 初始化失败 / 网络不可达）改 exit 0 + 警告，不阻断 CI。
4. **Makefile 入口**：加 `make test`（pytest）与 `make eval`（跑 agnes + repeat=2 门禁）；`make eval-skip` 带 `EVAL_SKIP_ON_ERROR=1`。

## User Stories
- 作为维护者，改完 skill 跑 `make eval`，软契约回归立刻被阻断（exit≠0）。
- 作为 CI，eval 步骤直接吃 `run_dynamic_eval.py` 退出码；LLM 端点挂了用 `--skip` 不红 CI。

## Implementation Decisions
- **Seam（TDD 核心）**：`compute_summary(results) -> summary` 是纯函数，用 fixtures 单测，不依赖 API。
  - all core passed + kv stable → PASS
  - 任一 core failed → FAIL
  - 任一 kv unstable(stable=False) → FAIL（eval 自身故障）
  - kv unverified(stable=None) → PASS（毛刺，不阻断）
- **不重源码逻辑**：gate 规则与 G2 完全一致，仅抽取，不改语义。
- **不碰**：契约定义、`verify_lens.py`、脚本运行时、.env。

## Testing Decisions
- TDD：先写 `tests/test_eval_gate.py`（红：import `compute_summary` 失败），再抽取（绿）。
- 4+ 用例覆盖 PASS / core-fail / kv-unstable / kv-unverified。
- 全量 `pytest tests/` 需保持绿。

## Out of Scope
- pre-commit 框架接入（可选，Makefile 已满足核心门禁；文档注明即可）。
- 改 eval 用例 / 契约 / judge（本里程碑只做门禁基建）。
- 任何软契约行为变更。

## Evidence Tier
- 门禁逻辑 = SYNTHETIC-MECHANISM（纯函数 + fixtures，sandbox 全验，无需 live key）。
- `make eval` 真跑 = LLM-REAL（fresh evidence，需 agnes API；用户已授权）。
