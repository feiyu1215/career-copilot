# FILE_GUIDE.md — Career Copilot 文件详细说明

> 本文档为开发者视角的完整文件手册，记录每个文件的**职责定位、核心逻辑、依赖关系、输入/输出、与其他文件的协作方式**。
> 适用于：开发调试、架构理解、新贡献者 onboarding。

---

## 根目录文件

### `SKILL.md`

**职责**：Skill 主定义文件——CatDesk 框架通过此文件识别和加载 Career Copilot。

**核心内容**：
- 触发词列表（"帮我匹配岗位"、"smart score"、"对比 offer" 等）
- 五大意图路由（匹配 / 面试 / 简历 / 记忆 / 引导）+ 五大能力模式（对齐 / 规划 / 调研 / 研判 / 交接，自然语言触发、非命令）
- 执行约束（半自治 agent 模式、关键决策暂停点、并行 agent 调度）
- 各模块调用的具体 reference 文件和 script 指引
- 设计哲学与防护栏
- **身份设定**：`## 身份设定（你是谁）` 段声明 skill 角色边界，并要求与 `references/chatgpt-lite.md` 的「你是谁」保持口径一致（改一处同步另一处，防身份漂移）

**与其他文件的关系**：
- 路由到 `references/` 下各 guide 获取方法论
- 指引执行 `scripts/` 下各脚本完成实际计算
- 是整个 Skill 的"入口 + 路由表 + 约束集"

---

### `SKILL.md`「## 安装」与 `README.md`（运行时以 SKILL.md 为准）

> 按 Skill 编写规范，skill 运行时以 `SKILL.md` 为准，不依赖 README.md；原 README 的「快速开始 / LLM Provider 配置 / 目录结构 / 设计哲学 / License」已全部并入 `SKILL.md` 末尾「## 安装」段。
> 但本仓库**刻意保留 `README.md` 作为 GitHub 仓库入口**（对外浏览 / 发现用），与 `SKILL.md` 尽量保持同步——它不参与 skill 运行时加载。

**与其他文件的关系**：`SKILL.md` 是 Skill 主定义与入口（详见上方 `### SKILL.md` 条）；安装与配置说明统一在 `SKILL.md`「## 安装」+ 本目录 `.env.example`。

---

### `requirements.txt`

**职责**：Python 依赖声明。

**依赖列表**（以 `requirements.txt` 为准）：`openai`（LLM 调用，lazy import）、`pypdf`（PDF 简历解析，脚本内 try 多库回退）、`pytest`（测试框架）。

> 注：早期版本文档曾列 `httpx`/`python-dotenv`/`pdfplumber`/`tiktoken`，经核对代码未实际使用，已从依赖声明中移除。

---

### `.env.example`

**职责**：环境变量模板，指引用户配置双 Provider。

**关键变量**：

| 变量 | 用途 |
|------|------|
| `LLM_PROVIDER` | 默认 Provider 选择（`friday` / `sub2api` / `nvidia`） |
| `LLM_BASE_URL` | friday Provider 的 API 端点 |
| `FRIDAY_APP_ID` | friday 认证凭据 |
| `SUB2API_BASE_URL` | sub2api Provider 的 API 端点 |
| `SUB2API_API_KEY` | sub2api API 密钥 |

---

### `.gitignore`

**职责**：Git 忽略规则。排除 `.env`、`__pycache__`、`.pytest_cache`、输出文件（`*.json` 结果、`*.html` 报告）等。

---

### `LICENSE`

**职责**：GPL-3.0 开源许可证全文。

---

## `config/` — 配置层

### `config/pipeline.yaml`

**职责**：评分 pipeline 的全部数值参数，与 `smart_score.py` 的 `load_config()` 默认值一一对应。YAML 缺失时代码默认值兜底，零回归。

**关键段**：
- `stage1`：模型、batch_size、max_concurrent、truncation_chars、circuit_breaker_threshold、circuit_min_samples
- `stage1_5_calibration`：模型、top_k
- `stage2`：模型、group_size、truncation_chars、max_concurrent、**top_score_low / top_score_high / bottom_cap**（精排分数带，注入 prompt 模板）
- `stage2_5_rerank`：模型、layer_threshold
- `output`：**score_high / score_mid_high / score_mid / score_low**（全局分数带，注入重排 prompt 模板）
- `post_judge`：英语/核心团队/技术依赖惩罚阈值、A 档比例上限

### `config/prompts.yaml`

**职责**：所有 LLM prompt 模板的外部化管理。与 `smart_score.py` 的 `_DEFAULT_PROMPTS` 内联兜底保持同步（key 相同则 YAML 生效）。

**模板列表**：`stage1_system`、`stage2_system`、`calibration_system`、`global_rerank_system`

**参数化**：模板中的分数带使用 `{placeholder}` 变量（如 `{rerank_top_score}`、`{stage2_top_low}`），由 `build_stage2_system()` / `_build_rerank_system()` 在调用时从 `PIPELINE_CFG` 注入。JSON 示例中的花括号用 `{{}}` 转义。

---

## `scripts/` — 核心执行层

所有脚本均可独立命令行运行（`python3 scripts/xxx.py --help`），也可被 CatDesk Agent 以工具形式调用。

### `scripts/llm_client.py`

**职责**：共享 LLM 客户端，封装多 Provider（friday / sub2api / nvidia / agnes）调用逻辑，带并发控制、智能重试与 Provider 级 failover。

**核心逻辑**：
- `PROVIDERS` 注册表：每个 Provider 含 `base_url` / `api_key` / `default_model` / `available_models`
- `get_provider_config(provider=None)` → 按显式参数或 `LLM_PROVIDER` 环境变量解析 Provider 配置
- **Failover 机制**：`FAILOVER_CHAIN`（默认 `friday,sub2api,nvidia,agnes`，可通过 `LLM_FAILOVER_CHAIN` 环境变量覆盖）+ `PROVIDER_COOLDOWN_SECONDS`（默认 60s）。主 Provider 重试耗尽后自动冷却并沿链路尝试下一个 Provider（`_failover_chat` / `_failover_chat_raw`）
- `class LLMClient`：异步客户端，底层用 `openai.AsyncOpenAI`
  - `__init__(model=None, max_concurrent=5, provider=None, timeout=120)`
  - `await chat(system=, user=, temperature=0.0, max_tokens=, retries=5) -> str`：统一调用入口，自动处理重试 + failover
  - `await chat_raw(messages=, ...) -> response`：原始响应（需访问元数据时用）
  - `stats() -> {provider, model, total_calls, total_input_tokens, total_output_tokens}`
- 重试策略区分错误类型：`AuthenticationError` / `NotFoundError` 不重试；`APITimeoutError` 快速重试（2s）；`RateLimitError` 尊重 `retry-after`；其余指数退避

**被谁依赖**：`smart_score.py`、`gen_profile.py`、`assess_competitiveness.py`、`diff_watch.py`、`career_log.py`——所有需要 LLM 能力的脚本。

---

### `scripts/check_env.py`

**职责**：环境健康检测，一键验证"能否跑通"。

**检测项**：
1. Python 版本 ≥ 3.9
2. 所有 pip 依赖已安装
3. `.env` 文件存在且关键变量非空
4. LLM API 端点网络连通性（HTTP HEAD 探测）
5. API Key 有效性（尝试简单 completion 调用）

**输出**：彩色终端报告，逐项 ✓/✗，最终给出 PASS/FAIL。

**使用场景**：初次配置后运行、排查调用失败、CI 前置检测。

---

### `scripts/gen_profile.py`

**职责**：从简历 PDF 生成结构化"能力边界画像"（Boundary Profile）。

**输入**：`--resume <pdf_path>`（简历 PDF 文件）
**输出**：`--output <json_path>`（默认 `./boundary_profile.json`）

**核心逻辑**：
1. 使用 `PyPDF2 → pdfminer.six → pypdf` 多库回退提取简历全文（requirements.txt 已声明 `pypdf`，详见 line 42 说明）
2. 调用 LLM 进行结构化抽取：技术栈、行业经验、职级信号、核心优势、能力天花板
3. 输出 JSON 包含：`tech_stack[]`、`industries[]`、`level_signals`、`strengths[]`、`ceiling_risks[]`、`raw_text`

**被谁使用**：`smart_score.py`（作为 `--profile` 输入）、SKILL.md 路由的"能力边界探索"流程。

---

### `scripts/fetch_jobs.py`

**职责**：批量抓取招聘网站 JD。

**输入**：`--base-url <url>`（招聘列表页 URL）、`--total-pages <n>`（翻页上限，默认 60）
**输出**：`--output <txt_path>`（原始 JD 文本，每条以分隔符隔开）

**核心逻辑**：
- 通过 `catdesk-browser` 子进程驱动浏览器抓取页面（无 httpx 依赖；登录态页面由 CatDesk 浏览器自动化配合）
- 支持分页参数自动递增
- 提取 JD 正文（标题、公司、要求、描述）
- 无头浏览器依赖——纯 HTTP 抓取，适配主流招聘平台 URL 模式

**注意**：实际使用时多由 CatDesk 浏览器自动化配合完成登录态页面。

---

### `scripts/fetch_jobs_feishu.py`

**职责**：抓取飞书 ATS 类招聘站点的 JD（`*.jobs.feishu.cn`，如蔚来 `nio.jobs.feishu.cn`）。与 `fetch_jobs.py` **并列共存、互不影响**——`fetch_jobs.py` 走 catdesk-browser 路线，`fetch_jobs_feishu.py` 走 Playwright 拦截路线，两者输出同一份 `JOB_MATCHER_FORMAT v1`，下游 `smart_score` / `diff_watch` 零改动消费。

**为什么需要它**：飞书 ATS 是 SPA + 前端签名 API（请求带 JS 计算的 `_signature`），`catdesk-browser` + CSS 选择器拿不到完整 JD。本脚本用 Playwright 拦截 `/api/v1/search/job/posts` 与 `/api/v1/job/posts/{id}`，复用浏览器会话的签名 / Cookie 直接拿 JSON。

**输入**：`--url <url>`（飞书 ATS 列表页链接，保留 `project` / `functionCategory` 等过滤参数）
**输出**：`--output <txt_path>`（标准 `JOB_MATCHER_FORMAT v1` 原始 JD 文本）

**核心逻辑**：
- 翻页用 `current` 参数（非 `offset`，后者被 SPA 忽略会重复首页），`limit=200`，某页 `<limit` 即停
- 抓详情前重导航列表页刷新 `_signature` 防过期；失败退回列表 `description` 不阻塞
- 依赖：`pip install playwright && playwright install chromium`

**维护细节**：接口规律、字段名兜底、踩坑与故障排查见 `notes/feishu-ats-crawler.md`。

---

### `scripts/smart_score.py`

**职责**：六阶段评分 pipeline 主控脚本——项目的核心算法。

**输入**：
- `--jobs <txt_path>`（JD 列表文件）
- `--profile <json_path>`（能力画像）
- `--summary <txt_path>`（候选人一句话摘要，用于 LLM prompt）
- `--provider`（可选，覆盖默认 Provider）

**输出**：`--output <json_path>`（评分结果，含 A/B/C 分档）

**配置外部化**：
- `config/pipeline.yaml`：各阶段模型、并发数、截断长度、熔断阈值、分数带（`output.score_high/mid/low`、`stage2.top_score_low/high/bottom_cap`）等数值参数。代码内有完整默认值兜底（`load_config()`），YAML 缺失时零回归
- `config/prompts.yaml`：所有 LLM prompt 模板（stage1/stage2/calibration/global_rerank），用 `{placeholder}` 变量在调用时由 `PIPELINE_CFG` 注入分数带参数。`_DEFAULT_PROMPTS` 内联兜底与 YAML 保持同步

**六阶段流程**：

| 阶段 | 名称 | 方法 | 模型 |
|------|------|------|------|
| 1 | 粗筛 Coarse Screen | LLM pointwise 打分 | 便宜模型（如 GPT-4o-mini） |
| 1.5 | 校准 Calibration | 辨别知识生成 | 强模型 |
| 2 | 精排 Fine Rank | LLM listwise 对比排序 | 强模型（如 GPT-4.1-mini） |
| 2.5 | 全局重排 Re-rank | 跨组全局排序（`_build_rerank_system()` 动态注入分数带） | 强模型 |
| 5 | 后处理 Post-process | 确定性规则约束（`post_judge.py`，配置由 `PIPELINE_CFG["post_judge"]` 注入） | 代码 |
| 6 | 验证 Verify | 12 项回归断言 | `verify_output.py` |

**熔断器**：Stage 1 使用 `processed_failure_rate`（已处理样本的失败率，而非全量失败率）判断是否中止 pipeline，避免小批量失败被大分母稀释。

**内部调用链**：`pre_filter.py`（阶段 1 前的确定性预过滤） → `llm_client.py`（LLM 调用） → `post_judge.py`（阶段 5）→ `verify_output.py`（阶段 6）

---

### `scripts/pre_filter.py`

**职责**：确定性预过滤——在 LLM 介入前用规则剔除明显不匹配的 JD。

**过滤规则**：
- 学历硬性不匹配（如要求博士但画像为本科）
- 工作年限不达标
- 语言要求不满足（如要求日语/德语）
- 地域完全不匹配（当用户设定了地域约束时）

**被谁调用**：`smart_score.py` 的阶段 1 之前。

**单测**：`tests/test_pre_filter.py`

---

### `scripts/post_judge.py`

**职责**：确定性后处理——LLM 打分后的规则兜底。

**配置外部化**：所有惩罚阈值（英语 cap、核心团队 cap、技术依赖 penalty、A 档比例上限等）集中在 `DEFAULT_CONFIG` 字典中，`post_judge(analyzed_jobs, profile, config=None)` 接受可选 `config` 参数（由 `smart_score.py` 传入 `PIPELINE_CFG["post_judge"]`），与 `config/pipeline.yaml` 的 `post_judge` 段对齐。

**后处理规则**：
- 英语要求校验（JD 要求英语流利但画像无英语信号 → 降级）
- 核心团队 + 学历交叉约束（`detect_core_team` + `education_tier` → cap）
- 技术栈依赖惩罚（JD 强技术但候选人无技术信号 → 扣分）
- A 档分布强制（`enforce_distribution`；比例由 `config/constraints.yaml` → `a_tier_cap.max_ratio` 决定，当前 25%）

**被谁调用**：`smart_score.py` 的阶段 5。

**单测**：`tests/test_post_judge.py`

---

### `scripts/verify_output.py`

**职责**：输出验证——12 项回归断言检查。

**检查项包括**：
- JSON 结构完整性（必须有 `results[]`、每项有 `score`/`tier`/`risks`）
- 分数范围合法（0-100）
- 分档一致性（A ≥ 80, B ≥ 60, C < 60）
- 无重复 JD ID
- risks 非空时必须有具体描述
- A 档数量不超过总数 25%（= `max(min_floor, int(total*max_ratio))`，比例由 `config/constraints.yaml` → `a_tier_cap` 定义，与 post_judge.enforce_distribution 完全一致；防止"全好"bug）

**使用方式**：可独立运行 `python3 scripts/verify_output.py --input results.json`，也被 `smart_score.py` 内部自动调用。

---

### `scripts/verify_lens.py`

**职责**：对白 transcript 的**软契约（lens）确定性检查**——补齐 `verify_output.py` 的盲区。`verify_output` 检 pipeline 的 `scored_results.json`（结构化产物），本脚本检**对话回合**里的软契约（①③④：前提来源标注 / 单源红线 / Over-Claim 镜面），这些契约发生在对白中，不进 `scored_results.json`。

**设计原则（对齐 `notes/addition-criteria.md`）**：
- 只做**标签存在性**检查，绝不用正则判断「断言是否真的推测」（判断留给人/prompt）
- 默认 WARNING 模式（非阻断，保灵活性）；`--strict` 时 WARNING 升级为失败（可作门禁）
- 显式暴露（契合「隐蔽 fallback 更危险」）

**输入**：JSONL，每行 `{"role":"agent"|"user","text":"..."}`；仅检查 `role=="agent"` 回合。

**三条检查（warning 码）**：
- `[LENS-W1]` 强断言（高度匹配/必中/稳了…）缺来源标签 `[事实]/[推测]/[脑补]/[来源]`
- `[LENS-W2]` 对外简历硬数字（`50%`/`3 年`…）缺 `[事实]` 标注（单源红线）
- `[LENS-W3]` 绝对化保证（绝对/一定/guaranteed…）缺来源标签（Over-Claim 镜面）

**使用方式**：`python3 scripts/verify_lens.py --input transcript.jsonl [--strict]`。对抗 fixture：`tests/fixtures/lens_adversarial.jsonl`。单测：`tests/test_verify_lens.py`。

**当前范围**：离线扫 transcript。采集 enabler 已就绪——`evals/collect_transcript.py` 的 `collect_session()` 可程序化落盘 + SKILL.md session-end 已加可选授权采集入口；数据积累后由 `blind_eval_runner.py --live` 跑真实盲评（见上方 `evals/` 段）。

---

### `scripts/generate_report.py`

**职责**：从评分结果 JSON 生成可交互的 HTML 报告。

**输入**：`--input <json_path>`（scored_results.json）
**输出**：`--output <html_path>`（默认 `./report.html`）

**报告内容**：
- 概览统计（总数、各档数量、Top 5 推荐）
- 按 Tier 分组的岗位卡片（含公司、岗位、分数、核心匹配点、风险点）
- 可折叠的详细评分理由
- 筛选/排序交互
- 纯前端实现，单文件 HTML，无外部依赖

---

### `scripts/assess_competitiveness.py`

**职责**：投递难度评估——分析某个具体岗位的竞争激烈程度。

**核心逻辑**：
- 综合分析 JD 要求、公司层级、岗位热度信号
- 评估候选人在该岗位竞争池中的相对位置
- 输出：竞争力评级（Easy/Medium/Hard/Extreme）+ 关键竞争维度分析

---

### `scripts/diff_watch.py`

**职责**：增量监测——检测招聘页面的新增/下架岗位。

**核心逻辑**：
- 对比两次抓取结果的 diff
- 识别新增岗位、已下架岗位、描述变更岗位
- 可配合定时运行实现"订阅式"监测
- 新增岗位自动触发 smart_score 评分

---

### `scripts/career_log.py`

**职责**：职业记忆管理——JSONL 事件日志系统。

**核心功能**：
- `log_event(event_type, data)` → 追加事件到 `~/.career-copilot/events.jsonl`
- `get_timeline(filter)` → 检索历史事件（按类型/时间范围/关键词）
- `build_snapshot()` → 从事件流聚合生成当前画像快照
- 支持事件类型：`match_run`、`resume_update`、`interview_feedback`、`offer_received`、`preference_change`

**设计思想**：Event Sourcing 模式——只追加不修改，快照从事件流重建。

---

### `scripts/cache.py`

**职责**：LLM 语义缓存（T13）——跨 run 复用 LLM 响应，降低调用成本、提升响应速度。

**核心逻辑**：
- 基于请求指纹（system + user + model + 参数）的语义相似命中，命中即返回缓存结果
- 缓存落盘 `.cache/`，受 `.gitignore` 管控

---

### `scripts/log_utils.py`

**职责**：结构化日志工具——统一 JSON 日志格式，供 trace / 调试链路消费。

---

### `scripts/provider_chain.py`

**职责**：Provider 自动降级链——封装 friday / sub2api / nvidia / agnes 的 failover 顺序与冷却（对应 `docs/adr/ADR-002-llm-client-failover.md`），被 `llm_client.py` 调用。

---

### `scripts/report_assets.py`

**职责**：report 静态资源——生成 HTML 报告用的内联 CSS / JS，从 `generate_report.py` 抽出的展示层。

---

### `scripts/trace.py`

**职责**：执行 Trace——记录 pipeline 各阶段耗时与 LLM 调用，用于性能分析与回归诊断。

---

### `scripts/config_loader.py`

**职责**：加载 `config/constraints.yaml`——skill 关键确定性约束（A 档比例 `a_tier_cap`、C9 生效判定 `post_judge_check`）的单一事实源加载器，供 `verify_output.py` / `post_judge.py` 引用，消除代码/文档/测试三处同源漂移。依赖 PyYAML（`pip install pyyaml`）。

---

### `scripts/check_notes_freshness.py`

**职责**：扫描 `notes/*.md` 头部的 `last_reviewed` 评审标记，超过 `review_cycle_days` 自动列为「待复核」；`--strict` 时存在过期/缺失返回退出码 1，可作 CI / pre-commit 门禁。详见下方 `notes/` 评审新鲜度规则。

---

### `scripts/` 新增脚本速览（v2 以来新增，无独立 prose）

> 以下 25 个脚本在初版 FILE_GUIDE 之后加入，统一以「一行职责」速览，避免正文膨胀。详细 bus-factor 见上方 `### `scripts/`（46 个）` 表。Owner 均为闫飞宇，最后核实 2026-07-30。

| 文件 | 一行职责 |
|------|---------|
| `batch_fetch.py` | N2 多 portal 批处理 Orchestrator（统一调度各门户后端） |
| `behavior_fit.py` | 行为风格 × JD 要求 拟合评分（确定性，纯 stdlib，零网络） |
| `build_cv.py` | 把 drafter_reviewer 产出的 LaTeX 草稿编译为可投递 PDF，并跑 ATS 校验闭环 |
| `build_cv_docx.py` | 非 LaTeX 降级：用 python-docx 从结构化草稿生成 .docx 简历 |
| `build_upskill_brief.py` | 方向性缺口 / 升级概览生成器（refined upskill） |
| `calibration_feedback.py` | 投递结果反馈 → 评分校准（Phase 6.1） |
| `competitiveness_tracker.py` | Phase 8.2 竞争力动态评估（纯本地、零 LLM 确定性内核 + 可选增强） |
| `drafter_reviewer.py` | Tier2 简历 Drafter-Reviewer 双轨评审 |
| `fetch_boss.py` | BOSS 直聘岗位抓取（薄封装 + 可插拔后端） |
| `fetch_jobs_linkedin.py` | LinkedIn 多门户后端 |
| `fetch_jobs_nowcoder.py` | 牛客网（校招/社招）多门户后端 |
| `fetch_jobs_shixiseng.py` | 实习僧（实习岗）多门户后端 |
| `first_seen.py` | Phase 8.3 智能投递时机建议（first_seen 追踪 + 时机建议） |
| `jd_guard.py` | JD 信任边界（不可信数据） |
| `job_common.py` | 多门户抓取的共享逻辑（纯 stdlib，离线可测） |
| `job_tracker.py` | 申请/结果生命周期闭环 + 反馈回路 |
| `manage_template.py` | U6 简历/求职信 LaTeX 模板注册（外观定制，非替人决策） |
| `notify_wecom.py` | 企业微信群机器人推送（纯 stdlib，零第三方依赖） |
| `relevance_trim.py` | 简历超页时「按相关性而非按时间」裁页 |
| `run_pipeline.py` | 2.1 端到端求职编排器（体验质变点） |
| `setup_wizard.py` | 交互式建档引导（Phase 5.1） |
| `trend_analyzer.py` | 岗位市场趋势感知（Phase 8.1，纯本地、零 LLM） |
| `verify_ats.py` | 简历 PDF 的 ATS 文本层与硬性不变量检查 |
| `verify_fetch_quality.py` | 抓取结果质量守门（Phase 4.3）的契约化校验 CLI |
| `visual_inspect.py` | 编译后「逐页看 PDF」的确定性视觉巡检 + 源码级防孤行 |

---

## `evals/` — 评测脚手架

复用 `scripts/llm_client.py` 的真实 LLM Provider，对 Skill 的「契约遵循度」做可量化评测。所有结果 JSON（`eval_results_dynamic*.json`）已 `.gitignore`，不进版本库。

### `evals/eval_env.py`

**职责**：共享 `.env` 加载器（2026-07-22 由 3 处重复逻辑抽出）。统一 scholar `.env` 的硬编码路径问题与 provider 名映射。

**关键 API**：
- `load_dotenv_like(path, mapping=None)`：overwrite 语义注入（`os.environ[k]=v`），支持 `mapping`（scholar→friday 名映射）与缺文件静默 noop
- `scholar_dotenv_path()`：返回 `SCHOLAR_DOTENV` env 或默认开发机路径
- `load_provider_env()`：`load_dotenv_like(".env")` + scholar `.env` 映射注入

**被谁调用**：`run_dynamic_eval.py` / `judge_ab_probe.py` / `blind_eval_runner.py`。

---

### `evals/run_dynamic_eval.py`

**职责**：LLM-judge 动态评测 harness——用真实 LLM 跑 `evals.json` 的 contract_adherence 用例并判分。

**核心逻辑**：
- `EVAL_PROVIDER`（agnes/nvidia/friday/sub2api）切换；模型名 fallback 到 `PROVIDERS[provider]["default_model"]`（修复硬编码默认导致的 404）
- `GEN_MODEL`/`JUDGE_MODEL` 经 `JUDGE_SYS` 按 G1 细则判分（带标签概率化估计不算 over-claim）
- `compute_summary(results)` 纯函数：核心用例计硬门槛，known_variance 不计入但要求 judge 跨 run 稳定
- `EVAL_REPEAT` / `EVAL_NULL_RETRIES` 支持重跑与瞬态空响应重试；`try/except` 兜底单 case 失败不中断整跑
- `gate`：`[gate] core=N/M → PASS/FAIL`，`main()` 末尾 `sys.exit(0 if gate=="PASS" else 1)`

**使用方式**：`EVAL_PROVIDER=agnes uv run --with openai python evals/run_dynamic_eval.py`；`Makefile` 封装 `make eval` / `make eval-skip`。

**单测**：`tests/test_eval_gate.py`。

---

### `evals/run_ablation.py`

**职责**：before/after 合成提示消融——隔离「契约指令」对合规行为的因果贡献。

**核心逻辑**：复用 `run_dynamic_eval` 的 `SYSTEM_REFS`/`JUDGE_SYS`/`run_one`；`before`=裸顾问（移除 4 契约指令），`after`=SKILL.md+3 references；agnes repeat=2，本地 `run_one` 带 `EVAL_NULL_RETRIES`+退避。

**输出**：`evals/before_after_contrast.json` + `notes/before_after_contrast_report.md`。

---

### `evals/judge_ab_probe.py`

**职责**：judge 前后对比探针——同一份输出用 G1 前(OLD)/后(NEW) `JUDGE_SYS` 判分，排除「judge 误伤」。

**使用方式**：`uv run --with openai python evals/judge_ab_probe.py`。

---

### `evals/blind_eval_runner.py`

**职责**：P2-3 路径1 盲评 runner——对真实/合成 transcript 做 D1–D6 维度盲评（去同源偏差）。

**两种模式**：
- `--demo`：内置合成 transcript + stub judge，证明整条 pipeline 接线，**不烧 API**，报告 `EVIDENCE_TIER=SYNTHETIC-MECHANISM`
- `--live`：读 `evals/transcripts/` 下 before/after，调 LLM-judge（需 `uv run --with openai` + 真实数据），报告 `EVIDENCE_TIER=LLM-REAL`

**依赖**：`_PROVIDER_ENV` 按 provider 取正确 env 名（friday→`FRIDAY_APP_ID`/`LLM_BASE_URL`）；`--live` 需 `openai` 依赖（缺则清晰报错而非静默全 0）。

**单测**：`tests/test_proxy_eval.py` / `tests/test_blind_eval_provider_env.py`。

---

### `evals/collect_transcript.py`

**职责**：生产 transcript 采集 enabler——让盲评数据可程序化积累（真实跑分的前置）。

**关键 API**：`collect_session(turns, *, phase, before_or_after, model, session_id, redact, out_root)` → `(out_path, record, n_redacted)`；自动脱敏（复用 `career_log.SENSITIVE_PATTERNS`）+ 掩 `before_or_after` 标签防 B2 同源偏差；落盘 `evals/transcripts/<phase>/<before|after>/<session_id>.jsonl`（已 `.gitignore`）。

**使用方式**：`main()` 重构复用 `collect_session` 并支持 `--out-root`；SKILL.md session-end 已加可选授权采集入口。

**单测**：`tests/test_collect_transcript.py`。

---

### `evals/proxy_eval_lib.py`

**职责**：盲评纯函数库（被 `blind_eval_runner.py` 调用）。

**关键 API**：`redact_text` / `build_record` / `mask_label` / `aggregate_score`（D1–D6→0–12，resume 六维求和、其他 phase 五维归一）。

**单测**：`tests/test_proxy_eval.py`。

---

### `evals/`（结果文件）

- `eval_results_dynamic.json` / `_agnes` / `_nvidia` / `_contrast`：各 provider 动态评测结果（gitignored）
- `proxy-quality-eval-report.md`：盲评演练报告（LLM-REAL，绑定「演练声明」边界：数据源=eval after 组、非生产真实用户对话、无 before 组故无 Δ）

---

### `Makefile`

**职责**：常用命令封装。

- `make test`：跑全量 `pytest`
- `make eval`：agnes + repeat=2 真实评测（best-effort 信号，不稳时会红暴露真实方差）
- `make eval-skip`：CI 用 advisory 接入（`EVAL_SKIP_ON_ERROR=1`，不阻断流水线）

> 当前全量测试：**200 passed**（截至 2026-07-23；基线 105 → +24 bug-review → +71 T1-T15 升级）。

---

## `references/` — 方法论层

Agent 执行任务时参考的知识文档，LLM 通过读取这些文件获取领域知识。

### `references/matching-guide.md`

**职责**：岗位匹配 Pipeline 完整执行指南。

**内容**：
- 六阶段 pipeline 的详细执行规范
- 每个阶段的 prompt 模板、评分维度、阈值设定
- Listwise 对比排序的具体方法
- 行业知识注入点：哪些行业/岗位有特殊评估规则
- 异常处理指南（JD 信息不完整、画像信息不足时的降级策略）
- Provider 选择策略（粗筛用便宜模型，精排用强模型）

---

### `references/interview-prep.md`

**职责**：面试准备方法论。

**内容**：
- 从 JD + 匹配 risks 逆向推导面试考点的方法
- 技术面准备框架（按深度/广度/项目经验三维度）
- 行为面 STAR 模板与常见坑
- "向面试官提问"清单生成规则
- 面试复盘模板

---

### `references/resume-guide.md`

**职责**：简历定向优化框架。

**内容**：
- 区分"表述问题"（可改善）vs "能力缺失"（需坦诚面对）
- STAR 重写方法论
- 量化指标注入策略
- 针对不同岗位类型的简历侧重点
- ATS（Applicant Tracking System）关键词优化

---

### `references/career-memory.md`

**职责**：跨会话记忆系统规范。

**内容**：
- JSONL 事件日志格式定义
- 事件类型枚举与 schema
- 画像快照结构与重建算法
- 记忆检索策略（何时该调取历史、何时该忽略）
- 遗忘机制（过期事件的处理策略）

---

### `references/onboarding-guide.md`

**职责**：冷启动引导——方向不明确时的探索流程。

**内容**：
- "我不知道想做什么"场景的引导框架
- 能力边界探索问卷
- 行业/职能交叉分析方法
- 从过往经历提取核心竞争力
- 渐进式聚焦（从宽到窄的方向定位流程）

---

### `references/evolution-log.md`

**职责**：Skill 演化日志，记录版本迭代与用户偏好。

**内容**：
- 各版本的变更记录（新增功能、算法调整、bug 修复）
- 用户反馈沉淀（哪些设计受好评、哪些被吐槽）
- 待优化项目 backlog
- 评测指标趋势

---

### `references/chatgpt-lite.md`

**职责**：运行时无关的可粘贴精简段——把 SKILL.md 的 4 条核心契约（前提来源标注 / 单源外部红线 / 改稿熔断 / Over-Claim 镜面）+ lens 不分回合规则抽出，供手动粘贴到任意 LLM（如 ChatGPT）做轻量求职咨询。

**内容**：
- 4 条核心契约的精简 prompt 形态（带 `[事实]/[推测]/[脑补]` 标签规则、单源红线、>60% 熔断前置声明、Over-Claim 镜面含确定性终审禁区）
- lens 不分回合（澄清 / 延后 / 索要资料回合也要套）
- 红线（不编造 / 不替代决策 / 不确定必说）

**诚实标签**：文件顶部强制声明「**无机制保证**」——只有 prompt 级约束，无 verify 脚本校验，弱模型可能失效，且缺失 fetch_jobs / smart_score / 简历改写等全部 scripts 能力。**不与主 skill 路由体系耦合，仅作分发用**。

---

### `references/` 新增速览（v2 以来新增，无独立 prose）

> 以下 8 个 reference 在初版 FILE_GUIDE 之后加入。详细 bus-factor 见上方 `### `references/`（22 个）` 表。Owner 均为闫飞宇，最后核实 2026-07-30。

| 文件 | 一行职责 |
|------|---------|
| `behavioral-profile.md` | 行为画像（Behavioral Profile）方法论 |
| `boss-fetch.md` | BOSS 直聘抓取约定（fetch_boss.py） |
| `jd-trust-boundary.md` | JD 信任边界（不可信数据） |
| `job-fetch.md` | 多门户抓取编排（job-fetch） |
| `job-tracker.md` | Job Tracker（P5）规范 |
| `interview-done-template.md` | Interview Done — 面试结果事件模板 |
| `resource-index.md` | 本地资源索引（owner 自管，未联网） |
| `setup-guide.md` | 建档引导流程（Setup Guide） |

---

## `examples/` — 示例数据

### `examples/boundary_profile_example.json`

**职责**：`gen_profile.py` 的输出示例。

**结构**：展示一个完整的能力边界画像 JSON，包含 `tech_stack`、`industries`、`level_signals`、`strengths`、`ceiling_risks` 等字段，方便理解数据格式。

---

### `examples/scored_results_example.json`

**职责**：`smart_score.py` 的输出示例。

**结构**：展示评分结果 JSON，每个岗位包含 `job_id`、`title`、`company`、`score`、`tier`（A/B/C）、`match_points[]`、`risks[]`、`reasoning` 等字段。

---

## `evals/` — 评测体系

### `evals/evals.json`

**职责**：Skill 评测用例集（14 条：2 application_scenario + 1 variation_scenario + 4 edge_case + 3 negative_trigger + 4 contract_adherence），用于 CatDesk Desk Review 自动评测。

**结构**：每条包含 `input`（模拟用户输入）、`expected_behavior`（期望行为描述）、`criteria`（评分维度）。

---

### `evals/eval_results.json`

**职责**：Desk Review 评测运行结果。

**内容**：10 条用例的逐条评分、通过/失败状态、评审意见。

---

### `evals/skilllens_report.md`

**职责**：SkillLens Deep Review 深度评审报告。

**内容**：对 Skill 整体质量的多维度评估（架构完整性、prompt 质量、错误处理、用户体验、可维护性），含改进建议。

---

## `tests/` — 单元测试

### `tests/test_pre_filter.py`

**职责**：`pre_filter.py` 的单元测试。

**覆盖场景**：学历过滤、年限过滤、语言过滤、地域过滤、边界条件（信息缺失时不过滤）。

---

### `tests/test_post_judge.py`

**职责**：`post_judge.py` 的单元测试。

**覆盖场景**：英语降级、技术栈不匹配强制 C 档、职级约束、去重逻辑、多规则叠加。

---

## `notes/` — 开发笔记与规划

> 此目录为内部开发参考，不影响 Skill 运行。

### `notes/career-copilot-practical-workflow.md`

**职责**：Career Copilot 的实操工作流与设计决策记录（grill-me / spec-driven-development 拷问产出的 D1–D6 决策点与 T1–T8 实施票）。

**内容**：从"13+ 独立 skill"到"1 个内聚 skill"的架构取舍、对齐模式/交接模式的雏形设计、决策点（D1–D6）与推荐答案。

> ⚠️ **时效性**：本文记录的是「对齐模式 = 带推荐答案多问」的**升级前**设计。当前 `SKILL.md` ① 对齐模式已升级为 **deep-grill 哲学**（先调查、再自我反驳、只批量升级主观分歧），以 `SKILL.md` 为准。

### `notes/archive/notes/archive/improvement-roadmap.archived.md`（已归档 · SUPERSEDED）

> ⚠️ **已归档**：本路线图已于 2026-07-30 移入 `notes/archive/` 并改名 `improvement-roadmap.archived.md`，内容已被实际实现（v2 多门户抓取 / Tier2 简历生成 / Phase 8 系列 / 端到端编排器等）取代，仅作历史参考，不再作为待办来源。当前改进跟踪以 `notes/evolution-log.md` 与 `evals/` 为准。

**原职责**：改进路线图（短/中/长期改进计划、算法优化方向、新功能规划、技术债务清理等）。

---

### `notes/implementation-plan.md`

**职责**：实施方案详述。

**内容**：某一阶段的具体实施计划，含任务拆解、优先级、依赖关系。

---

### `notes/` 评审新鲜度规则（防止笔记腐烂）

> 每个 `notes/*.md` 必须在**文件头部**包含评审标记：
>
> ```markdown
> <!-- last_reviewed: YYYY-MM-DD | review_cycle_days: 90 -->
> ```
>
> - `last_reviewed`：最后评审日期；`review_cycle_days`：评审周期（天），默认 90。
> - 超过周期未评审 → 自动视为「待复核」；`.archived.md` 归档文件不参与评审。
> - 用 `scripts/check_notes_freshness.py` 自动扫描：
>   `python scripts/check_notes_freshness.py [notes_dir] [--strict]`
>   （`--strict` 时存在过期/缺失返回退出码 1，可作 CI / pre-commit 门禁）。
> - 评审通过后把头部 `last_reviewed` 改为当日即可；「过期自动待复核」由脚本判定，无需手工标记。

---

## 文件依赖关系图

```
用户触发 → SKILL.md（路由）
               │
               ├──→ references/*.md（方法论注入 LLM context）
               │
               └──→ scripts/（执行）
                      │
                      ├── llm_client.py ←── 被所有需要 LLM 的脚本导入
                      │
                      ├── gen_profile.py（画像生成）
                      │         │
                      │         └──→ boundary_profile.json
                      │
                      ├── fetch_jobs.py（JD 抓取 · catdesk-browser 路线）
                      │         │
                      │         └──→ jobs_raw.txt
                      │
                      ├── fetch_jobs_feishu.py（飞书 ATS 站点 JD 抓取 · Playwright 拦截路线）
                      │         │
                      │         └──→ jobs_raw.txt（同 JOB_MATCHER_FORMAT v1）
                      │
                      ├── smart_score.py（核心 pipeline）
                      │         │
                      │         ├── 调用 pre_filter.py
                      │         ├── 调用 llm_client.py
                      │         ├── 调用 post_judge.py
                      │                               ├── 调用 verify_output.py
                      │         │
                      │         └──→ scored_results.json
                      │
                      └── verify_lens.py（对白软契约检查 · 离线扫 transcript）
                      │
                      ├── generate_report.py
                      │         │
                      │         └──→ report.html
                      │
                      ├── assess_competitiveness.py（单岗位分析）
                      ├── diff_watch.py（增量监测）
                      └── career_log.py（记忆管理）
```

> **v2 以来新增的关键执行节点**（未在上图逐个画出，避免图过密）：`run_pipeline.py`（2.1 端到端编排器，串起建档→抓取→评分→报告→CV 生成）、`batch_fetch.py` + 各 `fetch_jobs_*` / `fetch_boss.py` + `job_common.py`（多门户抓取后端群）、`drafter_reviewer.py` / `build_cv.py` / `build_cv_docx.py` / `verify_ats.py` / `visual_inspect.py`（Tier2 简历生成与 ATS 闭环）、`jd_guard.py`（JD 信任边界）、`trend_analyzer.py` / `competitiveness_tracker.py` / `first_seen.py`（Phase 8 市场/竞争力/时机系列）、`job_tracker.py`（申请生命周期）。

---

## 典型开发工作流

1. **修改评分逻辑**：改 `smart_score.py` → 跑 `tests/test_post_judge.py` + `verify_output.py` 验证
2. **调整过滤规则**：改 `pre_filter.py` / `post_judge.py` → 跑对应单测
3. **优化 prompt**：改 `config/prompts.yaml` 中的模板（分数带参数由 `config/pipeline.yaml` 注入） → 用 `evals/evals.json` 回归验证
4. **新增功能**：在 `SKILL.md` 中增加路由 → 写对应 reference → 实现 script → 补 eval 用例
5. **调试 LLM 调用**：先 `check_env.py` 验证连通性 → 检查 `.env` 配置 → 看 `llm_client.py` 日志输出

---

## 维护信息（bus factor 视图）

> **bus factor 现状**：本项目当前为**单维护者（bus factor = 1）**，所有文件 owner 均为「闫飞宇（GitHub: Feiyu1215）」。下表供潜在接手者快速定位 ownership、改动频率与维护难度，降低「一人离开即项目停摆」风险。
>
> - **更新节律**：高频 = 随核心能力 / 红线频繁改动；中频 = 随模块演进偶发改动；低频 = 稳定，仅 bug 修复时动；不变 = 一次性写入。
> - **复杂度**：维护难度（改动需谨慎度）。高 = 入口 / 被多文件依赖 / 核心算法，改动须全量回归；中 = 局部逻辑；低 = 独立文档 / 模板。

### 根目录文件

| 文件 | Owner | 更新节律 | 复杂度 | 最后核实 |
|------|-------|---------|--------|---------|
| `SKILL.md` | 闫飞宇 | 中频 | 高（入口 + 约束集，改动需全量回归） | 2026-07-21 |
| `FILE_GUIDE.md` | 闫飞宇 | 中频 | 中（随文件增减更新） | 2026-07-30 |
| `requirements.txt` | 闫飞宇 | 低频 | 低 | 2026-07-21 |
| `.env.example` | 闫飞宇 | 低频 | 低 | 2026-07-21 |
| `.gitignore` | 闫飞宇 | 低频 | 低 | 2026-07-21 |
| `LICENSE` | 闫飞宇 | 不变 | 低 | 2026-07-21 |

### `scripts/`（46 个）

| 文件 | Owner | 更新节律 | 复杂度 | 最后核实 |
|------|-------|---------|--------|---------|
| `llm_client.py` | 闫飞宇 | 低频 | 高（所有脚本依赖，仅 provider 增减时动） | 2026-07-30 |
| `check_env.py` | 闫飞宇 | 低频 | 低 | 2026-07-30 |
| `gen_profile.py` | 闫飞宇 | 中频 | 中高（prompt / 模型改动） | 2026-07-30 |
| `fetch_jobs.py` | 闫飞宇 | 中频 | 中（随站点结构） | 2026-07-30 |
| `fetch_jobs_feishu.py` | 闫飞宇 | 中频 | 中高（随飞书 ATS API） | 2026-07-30 |
| `smart_score.py` | 闫飞宇 | 中频 | 高（核心六阶段 pipeline） | 2026-07-30 |
| `pre_filter.py` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `post_judge.py` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `verify_output.py` | 闫飞宇 | 低频 | 中（契约新增时动） | 2026-07-30 |
| `verify_lens.py` | 闫飞宇 | 低频 | 中（软契约新增时动） | 2026-07-30 |
| `generate_report.py` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `assess_competitiveness.py` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `diff_watch.py` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `career_log.py` | 闫飞宇 | 低频 | 中（记忆 schema 改动时动） | 2026-07-30 |
| `cache.py` | 闫飞宇 | 低频 | 低（T13 语义缓存，仅被 smart_score 调用） | 2026-07-30 |
| `log_utils.py` | 闫飞宇 | 低频 | 低（结构化日志工具） | 2026-07-30 |
| `provider_chain.py` | 闫飞宇 | 低频 | 中（Provider 降级链，被 llm_client 调用，对应 ADR-002） | 2026-07-30 |
| `report_assets.py` | 闫飞宇 | 低频 | 低（report 内联 CSS/JS 资源） | 2026-07-30 |
| `trace.py` | 闫飞宇 | 低频 | 低（执行 Trace，性能/回归诊断） | 2026-07-30 |
| `config_loader.py` | 闫飞宇 | 低频 | 低（加载 config/constraints.yaml 单一事实源） | 2026-07-30 |
| `check_notes_freshness.py` | 闫飞宇 | 低频 | 低（notes 评审新鲜度扫描，--strict 可作 CI 门禁） | 2026-07-30 |
| `batch_fetch.py` | 闫飞宇 | 中频 | 中（多门户批处理编排，随后端增减） | 2026-07-30 |
| `behavior_fit.py` | 闫飞宇 | 低频 | 中（确定性行为拟合，纯 stdlib） | 2026-07-30 |
| `build_cv.py` | 闫飞宇 | 中频 | 中高（LaTeX 编译 + ATS 闭环，随模板/引擎） | 2026-07-30 |
| `build_cv_docx.py` | 闫飞宇 | 低频 | 中（python-docx 降级路径） | 2026-07-30 |
| `build_upskill_brief.py` | 闫飞宇 | 低频 | 中（升级概览生成） | 2026-07-30 |
| `calibration_feedback.py` | 闫飞宇 | 低频 | 中（Phase 6.1 投递反馈校准） | 2026-07-30 |
| `competitiveness_tracker.py` | 闫飞宇 | 低频 | 中高（Phase 8.2 动态评估内核） | 2026-07-30 |
| `drafter_reviewer.py` | 闫飞宇 | 中频 | 中高（Tier2 双轨评审，随评审规则） | 2026-07-30 |
| `fetch_boss.py` | 闫飞宇 | 中频 | 中（BOSS 直聘后端，随站点） | 2026-07-30 |
| `fetch_jobs_linkedin.py` | 闫飞宇 | 中频 | 中（LinkedIn 后端，随站点） | 2026-07-30 |
| `fetch_jobs_nowcoder.py` | 闫飞宇 | 中频 | 中（牛客网后端，随站点） | 2026-07-30 |
| `fetch_jobs_shixiseng.py` | 闫飞宇 | 中频 | 中（实习僧后端，随站点） | 2026-07-30 |
| `first_seen.py` | 闫飞宇 | 低频 | 中（Phase 8.3 时机建议，纯本地） | 2026-07-30 |
| `jd_guard.py` | 闫飞宇 | 低频 | 中高（JD 信任边界，随风控规则） | 2026-07-30 |
| `job_common.py` | 闫飞宇 | 低频 | 中（多门户共享逻辑，被各 fetch 后端依赖） | 2026-07-30 |
| `job_tracker.py` | 闫飞宇 | 中频 | 中（P5 申请/结果生命周期闭环） | 2026-07-30 |
| `manage_template.py` | 闫飞宇 | 低频 | 低（U6 模板注册，外观定制） | 2026-07-30 |
| `notify_wecom.py` | 闫飞宇 | 低频 | 低（企业微信推送，零依赖） | 2026-07-30 |
| `relevance_trim.py` | 闫飞宇 | 低频 | 中（超页相关性裁页） | 2026-07-30 |
| `run_pipeline.py` | 闫飞宇 | 中频 | 高（2.1 端到端编排器，体验质变点） | 2026-07-30 |
| `setup_wizard.py` | 闫飞宇 | 低频 | 中（Phase 5.1 交互式建档引导） | 2026-07-30 |
| `trend_analyzer.py` | 闫飞宇 | 低频 | 中高（Phase 8.1 市场趋势，零 LLM 内核） | 2026-07-30 |
| `verify_ats.py` | 闫飞宇 | 低频 | 中（PDF ATS 文本层 + 不变量检查） | 2026-07-30 |
| `verify_fetch_quality.py` | 闫飞宇 | 低频 | 中（Phase 4.3 抓取质量守门 CLI） | 2026-07-30 |
| `visual_inspect.py` | 闫飞宇 | 低频 | 中（PDF 逐页视觉巡检 + 防孤行） | 2026-07-30 |

### `references/`（22 个）

| 文件 | Owner | 更新节律 | 复杂度 | 最后核实 |
|------|-------|---------|--------|---------|
| `matching-guide.md` | 闫飞宇 | 中频 | 高（核心匹配方法论） | 2026-07-30 |
| `capability-modes.md` | 闫飞宇 | 低频 | 中（能力模式定义） | 2026-07-30 |
| `session-lifecycle.md` | 闫飞宇 | 低频 | 中（会话生命周期） | 2026-07-30 |
| `resume-guide.md` | 闫飞宇 | 中频 | 高（核心简历护栏） | 2026-07-30 |
| `interview-prep.md` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `career-memory.md` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `onboarding-guide.md` | 闫飞宇 | 低频 | 低 | 2026-07-30 |
| `evolution-log.md` | 闫飞宇 | 中频 | 低 | 2026-07-30 |
| `career-context.template.md` | 闫飞宇 | 低频 | 低 | 2026-07-30 |
| `company-research.md` | 闫飞宇 | 低频 | 低 | 2026-07-30 |
| `decision-log.template.md` | 闫飞宇 | 低频 | 低 | 2026-07-30 |
| `job-search-spec.md` | 闫飞宇 | 低频 | 低 | 2026-07-30 |
| `risk-light.md` | 闫飞宇 | 低频 | 中 | 2026-07-30 |
| `chatgpt-lite.md` | 闫飞宇 | 低频 | 低（独立可粘贴文档） | 2026-07-30 |
| `behavioral-profile.md` | 闫飞宇 | 低频 | 中（行为画像方法论） | 2026-07-30 |
| `boss-fetch.md` | 闫飞宇 | 低频 | 中（BOSS 直聘抓取约定，配 fetch_boss.py） | 2026-07-30 |
| `jd-trust-boundary.md` | 闫飞宇 | 低频 | 中高（JD 信任边界，配 jd_guard.py） | 2026-07-30 |
| `job-fetch.md` | 闫飞宇 | 低频 | 中（多门户抓取编排说明，配 batch_fetch/job_common） | 2026-07-30 |
| `job-tracker.md` | 闫飞宇 | 低频 | 中（Job Tracker 规范，配 job_tracker.py） | 2026-07-30 |
| `interview-done-template.md` | 闫飞宇 | 低频 | 低（面试结果事件模板） | 2026-07-30 |
| `resource-index.md` | 闫飞宇 | 低频 | 低（本地资源索引，owner 自管） | 2026-07-30 |
| `setup-guide.md` | 闫飞宇 | 低频 | 低（建档引导流程，配 setup_wizard.py） | 2026-07-30 |

### 降低 bus factor 的建议（待办）

- [ ] 引入第二维护者（peer review 机制）
- [ ] 为 `gen_profile.py` 补架构决策记录（ADR）。`llm_client.py`（✅ `ADR-002-llm-client-failover`）、`smart_score.py`（✅ `ADR-001-smart-score-pipeline`）ADR 已补
- [ ] 本表随文件增删自动更新（CI 检查 `FILE_GUIDE.md` 与磁盘一致）
