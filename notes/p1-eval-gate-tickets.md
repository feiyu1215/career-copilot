<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P1-4 持续 eval 门禁 · Tickets（垂直切片）

> 父 PRD：`notes/p1-eval-gate-prd.md`。

## Ticket P1-4a：提取 compute_summary + 退出码 + skip
- **垂直切片**：改 `evals/run_dynamic_eval.py`。
- **内容**：
  1. 抽 `compute_summary(results) -> dict`（含 `gate`），替代 L209-225 内联；`main()` 调用之。
  2. `main()` 末尾 `sys.exit(0 if summary["gate"]=="PASS" else 1)`。
  3. `__main__`：`EVAL_SKIP_ON_ERROR=1` 时顶层异常改 exit 0 + 警告。
- **Acceptance**：`tests/test_eval_gate.py` 全绿；`make eval` 在 gate FAIL 时 exit≠0。
- **Blocking edges**：无。独立可 ship。
- **Out of scope**：Makefile（P1-4b）、契约/judge 变更。

## Ticket P1-4b：Makefile 入口
- **垂直切片**：新建 `Makefile`。
- **内容**：
  - `make test` → `python -m pytest tests/ -q`
  - `make eval` → `EVAL_PROVIDER=agnes EVAL_REPEAT=2 python evals/run_dynamic_eval.py`（exit 码即门禁）
  - `make eval-skip` → 带 `EVAL_SKIP_ON_ERROR=1`
- **Acceptance**：`make test` 绿；`make eval` 在 gate FAIL 时非零退出。
- **Blocking edges**：依赖 P1-4a（退出码）。
- **Out of scope**：pre-commit 框架（文档注明可选）。

## 执行顺序
P1-4a → P1-4b。每票 TDD：红测试 → 改 → 绿 → 双轴 review → ship。最后 `make eval` 真跑（LLM-REAL fresh evidence）。
