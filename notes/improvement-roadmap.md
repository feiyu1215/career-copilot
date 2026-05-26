# Career Copilot 改进路线图

> 基于 CatX 博客精选 16 篇文章 + 6 个外部资源的架构洞察，结合源码审视提出的改进方向。  
> 优先级：P0 = 立即可做，收益明显 / P1 = 中期迭代 / P2 = 长期演进  
> 外部资源：oh-my-claudecode / PraisonAI / andrej-karpathy-skills / claude-code-setup / Karpathy 12 Rules / SmithDB

### 实施状态追踪（截至本轮 neat-freak 审查）

| 改进项 | 状态 | 备注 |
|--------|------|------|
| SKILL.md 精简（306→120 行） | ✅ 已完成 | 见 evolution-log.md |
| Meta 权衡声明 | ✅ 已完成 | SKILL.md 顶部 |
| 智能模型路由 | ⏳ 未实施 | 需 pipeline_config.yaml |
| Token 黑洞修复 | ✅ 已完成 | SKILL.md 只声明核心入口 |
| Fallback 阈值 50→30 | ✅ 已完成 | smart_score.py |
| LLMClient timeout | ✅ 已完成 | llm_client.py timeout=120 |
| JSON 解析四层恢复 | ✅ 已完成 | smart_score.py _parse_json |
| CORE_TEAM_SIGNALS 动态化 | ✅ 已完成 | post_judge.py |
| Pipeline Checkpoint | ✅ 已完成 | smart_score.py --resume |
| fetch_jobs 原子化保存 | ✅ 已完成 | fetch_jobs.py |
| LLM Provider 自动降级 | ✅ 已完成 | llm_client.py retry 分类 |
| pre_filter 规则可配置 | ✅ 已完成 | --include-intern 等 |
| Stage 2 并发度可配置 | ✅ 已完成 | --stage2-concurrency |
| check_env 网络连通性 | ✅ 已完成 | HEAD 请求检测 |
| diff_watch 上次运行提示 | ✅ 已完成 | |
| gen_profile 方向确认输出 | ✅ 已完成 | 打印 direction_anchors |
| Onboarding 冷启动引导 | ✅ 已完成 | references/onboarding-guide.md |
| 沟通风格指南 | ✅ 已完成 | SKILL.md "沟通风格"段 |
| 错误诊断表 | ✅ 已完成 | matching-guide.md |
| Sanity Check 优先级 | ✅ 已完成 | matching-guide.md |
| 记忆时序感知 | ⏳ 未实施 | |
| Pipeline 配置化（YAML） | ⏳ 未实施 | |
| 执行 Trace | ⏳ 未实施 | |
| Prompt 外置 | ⏳ 未实施 | |
| Golden Test Cases | ⏳ 未实施 | |
| generate_report 分层重构 | ⏳ 未实施 | |
| 约束分级制度（H/R/Rec/Rel） | ✅ 已完成 | easyslides 启发，见 upgrade-plan |
| 纯推理 Stop Conditions | ✅ 已完成 | SKILL.md + matching-guide.md |
| 违反归因标注 | ✅ 已完成 | SKILL.md "绝对不要"段 |
| 跨会话恢复协议 | ✅ 已完成 | matching-guide.md "操作经验"段 |
| 方向探索收敛规则 | ✅ 已完成 | onboarding-guide.md |
| Pipeline 配置锁定（snapshot） | ⏸ 暂缓 | 评估后认为当前不需要：CLI args 已不可变，无外部 config 被修改风险 |

---

## 一、渐进式加载 & Prompt Cache 优化

**来源**：《Prompt Cache 原理深度解析》《工具调用优化》《如何构建 Skills》

### P0：优化 SKILL.md 的 frontmatter description

**现状**：description 约 600 字符，全中文，缺少英文触发短语。

**改进**：
- 压缩到 900 字符以内
- 增加英文触发词：`job match`, `smart score`, `interview prep`, `resume optimize`, `offer compare`, `career plan`, `migration distance`, `competitiveness assessment`
- 增加常见口语触发：`帮我看看哪些岗位适合我`、`这个 JD 匹配度怎么样`、`帮我准备面试`

### P0：减少"Token 黑洞"

**现状**：SKILL.md 声明了 12 个脚本，所有脚本信息对 agent 同等暴露。

**改进**：
- 只声明 3 个核心入口脚本的完整签名（gen_profile、smart_score、fetch_jobs）
- 其他脚本标记为"内部模块，由主脚本自动调用，无需直接执行"
- matching-guide.md 的完整命令参考改为"按需加载"（agent 实际执行时才读取）

### P0：智能模型路由 ⭐ NEW

**来源**：oh-my-claudecode 的 Smart Model Routing（节省 30-50% token）

**现状**：所有 Stage 使用同一个 model，Stage 1 粗筛和 Stage 2 精排的推理复杂度差异 10 倍但用同等算力。

**改进**：
- Stage 1（粗筛）：使用 cheaper/faster 模型（如 claude-3-haiku、gpt-4o-mini）
- Stage 2（精排对比）：使用 stronger 模型（如 claude-sonnet、gpt-4o）
- Global Rerank：使用 stronger 模型
- 在 pipeline_config.yaml 中声明每阶段对应的 model

**预期收益**：token 成本降低 30-40%，Stage 1 速度提升 2-3x

### P1：System Prompt 稳定前缀设计

**现状**：smart_score.py 每组调用 system prompt 含 domain_knowledge + calibration_knowledge + 规则说明 (~3500 tokens)，8 组重复发 28,000 tokens。

**改进**：
- 将不变的规则部分（分档标准、评分锚点、核心规则）提取为 `SYSTEM_PREFIX` 常量
- domain_knowledge 和 calibration_knowledge 放到 user message 的前部
- 若 provider 支持 prompt caching（Anthropic beta），对 SYSTEM_PREFIX 标记 cache_control

### P0：规则精简工程 ⭐ NEW

**来源**：Karpathy 12 Rules（>14 条规则 compliance 下降）+ claude-code-setup（CLAUDE.md 不超 1500 tokens）

**现状**：SKILL.md 306 行，规则 15+ 条，后段规则遵守率明显低于前段（attention 稀释效应）。

**改进**：
- 将 15+ 条规则精简到 8-10 条：合并重复规则、删除从未被违反的规则
- 每条规则附具体正/反例（LLM 对"不要做 X"不如"做了 X 会导致 Y 错误"有效）
- 按"违反成本"降序排列——最容易犯且后果最严重的放最前面
- SKILL.md 主体压缩到 150 行 (~1200 tokens)

**验证方式**：对比精简前后 10 次运行的规则违反次数

### P1：SKILL.md 结构优化

**现状**：`User-Learned Best Practices`（动态频繁变化）位于文件末尾，符合 cache 最佳实践。但运行时自检规则位于中段。

**改进**：
- 将"运行时自检"和"禁止思想"移到全局约束之后（更前面）
- `User-Learned Best Practices` 外移到 `references/evolution-log.md`，SKILL.md 只保留引用
- 每个 reference 声明旁标注 `~tokens: 2500` 帮 agent 做加载决策

---

## 二、SubAgent 并行化

**来源**：《SubAgent 的工程实现》《工具调用优化》

### P1：Pipeline 分阶段 CLI 入口

**现状**：`run_pipeline` 是 190 行单体函数，必须从头跑到尾。

**改进**：支持分阶段独立执行：
```bash
python3 smart_score.py --mode stage1 --input jobs_raw.txt --output _stage1.json
python3 smart_score.py --mode stage2 --input _stage1.json --output _stage2.json
python3 smart_score.py --mode rerank --input _stage2.json --output scored_results.json
```

**收益**：
- 单阶段失败无需全部重跑
- SubAgent 模式下各阶段可并行调度
- Checkpoint 天然存在（中间文件即 checkpoint）

### P1：Stage 2 并发度提升

**现状**：`concurrent_groups = 2` 硬编码，50 个 JD / 6 = 8 组，每次只跑 2 组。

**改进**：
- 改为 `min(args.concurrency, len(groups))` 动态计算
- 暴露 `--stage2-concurrency` 参数
- 当单层 A/B/C > 15 个岗位时，在 global_rerank 中自动分片

### P2：流水线化 Stage 1 → Stage 1.5

**现状**：Stage 1 全部完成后才启动 Stage 1.5。

**改进**：当 Stage 1 已处理 80% 的 JD 且 top-k 排名稳定时，提前将当前 top-k 标题送入 Stage 1.5（流水线 fan-out）。

---

## 三、记忆系统升级

**来源**：《解密 CatX 的记忆模块 CatMemory》

### P0：增加时序感知

**现状**：事件只有 `timestamp`，无过期标记。offer 过了 deadline 仍被视为有效。

**改进**：
- 公共字段增加 `expires_at`（可选）和 `status: active | expired | superseded`
- `offer_received` 事件的 `deadline` 过后自动标记 `status: expired`
- Profile 快照生成时只聚合 `status: active` 的事件

### P1：关联推理

**现状**：interview_done 和 match_round 之间无自动关联。

**改进**：
- 当记录 `interview_done` 时，自动检索近 30 天内 `match_round` 中 top_matches 是否包含该公司
- 若命中，自动在事件中增加 `related_events: ["match-20250115-001"]`
- `interview_done` 增加 `related_match_round` 字段（interview_prep 已有）

### P1：场景化快照裁剪

**现状**：Profile 快照全量聚合，所有模块看同一份。

**改进**：
- 匹配模块加载时：高亮 direction_anchors、risks 频次、hard_negatives
- 面试模块加载时：高亮 weak_points、learnings、interview 通过率
- 简历模块加载时：高亮 能力标签频次、STAR 案例库

### P2：自动压缩 & Memory Dreaming

**改进**：
- 旧于 90 天的 JSONL 事件归档到 `career-log-archive.jsonl`
- 主文件只保留近 90 天 + 所有 `status: active` 的重要事件
- 当 interview_done 累积 5+ 条时，自动蒸馏"面试通过率高的岗位特征"注入 Profile

---

## 四、可靠性 & 自愈

**来源**：《运行环境可靠性建设》《热更新架构》《容器镜像分层》

### P0：Pipeline Checkpoint 机制

**现状**：run_pipeline 中途失败需从头重跑。

**改进**：
- 每个 Stage 完成后保存 `_checkpoint_stageN.json`
- 增加 `--resume` 参数，检测已有 checkpoint 并从最近阶段恢复
- 最终输出成功后清理 checkpoint 文件

### P0：fetch_jobs 原子化保存

**现状**：每 5 页保存一次，中间页丢失不可恢复。

**改进**：
- 每页成功后立即 append 到输出文件
- 维护 `_progress.json`：`{"completed_pages": [1,2,3,5], "failed_pages": [4]}`
- `--resume` 自动跳过已完成页，重试失败页

### P1：JSON 解析四层自愈

**现状**：_parse_json 只有两层恢复（直接解析 → 找括号）。

**改进**：
- 第三层：修复常见 JSON 错误（trailing comma, single quotes, unquoted keys）
- 第四层：regex 提取关键字段（score, tier）作为 graceful degradation
- 标记 `"is_fallback": true` 让用户知道哪些结果是降级推断的

### P1：LLM Provider 自动降级

**现状**：llm_client.py 实例化后 provider 固定，一个挂了整个 pipeline 挂。

**改进**：
- 增加 `fallback_provider` 配置
- 连续 3 次失败自动切换到 fallback（如 internal → external）
- 按错误类型分策略：rate limit 等更久、timeout 立即重试、bad JSON 换 temperature

### P1：Selector 漂移早期检测

**现状**：fetch_jobs 的 CSS selector 预设失效后，要跑完所有页才发现问题。

**改进**：
- 前 2 页如果返回 0 条结果，立即告警并建议切换 preset
- 增加 `--validate-selector` 模式，只跑 1 页验证 selector 有效性

---

## 五、代码结构 & 关注点分离

**来源**：《UI SDK 分层设计》《容器镜像分层》

### P1：generate_report.py 分层重构

**现状**：630 行 God function，数据/CSS/HTML/JS 全混一起。

**改进**：
```
generate_report.py
├── prepare_report_data()   # 数据层：原始数据 → 报告数据模型
├── REPORT_CSS             # 模板层：样式常量（含暗色模式）
├── REPORT_JS              # 模板层：交互逻辑
└── render_html()          # 渲染层：组装最终 HTML
```

新增功能：
- `@media (prefers-color-scheme: dark)` 暗色模式
- 搜索框（按标题/公司名过滤）
- "复制为 Markdown"按钮

### P1：脚本层次显式化

**现状**：12 个 .py 文件平级放在 scripts/ 下。

**改进**：在 README 或 scripts/__init__.py 中声明依赖关系：
```
Core:       llm_client.py（被所有 LLM 调用脚本依赖）
Pipeline:   smart_score.py → pre_filter.py + post_judge.py（内部调用）
Entry:      gen_profile.py, fetch_jobs.py, smart_score.py（用户直接调用）
Utility:    check_env.py, verify_output.py, generate_report.py
Monitor:    diff_watch.py, assess_competitiveness.py
Memory:     career_log.py
```

### P2：输入/输出 Schema 验证

**现状**：脚本间通过 JSON 文件传递数据，无格式校验。

**改进**：
- 创建 `scripts/schema.py`，用 TypedDict 或 dataclass 定义各中间文件格式
- 每个脚本入口做 schema validation
- 格式不对时给出明确错误信息而非崩溃

---

## 六、Pipeline 配置化与执行可观测性

**来源**：PraisonAI（YAML 配置化）+ SmithDB/LangSmith（trace 可观测性）

### P0：Pipeline 参数配置文件 ⭐ NEW

**现状**：pipeline 参数（batch_size、group_size、concurrency、model、JD 截断长度等）散布在代码各处（smart_score.py 硬编码 `concurrent_groups = 2`、`[:1500]` 等）。

**改进**：
- 创建 `config/pipeline_config.yaml`：
```yaml
pipeline:
  stage1:
    model: "claude-3-haiku"
    batch_size: 25
    jd_truncation: 1500
  stage2:
    model: "claude-sonnet-4"
    group_size: 6
    concurrency: 3
  global_rerank:
    model: "claude-sonnet-4"
  retry:
    max_retries: 3
    fallback_provider: "external"
```
- 脚本启动时读取配置，`--config` 参数可覆盖默认路径
- 改参数不动代码，A/B 测试只需复制配置文件

### P1：轻量执行 Trace ⭐ NEW

**现状**：smart_score 跑完只有最终 HTML 报告，执行过程是黑盒——哪个阶段耗时最久、哪组 LLM 调用失败了、token 消耗如何分布，全部不可见。

**改进**：
- 每次 LLM 调用记录 trace 到 `output/pipeline_trace.jsonl`：
```json
{"ts": "...", "stage": "stage1", "group": 3, "model": "haiku", "prompt_tokens": 2100, "completion_tokens": 450, "latency_ms": 1200, "success": true, "fallback": false}
```
- Pipeline 结束后自动输出摘要：
```
📊 Pipeline Trace Summary:
  Total LLM calls: 42 (success: 39, retry: 2, fallback: 1)
  Token usage: 89,200 input / 12,300 output
  Stage breakdown: S1=45% | S2=38% | Rerank=17%
  Slowest call: Stage2-Group4 (3.2s)
```
- 可选生成 trace 分析脚本（按 stage 聚合、按模型对比）

### P1：Prompt 版本化 ⭐ NEW

**现状**：修改 system prompt 后无法对比效果差异。

**改进**：
- 每个 system prompt 模板在 `config/prompts/` 下维护，带版本号（v1、v2...）
- trace 中记录 `prompt_version` 字段
- 提供对比脚本：输入两个不同版本的 trace 文件，输出同一批 JD 的评分差异

---

## 七、Token 预算与成本管理

**来源**：《Prompt Cache》《工具调用优化》

### P1：Pipeline 入口成本预估

**改进**：在 `run_pipeline` 开始前计算并展示预估 token 消耗：
```
📊 预估成本：
  Stage 1: 200 JDs × ~300 tokens = ~60K tokens
  Stage 1.5: ~2K tokens
  Stage 2: 30 JDs / 6 × ~4K tokens = ~20K tokens
  Stage 2.5: 30 × ~800 = ~24K tokens
  Global Rerank: ~5K tokens
  Total: ~111K tokens ≈ ¥X.XX
继续执行? [Y/n]
```

### P1：JD 截断策略优化

**现状**：`full_text[:1500]` 固定截断，可能丢失关键信息。

**改进**：提取前 500 字（概述）+ 最后 300 字（通常是硬性要求）+ 中间按 token 预算填充。关键信息（学历要求、英语要求、工作年限）用 regex 提取确保不丢失。

### P2：全局 Semaphore 共享

**现状**：多个 LLMClient 实例各有独立 semaphore，不感知 provider 全局 rate limit。

**改进**：创建全局 `RateLimitManager`，所有同 provider 的 client 共享限流。

---

## 八、新功能建议

### P1：增量评分

当 diff_watch.py 检测到新增 JD 时，只对新增做 Stage 1，高分者 merge 入已有 top-k 后重跑 Stage 2，避免完整 pipeline 重跑。

### P1：记忆驱动的个性化评分

当用户有 5+ 条 `interview_done` 数据时，从 learnings 和 outcomes 中提取"面试通过率高的岗位特征"，作为额外 calibration context 注入 Stage 2。

### P2：评分结果 A/B 测试

支持 `--ab-test` 模式：用两个不同 model 对相同 top-k 评分，输出对比报告，帮助用户校准模型选择。

### P2：自动 Sanity Check 修复

当 verify_output.py 发现异常（A 档 = 0、最高分 < 70），不只报告，而是自动尝试修复策略（降低阈值/放宽 top-k/重跑异常组）。

---

## 九、Slash Command 场景隔离 ⭐ NEW

**来源**：claude-code-setup（Slash Command 设计）+ oh-my-claudecode（Agent 角色分化）

### P1：拆分 SKILL.md 为场景化 Commands

**现状**：一个 306 行 SKILL.md 承担所有场景（匹配、面试、简历、规划），Agent 每次都要 parse 整个文件决定做什么。

**改进**：
- `/match` — 岗位匹配流程，只加载匹配相关的 context（smart_score 参数、评分标准）
- `/prep` — 面试准备流程，只加载面试相关 context（interview learnings、weak_points）
- `/resume` — 简历优化流程，只加载简历相关 context（STAR 案例库、能力标签）
- `/plan` — 职业规划流程，只加载规划相关 context（direction_anchors、market trends）
- SKILL.md 作为路由层：识别用户意图 → 调用对应 command → 各 command 独立加载所需 reference

**预期收益**：每次会话的有效 context 从 ~5000 tokens 降到 ~1500 tokens，Agent 注意力更集中

---

## 十、Working Memory 层 ⭐ NEW

**来源**：claude-code-setup（Dual-Memory 架构）+ CatMemory 的 L0-L3 分层

### P0：增加 career-context.md（即时上下文）

**现状**：每次会话开始要读完整 career-profile.md 快照（~2000+ tokens）才知道"用户现在在干什么"。实际有用的只是当前阶段信息。

**改进**：
- 新增 `career-context.md`——"Working Memory"层，只记录当前求职的即时状态：
```markdown
# 当前求职上下文
- 当前阶段: 面试期
- 焦点公司: [公司A-三面待通知, 公司B-已拿offer]
- 关键截止日期: 6月15日前决定
- 上次操作: 5月28日 匹配了新一批岗位
- 待办: 准备公司C的技术面
- 上次匹配批次 top3: [岗位X, 岗位Y, 岗位Z]
```
- 会话开始时先读 career-context.md（~200 tokens），必要时才加载完整 profile
- 每次操作结束后自动更新 career-context.md

**预期收益**：会话启动 token 消耗从 ~2000 降到 ~200，且 Agent 立即知道当前进度

---

## 十一、判断质量评估体系 ⭐ NEW

**来源**：LangSmith Evaluation 框架（Dataset + Target + Evaluator）+ Karpathy 实验设计（30 codebase × 50 tasks）

### P1：建立 Golden Test Cases

**现状**：`verify_output.py` 的 12 项检查只验证"输出结构完整性"（有 job_id、有 score、分布合理），不验证"判断质量"（评分是否准确）。`evals/evals.json` 仅 3 条用例，覆盖面不足。

**改进**：
- 创建 `evals/golden_cases.jsonl`，收集 15-20 个真实匹配案例：
```json
{"jd_text": "...", "resume_summary": "...", "human_score": 78, "human_tier": "B", "key_risks": ["经验不足"], "match_reasons": ["方向对齐", "技术栈匹配"]}
```
- 新增 `scripts/eval_scoring.py`：对比 smart_score 输出 vs 人工标注
- 输出指标：平均分偏差、tier 一致率、关键 risk 召回率
- 用于 prompt 迭代后的回归测试

### P1：Intent-Level 验证

**现状**：verify_output 只看结构，不看"匹配分 > 80 的岗位是否真的与 boundary_profile 方向对齐"。

**改进**：
- 在 verify_output 中新增"意图验证"类别：
  - 抽样 Top 3 岗位的 `match_reasons`，检查是否包含 `boundary_profile.direction_anchors` 中的核心方向词
  - 检查 A 档岗位是否存在 `hard_negatives` 关键词（若存在则报警）
  - 统计 risk_factors 为空的 A 档岗位数量（过多意味着风险识别不充分）

### P2：SKILL.md 规则 Compliance 审计

**来源**：Karpathy 发现 >14 条规则 compliance 急剧下降

**改进**：
- 设计 10 个测试场景，记录 Agent 在每个场景中违反了哪些规则
- 被频繁违反的规则要么重写得更清晰具体，要么合并/删除
- 定期审计（每 2 周），用数据驱动规则迭代而非凭感觉

---

## 十二、Pipeline 显式数据契约 ⭐ NEW

**来源**：PraisonAI（`context: [previous_task]` 显式依赖声明）+ LangSmith（RunTree 层级编码）+ oh-my-claudecode（Inbox/Outbox 模式）

### P1：每步 Input/Output Schema 声明

**现状**：Pipeline 各步通过文件名约定隐式传递数据（`boundary_profile.json` → `scored_results.json`），无格式校验。某步输出结构变化会静默传播到下游。

**改进**：
- 在 `matching-guide.md` 或新建 `references/pipeline-contract.md` 中为每步声明：
```
Step 1 gen_profile:
  Input:  resume.pdf | resume.txt
  Output: boundary_profile.json (schema: examples/boundary_profile_example.json)
  Type:   模型判断（语义理解）

Step 3 smart_score:
  Input:  boundary_profile.json + jobs_raw.txt
  Output: scored_results.json (schema: examples/scored_results_example.json)
  Type:   模型判断（粗筛）+ 代码约束（post_judge）

Step 4 generate_report:
  Input:  scored_results.json
  Output: report_YYYYMMDD.html
  Type:   代码确定性（模板渲染）
```
- 每步启动时做 input schema 验证，格式不对时给出明确错误信息而非崩溃（与 roadmap 五 P2 的 Schema 验证合并）

### P2：事件日志增加 trace_id 层级编码

**来源**：LangSmith 的 dotted_order 层级查询

**现状**：`career-log.jsonl` 事件是扁平的，"回顾某家公司完整历程"需要手动按 company 字段过滤拼接。

**改进**：
- 给每个事件增加 `trace_id`（同一家公司的所有事件共享）
- 使"从投递到 offer/拒绝的完整链路"变成一次 trace_id 查询
```json
{"event": "apply", "company": "ByteDance", "trace_id": "bd_2025q2", "ts": "..."}
{"event": "interview_1", "company": "ByteDance", "trace_id": "bd_2025q2", "ts": "..."}
{"event": "offer_received", "company": "ByteDance", "trace_id": "bd_2025q2", "ts": "..."}
```
- `career_log.py query --trace bd_2025q2` 一次拉出完整时间线

---

## 十三、Prompt 外置与版本管理 ⭐ NEW

**来源**：LangSmith Prompt Hub + oh-my-claudecode（每个 agent prompt 独立文件）

### P1：Prompt 模板外置到 prompts/ 目录

**现状**：`smart_score.py` 的评分 prompt 直接硬编码在 Python 代码中。修改 prompt 需要改代码、重新测试。

**改进**：
- 提取核心 prompt 到独立文件：
```
career-copilot/
├── prompts/
│   ├── profile_extraction_v2.md    # gen_profile 的 system prompt
│   ├── coarse_scoring_v3.md        # Stage 1 粗筛 prompt
│   ├── fine_scoring_v2.md          # Stage 2 精评 prompt
│   ├── rerank_v1.md                # Global Rerank prompt
│   └── competitiveness_v1.md       # 竞争力评估 prompt
```
- 脚本通过 `--prompt-version` 参数或 pipeline_config.yaml 指定用哪个版本
- 迭代 prompt 不需要改代码，回滚只需改版本号

### P2：Token Budget 参数化

**来源**：Karpathy Rule 6（Per-task 4000 tokens, Per-session 30000 tokens）

**现状**：pipeline 单次可能消耗 100K+ tokens（200 JD 粗筛 + 30 JD 精评），没有显式的 token 预算控制。

**改进**：
- 在 pipeline_config.yaml 中增加 token budget 配置：
```yaml
token_budget:
  stage1_per_jd: 300      # 粗筛单个 JD 的 output 上限
  stage2_per_group: 4000   # 精评单组的 output 上限
  session_total: 150000    # 总 session 上限
  action_on_exceed: "pause_and_report"  # 超预算时暂停并报告中间结果
```
- 超预算时不是静默停止，而是输出已有结果 + 暂停 + 报告预算使用情况

---

## 十四、Meta 规则与权衡声明 ⭐ NEW

**来源**：Karpathy 12 Rules 的权衡声明 + oh-my-claudecode 的 700-1500 tokens 约束

### P0：SKILL.md 200 行硬上限

**来源**：Karpathy 量化实验：>200 行 CLAUDE.md 合规率从 76% 暴跌到 52%

**现状**：SKILL.md 306 行，24 条规则。按实验数据预测，后段规则合规率可能只有 50% 左右。

**改进**：
- SKILL.md 主体压缩到 ≤ 150 行（~1200 tokens），只保留：
  - 全局约束 5 条 → 精简为 3 条（合并重叠的）
  - 思考框架 4 步（保留）
  - 意图路由表（保留）
  - 匹配哲学 5 条 → 精简为 3 条（最核心的）
- 运行时自检 10 条 → 移到 `rules/runtime-checks.md`，匹配模块执行时按需加载
- 禁止思想 9 条 → 精简为 5 条合并到全局约束
- User-Learned Best Practices → 移到 `references/evolution-log.md`
- 文件结构列表 → 删除（Agent 需要时直接 ls）

### P0：增加 Meta 权衡声明

**来源**：Karpathy 仓库 README 的 "Tradeoff" 声明

**现状**：SKILL.md 缺少"何时可以跳过完整框架"的说明。简单问题也走全流程太重。

**改进**：
- 在 SKILL.md 顶部增加：
```markdown
> **权衡声明**：本 Skill 偏向谨慎和完整性。对于快速判断型需求（单个 JD 
> 评估、仅需 Yes/No），可直接使用纯推理模式，无需走完整框架。当方向已
> 明确且用户催促时，跳过确认环节直接执行。
```
- 配合 autonomy 等级：首次使用低 autonomy（每步确认）→ 熟悉后高 autonomy（只在异常暂停）

---

## 实施优先级建议（最终版）

| 阶段 | 改进项 | 预计工作量 | 预期收益 |
|------|--------|-----------|---------|
| 第一批 | SKILL.md 200 行硬瘦身 + Meta 权衡声明 + Working Memory 层 + 智能模型路由 | 3-4 小时 | compliance ↑50%、成本↓30%、会话启动效率↑ |
| 第二批 | Pipeline 配置化 + checkpoint + fetch 原子化 + Token 黑洞修复 | 2-3 小时 | 可靠性↑、可维护性↑ |
| 第三批 | 执行 Trace + Prompt 外置 + Slash Command 拆分 + provider 降级 | 4-6 小时 | 可观测性↑、prompt 迭代效率↑、注意力集中↑ |
| 第四批 | Golden Test Cases + Intent 验证 + Pipeline 数据契约 + report 分层 | 1-2 天 | 判断质量可量化↑、数据流可靠性↑ |
| 第五批 | 记忆关联推理 + trace_id 层级编码 + Token Budget + 增量评分 | 1-2 天 | 智能化↑、记忆可查询↑ |
| 长期 | Compliance 审计 + 个性化评分 + A/B 测试 + Memory Dreaming + Autonomy 等级 | 持续迭代 | 自进化能力↑ |

---

*路线图完*
