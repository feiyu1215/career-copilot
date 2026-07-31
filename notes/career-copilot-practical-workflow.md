<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# career-copilot 实操工作流（基于 Matt Pocock skills 体系适配）

> 本文是把 Matt Pocock 的 `mattpocock/skills`（14 万星，agentic-coding 工作流）中**对求职助手有用**的部分，翻译成 career-copilot（单 skill + OpenClaw）能跑的形式。
> 配套文档：`notes/archive/skill2.0-upgrade-plan.archived.md`（2.0 升级，已执行第一批/第二批）、`skill-writing-audit.md`（结构层审计 #1–#11，待执行）。
> 本文属于**能力层**创新，与结构层审计互不冲突。

> ⚠️ **时效性提醒**：本文写于「对齐模式 = 带推荐答案多问」阶段。当前 `SKILL.md` ① 对齐模式已升级为 **deep-grill 哲学**（Agent 先调查、再自我反驳、只批量升级主观分歧 + Socratic 兜底），设计以 `SKILL.md` 为准，本文保留作决策史参考。

---

## 0. 适配前提（为什么不能直接照搬）

| Matt 的体系假设 | career-copilot 的现实 | 后果 |
|----------------|---------------------|------|
| 13+ 个独立 skill，Claude Code 插件 | 1 个内聚 skill，跑在 OpenClaw | 不能拆成 `/grill-me` `/tdd` 斜杠命令 |
| 面向「软件仓库 + agentic coding」 | 面向「人的求职全流程」 | `tdd`/`git-guardrails` 等代码 skill 不对应功能 |
| 有 `setup-matt-pocock-skills` 初始化追踪器 | OpenClaw 无此机制 | 用现有 `career-context.md` 当追踪器 |

**三条硬约束（来自本项目的既有决策）：**
1. **保灵活性**：career-copilot 的立身之本是「用户说模糊口语，AI 灵活判断走哪条路」。不引入显式命令收口（用户在 2.0 升级中明确否决）。
2. **单 skill 不拆**：数据强耦合（匹配结果同时喂简历+面试），拆多 skill 反而要跨 skill 传数据，OpenClaw 难编排。
3. **运行时无关**：只用通用最佳实践，Claude Code 专属 frontmatter 字段（model/effort/allowed-tools）不照搬。

→ 结论：**只搬「思想上能翻译」的，且内化成单 skill 的「模式（mode）」**，靠自然语言触发，不靠斜杠。

---

## 1. 筛选结果：Matt 的 skill 哪些对 career-copilot 有用

### 1.1 直接有用（功能层，内化为模式）
| Matt skill | 用途 | 在 career-copilot 变成 | 价值 |
|-----------|------|----------------------|------|
| `grill-me` | 动手前逐条追问，每题带推荐答案 | **对齐模式**：模糊目标→追问(带默认)→决策记录 | 高（已有雏形，系统化） |
| `grill-with-docs` | 追问同时维护领域模型/词汇表/ADR | 对齐模式 + 维护「求职决策记录」(ADR 式) | 高 |
| `to-spec` | 讨论→结构化 spec（用户故事+测试决策） | **规划模式**→「求职 spec」：目标/时间线/材料/成功标准 | 高（新能力） |
| `to-tickets` | spec→带依赖的任务切片 | 规划模式→周度 tickets，写入 `career-context.md` 待办 | 高（新能力） |
| `handoff` | 会话压缩成交接文档，跨会话保记忆 | **交接模式**：强化现有 `career-context.md` 写入 | 中（已有，做厚） |

### 1.2 概念有用（需跨工具/运行时，先记为「路由建议」）
| Matt skill | 用途 | career-copilot 如何处理 |
|-----------|------|----------------------|
| `comprehensive-thinking` | 复杂判断 | 用户说「offer A 还是 B 怎么选」时，SKILL.md 建议路由到思考层做结构化推理（WorkBuddy 侧已有此能力；OpenClaw 侧需等价能力或人工接管） |
| `research` | 带引用背景调研 | 用户说「调研某司 AI 岗」时路由到调研层，产出带引用 markdown |

### 1.3 元活动有用（维护 career-copilot 自身代码，独立工作线）
| Matt skill | 用途 | 处置 |
|-----------|------|------|
| `improve-codebase-architecture` / `code-review` / `tdd` / `diagnosing-bugs` | 代码体检/审查/测试/调试 | **已由 Ponytail 工作线覆盖**（独立，不混入本计划） |

### 1.4 不适用（求职助手场景无对应物）
`git-guardrails`、`resolving-merge-conflicts`、`migrate-to-shoehorn`、`setup-pre-commit`、`codebase-design`、`prototype`（代码原型）、`triage`（issue 分拣，单人求职无 issue 流）、`teach`（教学，边际）、`ask-matt`（元导航，可改为「本 skill 内自检」）、`wayfinder`（超大任务地图，部分被规划模式吸收）。

---

## 2. 创新点：把「13 命令插件」收敛成「1 个 skill 的 5 个模式」

**核心创新**——Matt 用「多 skill + 斜杠命令」解决「长任务前对齐、过程可追溯、跨会话记忆」；career-copilot 用「单 skill + 内部模式」解决同一件事，且**不牺牲 AI 灵活性**。

每个模式 = `自然语言触发` + `内部固定流程` + `副作用需显式确认`（沿用 Matt 的「有副作用的手动触发」原则）。

| 模式 | 触发（自然语言示例） | 内部流程 | 副作用确认 |
|------|------------------|---------|-----------|
| **A 对齐** | 「我想进腾讯 AI 岗，但没想清楚」 | 读 context→问 3–5 个关键点(各带推荐答案)→记录决策 | 写决策记录需确认 |
| **B 规划** | 「帮我规划接下来一个月」 | 目标→求职 spec→周度 tickets | 写 tickets 到 context 需确认 |
| **C 调研** | 「调研下 A Muse Lab」 | 拉公开信息→带引用整理 | 无（只读） |
| **D 研判** | 「offer A 和 B 怎么选」 | 结构化多视角推理 | 无（只读） |
| **E 交接** | （会话结束自动） | 更新 career-context：状态/已决策/待决策/下一步 | 写 log 沿用现有 `[R]` |

**与现有 SKILL.md 的咬合：**
- 对齐模式 = 强化现有「模糊输入 1 问澄清」（从「1 个问题」升级为「带推荐答案的多问 + 决策记录」）
- 交接模式 = 强化现有 `career-context.md` 写入（从「状态便利贴」升级为「结构化交接单」）
- 规划/调研/研判 = 新增能力，各加一个 reference（不拆 skill）

---

## 3. 实操版日常流（直接能上手）

镜像 Matt 的 ①②③④⑤，但换成求职语境：

```
① 用 对齐模式 把"【你的求职目标】"问清楚
   → 产出 career-spec（目标岗位 / 时间线 / 必需材料 / 成功标准）+ 决策记录
② 用 规划模式 把上面的讨论整理成周度 tickets
   → 每周动作切片（如：第1周改简历、第2周投X个JD+准备A面试），标好依赖
③ 用 调研模式 调研目标公司 / 岗位
   → 带引用的 markdown（业务/岗位/面试官画像）
④ 用 研判模式 处理 offer / 方向抉择
   → 结构化多视角推理，给结论 + 理由 + 风险
⑤ 会话结束自动 交接模式
   → 更新 career-context.md（状态 / 已决策 / 待决策 / 下一步）
```

**清上下文纪律**（对应 Matt「每个 ticket 之间清上下文」）：每个周度 ticket 之间，清空**对话历史**但从 `career-context.md` 重新载入记忆——保记忆不保冗余历史，避免长对话迷失。

---

## 4. 速查表：每个模式一句话 + 怎么调

**对齐 / 规划**
| 模式 | 怎么调 |
|------|--------|
| 对齐 (grill) | 「用对齐模式 梳理【X 求职目标】」— 边问边建决策记录 |
| 规划 (spec+tickets) | 「用规划模式 把【目标】拆成周计划」 — 产出 spec + tickets |

**调研 / 研判**
| 模式 | 怎么调 |
|------|--------|
| 调研 (research) | 「用调研模式 查【某公司/岗位】」 — 带引用 markdown |
| 研判 (thinking) | 「用研判模式 分析【offer A vs B】」 — 结构化推理 |

**交接（自动）**
| 模式 | 怎么调 |
|------|--------|
| 交接 (handoff) | 会话结束自动跑；也可「用交接模式 总结当前进度」手动触发 |

---

## 5. 与现有优化计划的关系

| 层 | 来源 | 内容 | 状态 |
|----|------|------|------|
| 结构层 | 如何写好 Skill audit (#1–#11) | 移 README / 负向触发测试 / reference 章节化 / 打分 / 基线 / description 瘦身 | 待执行（#1 最高优先） |
| 能力层 | 本文（Matt 体系适配） | 对齐/规划/调研/研判/交接 5 模式 | 设计完成，待落地 |
| 元活动层 | Ponytail 工作线 | career-copilot 自身 Python 代码体检 | 独立，已装 Ponytail 到 WorkBuddy |

三层正交，执行顺序建议：先结构层（便宜、踩硬规则），再能力层（对齐+交接先小改，规划+调研+研判后加）。

---

## 6. 落地批次建议（不在本文执行）

- **P0（小改，强化已有）**：对齐模式（升级现有「1 问澄清」为「带推荐答案多问+决策记录」）+ 交接模式（升级 context 为结构化交接单）。改 `SKILL.md` + 加 `references/decision-log.template.md`。
- **P1（新增能力）**：规划模式（加 `references/job-search-spec.md`）+ 调研模式（加 `references/company-research.md`）。
- **P2（路由建议）**：研判模式在 SKILL.md 里写明「复杂抉择路由到思考层」，等 OpenClaw 侧有等价能力或用户手动在 WorkBuddy 跑。

---

## 7. 经 grill-me + spec-driven-development 完善后的可执行计划

> 本节用两个 skill 实际跑了一遍来完善计划：
> - **grill-me（→ WorkBuddy `grilling`）**：逐枝拷问计划，挖出此前只有模糊"待确认"、未真正想透的 **6 个决策点**（D1–D6）。
> - **spec-driven-development**：把结构层 + 能力层 + 元活动层三份零散计划，落成**一份 spec（六核心区）+ 8 个可验收 ticket（T1–T8）**。

### 7.1 Spec（结构化规格）

**Objective**
把 career-copilot（单 skill，OpenClaw）从「能用」升级为「5 模式 + 结构卫生」的可信求职助手。
- 用户故事：求职者在模糊口语下，AI 灵活进入 对齐 / 规划 / 调研 / 研判 / 交接 任一模式；会话间不丢上下文；关键操作自动留痕。
- 成功：§7.3 验收全过，且优化**不牺牲 AI 灵活性**（单 skill 不拆、无硬命令）。

**Tech Stack / 运行时**
- OpenClaw skill：`SKILL.md`(≤500 行) + `references/*.md` + `scripts/*.py`，安装 `~/.catpaw/skills/career-copilot/`
- 不迁 Claude Code；不引入 `plugin.json` / `commands/` / `hooks/` 目录

**Commands（优化执行的动作）**
- 编辑：`SKILL.md`「会话生命周期」段 + 加 reference 模板（手改，无构建步骤）
- 评测：OpenClaw 侧 evals 机制待 T2 按 D5 决策确认

**Project Structure（保持）**
```
career-copilot/
  SKILL.md                # 入口 + 5 模式路由 + 会话生命周期
  references/             # 领域知识（按需加载，标 ~tokens）
  scripts/                # 确定性逻辑
  notes/                  # 规划文档（运行时不加载）
  evals/evals.json        # 触发 + 质量评测
```
⚠️ README.md 需按 T1/D4 移出 skill 文件夹。

**Code Style**
- 渐进式披露：SKILL.md 只放导航 / 原则 / 步骤 / 验证，细节进 references
- 软路由：自然语言触发，不预设命令
- 约束分级：`[R]` 强制 / `[H]` 硬钩子

**Testing Strategy**
- 触发层：`evals.json` 含 `should_trigger:true` + `false` 用例（T2）
- 质量层：结构化 `assertions` + 0–10 打分（T2 扩展现有 7 条）
- 基线：开 / 关 skill A/B（T2，待 OpenClaw 验证）

**Boundaries**
- **Always**：保单 skill / 保 AI 灵活 / 会话先读 context（用户可改全量）/ 副作用先确认
- **Ask first**：拆多 skill / 迁运行时 / 改 pipeline 脚本 / 改 `fetch_jobs`
- **Never**：显式 `/命令` 收口 / `plugin.json` / 删 pipeline / 求职决策全自动执行不确认

**Success Criteria**
- [ ] 5 模式均可自然语言触发，无需 `/命令`
- [ ] 结构层 #1 移 README 完成；#2 负向触发测试存在；#3 reference 章节化
- [ ] 原验收清单（skill2.0 §6）全过
- [ ] 优化后 `SKILL.md` ≤ 500 行

### 7.2 决策点（grill-me 拷问产出，每条带推荐答案）

| # | 决策点（计划原本模糊） | 推荐答案 | 影响 |
|---|----------------------|---------|------|
| **D1** | 规划模式的 spec / tickets 存哪？ | 存 `career-plan.md`（本地；OpenClaw 无 GitHub issues）；周度 tickets 同步进 `career-context.md` 待办 | 决定 T6 |
| **D2** | 研判模式（comprehensive-thinking）跨运行时怎么落地？ | SKILL.md 写「复杂抉择路由到思考层」；用户在 WorkBuddy 侧手动跑 comprehensive-thinking，OpenClaw 侧暂用内置推理 | 决定 T8 |
| **D3** | 对齐模式的「决策记录（ADR）」存哪？ | 单独 `references/decision-log.template.md` + 关键结论写回 `career-context.md`「已决策」 | 决定 T4 |
| **D4** | #1 移 README：career-copilot 当前是本地 skill 文件夹，无 GitHub 仓库根，移到哪？ | 安装说明**内联进 SKILL.md 末尾「安装」段**（避免悬空文件）；若未来建 git 仓再移到 repo 根 | 决定 T1 |
| **D5** | #2 负向触发测试在 OpenClaw 怎么跑？`evals.json` 是 SkillLens/Claude Code 格式 | 先验证 OpenClaw 是否读 `evals.json`；若不读，把负向用例写成 SKILL.md「不应触发」示例段 | 决定 T2 机制 |
| **D6** | #3 reference 章节化粒度：拆文件 vs 加 TOC？ | 先加**章节 TOC** + SKILL.md 指引「面试只需加载 §X」，不拆文件（避免跨文件引用复杂化） | 决定 T3 |

> 以上 6 点请拍板（可整体认可推荐答案，或改任意一条）。拍完即按 §7.3 落地。

### 7.3 Tasks（spec-driven 拆票，按依赖排序）

- [ ] **T1**：结构层 #1 移 README（按 D4 内联安装说明到 SKILL.md）
  - 接受：skill 文件夹无 README.md；安装步骤在 SKILL.md
  - 验证：`ls` 确认无 README.md；SKILL.md 含「安装」段
  - 文件：SKILL.md、删/移 README.md
- [ ] **T2**：结构层 #2 负向触发测试（按 D5）
  - 接受：`evals.json` 含 ≥3 条 `should_trigger:false`；或 SKILL.md 有「不应触发」示例段
  - 验证：跑评测，负例不触发
  - 文件：evals/evals.json 或 SKILL.md
- [ ] **T3**：结构层 #3 reference 章节化（按 D6）
  - 接受：`interview-prep` / `career-memory` 顶部有 TOC；SKILL.md 指引按需加载章节
  - 验证：加载指定章节不全载
  - 文件：references/*.md、SKILL.md
- [ ] **T4**：能力层 P0 对齐模式（按 D3）
  - 接受：模糊目标 → 带推荐答案多问 → 写 decision-log；SKILL.md 有对齐模式流程
  - 验证：模拟「没想清楚」输入，产出决策记录
  - 文件：SKILL.md、references/decision-log.template.md
- [ ] **T5**：能力层 P0 交接模式
  - 接受：`career-context` 升级为结构化交接单（状态 / 已决策 / 待决策 / 下一步）；session-end 明令写
  - 验证：一会话结束，context 含结构化交接
  - 文件：SKILL.md、career-context.template.md
- [ ] **T6**：能力层 P1 规划模式（依赖 D1）
  - 接受：目标 → career-spec → 周度 tickets；存 `career-plan.md` + context 待办
  - 验证：输入目标，产出 spec + tickets
  - 文件：SKILL.md、references/job-search-spec.md、career-plan.md
- [ ] **T7**：能力层 P1 调研模式
  - 接受：公司 / 岗位 → 带引用 markdown
  - 验证：输入公司名，产出调研
  - 文件：SKILL.md、references/company-research.md
- [ ] **T8**：能力层 P2 研判模式路由（依赖 D2）
  - 接受：SKILL.md 写明复杂抉择路由到思考层
  - 验证：输入 offer 抉择，给出路由建议
  - 文件：SKILL.md

**依赖与执行序**：T4/T5 独立于 T1–T3（不同文件）；T6 依赖 D1；T8 依赖 D2。
建议序：**T4 → T5**（快、强化已有）→ **T1 → T2 → T3**（结构卫生，便宜且踩硬规则）→ **T6 → T7 → T8**。

> 本节为**经 skill 完善后的可执行计划**，仍未改动 `SKILL.md` / pipeline / 运行时。落地需你先拍板 §7.2 的 D1–D6。
