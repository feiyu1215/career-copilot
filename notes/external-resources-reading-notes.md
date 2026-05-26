# 外部资源研读笔记 — Agent 工程与 Skill 设计

> 阅读时间：2025年7月  
> 来源：6 个外部项目/文章  
> 与 CatX 博客笔记互为补充，侧重"落地实践"层面

---

## 一、编排模式与多 Agent 协作

### 来源：oh-my-claudecode（GitHub 开源项目）

### 关键洞察

这个项目提供了 8 种编排模式（orchestration modes）和 29 个预置 Agent，本质上是用 CLAUDE.md + SubAgent 组合来模拟一个完整的软件工程团队。

核心架构：

- **智能模型路由（Smart Model Routing）**：根据任务复杂度动态选择模型（简单任务用小模型，复杂任务用大模型），实测节省 30-50% token 消耗。这不是"所有任务都用最贵的模型"，而是建立了一套任务分类→模型选择的映射规则。
- **8 种编排模式**的递进设计：从最简单的单 Agent 处理（boomerang），到多 Agent 并行（parallel-workers），到带反馈循环的迭代模式（iterative-refinement），再到完整的 Swarm 模式。每种模式有明确的适用场景。
- **Agent 角色分化**：不只是技术角色（coder、reviewer、tester），还包含流程角色（planner、coordinator、reporter）。29 个 Agent 中约 1/3 是"管理型"的，负责拆解、协调、汇总，而非直接产出代码。

特别值得注意的设计决策：

- 每个 Agent 的 prompt 控制在 700-1500 tokens 以内（类比 Karpathy 的规则精简思路）
- Coordinator 从不直接写代码，只做"拆任务+验收"——与 CatX SubAgent 博客中的 Coordinator 模式完全对应
- 用 `.claude/` 目录下的 markdown 文件定义整个团队结构，零代码改动就能切换编排策略

### 个人感悟

career-copilot 的 SKILL.md 试图用一个 300 行的 prompt 搞定所有事情——既是 planner（分析用户意图）、又是 executor（调用脚本）、又是 reporter（生成报告）。参考 oh-my-claudecode 的思路，可以考虑把"理解用户需求+路由到正确脚本"和"执行具体脚本+处理结果"拆开。前者需要高理解力（用大模型），后者可能只需要可靠执行（用小模型或结构化调用）。

智能模型路由对 smart_score 的直接启示：Stage 1 是粗筛（不需要深度推理），可以用 cheaper model；Stage 2 是精排（需要多维度对比推理），适合用 stronger model。目前所有阶段用同一个模型是浪费。

---

## 二、多 Agent 框架的工程极简主义

### 来源：PraisonAI（GitHub 开源框架）

### 关键洞察

PraisonAI 的卖点是"5 行代码启动多 Agent 系统"，支持 100+ LLM 后端，Agent 实例化延迟仅 3.77μs。表面上像是另一个 LangChain/CrewAI 竞品，但几个设计决策很有独特价值：

- **YAML 定义 Agent 团队**：整个多 Agent 协作通过一个 YAML 文件声明，包括角色、目标、工具、依赖关系。不写代码，改配置就能调整团队结构。
- **Tool 自动发现**：基于 Python 函数签名自动生成工具描述，不需要手写 JSON schema。降低了工具定义的维护成本。
- **内置 UI**：提供 web dashboard 查看 Agent 执行过程、token 消耗、中间结果。对调试多 Agent 系统非常关键。
- **3.77μs Agent 实例化**：不是每次调用都重建 Agent 对象，而是维护 Agent 池，复用已初始化的实例。

但也有明显的局限：

- 过度封装导致"黑盒"——当 Agent 行为不符预期时，debug 困难
- YAML 声明式虽好维护，但表达复杂流程（条件分支、动态路由）时不如代码灵活
- 100+ LLM 支持实际上是通过 LiteLLM 的统一接口实现的，provider-specific 优化（如 prompt cache）很难利用

### 个人感悟

career-copilot 目前用 Python 脚本群 + SKILL.md 文本指令的方式，虽然"原始"，但有一个优势：完全透明，任何行为都可以追踪到具体的 .py 代码行。PraisonAI 那种高封装方式在快速验证 idea 时很方便，但 career-copilot 的场景（简历评分需要精细调参）更适合底层可控的方式。

但 PraisonAI 的两个思路可以借鉴：

1. **YAML 配置化**：career-copilot 的 pipeline 参数（Stage 1 batch_size、Stage 2 group_size、并发度、JD 截断长度等）散在代码各处。抽成一个 pipeline_config.yaml 统一管理，改参数不动代码。
2. **执行可视化**：smart_score 跑完后只有最终 HTML 报告，没有"pipeline 执行过程"的可视化——哪个阶段耗时最长、哪组 LLM 调用失败了、token 消耗如何分布。即使不做 web UI，输出一份 pipeline_trace.json 也有价值。

---

## 三、规则工程：Less is More

### 来源：andrej-karpathy-skills（GitHub）+ Karpathy 12 Rules 文章

### 关键洞察

Karpathy 提出的编程 Agent 规则系统核心思想是"规则越少越好"——经过从 4 条核心规则迭代到 12 条扩展规则的过程，发现了一个关键阈值：

- **4 条核心规则**（约 200 tokens）：错误率从 41% 降到 11%。投入产出比极高。
- **12 条扩展规则**（约 700 tokens）：错误率进一步降到 3%。边际收益递减但仍有价值。
- **超过 14 条规则**：compliance 开始下降（LLM 无法同时 attend to 太多约束），反而不如 12 条。

核心 4 条规则的精华：

1. 不要臆测——有不确定的就问/搜索/验证
2. 改动最小化——不做用户没要求的事
3. 先理解后动手——写代码前先读懂现有代码
4. 验证再交付——声称完成前先跑测试

规则的格式也有讲究：

- 用祈使句而非描述句（"Always do X" 比 "It would be good if you do X" 有效得多）
- 具体 > 抽象（"删除 console.log" 比 "保持代码整洁" 有效）
- 负面例子和正面例子搭配（让 LLM 看到"错的长什么样"）

### 个人感悟

career-copilot 的 SKILL.md 中有一段"禁止思想"规则和"运行时自检清单"，大约有 15+ 条规则。根据 Karpathy 的发现，这已经接近甚至超过了最优规则数量的阈值。

审视当前规则的问题：

- 有些规则过于抽象：`"最少操作原则"` — 对 LLM 来说不够具体
- 有些规则重复：`"禁止在未经用户确认时修改 SKILL.md"` 和 `"User-Learned Best Practices 不允许自行编辑"` 说的是同一件事
- 缺少负面示例：只说"不要做什么"，没展示"做了会怎样"

改进方向：

1. 将 15+ 条规则精简到 8-10 条（合并重复、删除无效的）
2. 每条规则给一个具体的正/反例
3. 按"违反成本"排序——最容易犯且后果最严重的放最前面
4. 定期审计：哪些规则在实际使用中被违反过？被违反的规则要么重写得更清晰，要么删除（说明 LLM 不 attend to 它）

---

## 四、开发环境与 Agent 配置的最佳实践

### 来源：claude-code-setup（GitHub 项目）

### 关键洞察

这个项目是 Claude Code 的配置最佳实践集合，核心思路是把"Agent 使用环境"当作基础设施来工程化管理：

- **分层配置**：全局 settings.json（所有项目通用）→ 项目级 .claude/（项目特定）→ 会话级临时指令。三层叠加互不冲突。
- **CLAUDE.md 的组织哲学**：
  - 根目录 CLAUDE.md 放"我是谁、项目是什么、核心约束"
  - 子目录 CLAUDE.md 放该目录特有的规则（如 tests/CLAUDE.md 放测试规范）
  - 内容不超过 1500 tokens（否则前面内容会被 attention 稀释）
- **Slash Command 设计**：将重复操作封装为 `/命令`，每个命令有独立的 prompt 文件，可复用可组合。
- **MCP Server 精选原则**：不贪多——每增加一个 MCP Server 就增加几千 tokens 的 tool definitions。只保留真正高频使用的。

关于 CLAUDE.md 的一个反直觉发现：很多人把 CLAUDE.md 写得越来越长越来越详细，以为"给 Agent 越多信息越好"。实际效果是：超过 2000 tokens 后，Agent 对后面内容的遵守率急剧下降。**短而精 > 长而全**。

### 个人感悟

career-copilot 的 SKILL.md 有 306 行。按"1500 tokens 上限"原则来审视，它已经严重超标。这解释了一个我观察到的现象：SKILL.md 后段的"运行时自检"规则经常被 agent 忽略——不是 agent"不听话"，而是 attention 分配不到那里了。

具体改进：

1. SKILL.md 主体压缩到 150 行以内（~1200 tokens），只保留"触发条件 + 核心流程 + 关键约束"
2. 详细的脚本参数说明、reference 文件清单等迁移到 `references/` 目录按需加载
3. 每个 slash command 对应一个独立场景（`/match` 对应岗位匹配流程、`/prep` 对应面试准备流程），避免一个 prompt 塞入所有场景的上下文

---

## 五、开发工具链与数据库创新

### 来源：SmithDB / LangSmith

### 关键洞察

SmithDB 是 LangSmith 团队新推出的针对 trace 数据分析的专用数据库，核心卖点是针对 LLM observability 场景的极致查询性能：

- **技术栈**：Rust + Apache DataFusion（查询引擎）+ Vortex（列式存储格式），对比传统 PostgreSQL + JSONB 方案获得 6-15x 查询加速
- **设计理念**：trace 数据（Agent 执行日志）是"写入密集+分析查询为主"的，不适合通用 OLTP 数据库。传统方式把 trace 存到 Postgres 的 JSONB 列，查询时需要全表扫描解析 JSON。SmithDB 用列式存储预解析存储，查询时直接过滤，性能差异 10x+
- **Stateless Service 架构**：所有数据存在对象存储（S3），SmithDB 本身无状态，扩缩容只是增减查询节点。对比传统数据库的"有状态主从复制"模式，运维复杂度大幅降低
- **未开源**：这是 LangSmith 的商业竞争力之一，短期内不会开源

与 career-copilot 的间接关联：

- LangSmith 作为 LLM observability 平台，其核心能力（trace 收集、prompt 版本管理、评分对比）正是 career-copilot 在手动做的事
- smart_score 每次运行产生的 intermediate results（Stage 1 分数、Stage 2 对比推理、最终排序）本质上就是"trace 数据"
- 如果用 LangSmith 记录 pipeline 执行过程，可以：对比不同 prompt 版本的评分质量、发现哪个 Stage 的 LLM 调用最不稳定、追踪具体某个 JD 的评分推理链

### 个人感悟

虽然 SmithDB 不开源且对我们的项目规模来说杀鸡用牛刀，但它代表的"LLM 执行可观测性"思路非常值得借鉴。

career-copilot 目前的可观测性几乎为零：跑完 smart_score 只看最终 HTML 报告，中间发生了什么是黑盒。改进方向：

1. **轻量 trace 记录**：每次 LLM 调用记录 `{stage, group, prompt_tokens, completion_tokens, latency_ms, model, success}` 到一个 JSONL 文件
2. **Prompt 版本化**：system prompt 改动时记录版本号，trace 中关联版本号，方便对比不同 prompt 版本的效果
3. **异常 trace 标记**：当解析失败、分数异常、自愈触发时在 trace 中高亮，方便事后排查

不需要 LangSmith 那样的重型系统，一个 `pipeline_trace.jsonl` + 简单的 Python 分析脚本就够用了。

---

## 六、总结：从外部资源中提炼的核心行动方向

### 方向 A：智能模型路由（来自 oh-my-claudecode）

不同阶段用不同模型——粗筛用快模型，精排用强模型，省 30-50% 成本。OMC 用环境变量 `MODEL_LOW/MEDIUM/HIGH` 驱动三级路由，career-copilot 可以类似地在 config 中为每个 Stage 指定 model tier。

### 方向 B：规则精简工程（来自 Karpathy 12 Rules + claude-code-setup）

SKILL.md 从 300 行压缩到 150 行以内，规则从 15+ 条精简到 8-10 条，详细内容外移为按需加载。这不是"删减功能"，而是"提升遵守率"。Karpathy 的量化数据：>200 行合规率从 76% 暴跌到 52%，>14 条规则 compliance 急剧下降。

### 方向 C：Pipeline 配置化（来自 PraisonAI）

所有可调参数（batch_size、concurrency、model、截断长度等）抽成 YAML 配置文件，改参数不动代码。PraisonAI 的 `context: [previous_task]` 显式依赖声明也值得借鉴——为 pipeline 每步增加 input/output schema。

### 方向 D：执行可观测性（来自 SmithDB/LangSmith）

每次 LLM 调用输出轻量 trace，pipeline 结束后可分析耗时分布、失败率、token 消耗。LangSmith 的 `@traceable` 装饰器模式可以本地化实现为简单的 JSONL 日志。Prompt 版本管理（prompts/ 目录 + 版本号）让 prompt 迭代不改代码。

### 方向 E：Slash Command 场景隔离（来自 claude-code-setup + oh-my-claudecode）

一个 SKILL.md 不承担所有场景。拆成 `/match`、`/prep`、`/resume`、`/plan` 等独立 command，每个只加载相关上下文。

### 方向 F：Working Memory 层（来自 claude-code-setup 的 Dual-Memory）⭐ 补充

新增 `career-context.md` 作为即时上下文——只记录"当前阶段、焦点公司、关键截止日期、待办"等 ~200 tokens 的信息。会话启动时先读这个轻量文件，而非完整 profile 快照。

### 方向 G：判断质量评估（来自 LangSmith Evaluation + Karpathy 实验设计）⭐ 补充

当前 verify_output 只验证"输出结构完整性"，不验证"判断是否准确"。需要建立 golden test cases（15-20 个真实匹配案例的人工标注），对比模型输出 vs 人工评分，量化匹配质量。这是 prompt 迭代的量化基础。

### 方向 H：Pipeline 数据契约（来自 PraisonAI + LangSmith RunTree）⭐ 补充

为 pipeline 每步声明显式的 input/output schema + 类型标注（"模型判断"vs"代码确定性"）。事件日志增加 trace_id，使"回顾某家公司完整历程"变成一次查询。

### 方向 I：Meta 权衡声明 + 200 行硬约束（来自 Karpathy + OMC）⭐ 补充

SKILL.md 顶部增加权衡声明："简单问题可跳过完整框架"。结合 autonomy 等级概念：首次使用多确认，熟悉后只在异常暂停。200 行硬上限作为铁律执行。

---

*笔记完*
