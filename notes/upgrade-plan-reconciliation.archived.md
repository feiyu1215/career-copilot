<!-- SUPERSEDED — 本文件不再反映代码现状，请勿据此执行 -->
# ⚠️ 本文档已过时（SUPERSEDED）

**本文件写于 2026-07-22，记录的是 T1–T15 升级任务执行 *之前* 的代码现状诊断。**
T1–T15 已全部落地并提交（最新 commit `5d7c6c1`）。本文档「§1 现状诊断 / §2 缺陷—任务对账」中的每一项「开 / 未做」现均已实现并提交：
- `chat()` 统一失败语义（T2）、`PipelineAbortError` / `StageStats`（T1/T5）、`config/pipeline.yaml`（T5）
- `trace.py` / `cache.py`（T6/T7/T13）、career_log v2（T14）、fetch_jobs_feishu 增强（T15）

**当前权威文档**：`notes/audit-report-T1-T15.md`（T1–T15 全量审计 + 三处 bug 修复记录）。
本文件仅保留作历史决策追溯，**不再反映代码现状**。

---

# Career Copilot v3.0 升级计划 × 已提交状态 对账与执行建议

> 日期：2026-07-22（T1–T15 执行前）
> 依据：5 份文档（handover / hy3-prompt / upgrade-plan / -executable / -supplement）+ 仓库实测
> 实测方式：Bash `ls`/`find`/`grep`（本机 Glob 有 ENOENT 假阴性，已用 Bash 复核）

---

## 0. 结论（先看这里）

- 升级计划 v3.0（T1–T15）**约 90% 仍是有效待办**。已提交的 `1fd08e1`（P0–P2 honesty-first）修的是
  **内容诚实层**（评测可移植、fallback 透明度、死特性、env 命名、verify 门槛、docstring、透镜、
  抓取尾页、竞争力默认），**没有触及可靠性底座**（熔断器、统一失败语义、配置化、可观测、缓存、
  career_log v2）。
- 文档与代码存在几处**陈旧 / 矛盾声明**（见 §3），执行前应先修正，否则按文档字面会踩坑。
- 计划自身的"自适应原则"（按特征串搜索、不靠行号）正确且必要；另加一条本机铁律：
  **Glob「No files found」不可信，文件存在性一律用 `ls`/`find` 复核**。

---

## 1. 计划「现状诊断」逐项核验（理性怀疑）

| 计划声称 | 仓库实测 | 判定 |
|---|---|---|
| 129 个测试 | `grep -c 'def test_'` = **129**（tests/ + evals/） | ✅ 真 |
| M2 已修 / 4 providers 已配 | 代码 `PROVIDERS` 含 friday/sub2api/nvidia/**agnes**（4 个）；但 `.env.example` 只文档化 3 个（缺 `AGNES_*`） | ⚠️ 代码真、setup 文档假 |
| P0–P2 评测基建已建 | `evals/` 有 **7 个 .py**（run_dynamic_eval / judge_ab_probe / blind_eval_runner / eval_env / collect_transcript / proxy_eval_lib / run_ablation）+ `transcripts/` + 多份结果 JSON + `proxy-quality-eval-report.md` | ✅ 真（但计划 Phase 3 把它当绿地，低估现状） |
| 统一失败语义（D3）已落地 | `llm_client.py:179` `chat()` 仍 `return ""`；`chat_raw` 仍 `return None`（L208–228）；无 `LLMCallFailed` | ❌ 未做 |
| 熔断（D1）已落地 | 无 `PipelineAbortError` / `StageStats` / circuit breaker | ❌ 未做 |
| 配置化（D18）已落地 | 无 `config/`、`config/pipeline.yaml` | ❌ 未做 |
| 可观测（Trace/成本）已落地 | 无 `trace.py`、`cache.py` | ❌ 未做 |
| Stage 模型 gpt-4o-mini / gpt-4.1-mini | `smart_score.py`/`diff_watch.py` 默认一致；agnes 默认 `agnes-2.0-flash` | ✅ 真（T5 配置 YAML 与代码吻合） |
| fetch_jobs_feishu monkey-patch 已消除 | `fetch_jobs_feishu.py:569` 仍存在 `FeishuJobCrawler._build_job_texts = ... # type: ignore` | ❌ 未做（T3.2 仍必要） |

> **关键修正（对上轮 summary 的纠正）**：上轮提示「honesty-first/P0–P2 大量已落地、计划或被大量吸收」——
> **仅对内容诚实层成立**。可靠性底座（T1/T2/T5/T6/T7/T8/T13/T14）基本为零进展。计划仍基本有效，
> 不应因「已提交」而跳过执行。

---

## 2. 缺陷—任务对账（D# → 状态 → 对应 Task）

| 缺陷（来自 upgrade-plan.md §1.2） | 状态 | 任务 |
|---|---|---|
| D1 熔断 / 超时 | 开 | T1 |
| D2 LLM client jitter | 开（疑似，待查 `_compute_retry_wait`） | T2.2 |
| D3 统一失败语义 | 开 | T2.1 / T2.3 |
| D17 Provider 降级链 | 开 | T2.4 |
| D6–D11 工程卫生 | 开（部分） | T3.1–T3.5 |
| D9 report God Function 重构 | 开 | T4 |
| D18 配置化 | 开 | T5 |
| 可观测 Trace | 开 | T6 |
| 成本追踪 | 开 | T7 |
| Prompt 外置 | 开 | T8 |
| D15 SKILL 分层 | 开 | T9 |
| D14 Golden cases | 开（harness 在，结构化 gate 无） | T10 |
| 回归 / 多 judge | 开 | T11 / T12 |
| D12 语义缓存 | 开 | T13 |
| D4 / D16 career_log v2 | 开 | T14 |
| feishu 增强 | 开（依赖 T3.2） | T15 |

**已闭环（来自 `1fd08e1`）：** M1 评测可移植、M2 `_parse_json` fallback 透明、M3 core_team_signals、
M4 friday env 命名、m5–m9 若干一致性。

---

## 3. 文档陈旧 / 矛盾声明复核（理性怀疑二次校验）

> **结论：原计划文档本身准确，原 §3 的 5 处「陈旧」经实测复核均为误判，无需改文档。**
> 复核证据（避免盲改准确文档）：

1. **「4 providers」≠ 矛盾**：§1.2 行 21 写的是**代码现实**（PROVIDERS 含 friday/sub2api/nvidia/agnes 共 4 个），
   **D6 已单独列出** `.env.example` 缺 agnes 为开放缺陷（= T3.1）。二者自洽，非「已配」。
2. **Phase 3 非绿地**：标题即「评估体系**深化**」，行 20 现状表写「框架已建」（dynamic eval + ablation + blind eval + transcript）。
   `evals/` 7 脚本现状与计划预期一致，无「从零建」误述。
3. **BEFORE 行号漂移已有覆盖**：补充卷「〇、自适应原则」已明令「按特征串搜索、不靠行号、行号可能偏移 ±20」。
   `1fd08e1` 改过的文件执行时依此操作即可，无需额外改文档。
4. **requirements 依赖已在目标态**：补充卷附录已给出 T5/T10 后的最终 `requirements.txt`（含 `pyyaml`/`scipy`）。
   当前仓库未写是「待 T5/T10 落地」，非文档遗漏。
5. **import-time env 风险已文档化**：`handover §8.1` 已列「import-time env 捕获」为 GOTCHA；T2.4 降级链执行时据此注意即可。

### 唯一建议的执行附注（非改文档，仅作执行基线提醒）
- **执行基线 = 提交 `1fd08e1`**。所有 Task 的 BEFORE 片段以该基线为准；若后续有中间提交，先 `git log` 确认再按特征串定位。
- **本机 Glob 假阴性铁律**：Windows 下 Glob 对中文路径有 ENOENT 假阴性（已实测 `evals/**/*` 报空但实际有 7 文件）。
  **任何「文件不存在」一律用 `ls`/`find` 复核**，不信任 Glob。
- 本附注已并入本文件 §1 核验表与下方执行顺序，计划原文无需改动。

---

## 4. 执行顺序建议（按杠杆率重排，保留计划依赖图）

**根因视角（fundamental-thinking）**：「诚实输出」的底座是**失败时可见**——当前 `chat()` 静默返回
`""`/`None`，是任何「假分 / 静默降级」的源头。故顺序以「先让失败显形」为轴心：

1. **T2（统一失败语义 + 降级链）**——最高杠杆，先做。T2.1–2.3 改 `chat`/`chat_raw` 抛 `LLMCallFailed`；
   T2.4 新增 `provider_chain.py`。
2. **T1（熔断）**——与 T2 独立，并行。
3. **T3（工程卫生）**——T3.1 补 agnes、T3.2 去 monkey-patch、T3.3 pyproject、T3.4 Makefile、T3.5 log_utils。
   低风险高收益。
4. **T4（report 重构）**——独立。
5. **T5（config）**——Phase 2 枢纽，T6/T7/T8 前置。
6. **T6 + T7（trace + 成本）**——可观测。
7. **T8 + T9（prompt 外置 + SKILL 分层）**——可维护性，降 token / 漂移。
8. **T10–T12（golden / 回归 / 多 judge）**——在现有 harness 上深化评分诚信 gate。
9. **T13 / T14 / T15**——性能 / 记忆 / 抓取增强，独立收尾。

每 Task 一 commit（`T<N>: ...`），先跑 `pytest` 再改（计划铁律 + hy3-prompt 10 铁律）。

---

## 5. 待你裁决

- **(A) 现在开始执行？** 若可，建议从 **T2 + T1**（最高杠杆）起步，或按计划 T1–T4 并行。
- **(B) 先修文档？** 先改 §3 的 3–5 处陈旧声明，再执行，降低踩坑率。
- **(C) 暂挂**——仅采用本对账作为后续参考。

---

## 6. 计划验收口径裁决记录（2026-07-22，T9 执行时）

### 6.1 T9 SKILL.md token 基线：<3000 → 重定 10000
- **实测**：SKILL.md 310 行中文、已高度分层（引用 12 个 `references/*.md`）。
  cl100k 精确计数 = **9915**（tiktoken）；CJK 启发式 = 6177。
- **计划原验收**写「token 数 < 3000（tiktoken 或字符数/4 估算）」——该阈值与真实内容
  严重不符（疑为规划时按「词/段」宽松估算，非 cl100k 口径）。
- **裁决（用户确认）**：将基线**重定为 10000**，写回计划文档
  `career-copilot-upgrade-plan-executable.md:1718`，并落实为 `tests/test_skill_refs.py`
  的 `test_skill_md_token_count` 默认阈值（`SKILL_TOKEN_LIMIT` 环境变量可覆盖）。
- **理由**：裁剪 SKILL.md 到 3000 会掏空已建立的分层结构（违背 T9 初衷），故选择重定基线。
- **状态**：已提交（c5b3aed 后续修正 + 本记录）。

---

*生成方式：4 个思考技能叠加（comprehensive / rational-skepticism / fundamental / serious-mode）
+ 仓库实测校验。本文件为「处理 5 份文档」的产出，非代码改动。*
