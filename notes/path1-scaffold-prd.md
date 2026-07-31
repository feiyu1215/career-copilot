<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P2-3 路径1 盲评脚手架 PRD（scaffolding）

> 依据 `notes/proxy-quality-eval-protocol.md`（方法学已落地，真实数据待生产环境积累）。
> 开发规范：scholar-dev-process（Grill→To-Spec→To-Tickets→Implement(TDD)→Review→Ship）。
> EVIDENCE_TIER：本脚手架的确定性逻辑（脱敏/标签/掩码/聚合）+ demo 接线 = **SYNTHETIC-MECHANISM**（离线可验、demo 用 stub judge 不烧 API）；真实评分需生产 transcript + live judge（LLM-REAL，数据到位后跑）。

## Problem（问题）
`proxy-quality-eval-protocol.md` 固化了数据格式 / 盲评 rubric / 执行流程，但**没有可运行代码**。数据到位后还需现写采集 + 盲评脚本，容易临时拼凑、偏离协议（尤其脱敏与「屏蔽 before/after 防 B2」两处）。需要把方法学落成脚手架，使数据一到即可跑。

## Solution（方案）
新增 3 个文件（均在 `evals/`，与现有 eval 体系同目录）：
- `proxy_eval_lib.py`：确定性共享逻辑——`redact_text`（复用 `career_log.SENSITIVE_PATTERNS`）、`build_record`（加 `session_id/phase/before_or_after/model` 标签）、`mask_label`（剥离 before_or_after 防 B2）、`aggregate_score`（D1–D6 → 0–12）。
- `collect_transcript.py`：CLI——读 transcript（JSONL `{role,text}`），脱敏 + 标签，落盘 `evals/transcripts/<phase>/<before|after>/<session_id>.jsonl`。
- `blind_eval_runner.py`：CLI——读 transcripts，掩码标签，按 D1–D6 调 LLM-judge（复用 `JUDGE_SYS`），聚合 before/after 均值，出 `evals/proxy-quality-eval-report.md`（含 `self-eval-bias-template` 头部）。`--demo` 用内置合成 transcript + stub judge 证明接线、**不烧 API、明确标注 SCAFFOLD**。

## User Stories（长列表）
- 作为评测执行者，我想数据一到就 `collect_transcript.py` 脱敏落盘、`blind_eval_runner.py` 盲评出报告，而不必重写脱敏/掩码逻辑。
- 作为审计者，我想确认脚手架在「无真实数据」时也能跑通（demo），且真实跑分与生成侧不同源（B1 声明）。

## Implementation Decisions（含 seam 草拟）
- **Seam（实现）** = `proxy_eval_lib.py` 纯函数；**Seam（测试）** = `tests/test_proxy_eval.py` 离线断言。
- 脱敏复用 `career_log.SENSITIVE_PATTERNS`（DRY，不重造正则）。
- 盲评严格屏蔽 `before_or_after`（协议 B2）；judge 用与生成侧不同 provider 降低同源（仍非完全独立，报告 B1 声明）。
- CLI 一条命令可跑：`python evals/collect_transcript.py --input t.jsonl --phase 简历 --before-or-after after --model agnes-2.0-flash --session-id s1`。

## Testing Decisions
- TDD：先写 `tests/test_proxy_eval.py` 断言 redact/build_record/mask_label/aggregate（red→green），全离线无 API。
- demo 模式用 stub judge 跑通整条 pipeline，证明接线（SYNTHETIC-MECHANISM）；live 路径（有数据+API）由后续数据到位后验证。

## Out of Scope（不做）
- 不声称任何真实评测结论（无生产数据）。
- 不新增密钥 / 不改 `.gitignore`（transcript 已排除）。
- 不做人类专家盲评 UI（仅 LLM-judge 路径；专家路径留 protocol 文档）。
