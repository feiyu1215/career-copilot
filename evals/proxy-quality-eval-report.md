# 产出质量代理盲评报告（Proxy Quality Blind Eval）

> **本文件顶部为自评偏见模板必填项**（self-eval-bias-template）。

## 一、自评元信息

| 字段 | 值 |
|------|-----|
| 评测对象 | career-copilot skill（盲评脚手架live） |
| 评测日期 | 2026-07-22 |
| 评测方式 | LLM 盲评（LLM-as-judge） |
| 证据层级 | LLM-REAL |
| 总评结论 | 盲评链路真实跑通（演练：after 组 eval 真输出，无 before 组故无 Δ） |
| 可信度自评 | 中（judge 与生成可能同源） |

## 二、独立性声明

**1. 谁是评分人？** LLM-judge（provider 见 .env，默认 agnes）
**2. 评分人与被评对象的关系？** 零独立性（脚手架/评测与 skill 同源）。
**3. 出题人与阅卷人是否同一人？** 是（脚手架内置合成 transcript + stub judge），证明力上限：仅证明 pipeline 接线，**≠ 真实质量结论**。
**独立性结论：** 零独立（demo）/ 部分独立（live，judge 与生成可能同源）。结论不可外推为「跨模型/跨时间可靠」。

## 三、偏差自检

| # | 偏差类型 | 自检结果 | 缓解动作 / 证据 |
|---|---------|---------|---------------|
| B1 | 三重同源/零独立 | 已排查 | demo：stub judge 零独立，结论降级为「接线验证」；live：声明 judge 与生成可能同源 |
| B2 | 确认偏差 | 已排查 | 盲评严格 mask_label 剥 before_or_after，judge 不可见前后标签 |
| B3 | 边界凑分 | 不适用 | demo 仅验证机制，不声称压线结论 |
| B4 | 未验证事实 | 已排查 | 分数来自 fixture ground-truth（demo）或 LLM 返回（live），可溯源 |
| B5 | 自我服务归因 | 不适用 | demo 无归因 |
| B6 | 近因偏差 | 不适用 | demo 无历史上下文 |
| B7 | 框架效应 | 不适用 | 弱点直说，不粉饰 |

## 四、结果

| session_id | phase | before/after | model | D1 | D2 | D3 | D4 | D5 | D6 | 总分(0-12) |
|---|---|---|---|---|---|---|---|---|---|---|
| rehearsal_agnes-2.0-flash_11 | match | after | agnes-2.0-flash | 2 | 2 | 2 | 2 | n/a | 2 | **12** |
| rehearsal_agnes-2.0-flash_14 | match | after | agnes-2.0-flash | 2 | 2 | 2 | 2 | n/a | 2 | **12** |
| rehearsal_nvidia_11 | match | after | nvidia:deepseek-v4-flash | 2 | 2 | 2 | 2 | n/a | 2 | **12** |
| rehearsal_nvidia_14 | match | after | nvidia:deepseek-v4-flash | 2 | 2 | 2 | 2 | n/a | 2 | **12** |
| rehearsal_agnes-2.0-flash_12 | resume | after | agnes-2.0-flash | 1 | 2 | 2 | 0 | - | 1 | **6** |
| rehearsal_agnes-2.0-flash_13 | resume | after | agnes-2.0-flash | 2 | 2 | 2 | 2 | 2 | 2 | **12** |
| rehearsal_nvidia_12 | resume | after | nvidia:deepseek-v4-flash | 2 | 2 | 2 | 2 | 2 | 2 | **12** |
| rehearsal_nvidia_13 | resume | after | nvidia:deepseek-v4-flash | 2 | 2 | 2 | 2 | 2 | 2 | **12** |

### 阶段均值与 Δ

| phase | before 均值 | after 均值 | Δ (after-before) | n_before | n_after |
|---|---|---|---|---|---|
| match | nan | 12.00 | +nan | 0 | 4 |
| resume | nan | 10.50 | +nan | 0 | 4 |

## 五、强制承诺

- [x] 本报告已显式标注独立性缺陷，未隐瞒。
- [x] 所有分数/结论均可追溯到具体证据（fixture / LLM 返回）。
- [x] 证据为 LLM-REAL（真实 transcript + LLM-judge）；judge 与生成可能同源已在 B1 声明。

## 六、数据来源与边界（演练声明）

- **数据来源**：本跑 replay 的是 `evals/eval_results_dynamic*.json` 中 **after（契约硬化后）组** 的真实 LLM 输出，经脱敏 + 标签造 transcript；**非生产环境积累的真实用户对话**。
- **采集方式（enabler）**：本批 transcript 由 `evals/collect_transcript.py` 的 `collect_session()` **程序化采集**（脱敏 + 打 before/after 标签）落盘到 `evals/transcripts/<phase>/after/`，再经 `--live` 盲评；本次重跑验证了「采集 enabler → 盲评」整链在真实 LLM 输出上跑通，judge 与上次演练一致（agnes_12 仍 6/12、D4=0），证明 judge 可复现、非橡皮图章。
- **无 before 组**：仓库内无真实 before 输出，故 **无法计算 before/after Δ**；本跑仅证明 `--live` 盲评链路在真实 LLM 输出上能跑通并产出 D1–D6 分数，不构成质量提升结论。
- **judge 同源**：judge 默认 agnes，与部分生成模型同源（nvidia 生成由 agnes 评，部分独立）；跨模型稳健性仍需独立 judge 验证（见 B1）。
- **样本量小**：仅 8 条 after，其中多数满分、个别被 judge 判低分（如 D4 改稿熔断缺失=0、D1/D6 部分），说明 judge **确有区分度**、非橡皮图章；但样本小、无 before、judge 同源，**不能外推为生产稳健**。
- **下一步**：生产 transcript 积累后（每 phase ≥10 before+10 after）重跑 `--live`，方可得到可信 Δ。

