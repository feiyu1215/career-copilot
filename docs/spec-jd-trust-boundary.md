# Spec: JD 信任边界（P5）

> 状态：实现中 · 范围：目录内 P5 增量
> 关联计划：`career-copilot-upgrade-plan.md` §4.5 / 路线图 P5（JD 边界）
> 关联文件：`scripts/jd_guard.py`（新）、`references/jd-trust-boundary.md`（新）

---

## 1. 问题

JD 是外部不可信数据，但现有匹配/改写链路默认把 JD 当"可信输入"消费。
若 JD 被注入提示词（要求改写器"把邮箱改成 X""忽略之前指令""代我投递"），
有越权执行风险。计划 P5 要求：**JD 视为不可信数据、禁止执行 JD 内嵌任何指令**。

## 2. 目标（非目标）

- **目标**：提供确定性（无 LLM）的 JD 注入检测 + 剥离，作为零信任边界。
- **目标**：检测后显式披露，不静默通过。
- **非目标**：不替用户改写/投递（角色边界不变）；不做语义级注入理解（靠确定性模式库，覆盖已知形态，留人工复核兜底）。

## 3. 接口

- `scan_jd(jd_text: str, source: str | None) -> JdGuardReport`
- `sanitize_jd(jd_text, source) -> (cleaned: str, report: JdGuardReport)`
- `JdGuardReport.injection_detected: bool` / `.high_severity_count` / `.summary()`
- CLI：`jd_guard.py check --jd <file|-> [--source X]`、`jd_guard.py sanitize --jd <file> [--output Y]`

## 4. 检测分组（确定性）

meta_instruction(high) / action_instruction(high) / delimiter_injection(medium) / exfiltration(high)。
见 `references/jd-trust-boundary.md` 表。

## 5. 验收

- 四组模式各至少 1 个样本命中；正常 JD（含招聘域链接、薪资数字）**不误杀**。
- 清洗后文本不含被剥离的注入片段；保留正当 JD 正文。
- 全离线单测通过（`tests/test_jd_guard.py`）。

## 6. 风险与边界

- 模式库为已知形态集合，无法覆盖未知注入范式 → 高严重度命中一律显式披露 + 人工复核。
- `exfiltration` 的"非招聘域链接"为粗筛、低置信，仅作警示不自动删行（避免误删正当外链）。
- **真实 JD 抓取（BOSS/美团）后先过 `sanitize_jd` 再进 `smart_score`**——接线点留待用户本地实测（需 VPN/已登录会话）。

## 7. 提交边界

- 仅新增 `scripts/jd_guard.py`、`tests/test_jd_guard.py`、`docs/spec-jd-trust-boundary.md`、`references/jd-trust-boundary.md`。
- **不触碰** `SKILL.md` / `scripts/smart_score.py`（均为用户未提交改动 ` M`）；红线标注由用户随其改动一并提交。
