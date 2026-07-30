# Spec: Drafter-Reviewer 双轨评审（P4）

> 状态：实现中 · 范围：目录内 P4 增量
> 关联计划：`career-copilot-upgrade-plan.md` §4.5 / 路线图 P4（Drafter-Reviewer 接线）
> 关联文件：`scripts/drafter_reviewer.py`（新）、`tests/test_drafter_reviewer.py`（新）、`references/resume-guide.md`（红线口径，既有）

---

## 1. 问题

Tier2 精投需要"产出对外简历/求职信"，但产出有越权造假风险。计划 P4 要求：
Tier2 内 `llm_client` 两次调用（drafter + reviewer）+ 套四条硬契约。模型负责判断力，
代码负责约束力（与 `post_judge.py` 同哲学）。

## 2. 目标（非目标）

- **目标**：Drafter 产出草稿 → Reviewer 套四条硬契约 + Over-Claim 四陷阱 + 改稿护栏，确定性部分 0 违规才允许对外。
- **目标**：确定性检查器与护栏**完全离线可测/可 CI**，不依赖 LLM 网关。
- **非目标**：不在本机做真实 LLM 调用验证（需 VPN/网关，留用户本地实测）；不替用户投递。

## 3. 四条硬契约（确定性）

| 契约 | 检测 | 离线可测 |
|------|------|----------|
| C_R1 不编造 | 对外简历含 profile 无对应且未标 `[推测]/[脑补]` 的数字 → 违规 | ✅ |
| C_R2 不过度声称 | Over-Claim 四陷阱（修辞当测量/同构当佐证/偷换论题/结论过满） | ✅ |
| C_R3 单源未复现数字不进对外简历 | 与 C_R1 合并检测（红线条） | ✅ |
| C_R4 JD 注入未被执行 | 复用 `jd_guard.scan_jd`，草稿不得 obedient 含注入目标 | ✅ |

## 4. 接口

- `DrafterReviewer().draft(profile, jd_text)` / `.review(...)` / `.revise(...)`（async，需 LLM）
- `check_hard_contracts(draft_text, profile, jd_text="") -> list[(契约号, 说明)]`
- `detect_overclaim(text)` / `lock_original_hash(text)` / `compute_edit_ratio` / `check_edit_brake`
- CLI：`check`（离线）/ `brake`（离线）/ `draft`/`review`/`revise`（需网关）

## 5. 验收

- `tests/test_drafter_reviewer.py` 覆盖四契约各形态 + 清洁稿 0 违规 + 护栏熔断。全过。
- `tests/test_jd_guard.py` 覆盖 JD 信任边界全过。
- **真实 LLM 接线（draft/review/revise）待用户本地 VPN 实测**，本机不伪造证据。

## 6. 风险与边界

- 确定性检查器为启发式（已知形态），无法覆盖所有造假/注入范式 → 高严重度一律显式披露 + 人工复核兜底。
- LLM 调用延迟导入 `llm_client`，离线单测不触发网关依赖。
- 改稿护栏阈值 0.6 为经验常量（与 `resume-guide.md` 同源），可覆盖。

## 7. 提交边界

- 仅新增 `scripts/drafter_reviewer.py`、`tests/test_drafter_reviewer.py`、`docs/spec-drafter-reviewer.md`。
- **不触碰** `SKILL.md` / `scripts/llm_client.py` / `references/resume-guide.md`（均用户未提交改动 ` M`）。
- P3（两档软模式）的 `capability-modes.md` + SKILL.md 路由已在用户树中，视为已完成，不重复提交。
