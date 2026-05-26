# 匹配引擎执行指南

> **加载上下文**：当 SKILL.md 路由到匹配模块，且需要执行 pipeline、处理异常、查看命令参考、或理解数据结构时加载本文件。纯推理模式通常不需要加载（SKILL.md 中已包含判断框架）。

本文件是岗位匹配模块的完整执行方法论。路由层（SKILL.md）决定何时进入匹配流程，本文件决定进入后怎么做。

---

## 匹配哲学

五条核心原则，指导所有匹配相关的设计与执行决策。

**1. 模型负责判断力，代码负责约束力**

需要"理解"的事交给模型（语义匹配、迁移距离估算、JD 真实需求推断）。能写死的逻辑交给代码（英语门槛、学历硬约束、分布校正）。分界线：如果一个判断在 100 个不同 case 上答案都一样，它就该是代码。

**2. 方向锚定 + 行业知识注入**

模型不了解行业细节（"火山方舟的 RAG 产品"和"业务侧 RAG 优化"不是一回事）。从候选人画像中自动提取方向锚点和辨别知识，让模型评分前就知道什么算真匹配。

**3. 先粗后精，分层控成本**

便宜模型全量粗筛（淘汰 75%）→ 强模型只处理 Top K。总成本 ~1 RMB，总时间 ~6 分钟（以 200 条 JD、top-k=50 计）。

**4. Listwise > Pointwise**

让模型在一组岗位中做对比排序，强制拉开分差，结果更接近人类判断。

**5. 确定性后处理兜底**

代码在模型评分后做 Post-Judge：英语门槛、核心团队学历、技术栈依赖——100% 确定性规则，不依赖模型的判断一致性。

---

## 决策路由

面对匹配任务时的第一个判断——用户给了什么，决定走哪条路：

| 用户给了什么 | 执行路径 |
|---|---|
| 简历 + **列表页**链接，要完整报告 | → 全流程 Pipeline |
| 简历 + **单个岗位详情页**链接 | → 纯推理模式 |
| 已有部分数据，只需跑某个环节 | → 单环节独立使用 |
| JD ≤ 5 个，或只想聊聊 | → 纯推理模式 |
| 没见过的网站，需要先摸清结构 | → 探索模式 |
| 没有简历，只问"这个岗位适合我吗" | → 对话了解背景后纯推理 |

**链接是列表页还是详情页？** URL 含具体岗位 ID（`/job/12345`、`/position/xxx`）→ 详情页，用纯推理。URL 是搜索结果/含翻页参数 → 列表页，走 pipeline。不确定 → 用 catdesk-browser 打开看一眼。

---

## 全流程 Pipeline

```
输入：简历(PDF/TXT) + 列表页链接
  │
  ├─ Step 0: 选择 LLM Provider（首次使用时询问）
  │    ⏸ 用 AskQuestion 让用户选择 internal 或 external
  │
  ├─ Step 1: gen_profile.py → boundary_profile.json + candidate_summary.txt
  │    ⏸ 展示方向，等用户确认
  │
  ├─ Step 2: fetch_jobs.py → jobs_raw.txt
  │
  ├─ Step 3: smart_score.py → scored_results.json
  │    ⏸ Sanity Check 后再继续
  │
  ├─ Step 4: generate_report.py → report.html
  │    ⏸ 展示摘要 + 选项菜单，等用户回复
  │
  └─ Step 5（可选）: assess_competitiveness.py → decision_context.json
```

### 暂停点（不可跳过）

| 位置 | 做什么 | 跳过后果 |
|---|---|---|
| Step 0 | 用 AskQuestion 询问用户选择哪个 LLM Provider（internal / external），将选择结果作为后续所有脚本的 `--provider` 参数 | 默认走 internal，用户无法使用更强模型 |
| Step 1 后 | 展示 direction_anchors + signal_words + education + english_evidence，等确认 | 方向锚点偏移，后续全部评分建立在错误假设上 |
| Step 4 后 | 展示 A/B/C 摘要 + 选项菜单，等回复 | 用户无法对结果提问或调整 |

**输出格式参考**：不确定 boundary_profile 或 scored_results 该长什么样时，看 `examples/boundary_profile_example.json` 和 `examples/scored_results_example.json`——真实运行的脱敏样本，体现正确的字段粒度和内容深度。

**Step 1 暂停点的判断深度**：不是所有用户都只需要"看一眼确认"。判断用户的方向确定性——简历经历跨行、用户说"想转行"/"想试试别的方向"、或搜索关键词和简历方向明显不一致，都是方向模糊的信号。方向模糊时，任务不是赶紧生成锚点让用户确认，而是先帮用户想清楚"你到底想要什么"：TA 已有的能力能迁移到哪些方向？TA 说的"转行"是彻底换赛道还是能力延伸？问清楚再锚定，比锚错了重来成本低得多。

### Step 4 选项菜单模板

A 档逐个列出（标题+分数+一句话理由），B 档列标题+分数，C 档只报数量。然后：

```
接下来你可以：
1. 📋 投递策略分析 — 评估投递难度，生成组合建议
2. 🔍 舆情搜索 — 搜索 A 档岗位的面经、团队评价、HC
3. 👀 Watch 模式 — 定期检查新增岗位
4. 🔄 重跑/调整 — 修改方向锚点或参数
5. ✅ 结束
```

---

## 单环节独立使用

| 用户已有的 | 想要的 | 执行什么 |
|---|---|---|
| 简历 | 了解定位和方向 | gen_profile.py → 展示并解读 |
| 简历 + jobs_raw.txt | 匹配评分 | gen_profile → smart_score → generate_report |
| profile + jobs_raw.txt | 重新评分 | smart_score → generate_report |
| scored_results.json | 可视化报告 | generate_report |
| 两份 jobs_raw.txt | 看新增岗位 | diff_watch |
| scored_results + profile | 投递难度 | assess_competitiveness |

关键约束：**简历变了必须重跑 gen_profile.py**；JD 变了但简历没变，profile 可复用。

---

## 纯推理模式

JD ≤ 5 或只讨论某个岗位时，不需要跑代码，但遵循相同判断框架：

1. 定位候选人的方向锚点
2. 分析 JD 真实需求（区分"写在 JD 里的"和"实际需要的"）
3. 估算迁移距离
4. 检测硬约束（英语/学历/技术栈/地点）
5. 给出 A/B/C 判断 + 标注置信度

输出用自然语言。多个 JD 时主动做对比——"哪个迁移距离更短？"而非每个都给模糊的"还不错"。

**置信度标注规则**：JD 信息极简（< 3 行正文）、岗位方向完全超出简历覆盖范围、单一信息源无法交叉验证——这些情况下输出是"带噪声的参考"，必须让用户知道。

### Stop Conditions（纯推理模式的停止规则）

**场景 1：无简历对话了解背景**

用户没有简历但想知道"这个岗位适合我吗"时：

- Questions Budget：最多 3 轮追问（每轮 1-2 个问题）
- Minimum Info Gate：至少获得以下 3/5 项才能给判断——当前/最近岗位（做什么的）、工作年限量级（1-3 / 3-5 / 5+）、核心技术栈或领域、求职动机（为什么想换）、教育背景（学历层次）
- Stop When：3/5 项信息已获得 → 立即给出判断，不继续追问；3 轮追问后无论信息是否完整 → 基于已有信息给出判断
- 输出要求：信息不完整时必须标注"基于有限信息的初步判断，置信度约 X%"

**场景 2：方向探索**

用户说"不知道想做什么" / 简历跨行 / 搜索方向与简历不一致时：

- Exploration Budget：最多 2 轮对话（每轮含分析 + 一个聚焦问题）
- Stop When：用户对某个方向表达了明确兴趣 → 立即锚定，不继续发散；2 轮后无论清晰度如何 → 给出 2-3 个可能方向 + 建议"各跑一批试试"；用户说"我也不确定"/"都试试" → 采用最宽泛的方向锚点开跑
- Anti-Pattern：连续追问 > 2 轮方向问题 → 你在拖延。给建议。

---

## 探索模式

未知站点时，用 catdesk-browser 浏览的目的**不是看内容，而是搞清楚三件事**：

1. URL 翻页模式（`{page}` 在哪）
2. JD 列表的 CSS selector
3. 单页 JD 数量

观察 1-2 页足够——拿到这些信息后立即切到 `fetch_jobs.py --preset generic --selector "..." --base-url "..."` 接管批量抓取。探索成功后把发现记入 memory（见"经验沉淀"）。

---

## 命令参考

所有脚本位于 `~/.catpaw/skills/career-copilot/scripts/`。

```bash
# Step 0: Provider 选择（在流程开头用 AskQuestion 询问用户，得到 PROVIDER 变量）
# 用户选择后，后续所有脚本加 --provider <用户选择>
# 可选值：internal | external

# Step 1: 生成画像
python3 ~/.catpaw/skills/career-copilot/scripts/gen_profile.py \
    --resume ./resume.pdf --output-dir ./ \
    --provider $PROVIDER

# Step 2: 抓取 JD
python3 ~/.catpaw/skills/career-copilot/scripts/fetch_jobs.py \
    --base-url "<含 {page} 占位符的 URL>" \
    --output ./jobs_raw.txt \
    --preset bytedance           # bytedance/meituan/alibaba/generic
    # --total-pages 60           # 默认60，可调
    # --start-page 15            # 断点续爬（从第15页继续）
    # --selector "js表达式"       # generic模式必填，从页面提取的CSS/JS
    # --delay 2.0                # 页间延迟秒数

# Step 3: 评分（⚠ top-k 经验值 = 总JD数×25%, 下限30上限80）
python3 ~/.catpaw/skills/career-copilot/scripts/smart_score.py \
    --jobs ./jobs_raw.txt --profile ./boundary_profile.json \
    --summary ./candidate_summary.txt --output ./scored_results.json \
    --top-k 50 --stage1-model gpt-4o-mini --stage2-model gpt-4.1-mini \
    --concurrency 5 \
    --provider $PROVIDER

# Step 3.5: 验证输出（评分后立即跑，1秒完成）
python3 ~/.catpaw/skills/career-copilot/scripts/verify_output.py \
    --input ./scored_results.json

# Step 4: 生成报告
python3 ~/.catpaw/skills/career-copilot/scripts/generate_report.py \
    --input ./scored_results.json --profile ./boundary_profile.json \
    --output ./report.html
    # 可选: --decision-context ./decision_context.json

# Step 5（可选）: 投递难度评估
python3 ~/.catpaw/skills/career-copilot/scripts/assess_competitiveness.py \
    --scored ./scored_results.json --profile ./boundary_profile.json \
    --summary ./candidate_summary.txt --output ./decision_context.json \
    --model gpt-4.1-mini \
    --provider $PROVIDER

# Watch: 增量检测
python3 ~/.catpaw/skills/career-copilot/scripts/diff_watch.py \
    --baseline ./prev_jobs_raw.txt --current ./jobs_raw.txt \
    --profile ./boundary_profile.json --summary ./candidate_summary.txt \
    --output ./watch_results.json --history ./watch_history.json \
    --provider $PROVIDER
```

---

## 操作经验

### 后台运行策略

| 脚本 | 何时需要后台 | 预期耗时 |
|---|---|---|
| fetch_jobs.py | 页数 > 20 | 2-4 分钟 |
| smart_score.py | JD > 50 | 3-6 分钟 |
| assess_competitiveness.py | A+B 档 > 10 | 1-2 分钟 |
| gen_profile.py / generate_report.py | 通常不需要 | < 30 秒 |

后台运行用 `is_background: true`。**轮询策略**：首次等 90 秒，之后每 30 秒检查输出文件，最多等 8 分钟。完成判定：文件存在且 > 1KB。超时 → 检查进程是否还在（`ps aux | grep <脚本名>`），进程在就继续等，进程没了且无输出 → 崩溃，向用户报告。

**缓冲注意**：后台运行时即使日志文件/tee 输出为空也不代表脚本卡死（Python stdout 缓冲）。判断进程存活用 `kill -0 <PID>` 或 `ps aux | grep`，不要依赖日志输出来判断进度。

### Sanity Check

**Step 2 → 3 之间**（抓取完成后、评分前）：

- JD < 20 → 搜索范围可能过窄，问用户是否扩大关键词或增加页数
- JD > 300 → `--total-pages` 可能过大，评分耗时和成本会显著上升，确认后再继续
- 抽查 3-5 条 JD 的描述长度：如果多数只有标题或 < 3 行摘要，评分将基于猜测——先确认是否需要用详情页链接补全 JD 内容

**scored_results.json 结构**：顶层 `recommendations.tier_A / tier_B / tier_C`（数组），每个 item 有 `score`、`title`、`risks`、`match_reasons`、`advice` 字段。运行元信息在 `pipeline` 下：`stage1 / stage1_5 / stage2 / stage2_5 / post_judge / direction_anchor`。

**Step 3 → 4 之间**（评分完成后、生成报告前）：

优先级从高到低检查——**先排除方向性错误，再看数值分布**：

1. 🔴 搜索关键词与 direction_anchors 明显不一致（如用户搜"芯片"但方向是 AI 产品）→ **最高优先级**：这是根因级问题。即使数值正常也应提醒用户确认搜索方向是否有意为之。如果确认不一致，下面的数值检查全部无意义（A档=0 不是因为 top-k 不足，而是方向本身就不匹配）
2. 🟡 A 档 = 0 → **仅在方向一致的前提下**才考虑：方向锚点可能过窄或 top-k 不足。如果方向本身不一致（上一条命中），不要建议调 top-k
3. 🟡 A 档占比 > 50% → 区分度不足，评分阈值可能偏松
4. 🟡 最高分 < 70 或最低分 > 60 → 分布异常收窄
5. 🟠 多个岗位 risks 含"模型未返回该岗位评估" → 这是 Stage 2 fallback（模型跳过了该岗位），其分数 = stage1_score × 0.7，不代表真实匹配度。此类岗位数量多时说明 Stage 2 部分失败，考虑降低 `--concurrency` 或换模型重跑

**原则**：异常 → 先诊断根因再决定对策，不要直接生成报告。多条规则同时命中时，优先处理排序靠前的（根因级问题），不要同时列出所有建议让用户困惑。

**Step 5 完成后**（assess_competitiveness 的结果）：

- safe = 0 且 A 档 ≥ 3 个高分(≥90) → prompt 对 safe 定义偏严（对实习生尤其明显）。直接基于评分数据做人工判断：A 档 ≥ 93 分且 risks 为空 → 视为 safe/match
- strategy_summary = "策略生成失败" → 第二阶段失败。**降级**：逐岗 positioning 仍有效，直接用自然语言做策略分析（参考黄金比例 30% stretch + 50% match + 20% safe）
- stretch > 80% → 回查 A 档 gaps 字段，如果都是"加分项缺失"而非"核心能力缺失"，手动提升部分为 match

### 降级路径

**Step 2 抓取降级链**（按顺序尝试，不要跳级）：

1. `--preset <站点>` → 失败/返回 0 条
2. `--preset generic --selector "<从页面观察到的 CSS>"` → 失败/返回 0 条
3. catdesk-browser 手动翻 1-2 页确认结构 → 提取 selector → 回到第 2 步
4. 以上全部失败 → 告知用户，问能否提供截图或文本

**其他降级场景**：

| 场景 | 处理方式 |
|---|---|
| JD 描述极简（< 3 行） | 诚实告知"信息太少"，给初步判断但标注不确定性 |
| 脚本部分成功部分失败 | 检查输出完整性（strategy 字段、tier 是否为空），有效部分直接用，失败部分用推理补偿 |
| 没有简历只想问 | 2-3 个关键问题了解背景后用纯推理模式 |

### 常见错误类型及诊断方向

连续失败时，**先分类错误再决定对策**——不同错误类型对应完全不同的排查路径：

| 错误类型 | 常见表现 | 可能原因 | 排查步骤 |
|----------|----------|----------|----------|
| **Timeout** | `TimeoutError`、`ReadTimeout`、脚本挂住无输出 | 网络不稳定；Provider 过载；`--concurrency` 过高导致限流 | ① 降低 `--concurrency`（如 5→2）② 检查网络连通性（`check_env.py`）③ 换 Provider 试一次 |
| **JSONDecodeError** | `json.decoder.JSONDecodeError`、`Expecting value` | 模型返回被截断（token 超限）；模型返回非 JSON 格式（如 markdown 包裹）；网络中断导致响应不完整 | ① 检查 `--stage2-model` 的 max_tokens 是否足够 ② 查看错误位置（position N）——靠前说明整个响应就不是 JSON，靠后说明被截断 ③ 降低 `--concurrency` 减少并发压力 |
| **AuthError** | `401 Unauthorized`、`403 Forbidden`、`Invalid API Key` | API Key 过期或无效；Provider 账户余额不足；环境变量未正确设置 | ① 检查 `.env` 或环境变量中的 Key ② 运行 `check_env.py` 验证凭据 ③ **不要重试**（Auth 问题重试无意义） |
| **RateLimit** | `429 Too Many Requests`、`rate_limit_exceeded` | 短时间请求过多；账户配额耗尽 | ① 尊重 `retry-after` header（脚本已内置）② 降低 `--concurrency` ③ 等待一段时间后重跑 |
| **ConnectionError** | `ConnectionRefusedError`、`DNS resolution failed` | 网络完全不通；VPN 断开；Provider 服务宕机 | ① 检查网络基础连通性 ② 检查 VPN 状态 ③ 确认 Provider 服务状态 |
| **脚本崩溃** | `KeyError`、`TypeError`、`FileNotFoundError` | 输入文件格式不符合预期；缺少必需文件；boundary_profile 与当前版本不兼容 | ① 检查输入文件是否存在且非空 ② 运行 `--help` 确认参数正确 ③ 如果是 profile 问题，重跑 `gen_profile.py` |

**诊断优先级规则**：

1. **先看错误类型**——同一类型的连续失败（如 3 次 timeout）说明问题稳定存在，不是偶发
2. **混合错误**更需要注意——如果 timeout + JSONDecodeError 交替出现，大概率是 Provider 过载导致响应不稳定
3. **AuthError 立即停止**——永远不要重试 Auth 错误，它不会自己好
4. 诊断完成后，**向用户报告**发现和建议，由用户决定是否重跑

### 经验沉淀

两类经验值得跨会话保留：

- **站点特点**（URL 模式、selector、翻页上限、登录需求）→ 探索成功后 `memory_write type=daily`，标注域名，下次同站点先 `memory_search`
- **用户偏好**（评分阈值调整、地域过滤、展示偏好）→ 用户明确表达后 `memory_write type=longterm`，下次会话开始时读取并应用

### 跨会话恢复协议

当用户在新会话中说"继续上次的结果"或存在未完成的 pipeline 状态时，按两阶段恢复：

**Phase A — 恢复期**（目标：200-500 tokens 恢复摘要）：

1. 读 career-context.md → 确认上次停在哪一步
2. 读 scored_results.json 的 `pipeline.metadata`（运行参数、时间戳、总数）
3. 只读 tier_A 列表的标题 + 分数（不读完整 match_reasons）
4. 向用户展示恢复摘要："上次你跑了 XX 个岗位的匹配，A 档 N 个，最高分 XX。现在继续？"

**Phase B — 执行期**（用户确认继续后，按需加载）：

- 选"生成报告" → 不需要读 scored_results 详情，直接调 generate_report.py
- 选"看 A 档详情" → 只加载 tier_A 的完整数据
- 选"投递策略分析" → 加载 tier_A + boundary_profile

**关键约束**：恢复期**禁止**将完整 scored_results.json 读入对话上下文（50+ 岗位可消耗 8000-15000 tokens，撑爆执行窗口）。始终按需、按用户选择的操作加载最小必要数据。

---

## 与其他模块的数据接口

匹配引擎不是孤立运行的，它与 career-copilot 的其他模块通过文件交换数据：

**输出 → resume-guide 模块**：
- `boundary_profile.json`：包含 direction_anchors、signal_words、education、english_evidence 等字段。resume-guide 读取后用于针对性的简历优化建议——知道用户的方向定位才能判断简历哪里该强化、哪里该弱化。

**输出 → interview-prep 模块**：
- `scored_results.json`：包含每个岗位的 match_reasons、risks、advice 字段。interview-prep 读取后用于生成针对性的面试准备方案——知道匹配的原因和风险点才能预判面试官会追问什么。

**输入 ← career-memory**：
- 历史匹配偏好：通过 `memory_search` 查询用户过往的方向确认记录、阈值调整偏好、已排除的岗位方向。首次运行 gen_profile.py 前检查是否有历史锚点可复用，避免每次都从零开始方向对齐。

**数据流向图**：

```
career-memory (历史偏好)
       │
       ▼
  gen_profile.py ──→ boundary_profile.json ──→ resume-guide
       │
       ▼
  smart_score.py ──→ scored_results.json ──→ interview-prep
       │
       ▼
  assess_competitiveness.py ──→ decision_context.json
```

---

## 运行时自检

如果处于以下状态，**停下纠正**：

- `[H]` 正在写 `.py` 做抓取或评分 → 用 `scripts/` 已有工具（数据转换脚本除外，用完即删）
- `[H]` 跑完 Step 3 但从未展示 boundary_profile → 跳过了暂停点，必须回退
- `[H]` smart_score.py 完成但没跑 verify_output.py → **禁止继续**。立即跑，1 秒出结果。验证未通过 → 先修（调参/重跑/降级），再向用户展示
- `[R]` 一条消息里输出完整报告且没问下一步 → 补选项菜单
- `[R]` 连续 3 次失败 → 停止重试，看 `--help`，向用户报告
- `[R]` assess_competitiveness 完成但没检查 strategy + positioning 分布 → 打开 JSON 检查
- `[Rec]` catdesk-browser 逐页抓取超过 3 页 → 切到 fetch_jobs.py
- `[Rec]` 前台运行长脚本已等超 60 秒 → 应该后台运行。没超时就继续等；被中断则后台重跑

---

## 约束

### 环境依赖

- Python ≥ 3.9
- PDF 解析：`pypdf`/`PyPDF2`/`pdfminer.six`（至少装一个）
- LLM 调用：支持多 Provider 切换（详见 `.env.example`）。通过环境变量 `LLM_PROVIDER` 切换（值为 `internal` 或 `external`），或在脚本命令中用 `--provider external` 参数指定。也可单独设置 `LLM_BASE_URL`/`LLM_API_KEY`（internal）或 `EXTERNAL_BASE_URL`/`EXTERNAL_API_KEY`（external）覆盖默认值
- 浏览器能力：fetch_jobs.py 的通用模式（`--preset generic --selector`）依赖从页面提取 CSS selector，需要 web-access skill 或等效的浏览器操作能力

### 数据约束

- boundary_profile 每份新简历必须重新生成
- 工作区最终只保留：`boundary_profile.json`、`candidate_summary.txt`、`jobs_raw.txt`、`scored_results.json`、`report.html`、`decision_context.json`（Step 5）、`watch_history.json`（Watch）

### 禁止行为

禁止创建临时脚本**来替代 pipeline 脚本**（fetch/score/report）。能力不足时改进 `scripts/` 下的已有脚本。**例外**：非标格式数据（Excel、截图文字）转换成 `jobs_raw.txt` 的一次性脚本允许，用完即删。
