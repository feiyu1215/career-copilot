<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# Bug Review — 2026-07-21（广扫：逻辑 / 可移植 / 一致性）

> 范围：对 `scripts/`、`evals/`、`tests/` 全部逻辑文件做静态复审（不跑 live，纯读码）。
> 与上一轮已修的 P1–P4 无关（P1 `sk-` 正则 / P2 测试 / P3 SKILL.md 编号 / P4 blind_eval_runner 路径 已落地）。
> 结论：**无崩溃级 bug**；以下为逻辑 / 可移植 / 一致性问题，按严重度排序。

---

## 🔴 Moderate（真实逻辑 / 可移植问题）

### M1. P4 修复不完整 —— scholar `.env` 硬编码路径仍残留 2 处
- `evals/run_dynamic_eval.py:59` `SCHOLAR_ENV = r"D:\57709\Desktop\Apple\美团\scholar-agent-public.working-20260707\.env"` 硬编码，无 `SCHOLAR_DOTENV` 覆盖。
- `evals/judge_ab_probe.py:44` 同路径硬编码（且自带 `load_env` 用 `os.environ.setdefault`，与 `run_dynamic_eval`/`blind_eval_runner` 的 `os.environ[k]=v` 语义不一致 —— setdefault 不会覆盖已设 key，CI 下可能吃到陈旧 key）。
- 已修：`blind_eval_runner.py`（用 `SCHOLAR_DOTENV` env 覆盖）；`run_ablation.py` 因 `import run_dynamic_eval` 继承其修复。
- 影响：在任意非开发机 / CI 上跑 `run_dynamic_eval.py`、`judge_ab_probe.py` 会找不到 scholar key。
- 建议：把 `blind_eval_runner._load_provider_env` 的 `SCHOLAR_DOTENV` 模式抽到共享函数，三处统一引用；并统一用 `os.environ[k]=v` 语义。

### M2. `_parse_json` Layer-4 正则兜底被当成真分（fallback 标记失效）
- `scripts/smart_score.py` `_parse_json` 第 4 层兜底：`re.search(r'"score"\s*:\s*(\d+)', text)` 命中后返回 `{"score": int, ..., "is_fallback": True}`。
- 但 `stage1` 里 `is_fallback = result is None or "score" not in result` —— 既然兜底结果**带** `score`，`is_fallback` 被算成 `False`；内层 `"is_fallback": True` 成死字段。
- 后果：残缺 / 半截 LLM 输出只要恰好含 `"score": N` 就被当有效 Stage-1 评估，**不标 fallback**；而 `verify_output` 的 C12 只查 Stage-2 的 `risks`，Stage-1 正则恢复项永远不被暴露为 fallback → fallback 透明度被破坏。
- 建议：`_parse_json` 返回 `(result, is_fallback)` 元组，或 stage1 同时检查 `result.get("is_fallback")`；最简单：Layer-4 兜底**不**放 `score` 键，让外层判定走 fallback 分支（含默认分 30）。

### M3. `core_team_signals` 是死特性 —— gen_profile 从不生成它
- `scripts/post_judge.py:detect_core_team` 读 `profile.get("core_team_signals", [])`（用户特定目标公司核心业务线信号）；`gen_profile.py` 还 `print(profile.get("core_team_signals"))`。
- 但 `gen_profile.PROFILE_SYSTEM_PROMPT` 的 JSON schema **没有 `core_team_signals` 字段** → LLM 从不输出 → 永远缺失 → 用户特定的核心团队降级路径**永不触发**（只 `GENERIC_CORE_SIGNALS` 生效）。
- 建议：在 prompt schema 加 `core_team_signals`（并说明取值来源，如「目标公司核心业务线关键词：豆包/火山方舟/Coze…」），或删掉 `detect_core_team` 里的死分支。

### M4. `blind_eval_runner._make_client` 对 friday provider 的 env 命名错位
- `_make_client` 读 `os.environ.get(f"{provider.upper()}_API_KEY")` / `_BASE_URL` → `friday` 期望 `FRIDAY_API_KEY` / `FRIDAY_BASE_URL`。
- 但 `.env` 映射（`_load_provider_env`）把 scholar 的 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 映射成 `FRIDAY_APP_ID` / `LLM_BASE_URL`，**不是** `FRIDAY_API_KEY`/`FRIDAY_BASE_URL`。
- `agnes`/`nvidia` 命名对得上（AGNES_* / NVIDIA_*），但 `friday` 会传 `None`/`None` 并静默回退到 import-time 的 PROVIDERS 快照 —— 该脚本下 friday provider 潜在失效。
- 建议：对齐命名（friday 读 `FRIDAY_APP_ID`/`LLM_BASE_URL`，或改映射键）。

---

## 🟡 Minor（文档 / 一致性）

- **m5. `verify_output.py` C7 注释与门槛不一致**：注释 L101「A 档应 ≥ 80」但实际门槛 `min_a < 75`（L112）；测试 `build()` 自身也把 75 当下限。建议注释改「≥ 75」或把门槛提到 80。
- **m6. `llm_client.py` docstring 漂移**：模块 docstring 只写 friday/sub2api，实际 `PROVIDERS` 还含 nvidia/agnes，误导维护者。
- **m7. `verify_lens.py` 小瑕疵**：`SOURCE_TAGS` 含 `"[来源"`（无 `]`，疑似为前缀匹配 `[来源：…]` 但与其他三项不一致，易误读）；`"肯定能过"` 同时出现在 `STRONG_MARKERS` 与 `ABSOLUTE_MARKERS`，同一句会触发 W1+W3 双告警（冗余）。
- **m8. `fetch_jobs.py` 合法空尾页被计入 `failed_pages`**：`fetch_all_jobs` 在空页终止分支（L352）仍 `failed_pages.append(page)`，导致最终「失败页面」报告混入合法的末页，误导运营。
- **m9. `assess_competitiveness.py` 解析失败静默默认 `match`**：`assess_single` 在 LLM JSON 解析失败时默认 `positioning="match"`，无 fallback 标记、不向决策输出暴露，可能污染投递策略。建议标 `needs_review`。

---

## 未改动说明
本轮严格「都看看再说」：**未修改任何代码 / 配置**。以上为静态复审结论，待用户确认后决定修复范围（全修 / 仅 Moderate / 选择性）。

> **后续裁决（2026-07-21 续）**：用户选「全部修（最高标准）」→ 9 项（M1–M4 + m5–m9）全部修复 + 补测试，按 scholar-dev-process 走 fix+test+green+doc。详见下方「修复记录」。

---

## 修复记录（2026-07-21 续 · 用户裁决：全部修 / 最高标准）

> 规范：scholar-dev-process（Implement=TDD → Review 双轴 + 置信度 → Ship=DoD）。DoD = ① fresh 测试通过 ② review_gate 无 P1 ③ 文档更新。
> 验证：`uv run --with pytest python -m pytest tests/ -q` → **129 passed**（基线 105 → +24 测试）；11 个改动文件 `py_compile` 全 OK。

### ✅ M1 — scholar `.env` 硬编码路径 + setdefault 语义不一致（可移植 / 一致性）
- **文件**：`evals/eval_env.py`（新，共享模块）、`evals/run_dynamic_eval.py`、`evals/judge_ab_probe.py`、`evals/blind_eval_runner.py`
- **做法**：抽出 3 处重复的 `.env` 加载器到 `eval_env.py`：
  - `load_dotenv_like(path, mapping=None)`：overwrite-style 注入（`os.environ[k]=v`），支持 `mapping`（scholar → friday 名映射）+ 缺文件静默 noop；统一 `setdefault` 不一致语义。
  - `scholar_dotenv_path()`：返回 `SCHOLAR_DOTENV` env 或默认 `D:\57709\Desktop\Apple\美团\scholar-agent-public.working-20260707\.env`。
  - `load_provider_env()`：`load_dotenv_like(".env")` + `load_dotenv_like(scholar_dotenv_path(), mapping=SCHOLAR_MAPPING)`。
  - 三处脚本改为 `from eval_env import load_provider_env` + `load_provider_env()`，删除各自的本地 `load_env()`/`SCHOLAR_ENV`。
- **测试**：`tests/test_eval_env.py`（5 项：mapping 加载 / 缺文件 noop / `SCHOLAR_DOTENV` 覆盖 / 默认路径 / `load_provider_env` 覆盖）。
- **Review**：Standards/Spec 过；置信度 9/10；Scope Drift=CLEAN（仅抽公共函数，未动运行时/命令/红线）。

### ✅ M2 — `_parse_json` L4 正则兜底被当真分（fallback 透明度破坏）
- **文件**：`scripts/smart_score.py`
- **做法**：新增 helper `_classify_parse(result)`：`is_fallback = bool(result.get("is_fallback")) or "score" not in result`，显式透传 `is_fallback`；`stage1` 的 `eval_one` 改用 `is_fallback, score, reasoning = _classify_parse(result)`，替代旧 `"score" not in result` 误判（L4 兜底带 `score` 键故旧逻辑永判 False）。
- **测试**：`tests/test_smart_score_parse.py`（5 项：L4 兜底标记 is_fallback / 合法 JSON 不标 / `_classify_parse` 对 None/正常/L4 三种形态）。
- **Review**：置信度 9/10；CLEAN。

### ✅ M3 — `core_team_signals` 死特性（gen_profile 从不生成）
- **文件**：`scripts/gen_profile.py`
- **做法**：在 `PROFILE_SYSTEM_PROMPT` 的 JSON schema 新增 `"core_team_signals"` 字段（在 `adjacent_but_different` 之后），并加 `## core_team_signals 规则` 段说明取值来源（候选人简历中真实参与的核心团队/战略项目/核心产品线关键词；无则 `[]`），让 `post_judge.detect_core_team` 的降级路径真正可用——**无需目标公司输入**，从简历真实关键词派生。
- **测试**：`tests/test_gen_profile.py`（1 项：prompt 含 `core_team_signals`）。
- **Review**：置信度 9/10；CLEAN（选「补字段使特性真实」而非「删死分支」，更保功能）。

### ✅ M4 — `blind_eval_runner._make_client` env 命名错位（friday 潜在失效）
- **文件**：`evals/blind_eval_runner.py`
- **做法**：新增 `_PROVIDER_ENV` 映射 `{"friday": ("FRIDAY_APP_ID","LLM_BASE_URL"), "sub2api": (SUB2API_*), "nvidia": (NVIDIA_*), "agnes": (AGNES_*)}` + `_provider_env_names(provider)`；`_make_client` 改用 `_provider_env_names` 取名，friday 读 `FRIDAY_APP_ID`/`LLM_BASE_URL`（对齐 `.env` 映射），未知 provider 回退 `{PROVIDER}_API_KEY/_BASE_URL`。删除旧的 `_load_env_file()`/`_load_provider_env()`，改用 `eval_env.load_provider_env()`。
- **测试**：`tests/test_blind_eval_provider_env.py`（4 项：friday 特殊名 / 其余 provider / 未知回退 / 取函数）。
- **Review**：置信度 9/10；CLEAN（与 M1 同改一处文件，命名对齐）。

### ✅ m5 — `verify_output` C7 注释(≥80)与门槛(75)不符
- **文件**：`scripts/verify_output.py`
- **做法**：`run_checks` C7 块 `if min_a < 75:` → `if min_a < 80:`，注释同步为「低于 80」，对齐既有「A 档：应 ≥ 80」质量门槛（取更高标准，非降注释）。
- **测试**：`tests/test_verify_output_c7.py`（2 项：80 通过 / 低于 80 失败）。

### ✅ m6 — `llm_client.py` docstring 漂移（缺 nvidia/agnes）
- **文件**：`scripts/llm_client.py`
- **做法**：模块 docstring 补全 4 个 provider（friday/sub2api/nvidia/agnes）及 `LLM_PROVIDER` 取值 `friday/sub2api/nvidia/agnes`。
- **测试**：`tests/test_llm_client_doc.py`（1 项：docstring 列全 4 provider）。

### ✅ m7 — `verify_lens.py` 标签未闭合 + 双表重复告警
- **文件**：`scripts/verify_lens.py`
- **做法**：`SOURCE_TAGS` 中 `"[来源"` → `"[来源]"`；`"肯定能过"` 从 `STRONG_MARKERS` 移除、仅保留在 `ABSOLUTE_MARKERS`（注释说明其为绝对保证语义，避免同句 W1+W3 双告警）。
- **测试**：`tests/test_verify_lens_tags.py`（3 项：`[来源]` 存在 / 无未闭合 `[来源` / `肯定能过` 仅出现一次 / `has_source_tag` 仍工作）。

### ✅ m8 — `fetch_jobs.py` 合法空尾页计入 `failed_pages`
- **文件**：`scripts/fetch_jobs.py`
- **做法**：`fetch_all_jobs` 空页终止分支（连续空页计数路径）移除 `failed_pages.append(page)`，合法末页不再污染失败报告；保留 `continue` + `consecutive_empty_pages >= 2` 终止逻辑；导航/解析真实失败分支仍计 `failed_pages`。
- **测试**：`tests/test_fetch_jobs.py`（2 项：空尾页不进 failed / 导航失败计入）。

### ✅ m9 — `assess_competitiveness.py` 解析失败静默默认 `match`
- **文件**：`scripts/assess_competitiveness.py`
- **做法**：`assess_single` 两处解析失败分支（内层 `json.JSONDecodeError` 与 `else` 无 `{` 分支）均改返回 `{"positioning": "needs_review", "needs_review": True, "confidence": 0.0, "gaps": [], "interview_risk": "解析失败", "reasoning": "模型输出无法解析，需人工复核"}`，向决策暴露而非污染投递策略。
- **测试**：`tests/test_assess_competitiveness.py`（2 项：解析失败→needs_review / 合法 JSON→match）。

### 修复总览
| 项 | 严重度 | 文件 | 测试文件 | 状态 |
|---|---|---|---|---|
| M1 | Moderate | evals/eval_env.py(新) + 3 evals 脚本 | test_eval_env | ✅ |
| M2 | Moderate | scripts/smart_score.py | test_smart_score_parse | ✅ |
| M3 | Moderate | scripts/gen_profile.py | test_gen_profile | ✅ |
| M4 | Moderate | evals/blind_eval_runner.py | test_blind_eval_provider_env | ✅ |
| m5 | Minor | scripts/verify_output.py | test_verify_output_c7 | ✅ |
| m6 | Minor | scripts/llm_client.py | test_llm_client_doc | ✅ |
| m7 | Minor | scripts/verify_lens.py | test_verify_lens_tags | ✅ |
| m8 | Minor | scripts/fetch_jobs.py | test_fetch_jobs | ✅ |
| m9 | Minor | scripts/assess_competitiveness.py | test_assess_competitiveness | ✅ |

- **全量测试**：105 → **129 passed**（+24，无回归）。
- **编译**：11 改动文件 `py_compile` 全 OK。
- **残留引用**：grep 确认 `evals/` 内无 `_load_provider_env`/`load_env(`/`SCHOLAR_ENV`/`_load_env_file` 残留。
- **DoD**：① fresh 测试通过 ✅ ② review_gate 无 P1 ✅ ③ 文档更新（本记录）✅。
- **未提交**：全部改动（含 9 新测试文件）在 working tree，延续用户「暂不 commit」；push 需另行确认。
