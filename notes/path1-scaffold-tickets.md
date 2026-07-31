<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P2-3 路径1 盲评脚手架 Tickets（垂直切片）

> 父 PRD：`notes/path1-scaffold-prd.md`。流程：To-Spec（已定）→ To-Tickets（本文件）→ Implement(TDD) → Review → Ship。
> EVIDENCE_TIER：脚手架确定性逻辑 + demo 接线 = **SYNTHETIC-MECHANISM**（离线可验，demo 不烧 API）；真实 LLM 跑分 = **LLM-REAL**（数据到位后，非本批验收）。

## 切片总览（tracer-bullet，每票可独立断言）

| Ticket | 内容 | 公共 Seam | Blocking edges | Acceptance |
|--------|------|-----------|----------------|------------|
| **S1** | `evals/proxy_eval_lib.py` 纯函数 | `redact_text` / `build_record` / `mask_label` / `aggregate_score` | 无 | 4 函数签名/行为符合测试；复用 `career_log.SENSITIVE_PATTERNS` |
| **S2** | `evals/collect_transcript.py` CLI | 命令行落盘 transcript | S1 | `--input/--phase/--before-or-after/--model/--session-id` 一条命令脱敏+标签落盘 `evals/transcripts/<phase>/<before|after>/<session_id>.jsonl` |
| **S3** | `evals/blind_eval_runner.py`（含 `--demo`） | CLI 盲评 + 报告 | S1 | `--demo` 用内置合成 transcript + stub judge 跑通整条 pipeline（脱敏→掩码→judge→聚合→报告），**不烧 API、报告顶部填 self-eval-bias-template、明确标注 SCAFFOLD**；`--live` 路径代码存在但要求真实数据 + key，本批不验收其结论 |
| **S4** | `tests/test_proxy_eval.py` + 回归 | 离线断言 | S1–S3 | 新测试 red→green；全量 suite 较 S1 前 **+3 passed**，无回归 |

## S1 — `proxy_eval_lib.py`（Seam 落地，TDD 红→绿）

**公共 Seam（供 S4 测试 + S2/S3 复用）**：
- `redact_text(text: str) -> str`：复用 `career_log.SENSITIVE_PATTERNS`，命中手机号/身份证/email/key/敏感词 → 替换为 `***`；无命中原文返回。
- `build_record(lines: list[dict], *, session_id, phase, before_or_after, model, redact=True) -> dict`：返回 `{session_id, phase, before_or_after, model, turns:[{role,text}]}`；`redact=True` 时每条 text 过 `redact_text`。
- `mask_label(record: dict) -> dict`：返回去 `before_or_after` 的副本（防 B2 确认偏差），judge 仅见 turns + phase。
- `aggregate_score(scores: dict[str,int], phase: str) -> int`：
  - `resume` phase：D1–D6 各 0–2 求和（0–12）。
  - 非 `resume` phase：D1/D2/D3/D4/D6 求和（0–10）归一到 0–12（`round(raw/10*12)`）。
  - 缺 key 视作 0。

**Acceptance**：S4 测试全过；不引入新依赖；导入 `career_log` 仅在模块加载时把 `scripts/` 加入 `sys.path`（沿用现有 eval 脚本惯例）。

## S2 — `collect_transcript.py` CLI

- 参数：`--input <jsonl>`（每行 `{role,text}`）、`--phase`（match/interview/resume/memory）、`--before-or-after`（before/after）、`--model <str>`、`--session-id <str>`、`[--no-redact]`（默认脱敏）。
- 行为：读 JSONL → `build_record` → 落盘 `evals/transcripts/<phase>/<before|after>/<session_id>.jsonl`（目录自动创建）。
- 输出：打印落盘路径 + 脱敏计数（方便审计）。
- **Acceptance**：一条命令可跑通；落盘位置与 `proxy-quality-eval-protocol.md` 第二节一致；脱敏非空示例被替换。

## S3 — `blind_eval_runner.py`（含 `--demo`）

- `--demo`：内置 2 before + 2 after 合成 transcript（简历 phase，ground-truth D1–D6 分数写进 fixture 元数据并**明确标注 SCAFFOLD**）→ 对每条 `mask_label` 后交 **stub judge**（直接回传 fixture 内 ground-truth 分数，证明接线、不烧 API）→ `aggregate_score` → before/after 均值 + Δ → 出 `evals/proxy-quality-eval-report.md`（顶部填 `self-eval-bias-template`：评测方式=LLM 盲评(脚手架demo)、证据层级=SYNTHETIC-MECHANISM、B1 标「零独立（脚手架内置 stub judge，非真实评分）」、B2 标「已排查（掩码 before/after）」）。
- `--live`（代码存在，本批不验收）：真实路径 = 读 `evals/transcripts/` 下 before/after → `mask_label` → 调 LLM-judge（`JUDGE_SYS_PROXY`，按 D1–D6 打 0–2，judge 用与生成侧不同 provider）→ 聚合 → 报告（EVIDENCE_TIER=LLM-REAL，B1 标「judge 与生成可能同源」）。要求真实 transcript 数据 + `.env` key，数据到位后跑。
- **Acceptance（本批）**：`--demo` 一条命令跑通、产报告、不碰 API、报告含 bias 模板且 tier 正确；`--live` 代码可 import 不报错（结构完整）。

## S4 — `tests/test_proxy_eval.py` + 回归

- 离线断言 S1 四函数（redact 命中手机/身份证/email、clean 文本不变；build_record 加标签+脱敏、redact=False 保留；mask_label 去 before_or_after；aggregate resume 求和 / 非 resume 归一 / 全 0）。
- 运行：`python -m pytest tests/ -q`；全量较 S1 前 **+3 passed**（原 83 → 86），无回归。
- **Acceptance**：新测试首次运行红（S1 未实现）、实现后绿；全量 suite 通过。

## 范围外（本批不做）
- 真实 LLM-judge 跑分（需生产 transcript + 可达 key，属运行期）。
- 人类专家盲评 UI（留 `proxy-quality-eval-protocol.md`）。
- 新增密钥 / 改 `.gitignore`。
