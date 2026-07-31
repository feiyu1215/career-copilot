<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->

<!-- SUPERSEDED: 2026-07-30 归档至 notes/archive/。本文件内容已被实际实现（v2 多门户抓取 / Tier2 简历生成 / Phase 8 系列 / 端到端编排器等）取代，仅作历史参考，不再作为待办来源。 -->

> [SUPERSEDED] 本文档已于 2026-07-30 归档，已移入 `notes/archive/`。内容多为早期规划 / 灵感探索，已被实际实现取代，不再作为活跃待办。当前改进跟踪以 `notes/evolution-log.md` 与 `evals/` 为准。

# Career Copilot · Skill 2.0 升级方案（OpenClaw 适配版）

> **📌 状态（2026-07-21）**：早期灵感探索（Skill 2.0 / Plugin 方法论），部分项已落地（见文末验收清单 `[x]`）。当前活跃执行计划为 `audit-borrowing-plan.md`（2026-07-21，8/8 全做）；本文件保留为历史参考，非当前待办清单。

> 依据公众号文章《用完全网最火的 PM Skills，我决定把 163 个 Skill 推倒重做》（Skill 2.0 / Plugin 方法论）评估本项目后制定的升级计划。
> 适用运行时：career-copilot 当前跑在 OpenClaw / CatDesk（单 `SKILL.md`，安装于 `~/.catpaw/skills/`）。
> 制定日期：2026-07-09
> 关联文档：`improvement-roadmap.archived.md`（既有路线图，本文在其基础上做 2.0 视角修正）

> **🚧 边界说明（与 Ponytail 解耦）**：Ponytail 已作为**独立 skill** 安装在 WorkBuddy 上，后续可用于对 career-copilot 的 `scripts/` 做"过度工程 / 技术债"审计。但那是**另一条独立工作流**，**不在本 2.0 升级计划内**。本计划只解决"跨会话记忆 + 自动化 hooks + 软路由增强 + 模块化"的**方法论升级**，不触及代码精简、不碰 pipeline 脚本、不迁运行时。两者请分开推进，不要混为一谈。

---

## 0. 一句话结论

career-copilot **需要升级，但是「把已有的 2.0 思想收口」，不是「范式重写」**。且**绝不做「显式命令收口」**——因为本项目是「单 skill、AI 原生、靠灵活理解意图吃饭」，硬塞显式命令反而钝化它最大的优势。

---

## 1. 为什么「显式命令收口」对我这个项目不合理（重要修正）

文章里 `command` 的价值场景是：**仓库里有几十个 skill 散落，AI 经常挑错、用户记不住名字时，用 `/discover` 这种斜杠命令把一串 skill 串起来**。

但 career-copilot 是 **1 个内聚 skill**，它的价值恰恰是：
- 用户说「帮我看看这个 JD 适不适合我」「我该怎么找工作」这种**模糊、口语、跨场景**的话，AI 能灵活判断该走匹配 / 面试 / 简历 / 规划哪条路；
- 模块间数据强耦合（`scored_results` 同时喂简历和面试，`profile` 喂全部），本就该在一个 skill 内灵活流转。

如果硬加 4 个显式命令入口（`/match /prep /resume /plan`），等于：
1. **钝化 AI 灵活性**——用户说了句新话，AI 被逼进 4 个固定桶之一，丢了「理解意图」这个 skill 的立身之本；
2. **自相矛盾**——前面决定「不拆成多 skill」，后面却用「命令串多 skill」的套路，而 command 本身就是为「多 skill 编排」设计的，套到单 skill 上错位；
3. **文章触发条件不满足**——文章自己说「skill > 10 才改 plugin / 用 command 组织」，本项目只有 1 个 skill。

**结论**：意图路由表（5 行）保留作「软引导」，但**不升级为强制命令**。`command` 这套只在「未来真把本 skill 拆成多个原子 skill」时才用得上——而本项目决定不拆。

---

## 2. 本项目真正该升级的 2.0 思想（适配 OpenClaw）

文章的 2.0 四件套里，对「单 skill + OpenClaw」真正有用的是这三件（且都不钝化 AI）：

| 2.0 概念 | 本项目对应升级 | 是否钝化 AI |
|---------|---------------|-----------|
| **Working Memory**（轻量上下文） | `career-context.md` 会话必读 | ❌ 不钝化，反而让 AI 更快进入状态 |
| **Hooks（强制约束）** | 已有 verify + 运行时自检，补「收尾写 log」明令 | ❌ 不钝化，是兜底 |
| **Hooks（自动化重复动作）** | session-start 读 context / session-end 写 log 明令为步骤 | ❌ 不钝化 |
| Command（显式命令串） | **不做** | ✅ 会钝化（见第 1 节） |
| Plugin 打包 | **不做**（OpenClaw 不支持，且 1 skill） | — |
| 拆多 skill | **不做**（数据强耦合） | — |

---

## 3. 详细升级项

### 3.1 Working Memory 层（优先级 P0，最大收益）

**现状**：每次会话开始要读 `career-profile.md`（~2000 tokens）才知道进度；且只有「重 profile」，没有「当前在干嘛」的轻量状态。

**做法**：
- 新增 `career-context.md`（~200 tokens），只记「即时上下文」：
  ```markdown
  # 当前求职上下文
  - 当前阶段: 面试期 / 匹配期 / 规划期
  - 焦点公司: [A-三面待通知, B-已拿offer]
  - 关键截止: 6月15日前决定
  - 上次操作: 5月28日 匹配新一批岗位
  - 待办: 准备C技术面
  - 上次匹配 top3: [X, Y, Z]
  ```
- 在 `SKILL.md`「记忆」段改为：**会话第 1 步先读 `career-context.md`（~200 tokens）；需要历史细节再读 `career-profile.md`**。
- 每次关键操作后**更新** `career-context.md`（见 3.2 session-end）。

**收益**：会话启动 token 2000 → 200，AI 立即知道进度，跨会话连续性 ↑。这正是文章 hooks + working memory 想解决的核心痛点。

**实现注意**：OpenClaw 无 OS 级 hook，所以「会话第 1 步必读」用 `SKILL.md` 强制步骤实现，效果等同 Claude Code 的 `session-start` hook。

### 3.2 自动化 Hooks（优先级 P0 / P1）

把「每次都得做」的动作明令为强制步骤（OpenClaw 下即 `SKILL.md` 规则）：

**session-start（开始必做）**
- `[R]` 读 `career-context.md` 了解当前状态（见 3.1）。

**session-end（收尾必做）**
- `[R]` 关键操作（匹配完成 / 面试记录 / 简历修改）后，调用 `career_log.py` 写入 `career-log.jsonl`，并同步更新 `career-context.md` 的「上次操作 / 待办 / 阶段」。
- 现有 `evolution-log`（站点经验 → `memory_write`）保持，并入此收尾流程。

**已有强制约束（保持并强化）**
- `verify_output.py` 在 `smart_score` 后不可跳过（已有 `[H]`）。
- `运行时自检` + `禁止思想` 表保持（强制兜底）。

**收益**：记忆自动维护、跨会话不丢上下文、AI 不会「忘了刚才干了啥」。

### 3.3 意图路由优化（软引导，非硬命令）

**现状**：`SKILL.md` 已有 5 行意图路由表，AI 靠 description 匹配触发。

**做法（保持灵活，只做增强）**：
- 路由表**保留作软引导**，不改为强制命令。
- 增强 `description` 触发词覆盖（roadmap P0 已规划：加英文短语 + 口语触发），让模糊表述也能命中。
- 对**高度模糊 / 跨场景**的输入（如「我该怎么找工作」），加一条轻量「意图澄清」：先读 `career-context.md`，再用 1 个问题确认走哪条路，**不预设命令**。

**不做**：不引入 `/match` 等硬命令入口（理由见第 1 节）。

### 3.4 模块化保持 + 按需加载（优先级 P1）

**现状**：`SKILL.md` 路由 → references 注入 → scripts 执行，已较清晰。

**做法**：
- **保持 1 个 `SKILL.md` + references 模块化**（不拆多 skill）。
- 给每个 reference 标注 `~tokens: N`（roadmap 已规划），帮 AI 做加载决策，避免一次加载全部。
- 明确模块间**数据契约**：`scored_results.json` schema 固定（匹配 → 简历 / 面试读取的字段不变），避免某模块改输出结构静默影响下游（roadmap 十二 Pipeline 数据契约）。

### 3.5 可靠性 / 自愈（沿用现有 roadmap，不在本文新增）

以下已在 `improvement-roadmap.archived.md` 规划且部分完成，是「强制 hooks」的工程体现，继续推进即可：
- Pipeline Checkpoint（`--resume`）✅
- fetch_jobs 原子化保存 ✅
- verify_output 四层 JSON 自愈（P1）
- LLM Provider 自动降级（P1）

---

## 4. 明确不做的（Anti-patterns）

| 不做 | 原因 |
|------|------|
| 显式 command 入口（`/match` 等） | 钝化 AI 灵活性；单 skill 不需要多 skill 编排；文章触发条件不满足 |
| `plugin.json` / `commands/` / `hooks/` 目录 | Claude Code 专属格式，OpenClaw 不支持 |
| 拆成 5 个原子 skill | 模块数据强耦合，拆了要跨 skill 传数据，OpenClaw 难编排 |
| 迁 Claude Code | 除非另议；`fetch_jobs.py` 依赖 CatDesk 浏览器自动化，新运行时无等价物，核心抓取或失效 |

---

## 5. 优先级与工作量

| 批次 | 升级项 | 工作量 | 收益 |
|------|--------|--------|------|
| 第一批 | 3.1 `career-context.md` + 3.2 session 起止明令 | 1-2 小时 | 跨会话连续性 ↑、启动效率 ↑ |
| 第二批 | 3.3 意图路由软增强（触发词 + 澄清） | 0.5 小时 | 模糊输入命中率 ↑ |
| 第三批 | 3.4 reference token 标注 + 数据契约 | 1 小时 | 注意力集中、数据流可靠 |
| 持续 | 3.5 可靠性（沿用 roadmap） | 迭代 | 自愈能力 ↑ |

---

## 6. 验收标准

- [ ] 新会话开始时，AI 先读 `career-context.md`（~200 tokens）而非全量 profile
- [ ] 一次完整匹配后，`career-context.md` 的「上次操作 / 待办 / 阶段」被更新
- [ ] 收尾写 `career_log` 成为明令步骤，不再依赖「AI 记得」
- [ ] 模糊口语输入（如「我该咋办」）能被路由到合适模块，而非卡死或乱猜
- [ ] `SKILL.md` 仍保持单 skill 结构，未引入 plugin / command 文件

---

*本方案基于 Skill 2.0 方法论，但针对「单 skill + OpenClaw + 数据强耦合」做了适配修正：保留 AI 灵活性，只收口 Working Memory 与自动化 Hooks，不做显式命令收口与 Plugin 打包。*

---

## 7. 执行记录

**执行日期**：2026-07-09（serious-mode 高标准执行）

**第一批（P0，已执行）** — 仅方法论升级，未碰 pipeline 脚本、未迁运行时、未引入 Ponytail：
- 新增 `references/career-context.template.md`：轻量上下文模板（字段 schema + 初始化/更新规则 + 隐私约束）
- `SKILL.md`「记忆」段改写：分层——先读 200-token context，按需读 2000-token profile
- `SKILL.md` 新增「会话生命周期（强制步骤）」：session-start `[R]` 读 context（模糊输入 1 问澄清，不预设命令）+ session-end `[R]` 写 log 并同步更新 context

**第二批（3.3 意图路由软增强，已执行）**：
- `SKILL.md`「意图路由」表扩为 4 列，新增「触发词（口语 / 英文 / 边界）」覆盖模糊表述
- 新增「模糊 / 跨场景输入」正式澄清规则（带默认、给行动、不预设命令）；session-start 对应行改为指向该规则
- 验收「模糊口语输入（如『我该咋办』）能被路由到合适模块，而非卡死或乱猜」已满足

**两次用户反馈修正（2026-07-09，均针对 session-start 读取范围）**：
1. **去绝对化**：原「第 1 步必读 200-token context」过于绝对 → 改为条件式：优先读 context，但 (a) 新用户 / 无 context、(b) 用户明确要求读全量 时直接读全量 `career-profile.md`（效率让位于用户意图与常识）。同步更新「记忆」段 bullet 与「读取策略」一行。
2. **交还决定权**：进一步改为**动手前先向用户确认读取范围**——读轻量 context 掌握状态后，给用户三选一（a 用便利贴继续 / b 读全量档案 / c 重新读或重建），不阻塞、用户直接说话即视为选默认。新用户 / 无 context 无选项、直接读全量或走 onboarding；会话中途用户要求全量 / 重读立即执行。「记忆」段 bullet 与「读取策略」同步改为「由用户决定读取范围」。`SKILL.md` 三处口径已对齐。

**未做（红线）**：显式 `/命令` 入口、plugin.json、拆多 skill、迁 Claude Code、Ponytail 审计（独立工作线）。

**验收对照（计划 §6）**：
- [x] 新会话先读 `career-context.md`（~200 tokens）而非全量 profile
- [x] 关键操作后 `career-context.md` 的「上次操作 / 待办 / 阶段」被更新
- [x] 收尾写 `career_log` 成为明令步骤 `[R]`
- [x] 模糊口语输入先读 context 再 1 问澄清，不卡死/不预设命令
- [x] `SKILL.md` 仍单 skill 结构，无 plugin / command 文件

**遗留 / 后续批次**：第三批（3.4 reference token 标注 + 数据契约）尚未执行。
