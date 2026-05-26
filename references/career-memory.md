# 记忆层操作规范

> 本文档定义 career-copilot 的结构化记忆系统，用于跨会话维护求职上下文。

---

## 一、设计目标

在用户持续的求职过程中，维护一份结构化的职业记忆。核心目标：

- **跨会话保持上下文**：不需要每次重新介绍自己的背景、偏好和进展
- **积累面试经验和反馈模式**：从每次面试中提取可复用的经验
- **追踪求职进展和决策历程**：形成完整的求职时间线
- **为各模块提供个性化上下文**：matching、interview-prep、resume-guide 都能读取相关记忆

---

## 二、存储架构

### 主日志

**路径**：`~/.catpaw/career-copilot/career-log.jsonl`

- append-only 设计，每行一个 JSON 事件
- 按时间顺序追加，不修改历史记录
- 适合结构化查询（按 type、company、时间范围筛选）

### 快照

**路径**：`~/.catpaw/career-copilot/career-profile.md`

- 从日志中聚合生成的当前状态摘要
- 控制在 ~2000 tokens 以内
- 各模块优先读取此文件获取上下文
- 每次有重大更新时自动重新生成

### 脚本

**路径**：`~/.catpaw/skills/career-copilot/scripts/career_log.py`

- 所有读写操作通过此脚本完成
- 提供 init / append / query / profile / refresh-profile / stats / forget 子命令

---

## 三、JSONL 事件类型定义

共 8 种事件类型，每个事件都包含公共字段和类型特有字段。

### 公共字段

```json
{
  "type": "<事件类型>",
  "timestamp": "2025-01-15T14:30:00+08:00",
  "session_id": "<可选，关联同一次会话的多个事件>"
}
```

### 事件类型一览

| type | 触发时机 | 关键字段 |
|------|----------|----------|
| `match_round` | 完成一轮岗位匹配 | round_id, jd_count, top_matches[], direction_anchors |
| `interview_prep` | 准备某次面试 | company, role, focus_points[], prep_date |
| `interview_done` | 面试结束复盘 | company, role, round, result, learnings[], weak_points[] |
| `resume_update` | 简历修改 | version, changes_summary, trigger |
| `offer_received` | 收到 offer | company, role, package_summary, deadline |
| `decision` | 做出重要决策 | decision, reasoning, alternatives_considered[] |
| `reflection` | 阶段性反思 | period, insights[], next_actions[] |
| `profile_update` | 能力画像更新 | updated_fields[], source |

### 各类型详细字段定义

#### match_round

```json
{
  "type": "match_round",
  "timestamp": "2025-01-15T14:30:00+08:00",
  "round_id": "match-20250115-001",
  "jd_count": 15,
  "top_matches": [
    {
      "company": "字节跳动",
      "role": "AI产品经理",
      "score": 82,
      "match_reasons": ["LLM应用经验", "产品方法论"],
      "risks": ["缺少商业化经验"]
    }
  ],
  "direction_anchors": ["AI产品", "技术平台PM"],
  "source_url": "https://www.zhipin.com/..."
}
```

#### interview_prep

```json
{
  "type": "interview_prep",
  "timestamp": "2025-01-16T09:00:00+08:00",
  "company": "字节跳动",
  "role": "AI产品经理",
  "round": "初试",
  "focus_points": ["项目量化成果", "AI落地方法论", "业务sense"],
  "prep_date": "2025-01-17",
  "related_match_round": "match-20250115-001"
}
```

#### interview_done

```json
{
  "type": "interview_done",
  "timestamp": "2025-01-17T16:00:00+08:00",
  "company": "字节跳动",
  "role": "AI产品经理",
  "round": "初试",
  "result": "pass",
  "learnings": [
    "项目描述要更量化",
    "STAR法则用得好的问题反馈更积极"
  ],
  "weak_points": [
    "商业模式拆解不够深入"
  ],
  "questions_asked": [
    "介绍一个你主导的AI项目",
    "如何评估一个AI功能的ROI"
  ],
  "duration_minutes": 45,
  "notes": "面试官关注落地能力，不太问理论"
}
```

- `round` 可选值：`初试` / `复试` / `三面` / `HR` / `笔试` / `群面`
- `result` 可选值：`pass` / `fail` / `pending`

#### resume_update

```json
{
  "type": "resume_update",
  "timestamp": "2025-01-18T10:00:00+08:00",
  "version": "v3",
  "changes_summary": "强化了AI项目的量化成果描述，新增数据驱动决策案例",
  "trigger": "match-20250115-001 中多个JD要求量化能力",
  "sections_modified": ["项目经历", "技能摘要"]
}
```

#### offer_received

```json
{
  "type": "offer_received",
  "timestamp": "2025-01-25T11:00:00+08:00",
  "company": "字节跳动",
  "role": "AI产品经理",
  "package_summary": "符合预期，有期权",
  "deadline": "2025-02-01",
  "notes": "团队方向是AIGC平台"
}
```

注意：**禁止记录具体薪资数字**，只用模糊描述。

#### decision

```json
{
  "type": "decision",
  "timestamp": "2025-01-28T20:00:00+08:00",
  "decision": "接受字节AI产品经理offer",
  "reasoning": "方向匹配度最高，团队技术氛围好，成长空间大",
  "alternatives_considered": [
    "某厂-平台产品：方向偏传统",
    "继续面试-等阿里结果：时间风险高"
  ]
}
```

#### reflection

```json
{
  "type": "reflection",
  "timestamp": "2025-01-20T22:00:00+08:00",
  "period": "求职第二周",
  "insights": [
    "AI产品方向的面试普遍关注落地经验而非技术深度",
    "项目描述的量化改进后通过率明显提升",
    "准备时间不足2天的面试通过率低"
  ],
  "next_actions": [
    "补充商业模式分析能力",
    "整理3个可量化的核心项目案例"
  ]
}
```

#### profile_update

```json
{
  "type": "profile_update",
  "timestamp": "2025-01-20T22:30:00+08:00",
  "updated_fields": ["core_strengths", "improvement_areas"],
  "source": "interview_done 聚合分析",
  "changes": {
    "core_strengths_added": ["AI产品落地方法论"],
    "improvement_areas_added": ["商业模式拆解"]
  }
}
```

---

## 四、读取策略 — Summary First

各模块读取记忆时遵循以下优先级：

### 第一优先：读取 career-profile.md

适用于大多数场景。快照包含当前状态、能力摘要、统计数据，控制在 ~2000 tokens，不会消耗过多上下文窗口。

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py profile
```

### 第二优先：按条件筛选 JSONL

当需要细节信息时，按以下维度筛选：

- **按 type 筛选**：如准备面试时只看 `interview_done` 类型
- **按时间范围筛选**：如只看最近 30 天的事件
- **按 company 筛选**：如准备某公司面试时查看与该公司相关的所有记录
- **组合筛选**：如"最近30天 + 字节 + interview_done"

```bash
# 按类型查询
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --type interview_done --limit 5

# 按公司查询
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --company 字节

# 查看最近 30 天事件
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --days 30
```

### 禁止

**绝对不要一次性读取全部 JSONL 文件**。随着使用时间增长，日志文件可能非常长，全量读取会浪费上下文窗口且无法有效利用。

---

## 五、写入时机

各模块在以下时机写入记忆：

| 模块 | 写入事件类型 | 触发条件 |
|------|-------------|----------|
| matching-guide | `match_round` | 完成一轮完整岗位匹配后 |
| matching-guide | `profile_update` | boundary_profile 有显著变化时 |
| interview-prep | `interview_prep` | 开始为某次面试做准备时 |
| interview-prep | `interview_done` | 用户反馈面试结果或主动做复盘时 |
| resume-guide | `resume_update` | 完成一次简历修改后 |
| 用户主动 | `offer_received` | 用户告知收到 offer |
| 用户主动 | `decision` | 用户做出重要求职决策 |
| 用户主动 | `reflection` | 用户主动进行阶段反思 |

### 写入原则

1. **及时写入**：事件发生后立即追加，不要等到会话结束
2. **不重复写入**：同一事件不要追加两次，用 session_id 关联同一会话的事件
3. **精简记录**：只记录关键信息，不记录完整对话内容
4. **用户确认**：涉及结果判断（如面试是否通过）时，以用户明确表述为准

---

## 六、career-profile.md 快照格式

快照文件由脚本自动生成，格式如下：

```markdown
# Career Profile（自动生成，勿手动编辑）

> 最后更新：{timestamp}

## 当前状态

- 阶段：{探索 / 投递 / 面试 / 决策 / 已入职}
- 目标方向：{来自最近 match_round 的 direction_anchors}
- 活跃公司：{当前正在面试流程中的公司列表}
- 待处理：{pending 状态的面试结果、即将到期的 offer 等}

## 能力画像摘要

- 核心优势：{从 top_matches[].match_reasons 中高频出现的关键词}
- 待提升：{从 top_matches[].risks 和 interview_done.weak_points 中高频出现的}
- 面试表现模式：{从 learnings 中提取的规律}

## 求职历程统计

- 匹配轮次：{match_round 事件计数}
- 投递/面试公司：{去重后的 company 列表}
- 面试次数：{interview_done 事件计数}
- 通过率：{result=pass 的数量} / {result!=pending 的总数}
- 简历版本：当前 v{resume_update 最大版本号}，共迭代 {计数} 次
- Offer 数量：{offer_received 计数}

## 关键洞察

{从 reflection.insights 和 interview_done.learnings 中聚合，去重后取最有价值的 5-8 条}

## 近期事件（最近5条）

{最近 5 条事件的简要描述，格式如：}
- [2025-01-17] 字节-AI产品经理-初试 → 通过
- [2025-01-15] 完成第3轮岗位匹配，15个JD，方向锚定AI产品
```

### 快照生成规则

- 总长度控制在 2000 tokens 以内
- 统计数据从 JSONL 实时聚合计算
- "关键洞察"去重合并相似条目
- "近期事件"只保留最近 5 条

---

## 七、与 CatPaw 全局 memory 的关系

### 互补不替代

| 维度 | CatPaw 全局 memory | career-memory |
|------|-------------------|---------------|
| 存储工具 | `memory_write` MCP 工具 | `career_log.py` 脚本 |
| 内容类型 | 身份、编码偏好、长期稳定信息 | 求职过程数据、面试经历、匹配历史 |
| 时效性 | 30天以上不变的信息 | 随求职进展持续变化 |
| 格式 | Markdown | JSONL（结构化） |
| 查询方式 | 全文检索 | 按字段筛选 |

### 不要重复存储

以下信息应该只存在于全局 memory 中，career-memory 不再重复：

- 用户姓名、联系方式
- 技术栈偏好、编码习惯
- 教育背景（除非求职场景需要引用）
- 工作经历概述（career-memory 只记录求职过程中的增量信息）

### 交互方式

career-copilot 各模块启动时：

1. 先读 career-profile.md 获取求职上下文
2. 如需用户基础信息（如技术栈），通过 `memory_read` 从全局 memory 获取
3. 不要在 career-log.jsonl 中冗余存储全局 memory 已有的信息

---

## 八、隐私与安全

### 允许记录

- 公司名称、岗位名称
- 面试轮次（初试/复试/HR等）
- 面试结果（pass/fail/pending）
- 准备重点和策略
- 学到的经验和反思
- 自身的不足和改进方向
- 匹配分数和方向锚点
- 简历修改摘要
- 决策过程和理由

### 禁止记录

- **薪资具体数字**：只能用模糊描述如"符合预期"、"高于市场"
- **Offer 详细条款**：不记录具体金额、股票数量、签字费等
- **面试官姓名**：不记录任何面试官的个人信息
- **完整 JD 文本**：只记录关键匹配信息和岗位名称
- **个人隐私**：身份证号、手机号、家庭住址等
- **第三方隐私**：推荐人信息、内推人姓名等

### 数据生命周期

- 日志文件长期保留，用户可通过 `forget` 命令主动清除
- 快照文件随时可重新生成
- 用户有权随时要求删除全部记忆数据

---

## 九、脚本使用

所有记忆操作通过 `career_log.py` 脚本完成：

### 初始化

首次使用时执行，创建必要的目录和文件：

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py init
```

执行效果：
- 创建 `~/.catpaw/career-copilot/` 目录（如不存在）
- 创建空的 `career-log.jsonl`
- 生成初始的 `career-profile.md`（空状态）

### 追加事件

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py append \
  --type interview_done \
  --data '{"company":"字节","role":"AI产品","round":"初试","result":"pass","learnings":["项目描述要更量化"]}'
```

- `--type`：必填，8 种事件类型之一
- `--data`：必填，JSON 格式的事件特有字段
- 脚本会自动添加 `timestamp` 字段
- 脚本自动生成唯一事件 ID

### 查看快照

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py profile
```

输出 career-profile.md 的内容。如果文件不存在会提示先执行 `refresh-profile`。

### 按条件查询

```bash
# 按事件类型查询（最近5条）
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --type interview_done --limit 5

# 按公司名称查询
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --company 字节

# 最近 14 天的事件
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --days 14

# 组合查询
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py query --type interview_done --company 字节 --days 30 --limit 3
```

### 查看统计信息

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py stats
```

显示事件类型分布、时间范围、涉及的公司列表等概览信息。快速了解记忆库现状。

### 重新生成快照

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py refresh-profile
```

从 JSONL 全量重新聚合生成 career-profile.md。适用于：
- 快照文件损坏或丢失
- 手动修正了 JSONL 中的数据
- 定期维护

### 清除所有记忆

```bash
python3 ~/.catpaw/skills/career-copilot/scripts/career_log.py forget
```

**危险操作**：删除 career-log.jsonl 和 career-profile.md。执行前会要求确认。

---

## 十、快照刷新策略

### 自动刷新时机

以下事件追加后，脚本应自动触发快照重新生成：

- 新增 `match_round` 事件（完成一轮匹配会影响方向和统计）
- 新增 `interview_done` 且 `result != pending`（通过/失败会影响统计和洞察）
- 新增 `offer_received` 事件（进入新阶段）
- 新增 `decision` 事件（状态变更）
- 新增 `reflection` 事件（新增洞察）

### 不自动刷新的情况

- `interview_prep`：只是记录准备计划，不影响整体画像
- `interview_done` 且 `result = pending`：结果未定，等确认后再刷新
- `resume_update`：只更新版本号，对快照影响小
- `profile_update`：已经是对画像的更新，可纳入下次刷新

### 手动刷新

用户可随时通过 `refresh-profile` 命令手动触发刷新。

### 刷新性能

快照生成需要扫描全部 JSONL，但由于是本地文件操作且数据量有限（通常不超过几百条），性能不是问题。

---

## 十一、模块集成指南

### matching-guide 集成

```
读取：career-profile.md → 获取当前方向锚点和能力画像
写入：match_round（完成匹配后）、profile_update（画像变化时）
```

匹配模块应参考历史匹配结果避免重复推荐相同岗位，并利用能力画像优化匹配权重。

### interview-prep 集成

```
读取：career-profile.md → 获取能力优势和不足
查询：query --company {目标公司} → 获取与该公司的历史交互
查询：query --type interview_done --limit 5 → 获取近期面试经验
写入：interview_prep（开始准备时）、interview_done（面试结束后）
```

面试准备模块应利用历史面试中暴露的 weak_points 针对性准备，利用 learnings 优化策略。

### resume-guide 集成

```
读取：career-profile.md → 获取能力画像和方向
查询：query --type match_round --limit 3 → 获取近期匹配中的 risks
写入：resume_update（修改完成后）
```

简历模块应利用匹配中高频出现的 risks（如"缺少量化数据"）指导简历优化方向。

---

## 十二、错误处理

### 文件不存在

- `career-log.jsonl` 不存在：提示用户执行 `init`
- `career-profile.md` 不存在：提示执行 `refresh-profile`，或如果 JSONL 也不存在则执行 `init`

### JSON 解析错误

- 单行 JSONL 解析失败：跳过该行，输出警告，继续处理后续行
- append 的 data 参数不是合法 JSON：报错并拒绝写入

### 并发写入

- JSONL 为 append-only，通常不会有并发冲突
- 如果多个模块同时写入，由文件系统保证原子性（单行追加）

---

## 十三、最佳实践

1. **写入前确认**：在 append 之前，确认用户确实完成了该事件（如面试确实结束了）
2. **精简 learnings**：每次面试提取 2-5 条关键学习，不是完整复述
3. **方向锚点稳定性**：direction_anchors 不要每轮都大改，除非用户明确转向
4. **session_id 使用**：同一次对话中产生的多个事件使用相同 session_id
5. **定期反思**：每 1-2 周引导用户做一次 reflection，帮助沉淀洞察
6. **不过度记忆**：只记录对未来决策有参考价值的信息
