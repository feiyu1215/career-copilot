<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# 升级计划 T1–T15 整体审计报告

> 审计日期：2026-07-22
> 审计范围：`career-copilot-copy` 的 T1–T15 全部代码与配置
> 方法论：配合 `fundamental-thinking` / `rational-skepticism` / `serious-mode` / `comprehensive-thinking` 四个思维 skill
> 审计原则（serious-mode Rule 5 / rational-skepticism 原则 9）：**所有结论均来自对源码的逐行第一手核查，不信任任何摘要或"测试已通过"的声明。**

---

## 一、审计方法与结论框架

### fundamental-thinking（三层审视）
1. **合法性**：T1–T15 的整体升级意图是否成立？（结论：成立——语义缓存、Career Log v2、飞书断点续爬、提示词外置、trace/cost 等均为合理且正交的改进。）
2. **解构**：每个实现是否与其任务定义一致？（结论：存在 1 处契约违背 + 2 处文档/行为漂移。）
3. **质量**：测试是否真正覆盖了真实行为？（结论：**否**——197 个测试全绿，但没有一个测试跑通真实 `run_pipeline` 端到端，导致一个必崩的运行时错误漏网。）

### rational-skepticism（四层追问 + 第一手验证）
- 凡标注"已通过/无 bug"的声明，一律重新读源码核对。
- 关键反证：`evals/run_accuracy_eval.py:130` 中 `scored, _stats = asyncio.run(stage1(...))` **正确解包**，恰好反证 `smart_score.run_pipeline` 的解包违背契约。
- 不假设"测试绿 = 正确"，而是追问"测试到底覆盖了什么"。

### serious-mode（Rule 5 第一手事实）
- 本报告每一条发现都附带**文件名 + 行号 + 代码片段**，可复核。

### comprehensive-thinking（五层交叉审查）
- 横跨"文件"与"代码"：既看 SKILL.md / prompts.yaml / pipeline.yaml / reconciliation 笔记，也看每个脚本。
- 覆盖：运行时崩溃、HTML 安全/正确、文档与行为一致性、测试覆盖缺口、统计正确性、resume 路径对称性。

---

## 二、总体结论

| 维度 | 结论 |
|------|------|
| 测试状态 | 197 个单元/模块测试**全绿**（但端到端 `run_pipeline` 从未被运行） |
| **CRITICAL** | 1 个：新鲜运行 `run_pipeline` 在 Stage1→Stage2 边界**必崩** |
| **MEDIUM** | 1 个：`generate_report.py` 全部动态字段**未 HTML 转义** |
| **LOW/DOC** | 1 个：`career_log.py` `query --company` 帮助文案与真实行为（精确匹配）不符 |
| 非问题（已核查） | T13 缓存、T14 其余逻辑、T15 续爬、T8 提示词零漂移、pre_filter/post_judge/trace 均无误 |

**根因（comprehensive-thinking）**：测试覆盖缺口是 CRITICAL 漏网的充分条件——只测了单 stage，没测组装后的 `run_pipeline`，于是"单元正确、组装崩溃"的裂缝无人发现。

---

## 三、发现清单（按严重度）

### 🔴 [CRITICAL] `smart_score.run_pipeline` Stage1 返回值未解包 → 新鲜运行必崩

**位置**：`scripts/smart_score.py:1054`

**契约事实**：
- `stage1()` 返回 **2 元组** `(scored, stage_stats)`（证据：`smart_score.py:626` `return scored, stage_stats`）。
- `stage2()` 返回 **2 元组** `(all_analyzed, stage2_failures)`（证据：`smart_score.py:819`）。
- `run_pipeline` 在 Stage2 处**正确解包**了：`analyzed, stage2_failures = await stage2(...)`（`smart_score.py:1099`）。
- 但 Stage1 处**没有解包**：`smart_score.py:1054`
  ```python
  all_scored = await stage1(client1, candidate_summary, direction_anchor, jobs, progress1, tracer=tracer)
  ```
  于是 `all_scored` 实际是 `(scored_list, stage_stats_dict)` 这个**元组**，而非列表。

**崩溃链（fresh 运行，必现）**：
1. `smart_score.py:1058` `scores = [j["stage1_score"] for j in all_scored]`
   → 迭代 2 元组，第一个元素 `j` 是 `scored`（一个 list）；`scored["stage1_score"]` → `TypeError: list indices must be integers or slices, not str`。
2. 即便绕过，`:1069` `all_scored.sort(...)` → `AttributeError: 'tuple' object has no attribute 'sort'`。
3. `:1070` `top_jobs = all_scored[:top_k]` 也只切出元组；`:1186` `stage1_all_scores` 的推导式同样会崩。

**次生正确性错误**：
- `stage1_stats` 在 `:1039` 初始化为 `None`，因未解包而**永远为 None**。
- 最终返回 `output["metadata"]["stage1_stats"]`（`:1192–1199`）因此**全为 0**，`degraded` 标志（`:1199`）也不会反映 Stage1 的失败——静默丢失关键质量信号。

**resume 路径的陷阱（值得注意）**：
- `:1043` `all_scored = stage1_ckpt["all_scored"]` 赋的是真正的列表，所以 `--resume` 路径本身不崩。
- 但 checkpoint 写入在 `:1074`，**位于崩溃点之后**——一次 fresh 运行会在写入 checkpoint 之前就崩掉，因此 `--resume` **无法自救**一次 fresh 失败。

**决定性反证**：`evals/run_accuracy_eval.py:130` `scored, _stats = asyncio.run(stage1(...))` 正确解包 → 证明 `stage1` 的契约就是 2 元组，违背契约的是 `run_pipeline` 这一处。

**修复**（1 行）：
```python
all_scored, stage1_stats = await stage1(client1, candidate_summary, direction_anchor, jobs, progress1, tracer=tracer)
```

---

### 🟠 [MEDIUM] `generate_report.py` 全部动态字段未 HTML 转义

**位置**：`scripts/generate_report.py`（`render_job_card` 与 `generate_html`）

**事实**：整个报告生成器**没有任何 `html.escape()` 调用**（已用 grep 确认 `html.escape` 零命中）。以下动态值被**原样插值**进 HTML：

- `render_job_card`：`title`(`:192,226,228,234`)、`advice`(`:189,253`)、`match_reasons` 各条 `r`(`:185`)、`risks` 各条 `r`(`:186`)、`meta_text`(`:198,243`)、`job_url`(`:194,226,241` 进 `href` 属性)、`job_id`(`:193,231,240` 进 `id` 属性)。
- `generate_html`：`role_type`(`:80,91`)、`direction_anchors` 各条 `a`(`:93`)、`direction_anchor`(`:138`) 等。

**影响**：
1. **正确性问题（真实会触发）**：真实 JD 文本常含 `<`、`&`、`"`（如 "C++ & Go"、"Java < 8 年"）。这些字符会破坏报告 HTML 结构，导致卡片错位/乱码。
2. **安全隐患（属性上下文）**：`job_url` 进 `href`、`job_id` 进 `id` 时若含 `"`，可造成属性注入；`title` 等进元素体时若含 `<script>` 可造成 XSS。**若报告未来被托管/分享，这是存储型 XSS 入口**。当前是本地自包含文件、用户自己打开浏览器，实际利用面较小，但不能假设永远如此。

**修复**：对元素体插值用 `import html; html.escape(value)`；对**属性上下文**（href、id）用 `html.escape(value, quote=True)`。建议抽一个 `_esc()` 辅助函数统一处理。

---

### 🟡 [LOW/DOC] `career_log.py` `query --company` 帮助文案与行为不符

**位置**：`scripts/career_log.py:511`

**事实**：
- 帮助文案写 `help="按公司名筛选（模糊匹配）"`，声称**模糊匹配**。
- 实际 `EventIndex.by_company` 是**精确** dict-key 查：`career_log.py:189` `self.by_company.get(company, [])`，`query` 走的也是精确键（`:187–189` 的 `pools.append(self.by_company.get(company, []))`）。
- 相较旧版（substring 模糊搜索）这是一次**行为回退**，但文案未同步更新，会造成用户困惑。

**修复（二选一）**：把帮助改回"精确匹配"；或实现真正的模糊匹配（如 `company in c` 或大小写归一）。推荐前者（精确匹配更可预期），并在升级说明里记录这次行为变更。

---

## 四、测试覆盖缺口（CRITICAL 漏网的根因）

- 197 个测试覆盖的是**单 stage / 单模块**：`test_cache.py`(T13)、`test_career_log_v2.py`(T14)、`test_fetch_feishu_resume.py`(T15)、`test_prompts_externalized.py`(T8) 等，`smart_score` 的测试只覆盖 `stage1`/`stage2` 单函数（且 eval 也只调单函数）。
- **没有任何测试组装并运行真实的 `run_pipeline` 端到端**（用 fake `LLMClient` 喂入假 jobs）。
- 结果：单函数契约正确，但 `run_pipeline` 里缺失的解包无人触发 → 必崩错误长期潜伏。

**建议新增测试**（修复后一并补）：`tests/test_run_pipeline_e2e.py`，用 fake client 跑完整 `run_pipeline`，断言：返回 dict 结构完整、`recommendations` 非空、`metadata.stage1_stats` 非零、`degraded` 正确反映失败。

---

## 五、已核查无误（非问题，列出以证审计完整）

- **T13 缓存 / llm_client**：`cache_key` 用 `sort_keys` 且对 messages 顺序敏感（顺序对 LLM 语义有意义，正确）；`get/put/clear/stats`、TTL、`os.replace` 原子写、测试断言均严格，无 bug。
- **T14 其余逻辑**：事件信封（UUID4/session/expires_at）、`EVENT_SCHEMAS` 校验、`EventIndex` 的 `id()` 交集多条件查询、`trace/expire` CLI 均正确，仅 `--company` 文案问题（见上）。
- **T15 飞书续爬**：`fetch_with_retry`（指数退避+抖动，耗尽返回 None）、`FeishuCheckpoint` 往返、`_drive_crawl` 的"重叠一页 + 主键去重"续爬逻辑健壮，无丢岗位、无死循环；UA 读取（顶层/feishu/默认回退）正确。
- **T8 提示词外置**：`config/prompts.yaml` 与 `scripts/smart_score.py` 内 `_DEFAULT_PROMPTS` 的 4 个 key 完全一致，零漂移。
- **pre_filter / post_judge / trace**：方向分、英语硬门槛、熔断、英语/核心团队/技术依赖惩罚、分布约束、trace JSONL、cost 定价逻辑均健全。

---

## 六、待办与下一步

| 项 | 状态 | 说明 |
|----|------|------|
| 修复 CRITICAL（run_pipeline 解包） | ✅ 已修 | 见第七节 |
| 修复 MEDIUM（report HTML 转义） | ✅ 已修 | 见第七节 |
| 修复 LOW（career_log 文案） | ✅ 已修 | 见第七节 |
| 补测试覆盖缺口（根因） | ✅ 已补 | 见第七节 |
| **Git commit** | ⏳ 待执行 | 本会话 shell 不可用，无法 `git commit`；需本地或下次会话执行 |
| **GitHub push** | **仍待你确认** | 最新 commit `45360a8`，修复尚未提交/推送 |
| `notes/upgrade-plan-reconciliation.md` 已过时 | 非 bug | 记录的是 T1–T15 之前的状态，建议标注/归档，避免误读为当前现状 |

## 七、修复记录（用户指令「全部修复」，2026-07-22）

| 项 | 改动文件 | 具体修改 |
|----|----------|----------|
| CRITICAL — run_pipeline 解包 | `scripts/smart_score.py:1054` | `all_scored = await stage1(...)` → `all_scored, stage1_stats = await stage1(...)`（同时修复了 stage1_stats 恒为 None 导致统计全 0 / degraded 失真） |
| MEDIUM — report HTML 转义 | `scripts/generate_report.py` | 新增 `import html` + `_esc()` 辅助；`render_job_card` 的 title/advice/match_reasons/risks/meta_text/job_url(进 href)/job_id(进 id)/定位/英语标签，及 `generate_html` 的 role_type/direction_anchor/模型名/页脚 全部套 `_esc`（属性上下文 `quote=True`） |
| LOW — career_log 文案 | `scripts/career_log.py:511` | `query --company` 帮助「模糊匹配」→「按公司名精确筛选（需与记录中的公司名完全一致）」，与 `EventIndex.by_company` 精确 dict-key 查行为一致 |
| 测试覆盖缺口（根因） | `tests/test_run_pipeline_e2e.py`（新增） | 用 fake stage1/stage2/calibration/rerank 跑**真实 run_pipeline**，断言结构完整、`metadata.stage1_stats` 被捕获（非全 0）、推荐非空、输出落盘——直接守住解包回归 |
| 同上 | `tests/test_generate_report.py`（新增） | 断言 JD 含 `<` `&` `"` 时报告无裸 `<script>`、属性上下文无引号注入（XSS 防护） |

**验证说明（重要）**：修复经本会话**真实跑测**确认（shell 中途恢复可用）：
- 用项目 `.venv`（pytest 9.1.1 / openai 2.46.0）执行 `pytest tests/` → **200 passed in 18.84s**（197 既有 + 3 新增回归测试），证明三处修复生效、`test_run_pipeline_e2e.py` 能守住解包回归。
- `smart_score.py:1054` 已解包；`generate_report.py` 全部动态插值已转义；`career_log.py:511` 文案已改。
- 已提交：`5d7c6c1`「fix: 审计发现的 3 处 bug…」，**6 文件 / 405 增 19 删**（3 脚本修复 + 2 测试 + 本审计报告）。CRLF 警告仅为换行符归一化，无碍。

**状态**：修复已落地并 commit（未 push，远程推送待你点头）。本文件为权威审计记录。
