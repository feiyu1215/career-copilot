# Career-Copilot 升级计划：EasySlides 架构启发

> **背景**：基于对 easyslides skill 深层架构（strategist.md / executor-base.md / resume-execute.md / template-asset-bank.md / topic-research.md）的完整审视，经 serious-mode + fundamental-thinking + rational-skepticism 三重框架批判后，提炼出对 career-copilot 有真实迁移价值的改进方向。
>
> **原则**：只纳入"career-copilot 确实存在相同问题"的改进，拒绝"easyslides 有所以我们也要有"的惯性平移。不重复 improvement-roadmap.md 中已有的方向。
>
> **与现有 roadmap 的关系**：本文档是 improvement-roadmap.md 的**补充层**，新增 3 个维度 + 对 2 个已有方向的深化建议。

---

## 一、约束分级制度（新增维度）

### 问题诊断

easyslides 将规则分为 4 级：Hard Rule（违反即作废重做）/ Required（高优先，极端情况可申请豁免）/ Recommended（最佳实践）/ Relaxable（偏好级）。

career-copilot 当前有三类约束：红线 5 条 / 绝对不要 5 条 / 运行时自检 8 条。但没有显式标注每条的**违反后果严重程度**和**是否可在特定条件下豁免**。例如：

- "不要跳过 verify_output.py" — 违反后果：用户可能看到错误评分数据（**数据正确性**风险）
- "不要前台挂死" — 违反后果：用户等待时间过长（**体验**风险）
- "smart_score 完成后没跑 verify" — 违反后果：同上第一条

这三条在当前文档中**并列出现**，但严重程度差异巨大。Agent 的注意力是有限的（Karpathy 实验：>14 条规则 compliance 下降），不分级意味着 Agent 可能在低严重度约束上消耗注意力，而忽略高严重度约束。

### 设计方案

为 career-copilot 引入三级约束分类：

```
HARD（违反 = 任务失败，必须回退重做）：
- verify_output.py 未通过时继续生成报告
- 编造简历经历/数据
- 记录具体薪资数字到记忆系统

REQUIRED（高优先，仅当用户显式确认时可跳过）：
- 暂停点展示并等待确认
- 评分完成后展示 Sanity Check 结果
- 告知用户当前使用的是 fallback/降级结果

RECOMMENDED（最佳实践，可根据场景轻量化）：
- 后台运行长脚本 + 轮询
- Step 4 后展示完整选项菜单
- 错误 3 次后停止并报告

RELAXABLE（用户说"快速"/"跳过"时可省略）：
- 成本预估展示
- 详细降级路径尝试（可直接报告失败）
```

### 实施步骤

1. 在 SKILL.md 的"红线"段落后，增加一行声明：`规则按 HARD > REQUIRED > RECOMMENDED > RELAXABLE 分级，详见下文标注。`
2. 为"绝对不要"5 条和"运行时自检"8 条各标注级别（如 `[H]` / `[R]` / `[Rec]`）
3. 在 matching-guide.md 的 Sanity Check 和降级路径中同样标注级别

### 预期收益

- Agent 在注意力衰减时仍能保住 HARD 级约束的合规
- 用户说"快速看看"时，Agent 有依据跳过 RELAXABLE 级步骤而不触发自检报警
- 为后续 Compliance 审计（roadmap 十一 P2）提供分级评估维度

### 与 roadmap 的关系

roadmap 十四提到"规则精简到 8-10 条"和"按违反成本降序排列"，本方案是其**具体实现方式**——不只是排序，而是分级+标注可豁免条件。

---

## 二、跨会话恢复的 Context-Budget 隔离（新增维度）

### 问题诊断

easyslides 的 resume-execute.md 定义了严格的跨会话恢复协议：Phase A（恢复期）只读取 artifacts 重建上下文，Phase B（执行期）释放 A 的大部分上下文，确保执行窗口不被恢复信息占满。

career-copilot 的跨会话场景：
- 用户上次跑了 pipeline 到 Step 3（评分完成），暂停了
- 新会话开始，用户说"继续上次的结果"
- Agent 需要加载：career-context.md + boundary_profile.json + scored_results.json（可能 50+ 岗位的详细数据）+ 上次暂停位置

**风险**：scored_results.json 可能有 50-80 个岗位的完整评估（每个含 match_reasons、risks、advice），全量加载可能消耗 8000-15000 tokens 上下文。加上 Agent 的 system prompt + SKILL.md + matching-guide.md，执行窗口所剩无几。

当前 roadmap 中的 Working Memory（十 P0，career-context.md）解决了"启动时快速了解状态"的问题，但没有解决**恢复完整数据后的上下文膨胀**问题。

### 设计方案

定义 career-copilot 的跨会话恢复协议：

```
Phase A — 恢复期（目标：200-500 tokens 恢复摘要）：
1. 读 career-context.md（~200 tokens）→ 确认上次停在哪一步
2. 读 scored_results.json 的 pipeline.metadata（运行参数、时间戳、总数）
3. 只读 tier_A 列表的标题 + 分数（不读完整 match_reasons）
4. 向用户展示恢复摘要："上次你跑了 XX 个岗位的匹配，A 档 N 个，最高分 XX。现在继续？"

Phase B — 执行期（用户确认继续后）：
- 根据用户选择的操作，按需加载：
  - 选"生成报告" → 不需要读 scored_results 详情，直接调 generate_report.py
  - 选"看 A 档详情" → 只加载 tier_A 的完整数据
  - 选"投递策略分析" → 加载 tier_A + boundary_profile
- 执行完成后，更新 career-context.md
```

### 实施步骤

1. 在 matching-guide.md 的"操作经验"段增加"跨会话恢复"子节
2. 定义恢复摘要的生成规则（从 scored_results.json 中提取哪些字段）
3. 在 career-context.md 格式中增加 `last_pipeline_output_path` 字段
4. 明确：恢复期**禁止**读取完整 scored_results.json 到对话上下文

### 预期收益

- 跨会话恢复时的上下文消耗从 ~10000 tokens 降到 ~500 tokens
- Agent 在恢复后仍有充足的上下文窗口用于执行新操作
- 与 Working Memory（roadmap 十）互补：career-context.md 记录"在哪"，恢复协议规定"怎么恢复"

### 与 roadmap 的关系

这是 roadmap 十（Working Memory 层）的**下游延伸**——Working Memory 解决了"存什么"，本方案解决了"恢复时怎么分阶段加载而不撑爆上下文"。

---

## 三、纯推理模式的 Stop Conditions（新增维度）

### 问题诊断

easyslides 的 topic-research.md 定义了明确的研究停止条件：找到 N 个高质量来源 / 关键维度覆盖完整 / 时间预算用尽。

career-copilot 的纯推理模式（JD ≤ 5 或只讨论某个岗位时）定义了判断框架（5 步：定位锚点 → 分析 JD → 估迁移距离 → 检测硬约束 → A/B/C 判断），但缺乏两个场景的 stop conditions：

**场景 1：对话了解用户背景（无简历时）**
- 当前规则："2-3 个关键问题了解背景后用纯推理模式"
- 问题：什么算"了解够了"？如果用户的回答很模糊，是继续追问还是基于有限信息给出初步判断？追问几轮后 stop？

**场景 2：方向不明确时的探索**
- 当前规则（matching-guide）："方向模糊时，任务不是赶紧生成锚点让用户确认，而是先帮用户想清楚"
- 问题：帮用户"想清楚"这件事本身可能无限发散。什么时候从"帮你探索"切换到"给你一个初步定位你先跑着看"？

### 设计方案

为纯推理模式定义显式 Stop Conditions：

```
场景 1：无简历对话了解背景
  Start:  用户没有简历但想知道"这个岗位适合我吗"
  Questions Budget: 最多 3 轮追问（每轮 1-2 个问题）
  Minimum Info Gate: 至少获得以下 3/5 项才能给判断：
    - 当前/最近岗位（做什么的）
    - 工作年限量级（1-3年 / 3-5年 / 5+）
    - 核心技术栈或领域
    - 求职动机（为什么想换）
    - 教育背景（学历层次）
  Stop When:
    - 3 轮追问后，无论信息是否完整 → 基于已有信息给出判断 + 标注置信度
    - 3/5 项信息已获得 → 立即给出判断，不继续追问
  输出要求: 信息不完整时必须标注"基于有限信息的初步判断，置信度 X%"

场景 2：方向探索
  Start:  用户说"不知道想做什么" / 简历跨行 / 搜索方向与简历不一致
  Exploration Budget: 最多 2 轮对话（每轮含分析 + 一个聚焦问题）
  Stop When:
    - 2 轮后无论清晰度如何 → 给出 2-3 个可能方向 + 建议"各跑一批试试"
    - 用户对某个方向表达了明确兴趣 → 立即锚定，不继续发散
    - 用户说"我也不确定" / "都试试" → 采用最宽泛的方向锚点开跑
  Anti-Pattern: 连续追问 > 2 轮方向问题 → 你在拖延。给建议。
```

### 实施步骤

1. 在 SKILL.md 的"匹配引擎核心"→"决策路由"之后增加一个"纯推理 Stop Conditions"小节（~15 行）
2. 在 matching-guide.md 的"纯推理模式"段中扩展具体判断规则
3. 在 onboarding-guide.md 中增加"方向探索的收敛规则"

### 预期收益

- 防止 Agent 在"了解背景"阶段过度追问导致用户不耐烦
- 防止"帮用户想清楚方向"变成无限发散（easyslides topic-research 的核心教训）
- 为置信度标注提供触发条件（不是所有判断都需要标注，只有 stop 条件触发时才强制标注）

---

## 四、对 roadmap 已有方向的深化：Pipeline 配置化中增加"规则绑定"

### roadmap 原方案（六 P0）

创建 pipeline_config.yaml，把 model、batch_size、concurrency 等参数抽出来。

### 深化建议（来自 easyslides 的 spec_lock 思想）

easyslides 的 spec_lock 核心洞察：**配置一旦在执行开始时锁定，中途禁止修改**。这防止了"跑到一半改参数导致前后不一致"。

career-copilot 的对应风险：如果 pipeline_config.yaml 在 pipeline 执行中被修改（比如 Agent 在 Step 2 和 Step 3 之间决定调整 top-k），前半段用旧参数、后半段用新参数，scored_results.json 的一致性被破坏。

**增加规则**：

```yaml
# pipeline_config.yaml 顶部声明
_meta:
  lock_policy: "snapshot_at_start"
  # pipeline 启动时读取本文件一次，生成 _config_snapshot.json
  # 后续所有步骤从 snapshot 读取，修改原文件不影响正在运行的 pipeline
  # 若需中途调整：停止 → 修改 → 重跑受影响步骤
```

smart_score.py 启动时的行为：
1. 读取 pipeline_config.yaml → 写入 `output/_config_snapshot.json`
2. 后续所有阶段从 snapshot 读取
3. Pipeline trace 中记录使用的配置版本

### 实施成本

在 smart_score.py 的 `run_pipeline` 开头增加 ~10 行 snapshot 逻辑。不改变现有参数体系。

---

## 五、对 roadmap 已有方向的深化：Compliance 审计中增加"违反归因"

### roadmap 原方案（十一 P2）

设计 10 个测试场景，记录 Agent 违反了哪些规则，数据驱动规则迭代。

### 深化建议（来自 easyslides 的 evolution-driven 约束审计）

easyslides 的每条规则都追溯到"因为什么真实事故加入的"。career-copilot 的 evolution-log.md 有 Known Fixes，但规则本身缺乏"为什么这条规则存在"的标注。

**增加归因标注**：

```markdown
## 绝对不要（高频错误防线）

1. [H] **不要跳过暂停点**
   - 归因：2025-05 实测，跳过 Step 1 确认后方向锚点偏移导致 A 档命中率从 40% 降到 12%
   - 豁免条件：用户显式说"方向我确认了，直接跑"

2. [H] **不要跳过 verify_output.py**
   - 归因：2025-05 实测，未验证的 scored_results 中 15% 岗位为 fallback 分数但未标注
   - 豁免条件：无。任何情况下不可跳过。

3. [R] **不要死循环重试**
   - 归因：2025-04 fetch_jobs 在某站点连续超时 12 次，消耗 8 分钟无产出
   - 豁免条件：用户说"再试几次"时可放宽到 5 次
```

**为什么这有价值**：
- Agent 看到"为什么"比看到"不要做"更有效（Karpathy："做了 X 会导致 Y 错误" 比 "不要做 X" 合规率高）
- 未来删除/修改规则时，能回溯"这条规则解决的问题是否仍存在"
- 为 Compliance 审计提供基线——如果某条规则的归因场景不再发生，说明规则生效或环境已变

---

## 六、实施优先级

| 优先级 | 改进项 | 预估工作量 | 依赖 |
|--------|--------|-----------|------|
| P0 | 约束分级制度（标注 H/R/Rec/Rel） | 30 分钟 | 无，纯文档标注 |
| P0 | 纯推理 Stop Conditions | 30 分钟 | 无，纯文档增加 |
| P1 | 违反归因标注 | 1 小时 | 需要回溯历史事故 |
| P1 | 跨会话恢复协议 | 1-2 小时 | 依赖 Working Memory (roadmap 十) 先实施 |
| P1 | Pipeline 配置锁定（snapshot） | 30 分钟代码 | 依赖 Pipeline 配置化 (roadmap 六) 先实施 |

---

## 七、不采纳的 easyslides 机制（及原因）

记录经过批判性分析后决定**不**引入的机制，防止未来重复讨论：

| easyslides 机制 | 不采纳原因 |
|----------------|-----------|
| Eight Confirmations bundled gate | career-copilot 的暂停点分散在真实执行之间（各有几分钟运行时间），bundled 无意义 |
| Per-page spec_lock re-read | career-copilot 的 profile 在单次 pipeline 中不会变化，重读无收益 |
| Pre-generation batch read | pipeline 各步由独立脚本完成，不存在"生成过程中引用模板"的场景 |
| Mirror-mode (copy don't fill) | career-copilot 不处理视觉模板，代码中硬编码的 HTML 模板已满足需求 |
| Template Asset Bank | "判断类"skill 没有需要精确复用的视觉组件 |
| Three-candidate presentation | 方向已明确时强制三选一是过度设计；方向模糊时已有等价指导（"帮用户想清楚"） |

---

*计划完*
