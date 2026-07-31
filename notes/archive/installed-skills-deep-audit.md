# 已安装 203 个 Skill 深度审计 → career-copilot 借鉴清单

> 生成日期：2026-07-20（切片 1 / 2 / 8 于补全轮次补齐，确保 203 个 skill 全部被深入读取）
> 方法：8 个并行子代理，每个深入读取约 25 个 skill 的完整 SKILL.md（含其引用的核心手法文件 GLOSSARY.md / references/*.md），逐一提取可迁移到 career-copilot 的具体手法。本文件为全量留档；精炼版见文末《跨切片总鉴》。
> 目标 skill：career-copilot（求职全链路 AI Agent，路径 `D:\57709\Desktop\Apple\美团\career-copilot-copy`）。
>   当前结构：单 skill + 软意图路由 → 5 大模块（匹配 / 面试 / 简历 / 记忆 / 规划）；5 条红线（不编造经历 / 不替代决策 / 不泄露隐私 / 不绕过工具 / 不确定必须说）；约束 HARD>REQUIRED>RELAXABLE；Python pipeline（gen_profile / fetch_jobs / pre_filter / smart_score / post_judge / verify_output / assess_competitiveness）+ 暂停点 + verify 闸门；跨会话记忆（career-context.md ~200tok / career-profile.md ~2000tok / 事件 JSONL + session-start 读 / session-end 写交接单）；references/ 按需按章节加载；有 evals/ 与 tests/。

==================================================
## 切片 1（skills_list.txt 第 1-26 行）
==================================================
# Career-Copilot 技能深度审计 · Part 1（26 个源技能）

> 审计目标：`career-copilot`（求职全链路 AI Agent，位于 `D:\57709\Desktop\Apple\美团\career-copilot-copy`）
> 结构回顾：5 能力模块（匹配/matching、面试/interview、简历/resume、记忆/memory、规划/planning）｜5 红线（不编造经历 / 不替代决策 / 不泄露隐私 / 不绕过工具 / 不确定必须说）｜约束层级 HARD>REQUIRED>RECOMMENDED>RELAXABLE｜Python 流水线（gen_profile / fetch_jobs / pre_filter / smart_score / post_judge / verify_output / assess_competitiveness）+ 暂停点 + verify 闸门 ｜跨会话记忆（career-context.md ~200tok / career-profile.md ~2000tok / event JSONL，开局读、收尾写 handoff）｜references/ 按需加载｜有 evals/ 与 tests/
>
> 本文件专挖可迁移的 **元模式**：verify 闸门、记忆/状态管理、意图路由/消歧、护栏/红线、反幻觉/事实核查、结构化输出、eval/自检、语气一致、triage/优先级、规划/分解、反思/自驳、工具纪律、渐进披露、失败模式清单、leading words、跨会话 handoff。

---

## 1. agent-browser-core
- **一句话**：基于 `agent-browser` CLI 的网页自动化 playbook，核心是"快照→经 ref 操作→再快照"的操作节奏与一套安全模式默认值。
- **可借鉴的具体手法 + 关联**：
  - **Safe-mode 清单 + 高危能力 allowlist**（`references/agent-browser-safety.md`：allowlist 域名、封 localhost/内网、默认禁用 eval/file-access、日志脱敏 token、敏感操作需显式人工批准并记录原因与范围）→ 直接迁移为 career-copilot 的"安全模式闸门"：在流水线里给 `fetch_jobs`/`assess_competitiveness` 的对外动作（发请求、写文件、调用外部 API）加 allowlist 与"高危操作须显式批准"，对应**不绕过工具/不泄露隐私**红线与 HARD 约束层。
  - **结果验证 · No Fake Completions**："底层数据/页面状态未实质变化，严禁输出 'Task Completed'/'Updated Successfully'" → 直接强化 `verify_output`：只有当 `pre_filter`/`smart_score` 真的产出非空结果时才算通过，否则必须如实报"未筛出/分数退化"而非假装成功。
  - **Write Operation Re-check + 空值主动确认**：写操作后必须再快照；抓取字段为空/`0.00`/异常值 → 主动提示用户确认数据来源 → 对应 `verify_output` 检测到空职位列表、退化分数、异常匹配度时的**暂停点**逻辑。
  - **Escalation policy（记录批准的原因与范围）** + **Auth Fallback（验证码/复杂登录立即 hand-off 给用户而非无限重试）** → 对应**不替代决策**红线与流水线的暂停点：需要真人判断（如是否投递某岗）时显式交还并记 handoff。
- **相关性：5**（安全模式闸门 + No-Fake-Completion 与 verify_output / 红线几乎是同构映射）

## 2. aihot
- **一句话**：中文 AI 资讯查询 skill，核心是"按用户措辞路由到不同 API 端点 + 绝不凭训练数据脑补，永远走实时 API + 对用户隐藏内部参数"。
- **可借鉴的具体手法 + 关联**：
  - **路由优先级（第一原则）**：默认走 `mode=selected`，仅当用户说"日报"才走 `daily`，说"全部"才走 `all` → 对应 career-copilot 的**软意图路由**：用明确的措辞规则把"改简历/匹配岗位/模拟面试/做规划"分流到 5 个模块，避免误用；可写入路由判定表。
  - **"不要凭训练数据脑补，永远走 API"** → 直接支撑**不编造经历**红线与反幻觉：岗位信息、公司信息一律以 `fetch_jobs` 实时抓取的为准，绝不用模型记忆补全岗位职责。
  - **输出格式剥离**：用户侧绝不暴露 `mode=selected`/`cursor`/`限流` 等内部参数，只给 markdown 人话 → 对应**渐进披露**：career-copilot 对用户只呈现可读建议，把 `smart_score` 权重、pipeline 内部状态藏进 references/ 与日志，不污染对话。
  - **"不要做"显式清单（failure-mode list）** + 服务端参数硬上限（`since≤7d`、`q≥2` 字符）→ 对应约束层级与红线的"禁止项"清单写法。
- **相关性：4**（意图路由 + 反脑补 + 输出剥离对路由/反幻觉/渐进披露都直接可用）

## 3. api-and-interface-design
- **一句话**：教设计稳定、难误用的接口：契约优先、在边界校验、错误语义一致、优先新增而非修改。
- **可借鉴的具体手法 + 关联**：
  - **Hyrum's Law（每个可观察行为都会变成契约）** → 直接警示 career-copilot 的**跨会话记忆**：一旦 `career-context.md`/`career-profile.md` 被后续会话依赖，它们的字段就成了承诺，改动要向后兼容（优先新增可选字段而非删改）。
  - **Validate at boundaries + 第三方响应视为不可信数据** → 对应 `fetch_jobs` 返回属不可信输入：在 `pre_filter` 之前校验岗位数据结构/内容，防止脏数据进 `smart_score`（反幻觉/边界校验）。
  - **一致的错误语义（单一错误策略）+ Common Rationalizations 表 + Red Flags + Verification 清单** → 可照搬为 career-copilot 每个模块的"Red Flags / Verification checklist"，以及跨阶段**统一失败上报结构**。
  - **Prefer addition over modification（向后兼容）** → 演进 `career-profile.md` 时只加字段、不破坏旧消费者。
- **相关性：4**（边界校验 + Hyrum 定律对记忆契约 + Verification 清单高度可迁移）

## 4. ask-matt
- **一句话**：一个"技能路由器"，把用户的含糊意图引导到正确的 flow，并定义了跨会话的 `/handoff` 与 `/compact` 两种上下文延续方式。
- **可借鉴的具体手法 + 关联**：
  - **Crossing sessions：`/handoff`（压缩成 markdown 文件、开新会话引用该文件）vs `/compact`（同会话内摘要，丢逐字历史）** → 与 career-copilot 的**跨会话 handoff 几乎是同一机制**：`career-context.md`(200tok) 就是极简 handoff 文件，`career-profile.md`(2000tok) 是富上下文；建议显式区分"fork（开新会话带 handoff 文件）"与"continue（同会话 compact）"，并规定何时用哪种。
  - **Context hygiene / smart zone（~120k token 上限，逼近前先 handoff）** → 对应记忆预算意识：200tok/2000tok 的设计正是"smart zone"思路，提示在上下文变长前落盘到记忆文件。
  - **"你记不住每个 skill，所以问" 的路由器定位** + **Triage 产出 agent-ready issues** → 对应 5 模块的软意图路由与**规划/分解**：先把用户请求 triage 成 agent-ready 任务再分派模块。
- **相关性：5**（handoff/compact 二分法直接对应跨会话记忆设计，是最贴合的迁移之一）

## 5. awesome-ai-research-writing
- **一句话**：学术写作 prompt 模板库，按场景读 `README.md` 取对应模板，每个模板自含 Role/Task/Constraints/Execution Protocol。
- **可借鉴的具体手法 + 关联**：
  - **每个模板自含 Role+Task+Constraints+Execution Protocol** → 对应 5 模块的**自包含协议**：`resume`/`interview`/`planning` 各写成"角色+任务+约束+执行协议"的模板，便于一致调用。
  - **README.md 按场景按需读取** → 与 career-copilot 的 **references/ 按需加载**同构：面试模块只在进入面试场景时加载对应参考。
  - **De-AI writing（burstiness/perplexity/自然声线）** + **Reviewer 视角多评审模拟** → 对应**语气一致**（简历别像 AI 生成，躲 ATS/人工识别）与 `post_judge` 模拟招聘官多视角评审。
- **相关性：3**（模板自包含 + 按需加载对模块协议/references 设计有用，但偏内容层）

## 6. browser-router
- **一句话**：浏览器任务"路由员"：先澄清一个关键问题（要不要登录）再判定转交哪个浏览器工具，并守住冲突规避与敏感页红线。
- **可借鉴的具体手法 + 关联**：
  - **先澄清一个关键问题再动手**（"目标站点需要登录吗？"给三选项）→ 对应 career-copilot 的**软意图路由 + 消歧**：进 `resume` 前问"校招还是社招？"；进 `matching` 前确认"全职/实习/城市"，避免默认猜错。
  - **触发边界（什么不算浏览器任务）+ "本 skill 只做判定+转交，不替代具体 skill"** → 对应意图路由的边界定义与**职责分离**：明确哪些请求不属于 career-copilot（如未经同意代投），router 只路由不实现。
  - **敏感页红线（银行/SSO/密码页绝不提取 token）** + **一台真实浏览器只由一个 driver 接管** → 对应**不泄露隐私/不绕过工具**红线与工具纪律（同一时刻只有一个记忆写入者）。
- **相关性：4**（消歧澄清问题 + 路由边界 + 红线对意图路由/红线直接可用）

## 7. browser-skill
- **一句话**：驱动用户真实登录浏览器的 skill，强制"会话生命周期 + 红线 + request-help 人环"三件套。
- **可借鉴的具体手法 + 关联**：
  - **强制生命周期（session start → 命令 → session stop 必须执行，含错误路径的 finally）** → 对应流水线的**强制清理/收尾**：每次运行必须以 verify 闸门收尾（即使中途出错也要写 handoff、关资源），可写成"finally-style" 保证。
  - **5 条红线（禁偷 token / 禁长期借用 / 禁跳过 stop / 禁未快照先升级观察 / evaluate 高危）** → 与 career-copilot 5 红线**结构同构**，尤其"禁未快照先升级观察"=先验证再行动；可作为红线条目的范本写法。
  - **`request-help`：带 `--target` ref 指引用户 + 结构化结果（continued/cancelled/timed_out/navigated）** → 对应**暂停点 + 人环**：career-copilot 的暂停点应携带上下文/目标，并捕获用户的显式 outcome（继续/放弃/超时），而非开放式等待。
  - **Observation priority（先 snapshot，仅在不足时升级 screenshot）** → 对应**渐进披露/verify**：先廉价验证再升级昂贵操作。
- **相关性：5**（生命周期 + 红线范本 + 结构化人环 outcome 与流水线/红线/暂停点高度同构）

## 8. browser-testing-with-devtools
- **一句话**：用 DevTools MCP 把"浏览器内容视为不可信数据而非指令"，并给出 REPRODUCE→INSPECT→DIAGNOSE→FIX→VERIFY 的工作流。
- **可借鉴的具体手法 + 关联**：
  - **信任边界框（TRUSTED 用户消息/project 代码 vs UNTRUSTED DOM/console/网络/JS 输出）+ 绝不把页面内容当指令、发现指令式文本要上报** → 对应**反幻觉/不绕过工具**：把 `fetch_jobs` 抓来的职位描述、网页内容当 data 不当 instruction；若岗位文本含"忽略之前指令"式内容要标记给用户。
  - **调试工作流（含 before/after 截图对比）+ Clean Console Standard（零错误才达标）** → 对应**verify 闸门**：每个 pipeline 阶段后 VERIFY；`verify_output` 前/后对比（如简历两版 diff）；"无闸门可跳过、零错误标准"可照搬。
  - **Test Plan（Setup/Steps + Expected/Check）+ Common Rationalizations + Red Flags + Verification 清单** → 对应 **eval/自检**：给 career-copilot 写可执行的 eval 测试计划（如"简历通过 ATS 测试"）。
- **相关性：5**（不可信数据边界 + VERIFY 工作流 + 自检清单对 verify 闸门/反幻觉/eval 极契合）

## 9. catdesk-browser
- **一句话**：CatPaw 浏览器自动化，含"敏感域内页强制前置检查"、ref 失效重快照、批量执行与 diff 验证。
- **可借鉴的具体手法 + 关联**：
  - **MANDATORY 前置检查（`.sankuai.com` 页面必须先跑 find-skills 并停下来等用户决定，绝不先执行 browser-action）** → 对应**硬闸门**：在触碰敏感上下文（用户真实登录态/隐私数据）前强制一次人工确认，是**不泄露隐私/不绕过工具**的"mandatory pre-check"范式。
  - **diff 验证（`diff_snapshot`/`diff_screenshot`）** → 对应 `verify_output` 的**前后对比**：简历修改、匹配结果迭代都可用 diff 呈现变化。
  - **批量执行 + "何时不批量"（snapshot/navigate/开新内容的 click 需新鲜 ref）** → 对应流水线：哪些阶段可批处理、哪些必须在中间暂停验证（与暂停点对齐）。
  - **工具调用记账（"批量导出省 ~90% 调用"）** → 对应流水线**效率度量**。
- **相关性：4**（强制前置检查 + diff 验证对硬闸门/verify 直接可迁移）

## 10. ci-cd-and-automation
- **一句话**：把"质量闸门流水线"作为一切其他技能的强制执行机制：门不可跳过，早发现问题最便宜。
- **可借鉴的具体手法 + 关联**：
  - **Quality Gate Pipeline（Lint→Type→Unit→Build→Integration→E2E→Security→Bundle，"No gate can be skipped"）** → 与 career-copilot 的 **pipeline + verify 闸门几乎是同构**：把 `gen_profile→fetch_jobs→pre_filter→smart_score→post_judge→verify_output` 建模成质量闸门链，`verify_output` 即"构建+安全"那一关；任何一关失败不得跳过。
  - **Shift Left（越早捕获越便宜）+ Faster is Safer（小批量更稳）** → 对应 `pre_filter` 在 `smart_score` 之前早筛掉不匹配岗位，省算力降风险；以及把求职拆成小步、配**暂停点**。
  - **回灌闭环（CI 失败→贴给 agent→修→再跑）+ Feature flags/Staged rollout/Rollback plan** → 对应 **eval 闭环**与 `planning` 模块：求职策略可灰度上线、可回滚（投得不好就调策略）。
  - **Build Cop 角色 + Red Flags + Verification 清单** → 对应指定一个"验证者"角色与每关自检清单。
- **相关性：5**（质量闸门链与流水线/verify 闸门同构度最高，是 Part1 最强映射之一）

## 11. cnki-advanced-search
- **一句话**：CNKI 高级检索，把自然语言解析成结构化字段（作者/标题/期刊/年份/来源类别）再填表提交。
- **可借鉴的具体手法 + 关联**：
  - **自然语言→结构化字段解析**（主题/篇名/作者/期刊/年份/来源类别分别映射）→ 对应**意图路由/参数抽取**：把"我想投字节的后端实习"解析成 company+role+stage+城市，喂给 `matching`/`resume`。
  - **Verified selectors 表（页面结构地图）** → 对应 career-copilot 的 **references/ 按需加载**：把已知招聘站点的字段结构登记为"verified selectors"。
  - **Captcha 检测（真实阻塞→暂停点）** + **等待结果轮询带超时** → 对应 verify 闸门中的"检测到需真人/超时"分支。
- **相关性：3**（字段解析与 references 映射对路由/抽取有用，机制偏抓取层）

## 12. cnki-download
- **一句话**：CNKI 下载，强调"用 navigate 直达而非点链接（省 3 次工具调用）"与执行前状态检查。
- **可借鉴的具体手法 + 关联**：
  - **"直接 navigate 而非点击，省 3 次调用" + 前置状态检查（未登录→error；验证码→error）** → 对应**工具纪律/效率**与验证前置条件：`fetch_jobs` 直连而非多步；每个阶段先查前置条件（登录态/已生成 profile）再行动。
  - **tool-call 最小化** → 流水线效率度量。
- **相关性：2**（主要是效率与前置检查，机制对流水线帮助有限但可借鉴前置校验）

## 13. cnki-export
- **一句话**：把 CNKI 文献导出推送到 Zotero 或存 RIS，核心是"多文献优先批量导出"与 Windows 编码处理。
- **可借鉴的具体手法 + 关联**：
  - **Mode Selection 表（单条 vs 批量，"多个文献一律优先批量"省 ~90% 调用）** → 对应 **triage/优先级**：按上下文选模式，多岗位批量评分时优先批量。
  - **Windows 编码必须用 Python 脚本走 UTF-8（中文 JSON 不能直传 bash）** → 对应**跨会话记忆编码安全**：`career-profile.md` 含中文姓名/经历，必须 UTF-8 安全读写，避免乱码损坏记忆。
  - **外部集成带状态码（201/500/0）** → 对应对外动作的 verify 回报。
- **相关性：3**（批量优先 + UTF-8 记忆安全对记忆/优先级有用）

## 14. cnki-journal-index
- **一句话**：查期刊收录情况，用 knownTags 白名单从正文筛出"北大核心/CSSCI/..."等标签。
- **可借鉴的具体手法 + 关联**：
  - **knownTags 白名单过滤（只认列表内的标签，避免误报）** → 对应**反幻觉/边界校验**：`verify_output` 对岗位/技能字段用白名单校验，只断言"确实出现"的收录/技能，不脑补。
  - **渐进披露（`hasMoreIntro`→点"更多介绍"→再快照）** → 对应 references/ 按需加载：信息不足时按需展开更深层参考。
- **相关性：2**（白名单校验思路可借，但场景较远）

## 15. cnki-journal-search
- **一句话**：按刊名/ISSN/CN 搜期刊，含"按正则自动识别搜索类型"与"仅当验证码真正可见才算阻塞"的精细判定。
- **可借鉴的具体手法 + 关联**：
  - **按正则自动识别类型（ISSN/CN）→ 自动选搜索字段** → 对应**意图路由消歧**：自动判别用户请求类型再分派。
  - **Captcha 精细判定（预加载 SDK 在 `top:-1000000` 不算，仅 `top>=0` 可见才报阻塞）** → 对应 verify 闸门的**防误报**：区分"真阻塞"与"良性默认态"，避免假阳性暂停。
  - **Fallback 解析** → 鲁棒性。
- **相关性：3**（自动识别 + 防误报阻塞对路由/verify 有用）

## 16. cnki-journal-toc
- **一句话**：浏览期刊目录并下载原版 TOC，强调"会话相关的 URL 不可缓存复用"。
- **可借鉴的具体手法 + 关联**：
  - **会话相关 URL 不可缓存/复用（下载链接 session-specific）** → 对应**记忆新鲜度**：session 专属数据（如本次会话的临时岗位快照）不写进长期 `career-profile.md`，避免用过期/错绑数据。
  - **未找到时返回"可用的年份/期号"而非硬错** → 对应**优雅降级**：返回可用选项而非报错。
- **相关性：2**（记忆新鲜度/优雅降级可借鉴，机制偏抓取层）

## 17. cnki-navigate-pages
- **一句话**：CNKI 结果翻页/排序，单脚本完成，错误时返回"可用选项"。
- **可借鉴的具体手法 + 关联**：
  - **错误返回附带可用选项（page_not_found 返回所有页码）** → 对应**优雅错误**：verify 失败时一并给出可选项（如"未找到第 N 页，当前共 M 页"），便于用户决策。
  - **复用同一 evaluate_script、省 snapshot** → 效率。
  - **Captcha 复检** → verify 闸门。
- **相关性：2**（优雅错误 + 效率可借鉴）

## 18. cnki-paper-detail
- **一句话**：提取论文详情，含"JS 提取失败时回退到快照解析"与文本清洗（去"附视频/网络首发"）。
- **可借鉴的具体手法 + 关联**：
  - **Fallback：结构化提取失败→回退快照解析** → 对应流水线**鲁棒性/回退**：`smart_score` 主路径失败时有降级路径（如规则打分而非模型打分）。
  - **文本清洗（剥离噪声后缀）** → 对应 `verify_output` 的**输出归一化**：去掉噪声字段再呈现。
  - **Verified DOM selectors** → references/ 映射。
- **相关性：3**（回退路径 + 归一化对 verify/鲁棒性有用）

## 19. cnki-parse-results
- **一句话**：把当前结果页解析成结构化论文数据，`user-invokable:false`（内部工具），前置必须是结果页。
- **可借鉴的具体手法 + 关联**：
  - **`user-invokable:false` 的内部工具标记** → 对应**工具纪律**：pipeline 中某些阶段（如 `pre_filter` 内部归一化）是内部步骤，不暴露给用户，避免误调用。
  - **前置条件检查（必须在结果页，否则提示）** → 对应 verify 闸门**前置条件**。
  - **Fallback 快照解析** → 鲁棒性。
- **相关性：2**（内部工具标记 + 前置检查对工具纪律有用）

## 20. cnki-search
- **一句话**：CNKI 基础关键词搜索，单次调用完成搜索+抽取，强调"直达不点链接"与批量导出省调用。
- **可借鉴的具体手法 + 关联**：
  - **"勿点链接、用 navigate 直达"省 3 次调用 + "批量导出不要逐篇进详情页"** → 对应**工具纪律/效率**：`fetch_jobs` 后直接拿结构化数据，避免多余跳转；多岗位批量处理。
  - **tool-call 记账（"Tool calls: 2"）** → 对应流水线**效率度量**习惯。
  - **Captcha 检测 + Verified selectors** → verify 闸门 + references。
- **相关性：2**（效率与直达思路可借鉴，机制偏抓取层）

## 21. codebase-design
- **一句话**：设计"深模块"的共享词汇：小接口+大实现、放在干净 seam、可测试，并提供 DEEPENING 与 DESIGN-IT-TWICE 两种方法。
- **可借鉴的具体手法 + 关联**：
  - **深模块（小接口背后藏大量行为）** + **一致词汇（module/interface/seam/adapter 精确用语）** → 对应 5 模块的**结构设计**：每个模块应是"深模块"，对外小接口、内部富行为；`references/` 即藏在接口后的深实现；并要求 5 模块间**词汇一致**（匹配/面试/简历共用一套术语）。
  - **删除测试（删掉后复杂度消失=透传，不值）** → 对应避免"透传模块"：确保每个模块都创造真实价值。
  - **DESIGN-IT-TWICE（并行起 3+ 子 agent 各出" radically different" 接口，再按 depth/locality/seam 对比、给出主见）** → 对应 **规划/分解 与 multi-model 评审**：设计求职策略时并行起多个候选方案对比，或让 `post_judge` 与 `smart_score` 走不同"模型视角"互审。
- **相关性：4**（深模块 + 一致词汇 + Design-It-Twice 对模块设计与规划/评审直接可迁移）

## 22. code-review
- **一句话**：沿"标准轴"与"规格轴"两轴并行评审，聚合时**分开展示、不重排**，且评审前先钉死固定点并确认 diff 非空。
- **可借鉴的具体手法 + 关联**：
  - **双轴并行评审（Standards vs Spec）聚合时不合并/不重排** → 与 career-copilot 的 **eval 自检直接同构**：可让 `post_judge`（规格轴：简历是否匹配该岗）与 `smart_score`（标准轴：是否违反通用规则）并行跑、分开报，避免一轴掩盖另一轴（简历合规但方向错 / 方向对但触红线）。
  - **固定点先钉死 + diff 非空才进子 agent** → 对应 verify 闸门**前置条件**：不在空/ null 数据上跑评审。
  - **"非每条都是硬 violation——标注为启发式"** + **smell baseline 常开** → 对应**约束层级**（HARD vs 判断项）与常开的红线检查。
- **相关性：5**（双轴分离评审与 post_judge/smart_score + 约束层级同构，强映射）

## 23. code-review-and-quality
- **一句话**：五轴代码评审，给每条发现打严重度标签（Critical/Required/Nit/Optional/FYI），并强调"评审要诚实、不捧杀"。
- **可借鉴的具体手法 + 关联**：
  - **五轴 + 严重度标签（Critical/Required/Nit/Optional/FYI，区分"必改"与"可选"）** → 与 career-copilot 的 **约束层级 HARD>REQUIRED>RECOMMENDED>RELAXABLE 直接对应**：eval 发现按严重度标注，用户一眼知必改 vs 建议。
  - **诚实评审（不 rubber-stamp、量化问题、对拍马屁说不——AI 代码更需审视）** → 对应**不编造/不确定必须说**：求职建议必须诚实 critique，不迎合用户；anti-sycophancy 对职业建议尤其关键。
  - **Verify the verification（核查作者的验证故事）+ Review checklist + Dead code hygiene（删前先问）** → 对应 verify 闸门自我核查、每模块清单、以及**记忆**：删 `career-profile.md` 条目前先问用户。
- **相关性：5**（严重度标签=约束层级 + 诚实评审=反编造/反捧杀，强映射）

## 24. comprehensive-thinking
- **一句话**：高责任复杂判断的强制"五重审视"框架，每层必须说明"它改变了什么"，并强制加入最强反方与前提辩证。
- **可借鉴的具体手法 + 关联**：
  - **五重审视强制输出契约（定义问题→大师体系→关键事实→反方压力+前提辩证→可验证收束），每层必须显式写"改变了什么"** → 对应 **规划/反思模块**：职业策略类高责任判断应采用强制多层结构，每层必须改变结论否则降级为假设——直接强化"想清楚再给建议"。
  - **最强反方意见（真实有力、非稻草人）+ 前提辩证分析（标注来源：事实/推测/迁移/权威/脑补）+ 判断动作（降级/收缩/补证/重建/通过）** → 对应 **反幻觉 + 不编造经历 + 不确定必须说**：对一次"匹配 verdict"必须显式给出最强反方，并把每条前提标成"用户陈述事实"还是"模型推断"，仅对"事实"类前提下结论——这是把红线落进推理的核心机制。
  - **真抓实干（落到证据/实验/实现/测试/沉淀之一）+ 反形式主义纪律（不为填模板而填，每层须改变判断）** → 对应 **eval 落地**：判断须有真实证据支撑，且 eval 不得走形式。
  - **触发条件（高复杂度/不确定性/代价）** → 对应何时升级到"深思模式"。
- **相关性：5**（最强反方 + 前提来源标注 + 五重审视是反幻觉/反思/规划最强迁移，Part1 顶级发现）

## 25. computer-use-guidance-windows
- **一句话**：Windows 桌面自动化指南，核心是"工具选型优先级：内置>MCP>浏览器>Computer Use（优先程序化而非视觉）"与"操作-等待-验证"节奏。
- **可借鉴的具体手法 + 关联**：
  - **工具选型优先级（能 CLI/API 就别用 GUI；Computer Use 只做无程序化替代的事）** → 直接支撑**不绕过工具**红线与工具纪律：career-copilot 优先用可靠工具（真实岗位 API / 文件编辑）而非脆弱的 GUI 自动化；仅在无程序化替代时才退而求其次。
  - **Operate-Wait-Verify 节奏（动作自动回截图→验证）+ Screenshot First + 只用最近截图的坐标（禁复用陈旧坐标）** → 对应 **verify 闸门**与"状态失效即重读"：每步操作后验证，不用陈旧记忆/状态。
  - **Lazy-load Bootstrap（执行前先加载完整工具 schema，不猜参数）** → 对应 **references/ 按需加载**：行动前先加载对应参考，不凭记忆猜工具形状。
  - **Error recovery（Escape/wait/回到已知状态）** → 对应失败恢复/回滚。
- **相关性：4**（工具优先级=不绕过工具 + 操作-等待-验证=verify 闸门，直接可用）

## 26. code-simplification
- **一句话**：在不改行为前提下简化代码，强调"每次改动前先问是否保持行为一致"、Chesterton's Fence、范围自律。
- **可借鉴的具体手法 + 关联**：
  - **ASK BEFORE EVERY CHANGE 清单（同输入同输出？同错误行为？同副作用？测试仍过？）** + **Preserve Behavior Exactly** → 对应 **不替代决策/不编造**：改简历时只改表达、绝不改用户的真实经历与事实；任何"优化"若改变了事实即为违规。
  - **Chesterton's Fence（不懂为何存在就别拆）+ Scope to what changed（不做无关重构）** → 对应**记忆/规划**：改 `career-profile.md` 前先理解条目由来；只在本次任务范围内编辑，不顺手改无关内容。
  - **"简化后更难懂就 revert" + 验证清单** → 对应 verify：若简历"润色"反而更差则回退。
- **相关性：3**（行为保持 + Chesterton  fence 对简历编辑/记忆修改有用）

---

## 跨技能元模式汇总（供 career-copilot 落地的 Top 迁移）

1. **质量闸门链（ci-cd / agent-browser-core / browser-testing）= career-copilot 的 verify 闸门**：把 `gen_profile→…→verify_output` 建模成"门不可跳过、每门后 VERIFY、No-Fake-Completion、零错误标准"，并给失败以结构化回报。
2. **双轴/多轴分离评审（code-review / code-review-and-quality）= post_judge 与 smart_score + 约束层级**：两轴并行、分开报告、不重排；每条发现打严重度（= HARD>REQUIRED>RECOMMENDED>RELAXABLE）；且评审要诚实、不捧杀（anti-sycophancy 支撑不编造）。
3. **最强反方 + 前提来源标注（comprehensive-thinking）= 反幻觉/不编造经历 的推理内核**：对匹配 verdict 强制给最强反方，并把前提标为"事实/推测/迁移/权威/脑补"，只对事实类下结论——把红线嵌进推理链。
4. **跨会话 handoff/compact 二分（ask-matt）= career-context.md / career-profile.md 设计**：显式区分 fork（开新会话带 handoff 文件）与 continue（同会话 compact），并设定"smart zone"式落盘时机。
5. **安全模式闸门 + 强制前置检查 + 结构化人环 outcome（agent-browser-core / browser-skill / catdesk-browser / computer-use）= 红线 + 暂停点**：敏感/高危动作前强制人工确认并记录范围；暂停点携带 target/上下文并捕获用户显式 outcome（继续/放弃/超时）。

（其余可迁移项：意图路由消歧与"第一原则"默认分支 [aihot/browser-router/ask-matt]；不可信数据边界 [browser-testing]；工具纪律与效率记账 [computer-use/cnki-*]；references 按需加载与 verified-selectors 地图 [awesome-ai-research-writing/codebase-design/cnki-*]；Design-It-Twice 并行候选对比 [codebase-design]；优雅降级与防误报阻塞 [cnki-journal-toc/cnki-journal-search]；回退路径与输出归一化 [cnki-paper-detail]；UTF-8 记忆安全 [cnki-export]；行为保持与 Chesterton's Fence [code-simplification]。）
==================================================
## 切片 2（skills_list.txt 第 27-52 行）
==================================================
# career-copilot 可迁移元模式审计 · Part 2（26 个 skill 深读）

> 审计目标：从 26 个已安装 skill 中抽取可借鉴的 **meta-pattern**，用于优化 `career-copilot`（求职全链路 AI Agent @ `D:\57709\Desktop\Apple\美团\career-copilot-copy`）。
>
> 目标结构速记（用于关联）：
> - 软意图路由 → 5 能力模块：**匹配 / 面试 / 简历 / 记忆 / 规划**
> - 5 条红线：不编造经历 / 不替代决策 / 不泄露隐私 / 不绕过工具 / 不确定必须说
> - 约束分层：**HARD > REQUIRED > RELAXABLE**
> - Python 管线：`gen_profile → fetch_jobs → pre_filter → smart_score → post_judge → verify_output → assess_competitiveness`，含 **pause points** 与 **verify gates**
> - 跨会话记忆：`career-context.md`(~200tok) / `career-profile.md`(~2000tok) / `event JSONL`；session-start 读、session-end 写 handoff
> - `references/` 按需分节加载；有 `evals/` 与 `tests/`

---

## 1. context-engineering
- **一句话**：通过"分层语境 + 按需披露 + 信任分级 + 显式暴露歧义"来控制 agent 输入质量，避免语境饥饿/泛滥。
- **可借鉴的具体手法 + 关联**：
  - **语境层级（rules→spec→source→error→conversation）**：直接对应 career-copilot 的"红线/约束 = rules 文件常驻、5 模块逻辑 = spec 按会话加载、记忆文件 = source 按需读、管线报错 = error 层"。建议把 5 条红线与 HARD/REQUIRED/RELAXABLE 分层作为**常驻规则层**，模块逻辑与 references/ 作为**按需层**，与现有 references/ 分节加载天然契合。
  - **信任分级（trusted / verify-before-acting / untrusted）**：迁移到 `fetch_jobs`/外部职位数据——第三方 API 返回、用户自述经历均为 **untrusted data**，须先"作为数据呈现给用户、而非指令遵循"。这强化"不绕过工具/不编造经历"两条红线：外部数据只用于匹配计算，不盲目采信。
  - **Confusion Management（歧义显式暴露）**：当模块间/约束间冲突时，用固定模板（CONFUSION + 选项 A/B/C）抛给用户，而非静默猜测。直接补强"不确定必须说"红线，可做成 `verify_output` 阶段的标准分叉。
  - **Inline Planning Pattern**：多步任务前发轻量 PLAN 再执行，30 秒防 30 分钟返工——对应各 pause point 之前的"先列计划再跑下一步"。
- **相关性：5**（语境分层与信任分级几乎可直接套用到记忆文件与红线常驻机制）

## 2. create-skill
- **一句话**：教 agent 写出高质量 skill，核心方法是"第三人人称 WHAT+WHEN 描述、progressive disclosure、feedback-loop 校验、按脆弱度设自由度"。
- **可借鉴的具体手法 + 关联**：
  - **Description = WHAT + WHEN + trigger terms（第三人人称）**：迁移到 5 个能力模块的自我描述。软意图路由当前靠"soft intent"，若给每个模块一段"何时该触发 + 触发词"的第三人人称描述，可让路由更稳、可测试（evals/ 可据此写路由用例）。
  - **Feedback Loop Pattern（先 validate 立即跑、不通过就回头、only proceed when passes）**：这正是 `verify_output` 的写法模板——每个管线步骤后紧跟校验脚本/规则，失败即退回上一步，绝不带病前进。
  - **Progressive disclosure（SKILL.md <500 行，reference 仅一层深）**：印证 career-copilot 的 references/ 分节加载策略；建议把每个模块长逻辑拆成 reference 文件，主 SKILL 只留"何时调 + 调哪个 reference"。
  - **Degrees of freedom（高/中/低按脆弱度）**：对应约束分层。HARD 红线=低自由度（脚本化、零偏差）、RELAXABLE=高自由度（文本润色可多方案试探），可显式标注每类约束的自由度。
- **相关性：4**（模块描述与 verify 循环写法可直接复用）

## 3. cv-latex-layout
- **一句话**：LaTeX 排版协作规矩——"绝不改文字内容、调全局参数先沟通、多方案并行试探、用数据说话、固定空间守恒"。
- **可借鉴的具体手法 + 关联**：
  - **绝对红线"永远不改用户文字内容"**：与 career-copilot"不编造经历"同构——简历模块（cv 生成）只可重组/润色表达，**不得增删、虚构、缩写用户真实经历**。建议把这条写成 resume 子模块的最高优先级红线（对应 HARD）。
  - **调全局参数前先沟通（分析→列方案及影响→等确认）**：对应"不替代决策"——如调整简历字号/结构、面试策略等影响用户的全局决策，须先给方案与影响再动手。
  - **多方案并行试探而非串行试错**：面试/简历可一次给 2-3 个版本让用户比选，而非改一版问一版（尊重用户时间）。
  - **用数据说话（底部空白 30.7pt 而非"看起来还行"）**：迁移到 `assess_competitiveness`——竞争力评估须给**量化指标**（匹配度分数、缺口条目数、薪资分位）而非模糊描述。
- **相关性：4**（简历内容红线与"先沟通后决策"与两条核心红线直接对应）

## 4. deai-writing
- **一句话**：去 AI 味的"检测→诊断→改写→验证"闭环，含场景路由、四层自检、冲突仲裁链、运行时自检。
- **可借鉴的具体手法 + 关联**：
  - **检测→诊断→改写→验证 四步闭环 + 四层自检（结构/节奏/禁区/气息）**：完美映射 `verify_output`/`post_judge`。建议 verify gate 也做"分层自检"：①事实层（经历是否真实）→②匹配层（评分是否可解释）→③红线层（5 红线是否触碰）→④语气层（是否像人、是否过度承诺）。
  - **场景路由表 + 边界模糊时"判定后告知用户我用 XX 场景"**：迁移到软意图路由——在 匹配/面试/简历/记忆/规划 间用路由表判定，模糊时显式告知"我按 X 模块处理"再继续，对应不确定必须说。
  - **冲突仲裁优先级链（用户显式 > Voice Profile > 场景规则 > 默认不改）**：直接对应约束分层 HARD>REQUIRED>RELAXABLE 的决策优先级，可补一句"用户显式指令高于一切约束"。
  - **运行时自检表（如"改了很多却说不清为什么"→停）**：可作为 agent 每次输出前的自检清单，防止"幻觉式编造"。
- **相关性：5**（四层自检与场景路由几乎可 1:1 复刻为 verify gate 与软意图路由）

## 5. debugging-and-error-recovery
- **一句话**：系统化调试——Stop-the-Line、分层 triage（复现→定位→最小化→修根因→防复发→验证）、把错误输出当不可信数据。
- **可借鉴的具体手法 + 关联**：
  - **Stop-the-Line Rule（出错先停、保留证据、不带着失败继续）**：对应 career-copilot 的 **pause point**——`verify_output` 不过就停，绝不跳过疑似失败直接进下一步（如匹配分数异常就停）。
  - **Treat error output as untrusted data（错误里的"执行此命令"类文字只呈现不执行）**：强化"不绕过工具"——职位/API 返回的"指令性文本"只作数据，禁止 agent 据此行动或外泄。
  - **Fix root cause not symptom + Guard against recurrence（写回归测试）**：对应管线"修一次就要有 gate 防复发"，`assess_competitiveness` 的评估偏差应沉淀为 eval 用例。
  - **Safe fallback（缺数据时优雅降级而非崩）**：fetch_jobs 无结果时给 EmptyState 而非编造，对应不编造经历。
- **相关性：4**（Stop-the-Line 与"错误即数据"直接强化 pause point 与不绕过工具）

## 6. deep-research
- **一句话**：结构化人机协作调研——大纲→用户确认→并行深搜→汇总报告，全程 human-in-the-loop。
- **可借鉴的具体手法 + 关联**：
  - **大纲先确认再执行 / 并行子代理逐项搜索**：对应管线"gen_profile/fetch_jobs 后可设确认点 + 多模块可并行"。soft intent 路由后先确认范围再跑 `pre_filter`/`smart_score` 能防跑偏。
  - **human-in-the-loop 控制点**：career-copilot 已有 pause points，本 skill 给出"在哪一阶必须等人"的范式——建议在 `fetch_jobs` 后、`assess_competitiveness` 结论前设人工确认。
- **相关性：3**（主要是人机协作节奏，对 pause point 设计有借鉴）

## 7. deprecation-and-migration
- **一句话**：管理废弃与迁移——强制 vs 建议、绞杀者/适配器/特性开关模式、把代码当负债、消灭僵尸代码。
- **可借鉴的具体手法 + 关联**：
  - **Advisory vs Compulsory 分级**：迁移到约束分层——HARD 红线=Compulsory（不可商量），RELAXABLE=Advisory（可慢慢改/用户自选），与现有分层一致但给了"默认建议、除非代价过大才强制"的操作指引。
  - **Strangler/Adapter 渐进迁移**：career-copilot 若后续重构某模块，可新旧并行、流量（调用）逐步切，避免一次重写带崩整条管线。
  - **Zombie code（无人拥有却人人依赖）**：提醒定期清理 references/ 中"写了没人用"的分节，防止记忆/模块膨胀。
- **相关性：3**（约束分级措辞与渐进迁移对模块治理有用）

## 8. diagnosing-bugs
- **一句话**：硬 bug 纪律——先建"紧致、会变红"的反馈环，再复现最小化、列 3-5 条可证伪假设、打带标签的探针、先写回归测试再修、收尾 post-mortem。
- **可借鉴的具体手法 + 关联**：
  - **Phase 1 反馈环（red-capable + 确定性 + 快 + 可无人值守）**：`verify_output` 应设计成"能抓到这次具体失败"的 gate，而非"没报错就过"。建议每个 verify gate 写明"它会在什么条件下变红"。
  - **3-5 条 ranked 可证伪假设（If X 则 Y 消失）**：迁移到 `smart_score` 校准——给匹配打分前先列"哪些因素会拉高/拉低分"，可证伪、可解释，对抗黑箱评分。
  - **Post-mortem"什么能防止这个 bug"**：对应 `assess_competitiveness` 收尾——每次评估偏差后问"什么能防止下次再偏"，并沉淀进 evals/。
  - **带标签探针 + 清理**：agent 内部推理痕迹打标、结束清掉，对应 event JSONL 的"仅留结构化、可复盘"纪律。
- **相关性：5**（反馈环与 post-mortem 直接强化 verify gate 与 eval 闭环）

## 9. documentation-and-adrs
- **一句话**：记"为什么"而非"是什么"——ADR 捕获不可逆转决策的理由、不删旧 ADR、内联注释只写 why、记录已知坑。
- **可借鉴的具体手法 + 关联**：
  - **ADR 模板（Context/Decision/Alternatives/Consequences）**：迁移到记忆系统——当用户在 规划/匹配 中做"不可逆或高代价"的选择（如拒绝某 offer、锁定某赛道），写入类似 ADR 的 `career-profile.md` 决策段，记"为何选、放弃了什么"，对应不替代决策（agent 不替用户决定，但忠实记录）。
  - **Document the why, not what**：career-context.md（~200tok）应只存"决策结论 + 指针"，career-profile.md 存"为什么"，与"不重复、靠指针引用"一致。
  - **Known gotchas 内联**：把 agent 易踩的坑（如某平台职位字段缺失）写进 reference，对应 references/ 按需加载。
- **相关性：4**（ADR 模式是跨会话记忆记录决策的现成模板）

## 10. docx
- **一句话**：用 Task Decision Matrix 按目标路由、生成后必跑校验、严禁 Unicode 项目符号等反模式。
- **可借鉴的具体手法 + 关联**：
  - **Task Decision Matrix（按目标选路径）**：迁移到软意图路由——用一张"用户意图→模块"的矩阵决定走匹配/简历/面试哪条，比纯 soft intent 更稳。
  - **生成后必跑 validate.py**：对应 `verify_output`——docx 生成后校验 XML 合法性，career-copilot 在简历/报告产出后也应有结构化校验（字段齐全、无虚构项）。
  - **"NEVER 用 Unicode bullet"类硬反模式**：对应 5 红线写成不可违反的硬清单（HARD 级）。
- **相关性：2**（机制偏文档生成，路由/校验思路可借）

## 11. domain-modeling
- **一句话**：主动打磨领域模型——挑战术语冲突、锐化模糊词、用具体场景压边界、内联更新 glossary、ADR 仅用于"难逆转+无上下文会惊讶+真权衡"。
- **可借鉴的具体手法 + 关联**：
  - **Challenge glossary / 锐化模糊语言（"account" 是 Customer 还是 User？）**：直接补强"不确定必须说"——用户自述目标模糊时（如"我想进大厂"），agent 应像领域建模一样逼问清楚再匹配，对应 `gen_profile` 阶段。
  - **CONTEXT.md = 纯 glossary，不写实现**：迁移到 `career-context.md`(~200tok) 定位——只存术语/决策结论指针，不塞过程，与现有设计一致。
  - **ADR 三条件（难逆转 + 无上下文惊讶 + 真权衡）**：与 documentation-and-adrs 呼应，给 career-copilot"何时写决策记录"的可操作判据。
  - **Cross-reference with code（用户说的与代码不符就暴露）**：对应 verify——用户自述经历与工具抓取数据不符时，须暴露而非默认采信。
- **相关性：4**（术语锐化与 glossary 定位直接强化 gen_profile 与记忆文件）

## 12. doubt-driven-development
- **一句话**：对每个非平凡决策，用"全新上下文对抗式审查"在落地前证伪——CLAIM→EXTRACT→DOUBT→RECONCILE→STOP，对抗式提示"找问题而非验证"。
- **可借鉴的具体手法 + 关联**：
  - **Fresh-context 对抗审查（"find issues" 而非 "is it good"）**：迁移到 `post_judge`——对 `smart_score` 给出的匹配结论，用一段对抗式 prompt 找反例（"这人为啥其实不匹配？"），显著降幻觉。
  - **只传 ARTIFACT+CONTRACT，不传 CLAIM**：verify gate 应基于"客观契约（岗位要求 vs 用户画像）"判定，而非 agent 自己的结论，防自我印证。
  - **Reconcile 四级分类（契约误读/可用/权衡/噪音）**：对应 `smart_score` 的判定输出结构——每条减分归到"要求不清/真实硬伤/可接受权衡/误报"。
  - **STOP 有界循环（琐碎/3 轮/用户说 ship）**：对应 pause point 的"何时停止追问"，防无限质疑卡死用户。
  - **跨模型二审（可选、必须显式询问用户）**：career-copilot 高 stakes 决策（如拒 offer 建议）可设"要不要换模型二审"的可选确认。
- **相关性：5**（对抗审查与契约式 verify 是 post_judge/verify_output 的最佳范式）

## 13. e2e-llm-channel-verify
- **一句话**：证明"多个集成点都走同一个可选 LLM 通道"的 5 步法——单一工厂、计数代理、OFF 模式证一开关控全局、组件直驱、gotchas。
- **可借鉴的具体手法 + 关联**：
  - **单一工厂决策点（所有点调同一 factory，一处开关控全局）**：迁移到 career-copilot 的 verify gate——所有管线步骤经**同一个** `verify_output` 入口，一处"校验开关"统管，避免某步私自绕过。
  - **Counting proxy（每次调用计数，硬证据）**：verify gate 不只"跑过"，要能报"本步实际校验了几条/触发了几次工具"，对应 `fetch_jobs`/`smart_score` 的可观测性。
  - **OFF 模式优雅降级（开关关→全部计数 0、弱路径兜底）**：对应"不绕过工具"边界——工具不可用时应**明确降级并声明**，而非偷偷用模型编造。
  - **Gotchas（optimistic pass 导致路径不触发 / 超时吞掉异常）**：提醒 career-copilot 的 `smart_score` 在"无证据"时不应默认通过，须显式判"证据不足"。
- **相关性：4**（单开关工厂 + OFF 降级是可观测 verify  gate 的范本）

## 14. econ-write
- **一句话**：经济学论文写作——"每词都有用、具体而非抽象（给真实系数）、读者优先、倒三角先给结论、引文须逐条核实（AI 常幻觉）"。
- **可借鉴的具体手法 + 关联**：
  - **Concrete not abstract（给真实系数，不说"找到很多有趣结果"）**：迁移到 `assess_competitiveness` 与简历——所有结论须有**具体事实/数字**支撑，禁止"你很优秀"类空话，对应不编造经历。
  - **Citation integrity（AI 常幻觉/错引，须逐条核实一手源）**：直接强化"不编造经历/不绕过工具"——agent 引用的公司、岗位、薪资数据须回一手源核实，引用前标注来源。
  - **Triangular/newspaper style（最重要先给）**：面试反馈、竞争力报告应"结论/最该改的点先说"，再展开。
  - **Reader First（为谁写、他已知什么）**：简历/面试输出须针对目标岗位与用户已知水平定制。
- **相关性：4**（具体实证 + 引文核实是 anti-hallucination 的强范式）

## 15. extern-article-absorption
- **一句话**：外部文章批量吸收管线——Theatre-trap 铁律（候选须引真实 code file:line、二手数字回一手核实）、并行子代理分簇、主代理亲核 3-5 关键锚点。
- **可借鉴的具体手法 + 关联**：
  - **Theatre-trap 铁律（不得只 grep 单文件下结论；须真核 file:line）**：迁移到"不编造经历"——agent 说"你符合某岗位"必须能指向**真实依据**（用户画像字段/岗位 JD 字段），禁止凭印象断言；子代理产出的匹配理由须主代理复核。
  - **一手核实警示（数字错位/过时/论文错配）**：对应 `fetch_jobs` 后必须对职位薪资/要求做一手核实，二手聚合数据不可直接采信。
  - **主代理亲核 3-5 关键锚点**：对应 `post_judge` 中"对最高权重的匹配/减分点人工（主代理）复核"，是 verify gate 的二级保险。
  - **双轨（A 缝补须授权 / B 创新只登记待授权）**：迁移到约束——修改用户真实简历/决策（A 轨）需授权，纯建议（B 轨）仅登记，对应不替代决策。
- **相关性：5**（Theatre-trap 与一手核实是"基于证据不编造"的最强范本）

## 16. find-skills
- **一句话**：任务前先搜专用 skill——两个强制源 + 一个条件源、关键词单调用、结果全呈现且不超 4 项、安装前必问用户。
- **可借鉴的具体手法 + 关联**：
  - **先搜后执行（任何实质任务先查专用能力）**：迁移到软意图路由——用户请求进来先判断是否命中 5 模块之一，未命中才走通用处理，与"find-skills 永远先搜"同构。
  - **关键词单调用 + 双语覆盖**：career-copilot 路由若用关键词，须"一次一个意图词"，避免"简历 求职 匹配"拼一长串匹配失败。
  - **结果全呈现、AskUserQuestion 封顶 4 项、必问确认**：对应不替代决策——当多个模块都可能适用，用结构化提问让用户选（≤4 项），不替用户拍板。
- **相关性：3**（路由前先"查能力"与提问封顶 UX 可借）

## 17. frontend-ui-engineering
- **一句话**：生产级 UI——避免 AI 审美、统一间距刻度、有意义的空/错状态、红 flag 自检、验证清单。
- **可借鉴的具体手法 + 关联**：
  - **有意义的 Empty/Error 状态（不空白屏）**：迁移到 `fetch_jobs` 无结果 / `smart_score` 无匹配时的输出——给"为什么没有、下一步做什么"，而非空或编造，对应不编造经历。
  - **Verification checklist（键盘可达/响应式/加载错空态）**：对应 `verify_output` 的"产出前清单"，career-copilot 可给每份交付物一份 checklist。
  - **AI 审美反模式（紫渐变/圆角滥用/占位文案）**：提醒简历/报告生成避免"AI 味模板感"，与 deai-writing 联动。
- **相关性：2**（主要是 UI，空/错态与校验清单可借）

## 18. fundamental-thinking
- **一句话**：层次化合理性审视——合法性（该不该做）/方案空间（是不是最优路径）/执行质量（是否接近理想态），先审视后动手、假设显式化、trade-off 归用户。
- **可借鉴的具体手法 + 关联**：
  - **三层审视（该不该 / 是否最优 / 是否够好）**：迁移到 规划模块——给用户职业路径建议前，先问"这条路本身合理吗（合法性）""有没有被惯性屏蔽的更优路径""当前执行差距是可取舍还是偷懒"。
  - **Rule 0 先审视后动手 + 假设显式化**：对应 pause point——高风险建议（转行/跳槽）前先显式列出假设（"你假设 X 行业增长"），假设不成立就停，对应不确定必须说。
  - **trade-off 摆出来、决策权归用户**：直接强化"不替代决策"——给出方案 A/B 优劣与切换成本，让用户定。
  - **运行时自检信号（"说不清为什么选这方案"→回第二层）**：可作为规划/匹配模块的内部触发——一旦 agent 在惯性执行就回头重审。
- **相关性：5**（审视框架与"假设显式化/trade-off 归用户"深度契合红线与规划模块）

## 19. genuine-discourse
- **一句话**：真诚对话对象——不 concede-then-soften、不抢"最清醒"、不把讨论转成行政任务、不 patronize、每句前自检。
- **可借鉴的具体手法 + 关联**：
  - **绝不 concede-then-soften（承认部分就立刻找补"但…"是虚伪和稀泥）**：迁移到面试/规划沟通——若认同用户某判断就真认同，若分歧就真分歧，不为了"平衡"稀释，对应不替代决策（尊重用户真实立场）。
  - **不把讨论转成行政任务（反复"记下来/帮你改简历"是被体验为逃避）**：提醒 career-copilot 在"面试陪练/职业讨论"场景专注对话本身，不急着把一切转成工具调用。
  - **每回复前自检（真同意/真分歧/稀释？是否抢最清醒？是否 patronize？）**：可作为对话类模块的轻量 verify gate。
- **相关性：3**（对话姿态与"不稀释用户立场"补强不替代决策）

## 20. git-workflow-and-versioning
- **一句话**：Git 即安全网——Save-point 模式（每切片提交）、原子提交、Change Summary 含"DIDN'T TOUCH"、pre-commit 查密钥。
- **可借鉴的具体手法 + 关联**：
  - **Save-point 模式（改一片→测→提交→下一片，最多丢一个增量）**：迁移到 session-end 写 handoff + `event JSONL`——每次关键操作即落盘一条事件，崩溃/越界最多丢一个增量，对应跨会话记忆的鲁棒性。
  - **Change Summary 的 "THINGS I DIDN'T TOUCH" 段**：对应"不绕过工具/不越界"——agent 每次交付附"我**有意没动**的X（超出范围）"，展示范围纪律，防擅自 renovation。
  - **pre-commit 查密钥/PII**：对应"不泄露隐私"——写记忆/交付前扫敏感字段（身份证/薪资明文）再落盘。
- **相关性：4**（Save-point 与"DIDN'T TOUCH"直接强化记忆落盘与边界纪律）

## 21. grilling
- **一句话**： relentless 逐条逼问——一次一问等反馈、能查环境的事实就自查不问、未达成共享理解不动手。
- **可借鉴的具体手法 + 关联**：
  - **一次一问 + 等反馈**：迁移到 面试准备/需求澄清——gen_profile 时逐条澄清目标，避免一次性砸一堆问题让用户懵。
  - **事实能查就自查而非问**：对应"不绕过工具"——用户经历/技能能由工具或已有记忆取得就别重复问，只问真正主观的决策。
  - **未达共享理解不动手**：对应 pause point——匹配/简历动手前必须与用户对齐目标。
- **相关性：4**（逐条澄清与"查而不问"强化 gen_profile 与 pause point）

## 22. grill-me
- **一句话**：深度逼问——先自己调研计划本身（代码/文档/测试/子代理）、选最优解并自我反驳，只把主观问题批量抛给用户等确认。
- **可借鉴的具体手法 + 关联**：
  - **先调研计划本身、自我反驳至存活或变主观**：迁移到 `pre_filter`/`smart_score`——agent 先基于真实数据自行论证"该不该匹配/打几分"，自我反驳后，只把"取决于用户偏好/权威"的主观点抛给用户，对应不替代决策。
  - **disclose what remains unexamined（受限时披露未覆盖分支）**：直接强化"不确定必须说"——资源有限时显式声明"我没覆盖 X 维度"。
  - **把主观问题批量带建议抛出**：对应 pause point 的高效确认——一次给推荐项+选项，而非零散追问。
- **相关性：5**（"先自证再抛主观 + 披露未覆盖"是 smart_score/不替代决策/不确定必须说 的三合一范本）

## 23. grill-with-docs
- **一句话**：grill-me + 留纸痕——逼问同时把领域术语写进 glossary、把难逆转决策写成 ADR。
- **可借鉴的具体手法 + 关联**：
  - **边逼问边记 glossary + ADR（仅难逆转/无上下文惊讶/真权衡才写）**：迁移到记忆系统——在规划/匹配对话中，把 settle 的术语写 `career-context.md`、把高代价决策写 `career-profile.md` 决策段，与 documentation/domain-modeling 的 ADR 判据一致，避免"聊完即忘"。
  - **不为可逆/琐碎选择建文档**：对应记忆文件"轻量指针"原则——career-context.md 只存值得跨会话保留的结论。
- **相关性：4**（纸痕纪律是跨会话记忆落盘的直接操作指南）

## 24. gzh-design
- **一句话**：公众号排版引擎——主题库单一来源、结构自动识别、生成后校验脚本须 0 ERROR、按需取组件库、绝不改原文内容。
- **可借鉴的具体手法 + 关联**：
  - **校验脚本须 0 ERROR 才交付**：迁移到 `verify_output`——简历/报告生成后跑结构化校验（字段、虚构项、红线触碰），ERROR 清零才交付，半角标点级 WARNING 也修到 0。
  - **主题库/组件库 = 单一来源 + 按需加载**：印证 references/ 分节加载；建议给 references/ 建 `index.md` 单一来源（类似 theme-index），避免散落。
  - **绝不改原文内容（每段都转换、不增删实质）**：对应"不编造经历"——简历产出严格对应用户输入，不擅自加戏。
  - **视觉层级（锚点≤5 处、标记层每段 1-3）**：迁移到报告排版——重点强调全文克制，避免"到处加粗=没重点"。
- **相关性：4**（0 ERROR 校验与单一来源索引直接强化 verify gate 与 references 治理）

## 25. handoff
- **一句话**：把当前对话压缩成 handoff 文档交给下一 agent——存临时目录、含 suggested skills、不重复其他产物（按路径引用）、脱敏。
- **可借鉴的具体手法 + 关联**：
  - **直接对应跨会话记忆 handoff**：本 skill 几乎是 career-copilot"session-end 写 handoff"的范本——把对话压成下一 agent 可接的文档，存 `AppData/Local/Temp`（临时目录，非工作区）。
  - **不重复其他产物、按路径引用**：迁移到 `career-context.md`(~200tok 指针) + `career-profile.md`(~2000tok 细节) 的两级设计——小文件只放结论与指针，细节在 profile，不冗余。
  - **Redact 敏感信息（密钥/PII）**：直接强化"不泄露隐私"——handoff/记忆落盘前脱敏（姓名、身份证、薪资明文）。
  - **suggested skills 段**：下一 session 启动时据 handoff 推荐该调哪个模块/reference，对应软意图路由的 session-start 读取。
- **相关性：5**（与跨会话记忆 handoff 机制 1:1 对应，是最直接可借的 skill）

## 26. html-deploy
- **一句话**：单文件 HTML 即时发布——决策规则（何时用）、likeCount 锁（已赞版本不可覆盖/删）、版本追加而非每日新短码。
- **可借鉴的具体手法 + 关联**：
  - **append version 而非覆盖（保留历史）**：迁移到 `event JSONL`——记忆/事件**只追加不覆盖**，保留可复盘历史，与现有 append-only 设计一致。
  - **likeCount 锁（已赞=用户认可，不可改）**：对应"用户已确认/采纳的输出不可被静默改写"——career-copilot 对用户拍板的简历/决策，重跑时应追加新版本而非覆盖原版。
  - **决策规则（何时适合用本服务）**：提醒 career-copilot 给每个模块写清"何时该用/不该用"，防误路由。
- **相关性：2**（append-only 与"用户认可不可覆盖"可借，机制偏部署）

---

## 附：Top 5 最可借用的元模式（跨 skill 共识）

1. **基于"证据/契约"的 verify gate（而非"没报错就过"）**——来自 deai-writing 四层自检、doubt-driven 契约式对抗审查、diagnosing-bugs 变红反馈环、e2e-llm-channel-verify 计数代理、gzh-design 0-ERROR 校验。→ 直接升级 `verify_output`/`post_judge`：gate 须能"变红"、须基于客观契约（JD vs 画像）、须报真实校验计数。
2. **不编造 = Theatre-trap + 一手核实 + 红线硬清单**——来自 extern-article-absorption（引真实依据、二手数字回一手）、econ-write（引文逐条核实）、cv-latex-layout（绝不改用户内容）、context-engineering（外部数据=untrusted）。→ 强化"不编造经历/不绕过工具"：任何匹配/竞争力结论须指向真实字段、外部数据先核实、红线写成 HARD 不可违。
3. **跨会话记忆 handoff 的标准范式**——来自 handoff（压缩+脱敏+按路径引用+临时目录）、git Save-point（每增量落盘）、html-deploy（append-only + 用户认可不可覆盖）、documentation/domain-modeling（ADR/glossary 记 why）。→ 固化 career-copilot 的 session-end 写 handoff、脱敏、两级指针、append-only event JSONL。
4. **决策权归用户 + 假设显式化 + 披露未覆盖**——来自 fundamental-thinking（trade-off 归用户、假设显式）、grill-me（先自证再抛主观、披露未覆盖）、genuine-discourse（不稀释用户立场）、find-skills（≤4 项必问）。→ 强化"不替代决策/不确定必须说"：高 stakes 建议给 A/B trade-off、显式列假设、资源有限时声明未覆盖维度。
5. **软意图路由的结构化（路由表 + 先搜后执行 + 模糊时显式告知）**——来自 deai-writing 场景路由、find-skills 先查能力、docx 决策矩阵、create-skill 第三人人称 WHAT+WHEN 描述。→ 把"soft intent"升级为可测试的"意图→模块"路由表 + 每个模块带触发词描述 + 模糊时告知用户所走模块。
==================================================
## 切片 3（skills_list.txt 第 53-78 行）
==================================================
# career-copilot 深度审计 · Part 3（slice 53–78）

> 审计对象：已安装 203 个 skill 中第 53–78 行对应的 26 个 skill。
> 目标 skill：career-copilot（求职全链路 AI Agent，路径 `D:\57709\Desktop\Apple\美团\career-copilot-copy`）。
> 当前结构：单 skill + 软意图路由 → 5 大模块（匹配 / 面试 / 简历 / 记忆 / 规划）；5 条红线；约束 HARD>REQUIRED>RECOMMENDED>RELAXABLE；Python pipeline（gen_profile / fetch_jobs / pre_filter / smart_score / post_judge / verify_output / assess_competitiveness）+ 暂停点 + verify 闸门；跨会话记忆（career-context.md ~200tok / career-profile.md ~2000tok / 事件 JSONL + session-start 读 / session-end 写交接单）；references/ 按需按章节加载；有 evals/ 与 tests/。
> 本报告只挖掘**可迁移的底层元模式**：验证闸门、记忆/状态管理、意图路由、护栏/红线、防幻觉/事实核验、结构化输出、eval/自检、语气一致、triage/优先级、规划/拆解、反思/自我反驳、工具纪律、渐进式披露、失败模式清单、leading words、跨会话交接。

---

## 1. humanizer
- **一句话**：检测并去除文本中的 AI 写作痕迹（基于 Wikipedia "Signs of AI writing" 33 类模式），通过 draft → audit → final 循环产出自然文本。
- **可借鉴的具体手法 + 关联**：
  - 「集群判定法」——**单个 em dash 不算证据，em dash + rule-of-three + vibrant tapestry + 结论段才是供词**。迁移到**匹配/简历模块的"防编造自检"**：不要用孤立信号判断某段经历可疑，而是用"cluster of tells"（如"成就无数字 + 动词堆砌 + 第一人称过度 + 时间空泛"一起出现）才触发 verify 闸门追问。
  - 「draft → audit → final」三阶循环 + 「重写不删除、保留原意」原则：迁移到 **smart_score / post_judge 文案质量闸门**，让终稿文案先过一遍"AI 味/空洞化"自检再交付。
  - 「说你不知道，别用 stock phrase 掩盖猜测」（§21 知识截止/推测填坑）：直接强化**红线 1「不编造经历」与红线 5「不确定必须说」**。
- **相关性：4** （强在"文本事实/风格自检"与"诚实说不知道"，弱在它只处理写作不处理流程）

## 2. hv-analysis
- **一句话**：横纵分析法深度研究——纵轴追时间深度（叙事）、横轴做同期竞品对比、横纵交汇产出新判断，最终出 PDF 报告，含信息充分性自检与"搜不到标暂缺"纪律。
- **可借鉴的具体手法 + 关联**：
  - **双轴框架**（纵向历程 + 横向对比 + 横纵交汇洞察）直接迁移到 **assess_competitiveness（竞争力评估）模块**：候选人对岗位的竞争力 = 纵向（其能力成长轨迹）+ 横向（与同赛道其他候选人/岗位要求的比对）+ 交汇（历史如何导致当下竞争力缺口）。
  - **信息来源优先级（一手>二手，多源循环印证假象警告）**：强化 **fetch_jobs / gen_profile 的事实核验**——岗位要求优先取官方 JD，薪酬取官方/工商文件，避免从一篇转载文章循环印证。
  - **「搜不到诚实标注『暂缺』，绝不编造」**：直接对应**红线 1 不编造**。
  - **信息充分性自检清单（纵/横/来源三层）** 可作为 **verify_output 闸门**的通用模板：信息不够就补，不凑合。
- **相关性：4** （双轴分析框架与来源纪律高度契合匹配/竞争力模块）

## 3. idea-refine
- **一句话**：把模糊想法通过发散→收敛两阶段打磨成可执行的 one-pager，含"Not Doing 列表"、显式假设清单、红 flags 自检。
- **可借鉴的具体手法 + 关联**：
  - **"Not Doing 列表"（ arguably the most valuable part）**：迁移到**规划模块**——求职规划不仅列"要做的"，必须显式列"这阶段不投什么 / 不盲目海投 / 不碰不擅长的赛道"，把取舍外显（呼应红线 2 不替代决策，让用户拍板边界）。
  - **Key Assumptions to Validate（带验证方法）**：迁移到**规划/匹配前的需求澄清**——把"用户自认的劣势/兴趣"列为待验证假设，而非直接当真。
  - **7 个思维透镜（反转/去约束/受众移位/组合/简化/10x/专家视角）**：迁移到**面试/规划模块的探索式提问**，帮用户打开职业可能性。
- **相关性：3** （规划模块受益明显，但偏产品构思而非求职）

## 4. ima-skills
- **一句话**：统一笔记/知识库管理 skill，靠「模块决策表 + 易混淆场景路由表 + 跨模块任务必须读两个子模块 + MANDATORY RULES + 双层错误处理（脚本层/业务层）」来消除意图歧义。
- **可借鉴的具体手法 + 关联**：
  - **「模块决策表 + 易混淆场景表」**：career-copilot 当前是"软意图路由"，最该补的就是这种**显式消歧表**——例如"帮我看看这个岗位"(匹配) vs "帮我改下简历"(简历) vs "我该投还是等"(规划) 的路由判定，以及易混场景（"把岗位加到我的清单"→匹配 vs "把这段经历写进简历"→简历）。
  - **「跨模块任务必须读两个子模块再执行」**：对应 **规划跨匹配/简历时的 references 按需加载纪律**——用户说"根据匹配结果改简历"，必须先加载匹配结论和简历 references，不能只读一个就动手。
  - **双层错误处理（进程非 0 + 后端业务 code≠0）**：对应 **verify 闸门的"工具失败"与"业务不达标"分离判定**。
  - **每天首次调用自动检查更新**：可迁移为 **session-start 时检查 career-copilot 自身 references/pipeline 是否需要刷新**。
- **相关性：4** （其"决策表+易混淆表+跨模块加载纪律"正是软路由 skill 最缺的显式化手法）

## 5. implement
- **一句话**：极简执行 skill（disable-model-invocation，仅指引"用 /tdd、跑 typecheck/test、最后 /code-review、commit"），强调每步可独立验证。
- **可借鉴的具体手法 + 关联**：
  - **单一职责 + 每步可验证 + 最后 commit**：作为**匹配 pipeline 的工程纪律参照**——gen_profile / fetch_jobs / pre_filter / smart_score 等脚本各司其职、各自可单独跑通与验证，符合现有分脚本设计。
- **相关性：2** （过于精简，可借鉴处有限，主要印证"分脚本+可验证"方向正确）

## 6. improve-codebase-architecture
- **一句话**：扫描代码库找"深化机会"，先出 HTML 报告再进入 grill 循环，强调"先定范围再扫描（YAGNI）"、deletion test、不重造接口、ADR 冲突处理。
- **可借鉴的具体手法 + 关联**：
  - **"SCOPE before you scan — YAGNI"**：迁移到**面试/规划模块**——先通过澄清锁定用户真正的求职痛点，再展开分析，避免一上来就泛泛扫一遍所有模块（呼应 interview-me 的"先假设再提问"）。
  - **grilling 循环（质疑约束/依赖/形状）**：迁移到**面试模拟的对抗式反问**——AI 扮演面试官时持续追问"你的决策依据是什么、边界在哪"。
  - **"deletion test / 不重造接口"**：对**记忆模块的'毕业机制'**有旁证意义（见 neat-freak）。
- **相关性：3** （scope-first 与 grill 循环可迁移，但领域偏架构）

## 7. incremental-implementation
- **一句话**：薄垂直切片（thin vertical slices）+ 增量循环（Implement→Test→Verify→Commit）+ 风险优先切片 + Simplicity First + Scope Discipline + 红 flags + Common Rationalizations 表。
- **可借鉴的具体手法 + 关联**：
  - **增量可验证、每步可回滚、风险优先切片**：迁移到**匹配 pipeline 的执行纪律**——把 pre_filter（高风险/高不确定性，可能误杀岗位）前置，先验证它再跑后续；每步留可验证中间产物（对应现有暂停点）。
  - **Scope Discipline（只动任务需要的，注意到但不修）**：直接强化**红线 4「不绕过工具」**——不在本轮任务范围的事（如顺手改用户已定稿的简历）不碰。
  - **Common Rationalizations 表**（"我最后一起测"/"一次写完更快"）：可作为 **evals/ 里针对 pipeline 的 anti-pattern 测试样例**。
- **相关性：4** （增量/风险前置/Scope 纪律与 pipeline + 红线高度契合）

## 8. install-skill-dependency
- **一句话**：环境探测 → 扫描依赖 → 计划安装 → 用户授权(AskUserQuestion) → 逐项执行 → 复核，强调"安装前必须显式授权"。
- **可借鉴的具体手法 + 关联**：
  - **启动期"环境探测 → 扫描脚本依赖 → 用户授权 → 逐项验证"**：迁移为 **career-copilot 启动时对 Python pipeline 依赖的环境自检闸门**——run 前先确认 gen_profile 等所需依赖存在，缺失则列出并请求授权安装，而非中途崩溃。
  - **逐项执行+验证闭环**：对应 **verify 闸门**对每个 pipeline 步骤的"执行后复核"。
- **相关性：3** （环境自检闸门可借鉴，但偏运维）

## 9. interview-me
- **一句话**：用"一次一问 + 附猜测 + 置信度数字"把用户的真实意图（want vs should-want）挖出来，直到 ~95% 置信且用户显式 yes 才停止。
- **可借鉴的具体手法 + 关联**：
  - **「一次一问 + 附 agent 的猜测 + 置信度数字」**：直接迁移到**面试模块的对抗式追问**，以及**匹配/规划前的需求澄清**——例如澄清"你想找什么样的工作"时，每次只问一个点并附上猜测（"我猜你更看重成长空间而非薪资，对吗？"），用置信度逼迫诚实自省。
  - **「want vs should-want 探测」（"如果不用向任何人交代，你真正想要什么？"）**：迁移到**规划模块的价值观澄清**，避免用户用"应该稳定/应该进大厂"掩盖真实偏好（呼应红线 2 不替代决策，但帮用户自己看清）。
  - **「Out of scope 不可省略」「显式 yes 才算确认」**：迁移到**规划模块的收尾确认**——必须显式写出"这阶段不做什么"，且用户明确 yes 才进入执行。
  - **95% 停止条件（"能预测用户下一三个问题的反应吗？"）+ red flags**：可作为 **session-end 交接单的"意图已收敛"判据**。
- **相关性：5** （一次一问+猜测+置信度+want/should-want，几乎是为求职意图澄清与面试模拟量身定做）

## 10. khazix-writer
- **一句话**：公众号长文写作 skill，核心是「四层自检体系（L1 硬规则 / L2 风格 / L3 内容 / L4 活人感）」+ 角色边界（人会/AI会）+ 升番逻辑 + 人物画像法。
- **可借鉴的具体手法 + 关联**：
  - **四层自检体系（硬规则→风格→内容→终稿自然度）**：迁移到**简历/文案模块的质检**——L1 对应"红线硬规则扫描"（不编造、不泄露隐私），L2 风格一致，L3 内容有支撑（每段成就有数字/事实），L4"读起来像真人而非 AI 代写"。可直接复刻其"质检报告"输出格式。
  - **角色边界（一手观察/核心创意/真实情绪必须人做，AI 只做素材/类比/扩写）**：直接对应**红线 2「不替代决策」**——AI 提供岗位信息、话术素材、利弊分析，最终投递决策与经历真实性归用户。
  - **人物画像法（从一个数据点想象完整的人）**：迁移到**candidate 画像 / 岗位画像**——把冷冰冰的 JD 或用户经历还原成具体的人与场景，提升匹配与面试辅导的代入感。
- **相关性：4** （四层自检与角色边界对简历/文案模块极有用）

## 11. km-doc-extractor
- **一句话**：分阶段批量提取协作文档（文本/图片/DrawIO），附「已知陷阱清单」+「完整性验证（expected vs actual 对比）」+ 中间状态保存 + 错误不中断。
- **可借鉴的具体手法 + 关联**：
  - **「已知陷阱清单（Trap 1..7）」**：迁移到**匹配 pipeline 的"已知失败模式清单"**——例如 fetch_jobs 的"反爬 403""折叠区未展开丢内容""分页断裂"，写进 references 作为 verify 闸门的前置备忘。
  - **「完整性验证：对比 meta.json 的 expected 与实际下载 actual」**：迁移到 **fetch_jobs 后的"岗位数量预期 vs 实际"核对**，以及 pre_filter 前后岗位数变化核对，防止静默丢数据。
  - **「错误不中断、记录继续」「先试跑一个再批量」**：迁移到 **pipeline 的稳健性**——单岗位/单脚本失败不影响整体，先小样本验证再全量。
- **相关性：3** （陷阱清单+完整性验证对 pipeline 稳健性有借鉴）

## 12. latex-paper-en
- **一句话**：英文 LaTeX 论文助手，靠「Module Router 模块路由表 + 每个模块一个 Python 脚本 + 只加载当前模块 references + 路由顺序 + 脚本失败先报命令和退出码再给最小下一步（不静默切换） + Safety Boundaries（不编造引用/指标）」。
- **可借鉴的具体手法 + 关联**：
  - **Module Router 表 + 「Read only the file that matches the active module」**：这是与 career-copilot **最同构**的结构——多模块 skill + references 按需加载。验证了 career-copilot "references/ 按需按章节加载"方向正确，且应有一张显式**模块路由表**把软意图映射到具体模块与 references 文件。
  - **「脚本失败先返回精确命令+退出码+关键 stderr，再给最小下一步，不静默切换模块掩盖失败」**：直接强化 **verify 闸门**——gen_profile 等脚本失败时，必须原样报出命令与退出码，不得让 LLM 假装成功继续。
  - **「区分 [Script] 与 [LLM] 发现」「Never fabricate citations/metrics」**：迁移到 **post_judge / verify_output**——把"脚本算出的匹配分"与"LLM 的定性判断"分开呈现，且永不编造岗位数据（红线 1）。
  - **Output Contract（% MODULE (Line N) [Severity] [Priority]: Issue）**：可作为 **evals/ 评测报告的统一格式**。
- **相关性：5** （结构同构度最高，是 career-copilot 当前设计的"最佳实践镜像"）

## 13. latex-resume-page-balance
- **一句话**：先测量填充率再动手 + 调整优先级按影响从小到大 + 每轮重测验证闭环 + 每次只改 1–2 项。
- **可借鉴的具体手法 + 关联**：
  - **「先测量再动手 + 验证闭环（每轮重测填充率）」**：迁移到**简历模块的内容/排版平衡**——改简历前一屏先"测信息密度/篇幅占比"，小步调整（先动间距再动字号），每轮重测，避免一次改崩。
  - **「优先级按影响从小到大、每次只改 1–2 项」**：对应 **增量式简历编辑纪律**，可纳入简历模块的 verify 闸门。
- **相关性：3** （与简历排版直接相关但范围窄）

## 14. latex-thesis-zh
- **一句话**：中文学位论文助手，与 latex-paper-en 同构（Module Router + 多脚本 + 按需加载 + 路由顺序 + Safety Boundaries），另含"文献综述共识→分歧→局限→空白→本文切入点"重写蓝图。
- **可借鉴的具体手法 + 关联**：
  - 同 latex-paper-en 的 **Module Router / 按需加载 / 失败不静默切换 / 区分脚本与 LLM / 不编造**（见上条）。
  - **「文献综述重写蓝图：共识→分歧→局限→空白→本文切入点」**：迁移到**面试模块的"行业/岗位认知梳理"**——帮用户把对某行业/岗位的理解从"罗列"升级为"有张力的叙事"，以及**规划模块的机会缺口分析**。
  - **「模板不明时先 detect_template 再决定后续」**：类比 **career-copilot 应先识别用户处于求职哪一阶段（探索/准备/投递/面试）再路由模块**。
- **相关性：5** （与 latex-paper-en 并列为结构同构标杆）

## 15. layered-lens
- **一句话**：认知分层技术——把用户的"宣称信仰（OS 层）"与"现实操作（App 层）"分开，避免用 OS 标准审判 App 层（过度总括），发现张力先映射后评判、允许用户反驳即退让。
- **可借鉴的具体手法 + 关联**：
  - **「OS 层 vs App 层」认知分层**：迁移到**面试/规划模块的"框架张力处理"**——当用户用某理论/价值观解释求职选择却与其操作矛盾时（如"我想做有热情的事"却去考公），先判断这属于哪一层，若在 App 层（谋生/合规）则判定为合理工具选择而非信仰崩塌，避免 AI 用理想标准审判现实选择。
  - **「先映射后评判 + 被纠偏立即退让重构」**：强化**红线 2 不替代决策**与"AI 真错了干净认"的姿态——用户反驳时退让而非硬杠。
  - 也可用于**用户"宣称的兴趣/能力" vs "实际行为"缺口分析**，喂给匹配引擎的 gen_profile。
- **相关性：3** （对面试/规划的心理分层有用，但求职场景触发频率中等）

## 16. multi-search-engine
- **一句话**：集成 16 个搜索引擎，含语言评估、受控搜索（限速/批处理/重试）、cookie 仅内存不落盘、结果聚合。
- **可借鉴的具体手法 + 关联**：
  - **「受控抓取（1–2s 限速、分批 3–4 引擎、403/429 重试）」+「多来源聚合」**：迁移到 **fetch_jobs 的外部抓取**——对多个招聘站做限速批处理与重试，聚合去重后输出统一岗位列表。
  - **「Cookie 仅内存、不落盘、会话结束清除」**：直接关联**红线 3「不泄露隐私」**——抓取涉及的任何会话凭证/用户 cookie 不写入磁盘、不进记忆文件。
  - **「结果聚合报告」**：对应 **verify_output 的"抓取摘要"**。
- **相关性：3** （受控抓取与隐私处理可借鉴，但偏爬虫工程）

## 17. nano-banana-pro
- **一句话**：图像生成/编辑，采用 draft(1K)→iterate(小改 keep 新文件名)→final(4K) 的渐进式循环，生成后不读回图。
- **可借鉴的具体手法 + 关联**：
  - **「草案→迭代→终稿 + 每轮新文件名保留历史」**：迁移到**简历/岗位 JD 生成的迭代纪律**——每版留痕（v1/v2），便于 re-audit 对比（见 paper-audit）。
  - 图像领域本身与求职无关。
- **相关性：2** （渐进式+版本留痕可借鉴，但领域弱）

## 18. neat-freak
- **一句话**：会话结束时的知识洁癖同步——三类知识（agent 记忆 / 项目 CLAUDE.md / 项目 docs）受众不同职责不重叠；「毕业(promote)」机制把稳定知识从记忆泵进文档；体量体检防膨胀；减优于加/合并优于追加/删除优于保留；相对时间→绝对日期。
- **可借鉴的具体手法 + 关联**：
  - **「薄记忆 + 厚文档」分层 + 毕业机制（反复出现的稳定事实从 context 泵入 profile）**：**与 career-copilot 跨会话记忆设计（career-context.md ~200tok / career-profile.md ~2000tok / JSONL）几乎同构**。直接借鉴其"毕业"判据——同一职业事实第 3 次出现 → 并进 career-profile.md，原 context 缩成一行指针，防止 context 膨胀到 200tok 上限外。
  - **「体量体检防膨胀（MEMORY.md ≤25KB/200 行，超出部分静默不加载 = 等于没记）」**：直接对应 **career-context.md 的 ~200tok 硬约束**——session-end 写入前先做尺寸体检，超了就精简/毕业，否则下次会话读不到。
  - **「减优于加 / 合并优于追加 / 删除优于保留 / 绝对日期（永远 2026-04-29 不写'最近'）」**：作为 **记忆写入纪律**写入 career-copilot 的 session-end 交接单规范。
  - **「变更影响矩阵（新事实会波及哪些文档层级）」**：迁移到 **session-end 交接单要评估"这次对话改动了哪些记忆文件、哪些该毕业、有无矛盾"**，而非只追加。
  - **「自检清单逐项过（尺寸反膨胀 + 完整性反漏改）」**：可作为 **session-end 记忆同步的 verification 清单**。
- **相关性：5** （与跨会话记忆机制高度同构，是本次切片最值得借鉴的记忆管理手法）

## 19. observability-and-instrumentation
- **一句话**：先定义"什么叫正常工作"的问题再仪器化；结构化日志（稳定事件名+字段+关联 ID）；告警对症状而非原因；并验证遥测本身没坏。
- **可借鉴的具体手法 + 关联**：
  - **「先定义 on-call 会问的问题，再决定埋什么信号」**：迁移到 **verify 闸门的设计**——先写清楚"匹配成功/简历达标"长什么样（具体判据），再写 gen_profile / smart_score 的校验逻辑，避免"为验证而验证"。
  - **「结构化事件日志 + 关联 ID」**：强化 **事件 JSONL 日志**——每条记忆/匹配事件用稳定 event name + 结构化字段 + requestId 式关联，便于跨会话追溯。
  - **「验证遥测本身（诱导一次失败，确认能被定位）」**：迁移到 **verify_output 不仅要校验业务结果，还要校验 pipeline 工具自身没静默坏掉**（呼应 latex 系列"脚本失败时显性报错"）。
- **相关性：4** （"先定判据再校验 + 验证校验本身"对 verify 闸门设计极有启发）

## 20. obsidian
- **一句话**：Obsidian vault 即普通文件夹，配置（obsidian.json）即真相源，不硬编码 vault 路径，安全重命名会更新 wikilinks。
- **可借鉴的具体手法 + 关联**：
  - **「配置即真相源、不硬编码路径、先读配置再操作」**：迁移到 **记忆文件定位**——career-copilot 找 career-context.md / career-profile.md 应读配置或约定位置，而非假设固定绝对路径（与 neat-freak 配合）。
  - **「安全重命名/移动要更新所有引用链接」**：对应 **记忆文件改名时同步更新 session-end 交接单与 JSONL 中的引用**。
- **相关性：2** （主要是路径/配置纪律，对记忆存储有旁证）

## 21. orange-line-illustration
- **一句话**：橙线风格插画的完整风格系统——非协商的核心规则 + 先设计隐喻再生成 + 失败案例清单 + "抽卡而非 QA（人做质量门）" + 角色一致性（先定人设复用）。
- **可借鉴的具体手法 + 关联**：
  - **「非协商的核心规则（一致性是全部意义）」**：迁移到**简历/文案的"风格系统"**——先定义该用户的简历 voice（如"克制、有数字、不浮夸"）作为不可协商底线，再生成。
  - **「抽卡而非 QA：生成便宜，AI 自检贵且无效，人的品味是质量门」**：直接对应**红线 2 不替代决策**——终稿质量由用户把关（抽卡挑选），AI 不替用户判定"这份简历够好了"。
  - **「失败案例清单（哪些隐喻/渲染失败及为何）」**：对应**简历模块的负样本/反模式参考**。
  - **「先定人设再生成、后续复用同一 prompt block」**：对应**候选人/岗位画像的一致性**——同一次求职周期里用户画像描述要稳定复用。
- **相关性：3** （风格系统+抽卡质量门对简历模块有借鉴）

## 22. overleaf
- **一句话**：Overleaf 项目操作（list→read→write→compile→download），含确定性工作流、错误处理表（401/403/folder_not_found 等）、session cookie 配置。
- **可借鉴的具体手法 + 关联**：
  - **「确定性工作流 + 错误处理表（错误→原因→解决方案）」**：作为 **pipeline 工作流与错误表的模板参照**——fetch_jobs/write_profile/compile 各步都应有类似"错误→原因→对策"表。
  - 领域（LaTeX 协作）与求职弱相关。
- **相关性：2** （工作流/错误表模板可借鉴，领域弱）

## 23. paper-audit
- **一句话**：deep-review-first 论文审计——多角色委员会（5 角色）+ 审查泳道(lanes) + 严格区分 [Script] 与 [LLM] 发现 + 引用锚定原文 + 评分公式 + re-audit（对比前后 issue bundle：FULLY/PARTIALLY/NOT_ADDRESSED/NEW）+ gate（PASS/FAIL，仅 Critical 能阻塞）+ 永不编造审稿证据。
- **可借鉴的具体手法 + 关联**：
  - **「多角色评审委员会」**：迁移到 **post_judge / verify_output 的多视角评审**——例如一次匹配结果由"匹配官（匹配度）+ 真实性官（经历是否可证）+ 竞争力官（与同赛道比）"三个角色分别出判据，避免单一 LLM 视角偏见。
  - **「区分 [Script] 与 [LLM] 发现、引用锚定到原文」**：强化 **post_judge 的可追溯性**——定性判断必须锚定到具体岗位要求/用户经历原文，且脚本分与 LLM 判断分开。
  - **「re-audit：对比前后 issue bundle（FULLY/PARTIALLY/NOT_ADDRESSED/NEW）」**：**极有价值**——迁移到"改完简历后重跑匹配"的 **前后对比能力**，让用户看到"改了 X 后匹配分从 62→78，新暴露 Y 缺口"，直接服务评估模块与迭代闭环。
  - **「gate：只有 Critical 能阻塞，其余 advisory」**：迁移到 **verify 闸门的阻断级别**——红线类（编造/隐私）是 HARD 阻塞，风格/优化类是 RECOMMENDED  advisory，不要一刀切全阻塞。
  - **「永不编造审稿证据 / 锚定原文」**：再次强化**红线 1 不编造**。
- **相关性：5** （多角色评审 + 前后 re-audit 对比 + gate 分级阻塞，与 verify 闸门/评估模块高度契合）

## 24. pdf
- **一句话**：PDF 操作工具箱，核心是「能力矩阵（按操作选工具）+ 子脚本/参考文件按需引用」。
- **可借鉴的具体手法 + 关联**：
  - **「能力矩阵（Operation → Recommended Tool → Approach）」**：可作为 **career-copilot references/ 的索引范式**——把"匹配/面试/简历/记忆/规划"每个能力映射到对应 references 章节与脚本，按需加载。
  - 领域（PDF）与求职弱相关。
- **相关性：2** （能力矩阵范式可借鉴，领域弱）

## 25. performance-optimization
- **一句话**：先测量再优化（无测量=猜测）+ MEASURE→IDENTIFY→FIX→VERIFY→GUARD 工作流 + 症状→测量起点决策树 + 反模式表 + 性能预算 + CI 强制 + Rationalizations 表。
- **可借鉴的具体手法 + 关联**：
  - **「MEASURE→IDENTIFY→FIX→VERIFY→GUARD」**：迁移到 **smart_score / assess_competitiveness 的调优纪律**——先测基线（当前匹配分/竞争力）再改，改完复测，最后加"守卫"（如把量化阈值写进 verify 闸门防回归）。
  - **「性能预算（设阈值并在 CI 强制）」**：迁移到 **给每份简历/每个岗位设"量化指标阈值"作为 verify 闸门判据**（如"核心竞争力点 ≥3 条且有证据""硬门槛匹配率 ≥70%"）。
  - **「症状→测量起点决策树」「反模式表」「Rationalizations 表」**：可直接作为 **evals/ 的负样本与反模式测试集**。
- **相关性：3** （测量先行+预算阈值对评估/verify 闸门有借鉴）

## 26. planning-and-task-breakdown
- **一句话**：把工作拆成带验收标准的可验证任务——依赖图 + 垂直切片 + 任务结构（描述/验收/验证/依赖/文件/规模）+ 检查点(checkpoint) + 规模指南(XS–XL) + 并行安全/需协调/必须串行 + 人类评审关卡。
- **可借鉴的具体手法 + 关联**：
  - **任务结构（验收标准 + 验证步骤 + 依赖 + 规模 + 文件）**：直接迁移到**规划模块的"求职行动拆解"**——把"找工作"拆成带验收标准的可验证切片（如"本周产出 3 份定向简历""完成 2 场模拟面试"），每个有验证方式与检查点。
  - **「检查点 + 人类评审关卡」**：对应 **session 边界与暂停点**——每 2–3 个行动后设 checkpoint，需用户确认再继续（呼应红线 2 不替代决策）。
  - **「风险前置（fail fast）」「垂直切片而非水平切片」**：迁移到**求职计划的排序**——把最高风险/最不确定的环节（如"先验证目标岗位是否真的招人"）前置。
  - **「并行安全 / 需协调 / 必须串行」**：迁移到**多岗位投递的协调**——同时改多份简历需先定"用户核心画像"这一共享契约再并行，避免各份自相矛盾。
  - **「规模指南（XL 必须再拆）」「Common Rationalizations（'我边做边想'）」**：可作为 **规划模块的拆解纪律与 evals 反模式**。
- **相关性：5** （任务结构/检查点/风险前置/人类评审，与规划模块及暂停点设计高度契合）

---

# 本切片最值得借鉴的 5 条摘要

1. **结构化"验证闸门"模型（来自 latex-paper-en / latex-thesis-zh / paper-audit / observability）**：career-copilot 已有 verify 闸门与暂停点，但应借鉴 latex 系列的「Module Router + 脚本失败先报命令/退出码再给最小下一步（不静默切换）」+ observability 的「先定义什么叫成功再校验」+ paper-audit 的「区分 [Script] 与 [LLM] 发现、引用锚定原文」。把 verify_output / post_judge 升级为"先定判据 → 跑脚本拿硬数据 → LLM 定性判断分开呈现 → 失败显性报错而非假装通过"。

2. **跨会话记忆的"薄记忆+厚文档+毕业机制"（来自 neat-freak）**：career-context.md(~200tok)/career-profile.md(~2000tok)/JSONL 的设计正是对的方向，但应补上 neat-freak 的「毕业(promote)」与「体量体检防膨胀」——同一职业事实第 3 次出现就并进 profile、原 context 缩成指针；session-end 写入前先做尺寸体检，超出 200tok 就精简/毕业，否则下次会话静默读不到（等于没记）。再借其「减优于加、绝对日期、变更影响矩阵」作为记忆写入纪律。

3. **多角色评审 + 前后 re-audit 对比 + gate 分级阻塞（来自 paper-audit）**：把匹配/评估从"单一 LLM 判断"升级为「匹配官/真实性官/竞争力官」多角色委员会；引入 re-audit 的 FULLY/PARTIALLY/NOT_ADDRESSED/NEW 对比能力，让用户改完简历后能看到"改了 X → 分从 62 变 78、新缺口 Y"的迭代闭环；gate 只让 HARD 红线（编造/隐私）阻塞，RECOMMENDED 项仅 advisory，避免一刀切。

4. **意图路由的显式消歧（来自 ima-skills）+ 意图澄清的一次一问法（来自 interview-me）**：软路由应补一张「模块决策表 + 易混淆场景路由表」（如"看岗位"vs"改简历"vs"该投还是等"的判定与跨模块加载纪律）；匹配/规划前的需求澄清借用 interview-me 的「一次一问 + 附猜测 + 置信度数字 + want/should-want 探测 + 显式 yes 才停」，把"用户到底想找什么样的工作"在动手前收敛到 ~95%。

5. **规划模块的"可验证任务+检查点+人类评审"（来自 planning-and-task-breakdown）+ 简历/文案的"四层自检+角色边界"（来自 khazix-writer）**：规划参照 planning-and-task-breakdown 把求职拆成带验收标准/验证/依赖/规模的垂直切片，每 2–3 步设 checkpoint 与用户评审关卡（呼应不替代决策）；简历文案参照 khazix-writer 的「L1 红线硬规则→L4 终稿自然度」四层自检，并把"角色边界（AI 只做素材/话术/利弊，经历真实性与投递决策归用户）"显式写入，直接落实红线 1/2。
==================================================
## 切片 4（skills_list.txt 第 79-104 行）
==================================================
# career-copilot 深度审计 · Part 4（切片 79–104）

> 审计对象：career-copilot（求职全链路 AI Agent Skill）
> 本切片负责的 skill 目录（来自 `/tmp/skills_list.txt` 第 79–104 行，共 26 个，绝大多数为 PM / 产品管理类 skill）：
> plugin-creator, pm-ai-shipping-intended-vs-implemented, pm-ai-shipping-shipping-artifacts,
> pm-data-analytics-ab-test-analysis, pm-data-analytics-cohort-analysis, pm-data-analytics-sql-queries,
> pm-execution-brainstorm-okrs, pm-execution-create-prd, pm-execution-dummy-dataset, pm-execution-job-stories,
> pm-execution-outcome-roadmap, pm-execution-pre-mortem, pm-execution-prioritization-frameworks,
> pm-execution-release-notes, pm-execution-retro, pm-execution-sprint-plan, pm-execution-stakeholder-map,
> pm-execution-strategy-red-team, pm-execution-summarize-meeting, pm-execution-test-scenarios,
> pm-execution-user-stories, pm-execution-wwas, pm-go-to-market-beachhead-segment,
> pm-go-to-market-competitive-battlecard, pm-go-to-market-growth-loops, pm-go-to-market-gtm-motions

> 说明：相关性 1–5 仅衡量「该 skill 的某个底层元模式对 career-copilot 当前设计的可迁移价值」，不代表 skill 本身与求职领域的相关度。

---

## 1. plugin-creator
**一句话**：引导用户把某个职业/行业的日常任务打包成一个「插件（含多个 Skill + references 知识库）」的工具。

**可借鉴手法 + 关联**
- **内部知识库 Skill（user-invocable: false）**：把纯领域知识做成对用户隐藏、仅被其他 Skill 按需引用的子 Skill。→ 关联 **记忆/references 体系**：career-copilot 的 `references/` 与 `career-profile.md` 可改造为若干 `user-invocable: false` 的内部知识 Skill（如「行业词典」「面试话术库」），保持主 SKILL.md 精简、运行时按需注入，而非全文常驻。
- **SKILL.md < 500 行 + references/ 渐进式加载 + 「写 AI 不知道的增量信息」**：强调含糊指令（"analyze carefully"）无价值，要写具体框架/维度/输出格式/pass-fail 判定。→ 关联 **匹配引擎脚本与 verify 闸门**：career-copilot 的 verify 闸门与四级约束（HARD>REQUIRED>RECOMMENDED>RELAXABLE）正是「具体判定标准」的范例，可进一步落到每个闸门写明 pass/fail 条件与负向用例。
- **Simple Tool Mode vs Orchestration Mode（编排模式带进度文件，记录每阶段状态/产物/时间戳）**：→ 关联 **匹配引擎 pipeline**：career-copilot 已是 Python pipeline + 暂停点，可借鉴「编排 Skill 维护一个进度文件」来强化跨阶段产物传递与跨会话可恢复性（与现有 session-end 交接单互补）。

**相关性**：4
**理由**：直接命中 career-copilot 2.0「不拆多 skill、强化 working memory+references」方向，内部知识库 Skill 与编排进度文件是最顺手的两种现成模式。

---

## 2. pm-ai-shipping-intended-vs-implemented
**一句话**：审计「文档里声称的意图」与「代码实际做的」之间的落差，定位通用扫描器漏掉的边界级 bug。

**可借鉴手法 + 关联**
- **意图 vs 实现逐边界比对 + 不匹配是否「跨边界」才计入**：doc 说 A、code 做 B，且跨越信任/成本/数据/租户边界才算真问题，否则丢弃。→ 关联 **verify_output / post_judge 闸门**：把 career-copilot 的 5 条红线与四级约束视为「文档化意图」，pipeline 实际输出视为「实现」，每个闸门逐条比「约束声明 vs 输出实际」，只报告跨边界的真实偏差。
- **「if you cannot cite both sides of the gap, it is a question to investigate, not a finding」** + **「Never fabricate intent… if the docs are silent, say the docs are silent」**。→ 关联 **红线「不编造」「不确定必须说」**：这几乎是 career-copilot 第 5 条红线的操作化写法，可作为 verify 闸门的标准话术约束。

**相关性**：5
**理由**：把"意图—实现"审计框架原样迁移到"约束声明—pipeline 输出"的校验上，是 career-copilot verify 闸门最贴切的元模式。

---

## 3. pm-ai-shipping-shipping-artifacts
**一句话**：定义让 AI 生成代码可被审查的「核心文档 + 条件文档」集合（架构/流程/权限/变量/测试地图等）。

**可借鉴手法 + 关联**
- **核心文档 + 条件文档（不适用就写一行说明，而非编造空文档）**：诚实地图优先于漂亮清单。→ 关联 **career-copilot 的 references/ 与记忆文件组织**：现有 `career-context.md / career-profile.md / 事件日志` 已是"核心"结构，可显式标注"条件引用"（如仅当用户有面试记录才加载 interview-notes），避免无谓加载。
- **tests.md = 三栏验证地图（现有覆盖 / 建议测试 / 缺口），缺口按"跨边界暴露程度"排序**：→ 关联 **evals/ 与 verify 闸门盘点**：career-copilot 已有 evals/，可补一张「约束覆盖地图」，列出每条 HARD/REQUIRED 约束当前被哪个脚本/闸门验证、哪些是"仅建议/无验证"，按风险排序——这正是 shipping-artifacts 的 tests.md 思路。
- **automation.md：明确区分「agent 提议」vs「app 强制」、工具面作为硬护栏、输出契约校验**。→ 关联 **红线「不替代决策」「不绕过工具」**：直接提供"提案 vs 强制执行"边界的文档化模板，可写进 career-copilot 的面试/规划模块。

**相关性**：5
**理由**：tests.md 验证地图与 automation.md 的"提案/执行"边界，正好补齐 career-copilot 的 eval 盘点与"不替代决策"红线落地。

---

## 4. pm-data-analytics-ab-test-analysis
**一句话**：用统计显著性、样本量、置信区间与护栏指标，给出 Ship/Extend/Stop/Investigate 结论。

**可借鉴手法 + 关联**
- **护栏指标（guardrail metrics）概念：主指标赢了但护栏退化 ≠ 真赢**。→ 关联 **匹配引擎 smart_score / assess_competitiveness**：job 匹配不能只看"总匹配分"，应设护栏维度（如城市/薪资/签证/在岗状态），高分但护栏触雷应降权或拦截，与现有四级约束呼应。
- **决策矩阵（结果→建议）**：→ 关联 **post_judge 输出**：把"是否推荐投递"做成显式决策矩阵，而非模糊结论。

**相关性**：3
**理由**：护栏指标 + 决策矩阵可强化匹配引擎的"推荐与否"判定，但统计细节对求职场景只是类比启发。

---

## 5. pm-data-analytics-cohort-analysis
**一句话**：按队列做留存/采用/异常分析，并建议后续定性研究。

**可借鉴手法 + 关联**
- **Step 1 先读数据并做数据质量校验（缺失值、结构校验）**。→ 关联 **匹配引擎 pre_filter / fetch_jobs**：在抓到职位后先做数据质量门（字段完整性、去重、异常值），与现有 pre_filter 一致，可补"质量分"。

**相关性**：2
**理由**：核心可借鉴点仅"先校验数据质量再分析"这一条，career-copilot 的 pre_filter 已覆盖，增量有限。

---

## 6. pm-data-analytics-sql-queries
**一句话**：把自然语言翻成多方言 SQL，并解释逻辑、给测试/验证建议。

**可借鉴手法 + 关联**
- **「用大白话解释查询逻辑」+「建议如何验证结果」**。→ 关联 **匹配报告/简历模块的可解释性**：career-copilot 给用户的匹配分、竞争力评估应配套"为什么这样打分的白话说明"与"如何核对"提示，呼应红线"不确定必须说"。

**相关性**：2
**理由**：可借鉴点落在"输出可解释 + 可复核"，但 skill 本身是代码生成领域，迁移面窄。

---

## 7. pm-execution-brainstorm-okrs
**一句话**：产出三套等权、各自可信的 OKR 方案供讨论，而非单一"最优解"。

**可借鉴手法 + 关联**
- **生成多套等权可信选项（不预设一个明显更好）+ 显式 flag 数据可得性假设**。→ 关联 **面试/简历/规划模块**：给用户多套等权可选策略（如三种简历叙事角度、三种面试准备路径），并把隐含假设（"假设你有 2 周准备期"）显式标出，契合"不确定必须说"。

**相关性**：3
**理由**：多选项 + 假设外显是软性但实用的交互模式，适配 career-copilot 的咨询式风格。

---

## 8. pm-execution-create-prd
**一句话**：用 8 节模板写 PRD，强调"按问题/岗位定义市场""显式 flag 假设""用相对时间"。

**可借鉴手法 + 关联**
- **「Flag assumptions clearly so the team can validate them」** + **「Markets are defined by people's problems/jobs, not demographics」**。→ 关联 **规划模块 + 红线「不确定必须说」**：求职规划应基于"用户的真实痛点/目标（job-to-be-done）"而非人口标签；所有推断标为假设待核。
- **结构化模板（8 节）**。→ 关联 **匹配报告/简历结构化输出**。

**相关性**：3
**理由**：假设外显与"按 JTBD 定义"对规划模块有用，模板思路与现有结构化输出重叠。

---

## 9. pm-execution-dummy-dataset
**一句话**：按列定义/约束/格式生成拟真测试数据集（CSV/JSON/SQL/脚本）。

**可借鉴手法 + 关联**
- **带业务约束的拟真数据生成 + 输出后做数据质量校验**。→ 关联 **evals/ 测试资产**：career-copilot 的 evals/ 需要拟真候选人与职位样本；本 skill 的"列定义+约束+歪斜分布（如 rating 40% 5星）"做法可直接用于造评测集，并对 eval 输入输出做质量校验。

**相关性**：4
**理由**：为 career-copilot 的 evals/ 提供现成、可复用的拟真数据生成方法，提升回归测试质量。

---

## 10. pm-execution-job-stories
**一句话**：用「When [情境], I want [动机], so I can [结果]」+ 验收标准（含边界）写 Job Story。

**可借鉴手法 + 关联**
- **验收标准含「edge cases handled gracefully」+ 可观测/可度量语言**。→ 关联 **verify 闸门与面试模块**：把每条红线/约束写成带边界用例的验收标准；面试故事也可套 JTBD 句式训练 STAR。

**相关性**：2
**理由**：JTBD 句式对面试叙事有帮助，但整体与 career-copilot 已有实践重叠度高，增量小。

---

## 11. pm-execution-outcome-roadmap
**一句话**：把"功能清单式路线图"改写为"结果导向"陈述（Enable [人] to [结果] so that [业务影响]）。

**可借鉴手法 + 关联**
- **「So what?」追问法挖到真实价值/用户收益**。→ 关联 **面试/简历模块**：帮用户把"做过 X"追问到"带来了什么结果/价值"，强化简历 impact 化与面试 STAR 的"so that"。

**相关性**：3
**理由**："So what?" 苏格拉底式追问是简历/面试辅导的实用技巧，迁移自然。

---

## 12. pm-execution-pre-mortem
**一句话**：假设已失败并倒推原因，把风险分 Tigers（真问题）/ Paper Tigers（被夸大）/ Elephants（无人提及的担忧），再按 Launch-Blocking / Fast-Follow / Track 定 urgency。

**可借鉴手法 + 关联**
- **三类风险分类 + 三级 urgency 分级**。→ 关联 **匹配引擎 post_judge / verify_output 的失败模式清单**：可把"匹配可能出错的方式"建成 pre-mortem 式清单（如 Tigers=简历夸大未被拦截、Elephants=用户未说的离职风险），并按"阻断投递 / 快速跟进 / 仅观察"分级处置。
- **「Default to Tiger if unsure」**（不确定先当真风险）。→ 关联 **红线「不确定必须说」**：保守偏置，与 career-copilot 的谨慎基调完全吻合。

**相关性**：5
**理由**：风险三级分类 + 保守默认，是给 verify 闸门与失败模式清单最直接的"如何组织风险"的现成框架。

---

## 13. pm-execution-prioritization-frameworks
**一句话**：9 种优先级框架速查（RICE/ICE/Kano/MoSCoW 等），含公式与适用场景。

**可借鉴手法 + 关联**
- **MoSCoW（Must/Should/Could/Won't）** 与 career-copilot 的 **四级约束 HARD>REQUIRED>RELAXABLE** 几乎是同构；可对齐术语与处置（Must≈HARD 阻断，Should≈REQUIRED，Could≈RECOMMENDED，Won't≈RELAXABLE/本次不做）。
- **核心原则「Prioritize problems, not solutions」** + Opportunity Score = Importance×(1−Satisfaction)。→ 关联 **规划模块的职位优先级排序**：把"投哪家公司"建模为 Opportunity Score（用户重视度 × (1−市场满足度)），而非拍脑袋。

**相关性**：4
**理由**：MoSCoW 直接映射四级约束，Opportunity Score 给出可计算的职位排序模型，性价比高。

---

## 14. pm-execution-release-notes
**一句话**：把技术变更改写成以"用户收益"为先、口语化、分类的发布说明。

**可借鉴手法 + 关联**
- **「Lead with user benefit, not the technical change」+ 技术→用户视角转换示例** + **「Breaking Changes / Action required」分类**。→ 关联 **简历模块**：把用户的"技术动作"改写为"业务收益"bullet（如 Redis 缓存→"页面提速 3×"），并保留"需用户确认/行动"类条目（如"需补充某段经历佐证"）。

**相关性**：3
**理由**：技术→收益的语言转换模板对简历重写很实用，属于表达层借鉴。

---

## 15. pm-execution-retro
**一句话**：用 Start/Stop/Continue、4Ls、Sailboat 等格式做复盘，产出 2–3 个可归属、可度量的行动项，并带「上一轮 carry-over」。

**可借鉴手法 + 关联**
- **Carry-over from last retro（检查上期行动是否完成）**。→ 关联 **跨会话记忆 / session-end 交接单**：career-copilot 的 session-start 读 context、session-end 写交接单，正好对应"上期 carry-over"机制，可显式检查"上次待办是否推进"。
- **行动项限 2–3 个（多了做不完）+ 可度量成功指标**。→ 关联 **规划模块的周计划**：避免求职待办无限膨胀。

**相关性**：3
**理由**：carry-over 机制与现有跨会话交接单天然互补，复盘格式也可用于"求职阶段性复盘"。

---

## 16. pm-execution-sprint-plan
**一句话**：按容量估算（预留 15–20% buffer）、Definition of Ready、依赖图、关键路径、风险来排 sprint。

**可借鉴手法 + 关联**
- **Definition of Ready（明确 AC、已估点、无阻塞）作为准入门槛**。→ 关联 **匹配引擎 pre_filter / 暂停点**：职位进入"深入分析"前需满足 DoR（字段齐全、非重复、用户授权），与现有暂停点一致。
- **15–20% 容量 buffer + 关键路径**。→ 关联 **规划模块的求职冲刺计划**。

**相关性**：3
**理由**：DoR 门槛与 pre_filter 思路一致，冲刺规划对"求职项目管理"有借鉴，但偏 PM 通用。

---

## 17. pm-execution-stakeholder-map
**一句话**：用 Power×Interest 网格给干系人分类并定制沟通策略。

**可借鉴手法 + 关联**
- **Power/Interest 四象限 + 每象限沟通频率/渠道/关键信息**。→ 关联 **面试模块**：把面试中的多方（HR/用人经理/终面官/内推人）画成干系人图，定制沟通重点与跟进节奏。

**相关性**：2
**理由**：对面试关系管理有启发，但属于软性迁移，与核心机制关联弱。

---

## 18. pm-execution-strategy-red-team
**一句话**：红队审查计划——钢钉最强版本后再攻击，把每个失败模式写成「Fails if ___」，按 影响×可能性×测试成本 排序，给出最便宜的验证实验与 kill 准则，且"不自编弱点"。

**可借鉴手法 + 关联**
- **Steelman→Attack + 「Fails if ___」可证伪句式 + 按 impact×likelihood×cheapness-to-test 排序 + kill criterion + 最便宜测试**。→ 关联 **verify_output / post_judge 闸门**：把每条红线/约束写成可证伪的「Fails if」检查项，按（错判影响×发生概率×验证成本）排序，先跑最划算的验证；这正是 career-copilot 多阶段 pipeline（smart_score→post_judge→verify）的自我对抗版。
- **「Self-refute, don't fabricate… Never invent a weakness the plan doesn't have」「What I Couldn't Assess」**。→ 关联 **红线「不编造」「不确定必须说」**：直接提供"诚实红队"的话术与"无法评估"的显式出口。
- **可选 cross-model 模式（用第二个模型找分歧）**。→ 关联 **verify 闸门的二次校验**：可对高风险匹配/简历做"换一个模型复核"以暴露单一模型盲点。

**相关性**：5
**理由**：红队方法论几乎是 career-copilot verify 闸门与"不编造/不确定必须说"红线的完整操作手册，最值得直接吸收。

---

## 19. pm-execution-summarize-meeting
**一句话**：把会议转录结构化为 日期/参与者/主题/摘要/行动项(含负责人与截止)/决策/开放问题。

**可借鉴手法 + 关联**
- **结构化模板 + 「Open Questions（未决问题）」独立成节 + 行动项带 owner/due**。→ 关联 **session-end 结构化交接单**：career-copilot 的 session-end 交接单可直接套用此模板（决策=本次结论、行动项=下一步、Open Questions=不确定/待用户补充），与"不确定必须说"红线衔接。

**相关性**：4
**理由**：会议摘要模板与现有 session-end 交接单高度同构，能立刻提升跨会话交接的可读性与完整性。

---

## 20. pm-execution-test-scenarios
**一句话**：从用户故事生成测试场景：前置条件/角色/逐步操作(每步预期结果)/预期结果/边界用例。

**可借鉴手法 + 关联**
- **每步带「expected result」+ 显式边界/异常用例 + Starting Conditions**。→ 关联 **evals/ 与 verify 闸门用例化**：把 career-copilot 的 verify 闸门写成"测试场景"格式（前置=输入状态、步骤=脚本执行、预期=闸门应通过/拦截），边界用例覆盖"简历造假、隐私泄露、越权投递"等红线路径。

**相关性**：4
**理由**：把含糊的"验证"落成"测试场景"格式，正好强化 career-copilot 的 evals/ 与红线回归测试。

---

## 21. pm-execution-user-stories
**一句话**：按 3C（Card/Conversation/Confirmation）+ INVEST 写用户故事，验收标准含边界与性能。

**可借鉴手法 + 关联**
- **Confirmation = 清晰验收标准（可观测、可测）**。→ 关联 **verify 闸门判定标准**：每个闸门应有"Confirmation"式可观测验收条件，而非定性描述。

**相关性**：2
**理由**：验收标准思路与 test-scenarios、job-stories 重复，迁移价值被覆盖。

---

## 22. pm-execution-wwas
**一句话**：用 Why-What-Acceptance 写 backlog 项，强调"保持可协商、邀请对话而非加约束"。

**可借鉴手法 + 关联**
- **「Keep items negotiable — invite conversation, not constraints」**。→ 关联 **career-copilot 软意图路由哲学**：与 career-copilot「不拆显式 /command、靠理解模糊意图分流」一致——约束应留协商空间，避免过度硬编码路由。
- **Why 连接到战略/目标**。→ 关联 **规划模块的动机澄清**。

**相关性**：3
**理由**："保持可协商、邀请对话"精准呼应 career-copilot 的软路由设计哲学，是理念层面的印证。

---

## 23. pm-go-to-market-beachhead-segment
**一句话**：用 4 项标准（痛点烈度/付费意愿/可赢份额/转介绍潜力）评分选第一个切入点市场。

**可借鉴手法 + 关联**
- **4 维评分 + 「Start absurdly specific」「用 ≥10 次访谈验证」**。→ 关联 **assess_competitiveness / 职位优先级**：把"是否值得投这家公司"做成 4 维打分（匹配烈度/入职可行性/胜算/长期价值），并强调先用具体小样本验证假设。

**相关性**：3
**理由**：四标准评分框架可套到"职位机会评估"，但需做领域适配，属中借鉴。

---

## 24. pm-go-to-market-competitive-battlecard
**一句话**：做竞品对位卡：我们赢在哪/他们赢在哪(含反定位)/常见异议应对/胜负规律。

**可借鉴手法 + 关联**
- **「Where They Win + 我们的反定位」+ 「Common Objections & Responses」表**。→ 关联 **面试模块**：训练用户应对"你最大的弱点是什么""为什么选我们而非竞品"——用"诚实承认对方强点 + 反定位"结构，呼应"不编造"红线。
- **Win/Loss Patterns**。→ 关联 **复盘**：记录每次面试的胜负规律沉淀进记忆。

**相关性**：3
**理由**：异议应对 + 诚实反定位结构对面试辅导直接有用，且与不编造红线契合。

---

## 25. pm-go-to-market-growth-loops
**一句话**：识别 5 类增长飞轮（病毒/使用/协作/UGC/转介），估 loop coefficient，先做一个再叠加。

**可借鉴手法 + 关联**
- **「先精通一个 loop 再加复杂度」「按指标周度测量」**。→ 关联 **规划模块的执行纪律**：求职策略也应先聚焦 1–2 条主渠道（内推/猎头/直投），跑通再扩展，避免平均用力。

**相关性**：2
**理由**：仅"先聚焦单点再扩展"的纪律可借鉴，核心增长模型与求职弱相关。

---

## 26. pm-go-to-market-gtm-motions
**一句话**：对 7 类 GTM 动作按 1–10 打分，选 2–4 个组"动作栈"，排优先级与顺序。

**可借鉴手法 + 关联**
- **多维 1–10 打分 + 选 2–4 个互补动作 + 主/次分层 + 90 天路线**。→ 关联 **规划模块的渠道策略**：把求职渠道（内推/猎头/直投/招聘会/社媒）打分选栈、排主次与节奏，与 beachhead 的"聚焦"互补。

**相关性**：3
**理由**：打分选栈 + 主次分层可直接用于求职渠道规划，属中借鉴。

---

# 本切片跨 skill 反复出现的可迁移元模式（供主审计汇总）

1. **验证闸门 / 自我对抗**：strategy-red-team、intended-vs-implemented、shipping-artifacts(tests.md)、test-scenarios 共同指向"把约束落成可证伪检查项 + 红队攻击 + 覆盖地图"。
2. **风险/失败模式分级**：pre-mortem（Tigers/Paper Tigers/Elephants + Launch-Blocking/Fast-Follow/Track）提供"如何组织风险"。
3. **约束分级同构**：prioritization-frameworks 的 MoSCoW ≈ career-copilot 的 HARD/REQUIRED/RECOMMENDED/RELAXABLE。
4. **假设外显 / 诚实缺口**：create-prd、strategy-red-team、summarize-meeting(Open Questions)、intended-vs-implemented（"docs silent → say silent"）共同支撑"不编造 / 不确定必须说"。
5. **跨会话 carry-over**：retro(carry-over)、summarize-meeting(行动项+开放问题) 直接对应 session-end 交接单 / session-start 读取。
6. **references 渐进加载 + 内部知识库 Skill**：plugin-creator 提供"user-invocable:false 内部 Skill + SKILL.md<500 行"的现成结构。
7. **结构化输出模板**：meeting summary、test scenarios、release notes（收益优先）可直接复用为匹配报告/交接单/简历的版式。
8. **多可信选项 + 假设外显**：brainstorm-okrs、wwas（保持可协商）呼应软路由与咨询式风格。
9. **拟真 eval 数据**：dummy-dataset 直接服务 evals/。
10. **决策矩阵 + 护栏指标**：ab-test-analysis 强化"是否推荐"的判定。
==================================================
## 切片 5（skills_list.txt 第 105-129 行）
==================================================
# career-copilot 深度审计 · 切片 Part 5（skills_list 第 105–129 行）

> 审计对象：career-copilot（求职全链路 AI Agent Skill）
> 本切片负责的 25 个 skill（全部为 `pm-*` 产品管理系列）：
> pm-go-to-market-gtm-strategy / pm-go-to-market-ideal-customer-profile / pm-marketing-growth-marketing-ideas / pm-marketing-growth-north-star-metric / pm-marketing-growth-positioning-ideas / pm-marketing-growth-product-name / pm-marketing-growth-value-prop-statements / pm-market-research-competitor-analysis / pm-market-research-customer-journey-map / pm-market-research-market-segments / pm-market-research-market-sizing / pm-market-research-sentiment-analysis / pm-market-research-user-personas / pm-market-research-user-segmentation / pm-product-discovery-analyze-feature-requests / pm-product-discovery-brainstorm-experiments-existing / pm-product-discovery-brainstorm-experiments-new / pm-product-discovery-brainstorm-ideas-existing / pm-product-discovery-brainstorm-ideas-new / pm-product-discovery-identify-assumptions-existing / pm-product-discovery-identify-assumptions-new / pm-product-discovery-interview-script / pm-product-discovery-metrics-dashboard / pm-product-discovery-opportunity-solution-tree / pm-product-discovery-prioritize-assumptions
>
> 说明：本切片 25 个 skill 都是模板化、单文件（仅 SKILL.md，无 references/ 子文件，核心手法均内联在正文，少数引用外部 URL 或本切片外的 `prioritization-frameworks` skill，未越界读取）。这些 skill 表面是"产品管理"，但其底层元模式（验证闸门、假设管理、三视角压力测试、置信度标注、三角验证、负面清单、Mom Test 访谈、分类-校验、优先级矩阵、渐进式披露）对求职 Agent 高度可迁移。

---

## 1. pm-go-to-market-gtm-strategy
- **一句话**：生成产品上市的 GTM 策略文档（渠道、信息、指标、分阶段发布计划）。
- **可借鉴手法 + 关联**：分阶段发布计划里明确写入 **"go/no-go decision points（继续/终止决策点）"** 与 **"Establish baseline metrics before launch（发布前先建立基线指标）"**。→ 直接对应 career-copilot 匹配引擎的**"暂停点 + verify 闸门"**：在 `smart_score` / `post_judge` 之间插入显式 go/no-go 检查清单，并要求先有"基线"（如候选人当前匹配基线、岗位最低门槛），不满足则阻断而非软通过。
- **相关性：3** — 仅提供"分阶段+决策点"的骨架，未给判定标准，需自行补判定逻辑。

## 2. pm-go-to-market-ideal-customer-profile
- **一句话**：从调研数据提炼理想客户画像（ICP），含人口/行为/JTBD/痛点。
- **可借鉴手法 + 关联**：输出里强制包含 **"Disqualification criteria（谁 NOT 是合适人选）"** 与 **"ideal-of-the-ideal（最理想子集）"**。→ 对应 career-copilot 匹配引擎的 **`pre_filter` 负向过滤**与 `assess_competitiveness`：当前引擎偏正向打分，建议补充"硬性排除项"（如地点/签证/年限不符直接淘汰）与"钻石候选人"子集标记，提升 `verify_output` 的可解释性。
- **相关性：4** — 负面清单是匹配/过滤场景最直接可迁移的结构。

## 3. pm-marketing-growth-marketing-ideas
- **一句话**：生成 5 条低成本创意营销方案（渠道/核心信息/原理/成本效率）。
- **可借鉴手法 + 关联**：**每个方案固定 4 字段结构（Channel / Core Message / Why It Works / Cost Efficiency）**。→ 对应 career-copilot **简历/面试模块的结构化输出**：把"为什么推荐这个岗位/这条建议"强制拆成「渠道→信息→依据→代价」，避免泛泛而谈，也便于 `verify_output` 逐字段核验。
- **相关性：2** — 纯输出模板，结构化思路 career-copilot 已有，价值在"字段化约束"提示。

## 4. pm-marketing-growth-north-star-metric
- **一句话**：定义北极星指标及 3–5 个输入指标，先分类业务游戏再用 7 条标准校验。
- **可借鉴手法 + 关联**：**"先分类（3 类业务游戏）→ 再按 7 条显式标准逐条校验（Easy to Understand / Customer-Centric / …）"** 的 classify-then-validate 模式。→ 对应 career-copilot **意图路由 + 验证闸门**：软意图分流到 5 模块后，每个模块应先"分类"（如面试→行为/技术/案例面）再用该模块的校验清单逐条过闸，而非直接生成。
- **相关性：3** — 分类-校验的"显式逐项核对"范式可内化进各模块 verify 闸门。

## 5. pm-marketing-growth-positioning-ideas
- **一句话**：基于竞品生成差异化定位陈述（陈述/战略依据/支撑信息/竞争优势）。
- **可借鉴手法 + 关联**：**每个定位固定 4 字段（Positioning Statement / Strategic Rationale / Supporting Message / Competitive Advantage）**，且 Step 1 强制做竞品 landscape。→ 对应 career-copilot **`assess_competitiveness`（竞争力评估）模块**：把竞争力结论结构化到「定位句 / 依据 / 佐证 / 相对优势」四字段，并与岗位竞品（其他候选人）做对照。
- **相关性：3** — 字段化 + 竞品对照思路适配竞争力评估。

## 6. pm-marketing-growth-product-name
- **一句话**：生成 5 个产品名，每条含名称/理由/品牌契合/记忆度/商标域名。
- **可借鉴手法 + 关联**：**结尾给出"Prioritize names that are…"约束清单（易读易拼、差异化、贴合调性、可用商标）**。→ 对应 career-copilot **护栏/红线里的约束分级（REQUIRED/RELAXABLE）**：用"优先级约束清单"形式把软性偏好显式化，便于 `verify_output` 逐项打勾。
- **相关性：2** — 简单约束清单范式，可作为 verify 闸门的填写模板参考。

## 7. pm-marketing-growth-value-prop-statements
- **一句话**：从已有价值主张生成面向营销/销售/落地的价值陈述。
- **可借鉴手法 + 关联**：**内联 "Example Framework (Canva)" 少样本示例**，且要求每条陈述"directly addresses a specific target segment"。→ 对应 career-copilot **简历模块**：在生成简历/求职信时内联 1–2 个"好样例"（如优秀 bullet / 优秀 cover letter 片段）做 few-shot，并要求每条都锚定"具体岗位/具体能力"，呼应"不编造、贴合事实"。
- **相关性：3** — few-shot 示例是防泛化、提一致性的轻量手法。

## 8. pm-market-research-competitor-analysis
- **一句话**：分析竞品强弱与差异化机会，输出结构化竞品档案。
- **可借鉴手法 + 关联**：(a) **"Validate competitive insights across multiple sources（多源交叉验证）"**；(b) **"Distinguish direct competitors vs adjacent alternatives（区分直接/相邻对手）"**；(c) **"Flag competitors gaining traction"** 监控提示。→ 对应 career-copilot **`fetch_jobs` / `verify_output` 的事实核验**：岗位信息须多源验证、明确"直接竞争岗位 vs 相邻岗位"、并对"近期热度上升的岗位/行业"做监控标记，呼应 2.0 的 working memory。
- **相关性：4** — 多源校验 + 直接/相邻二分 + 监控标记，直接补强事实核验与记忆。

## 9. pm-market-research-customer-journey-map
- **一句话**：绘制端到端用户旅程（阶段/触点/情绪/痛点/机会）。
- **可借鉴手法 + 关联**：(a) **"Define the persona: use a specific persona with JTBD, not a generic user（用具体 persona+JTBD，拒绝泛化）"**；(b) **"Identify critical moments: Aha / Moments of truth / Churn triggers（关键决策时刻）"**；(c) **优先级改进按 impact / quick wins / deeper investment 分层**。→ 对应 career-copilot **面试模块 + 规划模块**：把求职者面试旅程当成"用户旅程"，识别"关键时刻"（如行为面陷阱题、谈薪节点），并把提升建议按"高影响/速赢/深投入"分层，直接服务规划模块的优先级。
- **相关性：4** — persona 具体化 + 关键时刻 + 三层优先级，对面试/规划模块都很贴切。

## 10. pm-market-research-market-segments
- **一句话**：识别 3–5 个互斥客户细分并做产品契合分析。
- **可借鉴手法 + 关联**：**"Create 3-5 distinct, non-overlapping segments + validate distinctness（互斥、校验可区分性）"** 与 **"Flag segments requiring additional market research（标记需补调研的细分）"**。→ 对应 career-copilot **意图路由 + 不确定必须说**：5 大模块路由要"互斥不重叠"，并在无法区分时显式标记需更多信息（而非强行归类），正是"不确定必须说"红线在路由层的落地。
- **相关性：4** — 互斥性 + 不确定性标记，直接加固软意图路由的健壮性。

## 11. pm-market-research-market-sizing
- **一句话**：用 TAM/SAM/SOM 估算市场规模，含自上而下与自下而上两种方法。
- **可借鉴手法 + 关联**：(a) **自上而下 + 自下而上双估算并做 "Reconciliation（对账/三角验证）"**；(b) **"Key Assumptions & Risks：每条假设标 Confidence（high/medium/low）+ 如何验证最不确定的假设"**；(c) **"Cite sources — avoid unsupported numbers（引源、禁止无据数字）"**。→ 这条是**本切片与 career-copilot verify 闸门 + 不确定必须说 + 不编造 三重红线的头号映射**：匹配打分/竞争力评估应做"两套独立算法对账"、每条结论标置信度、无源数字一律禁止。强烈建议内化进 `verify_output`。
- **相关性：5** — 三角验证 + 置信度标注 + 引源纪律，几乎逐条命中 career-copilot 红线与 verify 闸门。

## 12. pm-market-research-sentiment-analysis
- **一句话**：对大规模反馈做情感打分与细分洞察（-1 到 +1）。
- **可借鉴手法 + 关联**：**情感分数量化（-1~+1）** + **"Flag segments with small sample sizes or uncertain sentiment（小样本/不确定情绪要标记）"** + **"Ground all findings in actual feedback; cite sources"**。→ 对应 career-copilot **`assess_competitiveness` 与面试反馈**：把"匹配度/面试表现"做量化打分并强制标注样本量与确定性，小样本结论必须降级提示，呼应不确定必须说。
- **相关性：3** — 量化打分 + 小样本警示，是风控表达的现成范式。

## 13. pm-market-research-user-personas
- **一句话**：从调研数据生成 3 个研究支撑的用户画像（JTBD/痛点/收益）。
- **可借鉴手法 + 关联**：**固定产出 "One Unexpected Insight（反直觉洞察）"** 字段 + **"Flag any data gaps"**。→ 对应 career-copilot **`gen_profile` / 记忆模块**：在用户画像里强制挖掘"反直觉点"（如表面不匹配实则强相关的经历），并在数据缺口处显式标记，补强跨会话记忆的"该问什么"。
- **相关性：3** — 反直觉洞察 + 数据缺口标记，提升画像深度与追问质量。

## 14. pm-market-research-user-segmentation
- **一句话**：基于行为/JTBD/需求对用户做聚类细分（≥3 个）。
- **可借鉴手法 + 关联**：**"Segment Prioritization：Strategic importance / Implementation difficulty / Recommendation（invest/maintain/de-prioritize）"** 二维优先级 + **"Flag segments underrepresented in feedback"**。→ 对应 career-copilot **规划模块的优先级排序**：把求职行动（投哪些岗/补哪些技能）按"战略价值 × 执行难度"二维排，输出 invest/maintain/drop 建议；并对"样本不足的方向"显式降级。
- **相关性：4** — 价值×难度二维优先级，是规划模块 triage 的直接模板。

## 15. pm-product-discovery-analyze-feature-requests
- **一句话**：按主题/战略对齐/影响/ effort/风险对功能请求做优先级。
- **可借鉴手法 + 关联**：**"Never allow customers to design solutions. Prioritize opportunities (problems), not features（不让用户设计解决方案，优先问题而非功能）"** + **Opportunity Score = Importance × (1−Satisfaction)** + **每条 top 项给 "High-risk assumptions / 最小成本验证法"**。→ 这是 **"不替代决策 + 不确定必须说" 的教科书式表达**：career-copilot 应把用户"我要投这个岗/改这句简历"当作"机会"而非"方案"，先澄清目标再给选项，并把高风险假设显式列出待验证。强烈映射到 5 条红线第 2 条。
- **相关性：5** — "不替用户决策、优先问题、暴露假设" 与 career-copilot 红线 2 几乎同构。

## 16. pm-product-discovery-brainstorm-experiments-existing
- **一句话**：为现有产品的假设设计低成验证实验（原型/A-B/探针等）。
- **可借鉴手法 + 关联**：**每个实验固定 "Assumption / Experiment / Metric / Success threshold" 四元组** + **"Test responsibly — don't put users or business at risk；生产实验须给 risk mitigation"**。→ 对应 career-copilot **verify 闸门与面试沙盘**：把"验证一个判断"结构化到「假设/做法/指标/阈值」，且对高风险动作（如代发投递、虚构经历）强制要求缓解措施——直接服务"不绕过工具、不编造"两条红线。
- **相关性：4** — 实验四元组是 verify 闸门的可执行格式；"responsible test" 补强安全护栏。

## 17. pm-product-discovery-brainstorm-experiments-new
- **一句话**：为新产品的概念设计精益创业预原型实验。
- **可借鉴手法 + 关联**：(a) **XYZ 可证伪假设："At least X% of Y will do Z"**；(b) **"Skin-in-the-Game：测真实付费意愿而非兴趣"**；(c) **"YODA：用你自己的数据，而非 Others' Data（市场报告/类比）"**；(d) **"Measure actual behavior, not opinions"**。→ 对应 career-copilot **`verify_output` 的事实纪律**：求职判断要写成可证伪假设（"该候选人在 X 类岗命中率≥Y%"），优先用"一手数据"（候选人真实经历/真实岗位 JD）而非二手概括，禁止用"大家都说这个行业好"类二手断言。
- **相关性：5** — 可证伪假设 + 一手数据(YODA) + 行为而非观点，正是防幻觉/事实核验的方法论内核。

## 18. pm-product-discovery-brainstorm-ideas-existing
- **一句话**：从 PM/设计/工程三视角为现有产品头脑风暴点子并优选 Top5。
- **可借鉴手法 + 关联**：**三视角（PM/Designer/Engineer）并行构思** + **"Discovery is not linear — loop back if experiments fail（非线性、失败就回环）"** + 每条点子带 **"key assumptions to validate"**。→ 对应 career-copilot **面试/简历模块的"多视角自评"**：让 Agent 分别以"HR/业务主管/技术面试官"三视角审视同一份简历；并明确"规划不是线性的，验证失败要回环重做"，呼应 2.0 的 working memory 迭代。
- **相关性：4** — 多视角互审 + 非线性回环，提升简历/面试评估的全面性与健壮性。

## 19. pm-product-discovery-brainstorm-ideas-new
- **一句话**：为新产品的初期发现做三视角特性头脑风暴。
- **可借鉴手法 + 关联**：**区分 Initial Discovery（验证产品该不该存在）vs Continuous Discovery（边交付边学）**，且新产品的 Top5 加权偏向 **"Core value delivery / Speed to validate / Differentiation"**。→ 对应 career-copilot **规划模块的阶段化**：把"求职方向探索期"（该产品该不该做）与"执行期"（边投边学）分开处理，早期重"核心价值匹配+快速验证"，避免一开始就过度精细化。
- **相关性：3** — 初探 vs 持续的阶段区分，对规划模块节奏有参考价值。

## 20. pm-product-discovery-identify-assumptions-existing
- **一句话**：用魔鬼代言人三视角，对功能想法的风险假设做压力测试。
- **可借鉴手法 + 关联**：**三视角魔鬼代言人（PM/Designer/Engineer）** 找失败原因 + **假设按 4 类风险（Value/Usability/Viability/Feasibility）展开** + **每条假设标 "what could go wrong / Confidence High-Med-Low / suggested test"**。→ 这是 **verify 闸门 + 不确定必须说的核心骨架**：career-copilot 在给出匹配/建议前，应先用三视角压力测试并落到 4 类风险（价值/可用性/可行性/合规），每条带置信度与验证法。强烈映射 `verify_output` 与红线 5。
- **相关性：5** — 三视角压力测试 + 四维风险 + 置信度/验证，几乎就是 verify 闸门的设计说明书。

## 21. pm-product-discovery-identify-assumptions-new
- **一句话**：为新产品的假设做 8 类风险识别（在 4 核基础上扩展伦理/GT/战略/团队）。
- **可借鉴手法 + 关联**：**在 4 核风险上扩展出 Ethics / Go-to-Market / Strategy / Team 共 8 类**，并强调 **"Good teams assume at least 3/4 of ideas won't perform as hoped（预期大多数假设会失败）"**。→ 对应 career-copilot **`assess_competitiveness` 与红线自检**：求职判断应扩展风险维度到"伦理/求职策略/市场时机/个人执行力"，并默认"多数乐观假设会被现实打脸"，主动降低过度承诺——服务"不替代决策、不确定必须说"。
- **相关性：4** — 8 类风险框架 + "多数假设会失败"的谦逊预设，强化竞争力评估的现实感。

## 22. pm-product-discovery-interview-script
- **一句话**：按 The Mom Test 原则生成结构化用户访谈提纲（无引导、问过去行为）。
- **可借鉴手法 + 关联**：**Mom Test 铁律：问对方生活而非你的点子、问过去而非未来、绝不当场推销、夸奖是噪声**；**追问技术："Can you give me a specific example?"（把观点逼成事实）**；**内置 note-taking 模板（Key Jobs/Current Solution/Biggest Pain/Surprise Finding…）**。→ 这是 **career-copilot 面试模块的头号借鉴源**：生成面试问答时应遵循"不问诱导性问题、用具体事例逼事实、记录 Surprise Finding"，并把"候选人自述"当 Mom Test 访谈来核验真实性（而非照单全收），直接服务"不编造/事实核验"。
- **相关性：5** — Mom Test + 事实逼问 + 笔记模板，几乎逐条命中面试模块的防幻觉与结构化。

## 23. pm-product-discovery-metrics-dashboard
- **一句话**：设计产品指标看板（NSM/输入/健康/业务指标 + 阈值 + 复盘节奏）。
- **可借鉴手法 + 关联**：**指标分层（North Star / Input / Health 护栏 / Business）** + **每条指标表含 "Alert Threshold（告警阈值）"** + **复盘节奏（Daily/Weekly/Monthly/Quarterly）** + **"If a metric won't change how you behave, it's a bad metric"**。→ 对应 career-copilot **2.0 方向中的 working memory + 跨会话监控**：把求职进度做成"看板"（主线指标/输入指标/健康护栏如"是否已投出/是否收到回复"），设告警阈值（如两周无回复触发策略调整），并按日/周/月节奏在 session-start 拉起，正是 working memory 的可操作化。
- **相关性：4** — 看板分层 + 告警阈值 + 复盘节奏，是 2.0 working memory 最贴切的落地范式。

## 24. pm-product-discovery-opportunity-solution-tree
- **一句话**：用机会解法树把"目标→机会→解法→实验"结构化的发现框架。
- **可借鉴手法 + 关联**：**四层结构 Outcome→Opportunities(非功能)→Solutions(≥3)→Experiments**；**"Never allow customers to design solutions；One outcome at a time；Discovery is not linear—loop back if experiments fail；Continuous not periodic（每周更新）"**。→ 对应 career-copilot **规划模块的全局结构**：把"拿 offer"拆成机会（短板）→多解法（多条路径）→小实验（先投 5 家测反馈），坚持"一次聚焦一个目标、非线性回环、持续更新"，并把"用户说要改某句"挡回成"机会"层。直接服务红线 2 与 working memory。
- **相关性：5** — OST 几乎是规划模块的现成骨架，且内嵌"不替用户决策 + 迭代 + 持续"。

## 25. pm-product-discovery-prioritize-assumptions
- **一句话**：用 Impact×Risk 矩阵对假设做优先级排序并建议实验。
- **可借鉴手法 + 关联**：**Impact×Risk 2×2 矩阵**：低/低→推迟，高/低→直接做，低/高→否决，高/高→设计实验；Risk 定义为 (1−Confidence)×Effort；每条待测假设给"最小成本、测行为而非观点、明确阈值"的实验。→ 对应 career-copilot **规划模块 triage + verify 闸门触发条件**：把"要不要为这个岗位补短板"用 Impact×Risk 决策（高影响高风险→先小实验验证再投入），直接决定 pause-point 是"继续/暂停验证/放弃"。
- **相关性：4** — 2×2 决策矩阵是 pause-point 与规划优先级的可执行化模板。

---

## 跨切片共性元模式（对本批 25 个 skill 的总结）
- **意图路由信号**：几乎每个 skill 在 frontmatter/`When to Use` 里带 `Triggers:` 关键词行——可借鉴为 career-copilot 软意图路由的"显式触发词表"（即便不拆显式 /command，也可在内部维护关键词→模块映射，提升路由确定性）。
- **渐进式披露**：统一用 `Domain Context`（定义"X 是什么/不是什么"）+ `Further Reading`（外部延伸）实现"按需加载"——与 career-copilot 的 `references/` 章节加载同源；可补一条"Domain Context 速查块"进各模块。
- **读取纪律**：普遍首句 "If the user provides files, read them first"（先读用户给的文件再分析）——对应 career-copilot `gen_profile` 应先吃进用户已有简历/经历文件。
- **输出纪律**：普遍 "Think step by step" + "Save as markdown" + 固定 Output Structure——对应各模块的结构化输出与持久化交接单。
- **置信度/不确定性贯穿**：market-sizing、sentiment-analysis、identify-assumptions-*、user-personas/segmentation 都在不同位置强制"标置信度 / 标数据缺口 / 标小样本"——这是本批最一致、也最贴合 career-copilot "不确定必须说" 红线的共性手法。

---

## 本切片最值得借鉴的 5 条（摘要）

1. **market-sizing 的"双算法三角验证 + 置信度标注 + 引源禁令"**（相关性 5）：把自上而下/自下而上两套独立估算对账，每条结论标 high/med/low 置信度并写明"如何验证最不确定的假设"，无源数字一律禁止——这是 `verify_output` 闸门与"不编造/不确定必须说"两条红线的直接实现模板。

2. **identify-assumptions-（existing/new）的"三视角魔鬼代言人 + 四维/八类风险 + 每条假设带 Confidence 与测试法"**（相关性 5）：在给出任何匹配结论或建议前，先用 PM/设计/工程三视角压力测试，落到 Value/Usability/Viability/Feasibility（扩展 Ethics/GT/Strategy/Team）风险，每条标置信度与验证方式——几乎是 verify 闸门的设计说明书。

3. **interview-script 的 "The Mom Test" 事实逼问 + 笔记模板**（相关性 5）：不问诱导性问题、问过去行为而非未来、"Can you give me a specific example?" 把观点逼成事实、记录 Surprise Finding——直接用于面试模块的问答设计与"对候选人自述做事实核验而非照单全收"。

4. **opportunity-solution-tree 的 "Outcome→机会(非功能)→解法(≥3)→实验" 四层 + "不替用户决策/非线性回环/持续更新"**（相关性 5）：为规划模块提供现成骨架，并内嵌"Never allow customers to design solutions"（即"不替代决策"红线）与迭代回环，天然契合 2.0 的 working memory。

5. **brainstorm-experiments-new 的 "XYZ 可证伪假设 + YODA 一手数据 + Skin-in-the-Game"**（相关性 5）：把求职判断写成"At least X% of Y will do Z"的可证伪假设，优先用候选人真实经历/真实 JD 等一手数据而非二手概括，测真实行为而非观点——是防幻觉与事实核验的方法论内核，可直接内化进 `fetch_jobs` / `verify_output`。

（另：prioritize-assumptions 的 Impact×Risk 2×2 矩阵、metrics-dashboard 的"指标分层+告警阈值+日/周/月节奏"分别是最佳的 pause-point 决策与 working memory 落地范式，建议一并采纳。）
==================================================
## 切片 6（skills_list.txt 第 131-156 行）
==================================================
# career-copilot 深度审计 · 切片 Part6（第 131–156 行）

审计范围：从已安装 203 个 skill 中，本切片负责的 26 个 skill（行 131–156）为
career-copilot 挖掘可迁移的底层元模式。

切片清单（按 skills_list.txt 行序）：
pm-product-discovery-summarize-interview, pm-product-strategy-ansoff-matrix,
pm-product-strategy-business-model, pm-product-strategy-lean-canvas,
pm-product-strategy-monetization-strategy, pm-product-strategy-pestle-analysis,
pm-product-strategy-porters-five-forces, pm-product-strategy-pricing-strategy,
pm-product-strategy-product-strategy, pm-product-strategy-product-vision,
pm-product-strategy-startup-canvas, pm-product-strategy-swot-analysis,
pm-product-strategy-value-proposition, pm-toolkit-draft-nda, pm-toolkit-grammar-check,
pm-toolkit-privacy-policy, pm-toolkit-review-resume, ponytail, pptx, prototype,
qa, rational-skepticism, research, resolving-merge-conflicts, rw-claim-audit,
rw-evidence-map

每节结构：名称 / 一句话定位 / 可借鉴手法 + 与 career-copilot 模块-机制的具体关联 / 相关性(1–5) + 理由。

---

## 1. pm-product-discovery-summarize-interview
一句话：把面试/用户访谈转录整理成结构化模板（JTBD、满意度、行动项），缺失项填“-”。

可借鉴手法 + 关联：
- 「缺失填 `-` 而非让模型补」是防幻觉的核心纪律，可直接迁移到 career-copilot 的**面试/简历模块**：当用户未提供某信息（如某段经历的具体数据），模板字段标 `-`，绝不允许模型自行补全数字或事实——这正是红线「不编造经历」的操作化。
- 「小学毕业也能看懂」的极简语言 + 固定输出模板 + 保存为独立 markdown 文件，可迁移为面试复盘/准备的结构化产物格式，与现有 references/ 渐进披露一致。

相关性：4。理由：输出模板化与"缺失不编造"原则可被简历/面试模块直接复用为防幻觉纪律。

---

## 2. pm-product-strategy-ansoff-matrix
一句话：用 Ansoff 矩阵（市场渗透/开发/产品开发/多元化）评估增长战略四象限。

可借鉴手法 + 关联：
- 每个象限标注**风险等级（低/中/高）+ 时间线**的写法，可迁移到**规划模块**：给求职策略选项（冲刺大厂 / 保底 / 转行）标注风险等级与周期，而不是只给平铺建议。
- 结尾「战略问题」反问清单（最佳风险收益比？能力在哪给优势？）可作为规划模块的**引导式反问**，契合红线「不替代决策」——给问题让用户自己选，而非替他拍板。

相关性：3。理由：风险分级+反问清单能增强规划模块决策辅助，但不直接触及护栏核心。

---

## 3. pm-product-strategy-business-model
一句话：生成 9 宫格商业模式画布，含 Domain Context 对比与一致性自检。

可借鉴手法 + 关联：
- 「**coherence check**：所有 9 块是否互相支撑、强化」可迁移为**匹配模块**的内部一致性自检——岗位要求与候选经历是否互相印证，矛盾处标出。
- 「Domain Context」段对比不同框架优劣（BMC vs Lean vs Startup）的写法，可借鉴用于 references/ 中对比不同求职策略的适用边界，支撑 2.0 的渐进披露。
- 显式列出「关键假设与风险」可迁移为匹配/规划结论旁的假设外显。

相关性：3。理由：一致性自检与假设外显是通用的质量管理手法，对匹配模块有实质增益。

---

## 4. pm-product-strategy-lean-canvas
一句话：精益画布，聚焦问题/方案/不公平优势，并建议最小验证实验。

可借鉴手法 + 关联：
- 「**先验证最危险假设**（risk-first）」+ 显式「关键假设清单」可迁移到**规划模块**：求职规划应先验证最不确定的环节（某岗位真实门槛、自身核心短板），而非平均用力。其「验证实验」模式对应「小步试投、用市场反馈校正」。

相关性：3。理由：risk-first 验证顺序对规划模块是实在增益，但内容偏产品侧。

---

## 5. pm-product-strategy-monetization-strategy
一句话：并行头脑风暴 3–5 种变现策略，每策略含适配度/单位经济/风险/验证实验。

可借鉴手法 + 关联：
- 「多方案并列 + 每方案统一维度（如何运作/适配度/风险/竞争位/验证实验）+ **收敛推荐先测 1–2 个**」可迁移到**规划模块**的求职路径生成：多条路径并行评估后收口，而非发散不决。

相关性：2。理由：结构可借鉴，但内容离求职较远，增益有限。

---

## 6. pm-product-strategy-pestle-analysis
一句话：从政治/经济/社会/技术/法律/环境六维做宏观环境评分。

可借鉴手法 + 关联：
- 「**影响 × 概率**二维评分 + 优先级=影响×概率 + 建应急方案 + 文档化假设与未知」可迁移到**匹配/规划模块**对行业/岗位的风险评估（如某行业裁员概率×影响），帮助「不在不确定处编造」——未知项显式归档。

相关性：2。理由：评分矩阵可借鉴，但宏观分析离求职核心较远。

---

## 7. pm-product-strategy-porters-five-forces
一句话：用波特五力评估行业结构与吸引力。

可借鉴手法 + 关联：
- 每个力分「**高/中/低**」并给「何时高/何时低」判断清单 + 标注**趋势（增强/减弱）** + 行业吸引力综合判定，可迁移到**匹配模块**对目标公司/岗位竞争烈度的评估，呼应「不确定必须说」（趋势不明标 REVIEW）。

相关性：2。理由：判定框架可借鉴，应用面窄。

---

## 8. pm-product-strategy-pricing-strategy
一句话：设计定价策略，含价值/竞争/价格弹性/锚定与验证实验。

可借鉴手法 + 关联：
- 「**假设 → 如何验证**」成对结构 + 「风险 → 缓解」成对 + 显式标记需验证假设，可迁移到**规划模块**：每个求职判断都配验证路径（如"假设该岗看重 X → 验证方法：看 JD 关键词/问内推"），强化防幻觉。

相关性：2。理由：成对结构是通用好手法，但与求职关联一般。

---

## 9. pm-product-strategy-product-strategy
一句话：9 节产品战略画布，含假设清单、最小验证实验、Can't/Won't 防御检验。

可借鉴手法 + 关联：
- 「**假设必须为真清单**（hypotheses）+ **低投入验证实验**」直接迁移到**规划模块**：列出"这份求职规划成立必须为真的前提"，并给最小验证动作。
- 「**Can't/Won't 防御检验**：为什么对手难以复制整组选择」可迁移为"为什么这个岗位你比其他人更适配"的差异化论证，服务**匹配/简历**模块的"为什么选我"。

相关性：3。理由：假设外显+最小验证+差异化论证，对规划/匹配模块有实质增益。

---

## 10. pm-product-strategy-product-vision
一句话：先生成 3–5 个愿景变体，再用「启发/可达/情感」三标准筛选最强。

可借鉴手法 + 关联：
- 「**多候选变体 → 明确标准筛选**」可迁移到**规划/面试模块**的"职业叙事/自我定位"打磨：生成多个"我是谁/我想去哪"的叙事变体，用明确三标准筛选，契合「不替代决策」——给选项而非代写。
- 深度可调（轻/中/深）与 2.0 渐进披露方向一致。

相关性：3。理由：多候选+标准筛选法对帮助用户想清职业叙事很有用。

---

## 11. pm-product-strategy-startup-canvas
一句话：融合战略 9 节 + 商业模型的创业画布，强调混合适配而非僵化套用。

可借鉴手法 + 关联：
- 元提示「**混合/改造框架以适应需求，而非机械套用**」可强化 career-copilot 2.0 的"不拆多 skill、按需渐进披露"设计哲学——框架是工具不是教条。
- 「先验证假设再推进」与现有 verify 闸门精神一致。

相关性：2。理由：元提示契合现有设计理念，新增具体手法有限。

---

## 12. pm-product-strategy-swot-analysis
一句话：SWOT 内外部四象分析，并交叉推导 Build/Defend/Pivot/Exit 战略。

可借鉴手法 + 关联：
- 这是与本 skill 最贴合的 PM 框架，可直接迁移为「**候选人 SWOT**」：**优势/劣势/机会(岗位)/威胁(竞争)**，并用「交叉推导」（用优势抓机会、补弱项防威胁）生成求职策略。
- 自带 **Exit 决策纪律**（威胁过多且竞争位弱 → 退出）——直接服务「不替代决策」与「不确定必须说」：明确告诉用户"这个岗位建议放弃/降级"，而不是硬凑匹配。
- 「战略应用（Build/Defend/Pivot/Exit）」可成为规划模块的**动作词典**。

相关性：5。理由：SWOT 与求职自我评估天然同构，且自带 Exit 决策纪律，几乎可直接作为匹配/规划的结构骨架。

---

## 13. pm-product-strategy-value-proposition
一句话：6 段 JTBD 价值主张模板（Who/Why/WhatBefore/How/WhatAfter/Alternatives）。

可借鉴手法 + 关联：
- 六段结构 + 「**强制写出 Alternatives**：用户不用你会用啥**」+ 末了产出可复用一句话陈述，可改造为「**候选人价值主张**」：面向某岗位你能解决的 JTBD、当前方案（其他候选人）、你的 How、产出 WhatAfter、雇主的 Alternatives。
- 直接用于**简历/面试模块**的"为什么选我"与差异化论证，且 Alternatives 强制项防止只讲自己、回避竞争。

相关性：4。理由：六段结构与"强制写替代方案"极适合求职价值表达与差异化论证。

---

## 14. pm-toolkit-draft-nda
一句话：起草 NDA，顶部免责声明 + 标记需法务复核的条款。

可借鉴手法 + 关联：
- 「**顶部醒目免责声明**（非专业建议，须由律师复核）+ `[⚠️ LEGAL REVIEW REQUIRED]` 标记待专业确认处 + 输出分「摘要/全文/定制笔记」三段 + 明确下一步(法律复核)」可迁移到 career-copilot 的**红线「不替代决策」**与边界守护：凡涉及签字/薪酬谈判/背调授权等法律范畴，必须标 `[⚠️ 建议咨询专业方]`，并把"找真人确认"作为收尾下一步。

相关性：4。理由：免责+专业复核标记的护栏范式，可直接强化"不替代决策"红线。

---

## 15. pm-toolkit-grammar-check
一句话：不改写，只给带「位置/错误/修复/原因」的纠错清单，按优先级排序。

可借鉴手法 + 关联：
- 「**只给建议不改写**、保留作者声音 + 错误四元组（位置/错误/修复/为什么）+ **优先级(关键/重要/次要)** + 检查清单保证覆盖 + 明确「何时不改」边界」可迁移到**简历模块**的简历诊断：不改用户简历原文，只输出"定位+问题+改法+理由"的清单并按影响排序。呼应「不替代决策」与「不绕过工具」（用清单引导用户自己改）。

相关性：4。理由：不改写+定位化+优先级化的反馈模式，与简历诊断高度契合。

---

## 16. pm-toolkit-privacy-policy
一句话：起草隐私政策，标记复核条款，强调整体与真实行为一致。

可借鉴手法 + 关联：
- 「**policy 必须与产品实际行为一致，否则改产品或改政策**」的诚实原则，可迁移为记忆模块铁律：**career-context/profile 中记录的隐私信息，输出涉及须显式脱敏**；且"声称的资历须与已存档事实一致"——直接服务「不编造经历」。
- 每节 `[⚠️ 复核]` + 发布前检查清单，对应红线「不泄露隐私」与 verify 闸门。

相关性：4。理由："声明=实际"一致性纪律，是防幻觉与隐私红线的基础范式。

---

## 17. ponytail
一句话："最懒的高级工程师"——只返回精简/删除建议清单，绝不自动执行破坏性操作。

可借鉴手法 + 关联（本切片最高价值之一）：
- **(a) 永不可删的安全护栏**（信任边界校验/数据丢失处理/安全/可访问性）——这正是 career-copilot「红线不可降级」的范式对等：5 条红线映射为"永不可删清单"，任何优化都不得削弱。
- **(b) 强度模式（lite/full/ultra/off）**——直接映射约束四级 HARD>REQUIRED>RECOMMENDED>RELAXABLE 的**可调档位**，可加一档让用户控制严格度（如求职敏感场景默认 full/ultra）。
- **(c) 只返回清单不擅自改**——对应「不替代决策」。
- **(d) 技术债账本**（把"推迟的捷径"显式收集留待核实）——可迁移为「**记忆待核实账本**」：未确认的经历/信息标 ponytail 式注释，留待用户核实，而非当场编造或跳过。

相关性：5。理由：永不删护栏、强度分档、只建议不执行——与 career-copilot 红线/四级约束/不替代决策几乎同构。

---

## 18. pptx
一句话：生成/编辑 PPT 的技能，含「Quality Assurance (Mandatory)」强制复查流程。

可借鉴手法 + 关联（高价值）：
- **(a) 强制 QA 心态**：「默认假设有错、像找 bug 而非盖章；第一遍零问题=没看够」。
- **(b) 委托子代理做「新鲜眼睛」独立复查**（即便只有 2–3 页）——避免作者盲。
- **(c) 迭代 verify-fix-recheck 循环，直到一轮无新问题**；**至少完成一次 fix-then-verify 才宣布完成**。
这整套是 career-copilot **verify 闸门 / verify_output** 的成熟范本：匹配/简历产出后默认找错、用子代理独立复核、循环验证。尤其「子代理新鲜眼睛复查」可强化 post_judge 的客观性，防止主模型对自己产物放水。

相关性：5。理由：强制找错+子代理独立复核+迭代验证循环，是 verify 闸门可直接复用的工程化范式。

---

## 19. prototype
一句话：用一次性原型回答一个具体问题，标注可丢弃、默认无持久化。

可借鉴手法 + 关联：
- 「**默认无持久化、状态留内存**」恰是 career-copilot 2.0 **working memory** 的范式；「**每步后打印完整状态（surface the state）**」可迁移为匹配引擎每步（scan/score/judge）把中间状态显式呈现，利于透明与暂停点；「**从第一天就标注为可丢弃**」可迁移为草稿态求职材料；「**验证后把决策并入真代码、原型留作 primary source 并指回**」对应"结论入记忆、过程留痕"。

相关性：3。理由：working-memory/状态可见性范式与 2.0 方向契合，但偏理念层。

---

## 20. qa
一句话：交互式 QA 会话，把用户问题拆解为可独立验证的 GitHub issue。

可借鉴手法 + 关联：
- **(a) 最多 2–3 个澄清问题、不过度访谈**——对应软意图路由下的克制澄清。
- **(b) 单个 vs 拆分判断**（可并行 thin issues）+ **阻断关系诚实标注**——可迁移为把复杂求职问题拆成可独立验证子任务（改简历/练面试/找岗位）。
- **(c) issue 模板（What happened / expected / steps / context）+「无文件路径行号、用领域语言、描述行为不描述实现」**——可迁移为「**求职卡点记录模板**」写入事件日志 JSONL，支撑跨会话交接与失败模式清单。

相关性：3。理由：任务拆分与问题记录模板，对事件日志/规划模块有用。

---

## 21. rational-skepticism
一句话：用「假设→逻辑→风险→偏差」四层质疑框架制约 AI 的自动化输出。

可借鉴手法 + 关联（本切片最高价值之一）：
- **(a) 四层质疑闭环**：假设质疑 / 逻辑质疑 / 风险质疑 / 偏差检查——可作**匹配/规划模块的「决策前自检」**：给求职建议前过一遍四层。
- **(b) 8 条原则中「区分确定性：基于事实/数据 vs 直觉/猜测」**——几乎就是红线「**不确定必须说**」的现成实现：把每条就业判断标注为"基于事实/基于推断"。
- **(c) 「找反例 / 考虑边界 / 评估风险」**防过度自信，对应防幻觉。
- **(d) 运行时自检清单**（连续 3 个"可能不对"就停、篇幅超 N 倍就停）+ 错误模式表 + 暂停点 + 深度可调（轻/中/深）——可迁移为防 AI 自动驾驶的护栏，且深度可调对应 2.0 渐进披露。

相关性：5。理由：四层质疑+区分确定性+自检清单，几乎是"不确定必须说"与防幻觉的现成实现蓝图。

---

## 22. research
一句话：用后台子代理对齐高信任一手来源，逐条引用、追溯到源头。

可借鉴手法 + 关联：
- **(a) 只信一手来源**（官方文档/源码/规范），追溯到「拥有该声明的来源」+ **(b) 每条主张都附来源**——可迁移到匹配引擎的 fetch_jobs/verify_output：抓 JD/公司信息后以一手来源为准、每条关于公司/岗位的陈述附来源指针，直接服务「不编造」与 verify 闸门。
- **(c) 后台 agent 并行、主线程继续**——可迁移为匹配 pipeline 的并行抓取。

相关性：4。理由：一手来源+逐条溯源，是 verify 闸门与防编造的事实层基石。

---

## 23. resolving-merge-conflicts
一句话：解决 git 冲突，不引入新行为，保留双方意图，回 primary source。

可借鉴手法 + 关联：
- **(a)「Do not invent new behaviour」** + **(b) 回 primary source 理解每次改动原意** + **(c) 尽量保留双方意图** + **(d) 跑自动化检查再收尾**——可迁移到 career-copilot **跨会话记忆合并**：合并事件日志/context 时不编造新经历、保留用户原意、冲突时回到原始记录；"跑自动化检查"对应 verify 闸门。

相关性：3。理由：不发明+保留原意+回 primary source，是记忆合并与防编造的干净范式。

---

## 24. rw-claim-audit
一句话：逐条核验主张是否被来源原文支持，含 verdict 七档与 PASS/REVIEW/BLOCK 闸门。

可借鉴手法 + 关联（本切片最高价值，可直接移植）：
- **(a) claim-to-source 审计**：抽取主张（数字/类别/趋势/比较/因果/方法）→ 记录文档位置+主张范围 → 定位来源 → 比较人群/时间/变量/方向/数值/不确定性 → 给 verdict。
- **(b) verdict 七档**：VERIFIED / PARTIAL / DISTORTED / UNSUPPORTED / UNVERIFIABLE_ACCESS / NOT_CHECKED / NOT_APPLICABLE。
- **(c) gate**：PASS（全 VERIFIED/NOT_APPLICABLE）/ REVIEW（含 PARTIAL/UNVERIFIABLE_ACCESS/NOT_CHECKED）/ BLOCK（含 DISTORTED/UNSUPPORTED）。
- **(d) 硬规则**：来源存在≠支持；VERIFIED 必须有具体 locator+说明；支持范围<句子范围则收窄；摘要不支持摘要未报细节；作者解释/测得结果/当前推断分开核；**数字核分母/单位/时间点/人群/分析集**；因果措辞须匹配设计；无法访问全文用 UNVERIFIABLE_ACCESS 绝不写 VERIFIED；**不自动改文稿，先出结果**；DISTORTED/UNSUPPORTED 未处理则 BLOCK。
- → 可整体套到 career-copilot **匹配引擎 verify_output/post_judge 闸门**与红线「不编造经历」：把简历每条事实主张（学历/年限/项目成果/技能）与 JD 要求做 claim-to-source 核验，每条给 verdict，UNSUPPORTED/DISTORTED 触发 BLOCK（匹配结果不得基于未核实主张）。**「数字核分母/单位/时间/人群」正是防简历注水的最佳操作化**；gate 三态可直接成为匹配/简历产出的闸门，与现有 verify 闸门合并。

相关性：5。理由：claim→source→verdict→gate 全套机制，几乎是为"不编造+verify 闸门"量身定做，可直接移植。

---

## 25. rw-evidence-map
一句话：把研究/设计/结果/偏倚/冲突/缺口组织为可追溯证据图，含硬性反幻觉纪律。

可借鉴手法 + 关联（本切片最高价值之一）：
- **(a) 四类严格分离**：用户材料 / 公开来源 / 当前推断 / 未知——可迁移为记忆与推理的**分层存储**：已确认事实、外部抓取、模型推断、未知分别着色，输出时标注每句属于哪类，这正是「不确定必须说」的结构化实现。
- **(b)「不生成不存在的论文/数据/DOI/工具运行结果」**——是红线「不编造经历」的最强表述。
- **(c) 证据确定性是「结果层判断」而非整篇打分**——可迁移为匹配评分的**不确定性按点标注**（某匹配点是确信还是推断）。
- **(d) 关系无来源定位只进候选区** + **冲突先查人群/设计/测量/分析/时间差异** + **新增证据保留旧判断+变化原因**——可迁移为记忆更新与匹配冲突处理的纪律。

相关性：5。理由：四分类分离+反幻觉铁律+确定性按点标注，是记忆/防编造/不确定必须说的高阶范式。

---

# 本切片最值得借鉴的 5 条

1. **rw-claim-audit 的 claim→source→verdict→gate 机制（相关性 5）**
   把"每条事实主张逐条溯源、给 VERIFIED/PARTIAL/DISTORTED/UNSUPPORTED 等 verdict、最终 PASS/REVIEW/BLOCK 闸门"直接套到简历事实核验与匹配 verify_output。其"数字核分母/单位/时间/人群"是防简历注水的最佳操作化，可成为现有 verify 闸门的硬内核。

2. **rw-evidence-map 的"四分类分离 + 反幻觉铁律"（相关性 5）**
   把"用户材料/公开来源/当前推断/未知"严格分层，输出时标注每句归属；"不生成不存在的论文/数据/DOI"是"不编造经历"的最强表述；"确定性按结果分级而非整篇打分"可迁移为匹配评分的不确定性标注。这是记忆模块与防幻觉的结构化基石。

3. **rational-skepticism 的"四层质疑 + 区分确定性 + 自检清单"（相关性 5）**
   假设→逻辑→风险→偏差四层闭环作为匹配/规划"决策前自检"；其中"区分确定性：基于事实 vs 直觉猜测"几乎是红线"不确定必须说"的现成实现；运行时自检清单（连续否定就停、篇幅超限就停）是防 AI 自动驾驶的即插即用护栏。

4. **pptx 的"强制 QA：默认有错 + 子代理独立复核 + 迭代验证循环"（相关性 5）**
   把 verify 闸门工程化：产出后默认找错、委托子代理做"新鲜眼睛"独立复查、fix-then-verify 循环到零新问题才收口。可直接强化 post_judge 的客观性，防止主模型对自己产物放水。

5. **ponytail 的"永不删护栏 + 强度分档 + 只建议不执行"（相关性 5）**
   "永不可删安全护栏"是 5 条红线不可降级的范式对等；lite/full/ultra/off 强度模式直接映射 HARD>REQUIRED>RECOMMENDED>RELAXABLE 可调档位；"只返回清单不自动删"对应"不替代决策"；"技术债账本"可迁移为"记忆待核实账本"，把未确认信息留待用户核实而非编造。

（荣誉提名：pm-product-strategy-swot-analysis 的 Exit 决策纪律、pm-product-strategy-value-proposition 的"强制写 Alternatives"、pm-toolkit-draft-nda/privacy-policy 的"免责+专业复核标记"、pm-toolkit-grammar-check 的"定位化+优先级化不改写"反馈。）
==================================================
## 切片 7（skills_list.txt 第 157-182 行）
==================================================
# career-copilot 深度审计 · 切片 7（skills_list 第 157–182 行）

审计对象 skill：career-copilot（单 skill、软意图路由、5 条红线、四级约束 HARD>REQUIRED>RECOMMENDED>RELAXABLE、Python 匹配引擎 + 暂停点 + verify 闸门、跨会话记忆三件套 + session 交接单）。
本切片覆盖 25 个已安装 skill（第 179 项 `skills` 目录无 SKILL.md，已跳过）。

> 关联映射速查：
> 路由 = 软意图路由（5 模块分流）；匹配 = Python 匹配引擎（gen_profile/fetch_jobs/pre_filter/smart_score/post_judge/verify_output/assess_competitiveness）；简历 = 简历模块；面试 = 面试模块；记忆 = career-context.md/career-profile.md/事件日志 JSONL/session 交接单；规划 = 规划模块；红线 = 5 条红线；约束 = 四级约束；闸门 = 暂停点/verify 闸门；2.0 = working memory + hooks 方向。

---

## 157. rw-journal-submission（期刊投稿核验）

- **一句话**：核验期刊、准备投稿文件、把审稿意见拆成带状态编号的回复台账，并组织修改证据。
- **可借鉴手法 + 关联**：
  1. **稳定意见编号 + 五态状态机**（待处理/已处理/待作者确认/不同意/受阻）——"不把模型生成的回复直接标为完成"。直接套用到**匹配模块 verify_output 闸门**与**简历模块**：每条匹配结论/每段简历修改都应带稳定 ID + 状态，模型产物默认是"待用户确认"而非"完成"。
  2. **修改位置用页码行号/稳定块 ID，版本变化后旧位置标为失效**——对应**记忆模块**的"原始材料变化后旧判断标为待复核"（见 166）。可让 career-profile.md 中每条经历有稳定锚点，简历改写后失效旧锚。
  3. **来源纪律 + 停止条件**："不编造编辑姓名、偏好、费用、时限或录用概率""无法访问期刊当前官方要求时不标完成"——强化**红线·不编造经历 / 不确定必须说**；匹配引擎在无法 fetch 真实 JD 时不得估算薪资/录取率。
- **相关性：5** — 稳定编号 + 状态机 + "模型产物≠完成"是 verify 闸门最缺的成形范式。

---

## 158. rw-literature-discovery（文献发现）

- **一句话**：把模糊请求改写成"需要支持/反驳/界定/解释的具体判断"，再据证据修正搜索方向。
- **可借鉴手法 + 关联**：
  1. **"把请求改写成具体判断"**（support/refute/delimit/explain）——直接用于**路由**后的**匹配模块**：用户"帮我找个远程工作"应被重写为可判断的检索式（地域=远程、职能=？、阶段=？），而不是拿原话当查询。
  2. **"文献发现服务于判断，不以文献数量作为完成标准"**——治 career-copilot"给得越多越好"的诱惑；匹配输出应按决策价值排序，而非按数量。
  3. **失败静默禁止**："搜索失败、权限限制、超时、字段缺失要保留在运行记录中，不能静默删除"——对应**闸门/记忆**：fetch_jobs 失败必须显式写入事件日志，不得假装"无匹配"。
  4. **可取得层级标记**（全文已核验/仅摘要/仅元数据/无法取得）——可用于**匹配**的 JD 核验状态。
- **相关性：4** — 意图→判断重写 + 失败不静默，正是软路由与匹配引擎的薄弱点。

---

## 159. rw-paper-extractor（结构化提取）

- **一句话**：从论文提取结构化字段、原文位置、缺失项，并区分缺失/未报告/不适用/无法判断。
- **可借鉴手法 + 关联**：
  1. **提取 schema 由后续用途决定，不套同一张空表**——**匹配模块 smart_score** 的评分维度应按岗位类型（技术/产品/设计）动态选择，而非固定模板。
  2. **第二遍核对 + 四类区分**（缺失/未报告/不适用/无法判断）——可加到**简历模块**：解析简历时把"没写技能"和"明确写无该技能"区分开，避免误判。
  3. **关键字段修改保留原值/修改值/理由**（provenance）——**记忆模块**：career-profile.md 更新时保留旧值 + 改因，对接 166 的审计记录。
- **相关性：4** — schema 随用途生成 + 四类缺失区分 + provenance，直接补强 smart_score 与简历解析。

---

## 160. rw-phd-tone（作者语气指纹）

- **一句话**：从用户语料提取可复现的学术语气规则，只保留跨样本重复出现者，做最小改动。
- **可借鉴手法 + 关联**：
  1. **持久 tone profile 优先于本轮临时推断**——映射**记忆模块**：career-profile.md（全量语气/表达偏好）应优先于本次对话临时推断的"用户想要什么风格"。
  2. **证据阈值**："只保留在多个样本中重复出现"+"单个句子不能形成稳定规则"——**简历/面试模块**：用户偏好（如"别说我精通"）需 ≥N 次出现才固化为长期约束，避免单次情绪被当永久规则。
  3. **最小改动 + 偏移最大优先**——**简历模块**：改写时优先校正"不像用户"的句子，不整篇重写（呼应 171 的 scope guard）。
- **相关性：3** — 给 2.0 的 working memory 一个"偏好如何升级为长期"的明确阈值机制。

---

## 161. rw-phd-write（写作功能导向）

- **一句话**：先判断段落承担什么写作功能，再决定证据/解释/连接，而非从漂亮句子开始。
- **可借鉴手法 + 关联**：
  1. **function-to-claim-to-source 表**——**简历/匹配**输出：每条陈述都要能回到来源（JD 要求 or 简历事实 or 推断），直接服务**红线·不编造经历**。
  2. **读者推断检查**："关键结论只能靠读者脑补时，补写有证据的连接；证据不足标记缺口"——**面试模块**回答生成：答不上来的点标缺口而非硬编。
  3. **"公开正文不得包含搜索日志、claim audit 路径、draft-status note 等内部交接说明"**——关键！**记忆/路由**：给用户看的产出（简历、匹配报告）要剥离内部推理痕迹，但交接单（session-end）内部保留。这正是 career-copilot 需要显式区分"用户态输出 vs 内部态"的纪律。
  4. **"结果/解释/推断/建议使用不同证据强度"**——匹配报告里把"确定的""推断的""建议的"分级标出，服务**红线·不确定必须说**。
- **相关性：4** — 功能→主张→来源 表 + 公开正文剥离内部态，直击编造与过度自信。

---

## 162. rw-research-data（数据可取得性）

- **一句话**：审查数据/代码/材料的可取得性、版本、标识符、限制，不把"公开"等同"可复用"。
- **可借鉴手法 + 关联**：
  1. **稳定对象 ID + 四类状态分离**（公开/可取得/可互操作/可复用分别核验）——**匹配模块**：每个 JD 源、每份简历附件给稳定 ID，fetch 状态（可达/需登录/失效）分别标记。
  2. **最小访问测试 + "访问测试只证明测试时点状态"**——**匹配 fetch_jobs**：实测一次可达不等于长期有效，应在事件日志记录测试日期。
  3. **找不到材料时保留缺失状态，不生成文件/链接/许可证**——强化**红线·不编造经历**（不虚构 JD 链接）。
- **相关性：3** — 主要是"可达≠可用"的对象状态学，对 fetch_jobs 有用但非核心。

---

## 163. rw-research-design（研究设计）

- **一句话**：把问题转成构念/设计/样本/测量/分析/证伪/执行计划，并预设失败判据。
- **可借鉴手法 + 关联**：
  1. **"设计必须写明什么结果会削弱主要解释"**（预注册证伪条件）——直接用于**匹配 assess_competitiveness**：在给"竞争力强"结论前，先列"何种证据会推翻该结论"，把结论变成可证伪的。
  2. **可行性限制触发替代设计，不静默降低结论强度**——**规划模块**：当用户背景与目标岗位差距大，不得悄悄把结论降级为"还行"，要显式给出 Plan B。
  3. **主要/次要/探索分析预先区分**——**面试模块**备考规划：核心能力 vs 锦上添花分开排优先级。
- **相关性：4** — "预注册证伪条件"是 verify 闸门里最缺的"反方清单"机制。

---

## 164. rw-research-lab-router（工具选择）

- **一句话**：按任务/输入/数据敏感性选工具，给首选 + 回退 + 最小样本测试。
- **可借鉴手法 + 关联**：
  1. **首选工具 + 回退方案 + 最小样本测试**——**闸门/工具纪律**：career-copilot 调用 fetch_jobs / 投递类工具时，必须声明首选与回退，并在批量前先用 1 条样本验证字段与失败处理，服务**红线·不绕过工具**。
  2. **"代码能装≠实时 API 可用""限流/认证/费用批量前检查"**——**匹配 fetch_jobs**：先探活再批跑。
  3. **"没有合适工具时，输出可执行的人工流程而不是硬选"**——**路由/规划**：无匹配工具时给用户手动步骤，而非编造结果。
- **相关性：4** — 工具回退 + 最小样本探活，正是匹配引擎 verify 闸门可落地的形态。

---

## 165. rw-research-novelty（创新点筛选）

- **一句话**：把证据空白/冲突/异常转成候选创新点，每个至少列 2 个替代解释 + 1 反例 + 证伪条件。
- **可借鉴手法 + 关联**：
  1. **"每个候选方向至少列出两个替代解释和一个反例"**——**面试模块**（模拟反问）与**匹配 assess_competitiveness**：给"你适合该岗"这类正向结论时，强制附反方视角。
  2. **evidence-to-novelty 矩阵 + 排除理由 + 触发重评条件**——**规划模块**：职业路径建议要记录"为何排除其他选项"及"什么信号出现要重评"。
  3. **"只换国家/人群/变量名不自动构成创新"**——防**匹配 smart_score** 的伪差异化（把同一段经历换个说法重复计分）。
- **相关性：3** — 反例/替代解释强制化对面试与竞争力评估有价值，但需裁剪。

---

## 166. rw-research-passport（研究档案/交接状态文件）★最高相关

- **一句话**：为单个项目维护可审计的 JSON 状态文件（阶段/材料/判断/未知/交接/变更日志），是交接文件不是文献库。
- **可借鉴手法 + 关联**：
  1. **Passport = 交接文件不是记忆库，保存指针+状态不复制全文**——直接重塑**记忆模块**：career-context.md（轻量）就是 passport 的瘦身版；但应明确"它是指针+状态，不是经历全文"，避免与 career-profile.md 职责混淆。
  2. **稳定 ID + "判断必须连接材料 ID，或明确写成当前推断"**——**记忆/匹配**：每条判断（如"用户有 3 年经验"）要锚到材料 ID 或标 [推断]，服务**红线·不编造经历**。
  3. **"未知项不能因流程推进而自动关闭"**——**闸门**：用户没确认的能力缺口，不得因走到下一步就当已补。
  4. **"交接只传当前阶段需要的材料，避免把整个工作区当上下文"**——**记忆 session-end 交接单**：给下一 session/模块只传所需 ID，正是 working memory 要做的"按需放量"。
  5. **"原始材料变化后，旧判断标为待复核，不静默沿用" + 每次修改追加审计记录不覆盖**——**记忆模块版本化**：career-profile.md 改了，基于旧版的匹配结论要失效重审，事件日志用 append 而非覆盖。
  6. **Python 脚本 init/validate/summary（JSON schema 校验）**——**匹配引擎**：给 passport/context 加 `validate` 脚本，作为 session-start 的硬闸门（文件坏/缺字段则重建）。
  7. **"不把 Passport 当作跨项目个人记忆"**——提醒：career-context 是单用户求职项目态，不要跨项目串味。
- **相关性：5** — 这是 career-copilot 跨会话记忆与 session 交接单最对位的成形实现，几乎可照搬其 schema 思想。

---

## 167. rw-research-question（研究问题）

- **一句话**：把兴趣转成可界定/可检索/可证伪/可执行的问题，列替代解释与证伪结果。
- **可借鉴手法 + 关联**：
  1. **"可证伪的问题要说明何种观察会削弱主要解释"**——复用 163，进**匹配/面试**的结论护栏。
  2. **"描述问题不能变成因果问题""预测问题要区分开发/内部验证/外部验证"**——**匹配**：把"用户想转行"（描述）与"用户能转行"（因果）分开，不偷换。
  3. **"研究问题必须有范围边界，不能靠无限加变量解决"**——**路由/规划**：求职目标要收敛，不能用"再加几个岗位"回避决策（呼应**红线·不替代决策**）。
- **相关性：3** — 与 163/165 重叠，价值在"问题类型→框架"的映射纪律。

---

## 168. rw-research-referee（对抗式审稿）

- **一句话**：投稿前以严格审稿人身份检查结论所需证据、偏倚、替代解释与报告边界，按阻断程度排序。
- **可借鉴手法 + 关联**：
  1. **"先审最强结论，再审语言" + "每条批评必须说明它会怎样改变结论或决策"**——**匹配 verify_output 闸门**的"红队自审"：先拿最强卖点（"你最匹配这家"）开刀，每条质疑都要落到"是否改变投递建议"。
  2. **四级判定 通过/修改/重做/停止**——可直接作为 career-copilot 的**闸门 verdict 枚举**（对比 171 的错误/信息不足/需复核/通过/失效）。
  3. **"无法修复的设计限制要降低结论强度"**——**匹配 assess_competitiveness**：硬伤必须降级而非粉饰。
- **相关性：4** — 自带"自反驳 + verdict 枚举"的 verify 闸门范式，匹配引擎最该借鉴。

---

## 169. rw-research-router（科研阶段路由）★最高相关

- **一句话**：判断科研任务所处阶段，把它交给唯一主流程，新手入门时一次只问一个问题。
- **可借鉴手法 + 关联**：
  1. **"按当前瓶颈路由，不按用户提到的文件类型路由"**——直击 career-copilot**软意图路由**痛点：用户说"帮我改简历"（文件类型）可能是"先匹配岗位再改"（瓶颈），必须按瓶颈分流。
  2. **"主 Skill 一次只选一个，次要进后续队列""完成当前阶段后只给一个下一步，不同时启动整条链"**——**路由**：匹配→面试→简历→规划是串行队列，不要一次铺开 5 模块。
  3. **新手入门流**："不展示完整清单；第一轮只问手上有什么（想法/文献/数据/草稿/审稿意见/不知道）；第二轮只问想要什么结果；用户说不知道时问最卡的一件事，不让用户自选 skill；一轮只推进一个入口"——**2.0 / 路由冷启动**：career-copilot 首次触发应问"你现在手上有简历/JD/还是完全空白"，而非让用户选模块；"不知道"时主动给一个最小入口。
  4. **"不确定是材料缺失还是方法错误时，先列缺口不猜"**——**红线·不确定必须说**。
- **相关性：5** — 几乎是 career-copilot 软路由的参考答案，尤其"按瓶颈不按文件类型"和"新手一次一问"。

---

## 170. rw-review-methods（系统综述方法）

- **一句话**：设计可复现的综述流程，强调协议注册门、冻结版本、偏离记录。
- **可借鉴手法 + 关联**：
  1. **注册门**："没有注册 ID/URL/时间戳/冻结文件哈希，不得放行检索；注册后协议变化要停止并记录偏离，不得用新文件覆盖已注册版本"——**匹配引擎 verify 闸门**：进入正式匹配前必须先冻结"求职目标 + 筛选标准"（相当于注册），运行中变更标准要记偏离、不静默覆盖旧结论。
  2. **协议偏离记录时间/理由/对结论影响**——**记忆事件日志**结构化字段范式。
  3. **"是否合并由可比性决定，不由数量决定"**——**匹配**：岗位是否可合并比较看可比性，不看数量。
- **相关性：4** — "先冻结标准再放行 + 偏离即停"是把暂停点做成硬闸门的范本。

---

## 171. rw-revision-patch（局部修订补丁）★高相关

- **一句话**：把文稿切成带稳定 ID 和 hash 的块，只对用户批准的块替换，并报告保留比例。
- **可借鉴手法 + 关联**：
  1. **块级稳定 ID + 原 hash + 修改比例 + 超过 60% 停止**——**简历模块 scope guard**：改写简历时锁定原稿 hash，单轮改动超阈值必须用户显式批准；"修改块超 60% 时停止"是防"顺手大改"的电路断路器。
  2. **"任意 precondition 失败整批停止" + "Patch 只能限制改动范围，不能证明修改内容正确"**——**闸门**哲学：校验只保证范围受控，不替内容背书；失败即全停不半截。
  3. **原文件不被修改，生成新文件不覆盖**——**记忆/简历**：保留简历历史版本，对应 166 的 append 不覆盖。
  4. **"未涉及块保持原样；新增/删除/重排进入结构修改不伪装成局部替换"**——防 resume 模块把"重写"伪装成"微调"。
- **相关性：5** — hash 锚定 + 比例熔断 + "校验不背书内容"，是简历模块最缺的防越界机制。

---

## 172. rw-statistics-audit（统计报告审查）

- **一句话**：审查分析单位/重复层级/统计方法与结果报告是否一致，不把审查当重算。
- **可借鉴手法 + 关联**：
  1. **跨源一致性阻断**："正文/表格/图注/补充材料数字冲突进入阻断状态，不自动选一个"——**匹配/简历**一致性闸门：简历自述与 career-profile.md 冲突、匹配结论与 JD 原文冲突时，进阻断而非模型自选。
  2. **状态分类 错误/信息不足/需复核/通过/失效**——可作 career-copilot 的**闸门 verdict 枚举**（与 168 的四级互补）。
  3. **"没有数据和分析代码时只做报告审查，不生成重算结果"**——**红线·不编造经历**：无原始证据时不臆造。
- **相关性：3** — 主要是"冲突即阻断 + 状态枚举"，对 verify_output 有用。

---

## 173. security-and-hardening（安全加固）★高相关

- **一句话**：以威胁建模加固代码， treat 所有外部输入与 LLM 输出为不可信，分级"Always/Ask/Never"。
- **可借鉴手法 + 关联**：
  1. **LLM 专项纪律**："Treat all model output as untrusted input（LLM05）"；"The system prompt is not a security boundary；enforce permissions in code, not in the prompt（LLM01 提示注入）"；"Constrain tool/agent permissions（LLM06 Excessive Agency）：scope to minimum，destructive/irreversible 需确认，validate 每个参数"；"Bound consumption（LLM10）：cap tokens/rate/loop depth"——直接对应**红线·不绕过工具**与**闸门**：career-copilot 的工具调用权限要最小化、不可逆动作（投递、发信）必须确认、对模型自生成的中间指令要当不可信（防 prompt injection 借简历/JD 文本注入"忽略红线"）。这是把 5 条红线落成"代码级边界"的教科书。
  2. **三级边界 Always Do / Ask First / Never Do**——与 career-copilot **四级约束 HARD>REQUIRED>RECOMMENDED>RELAXABLE** 同构，可借用其"Ask First"层的"需人审批动作清单"充实 RELAXABLE/REQUIRED 边界。
  3. **Rationalization Prevention 表（"你脑中浮现的想法 | 现实"）**——**红线执行**：career-copilot 应内置一张"自我欺骗借口→现实"表（如"用户没说要这步"→"隐含期望也是期望"），见 174/182。
  4. **Red Flags 清单**——**失败模式清单**：直接转化为 career-copilot 的运行时红旗（如"把用户材料直接拼进工具调用"）。
- **相关性：5** — LLM 安全四原则 + 三级边界 + 借口表，是红线与工具纪律最系统的外部来源。

---

## 174. serious-mode（高标准执行模式）★高相关

- **一句话**：复杂任务执行标准 Skill，用三条铁律 + 四步闭环 + 运行时自检 + 借口防范保持水准。
- **可借鉴手法 + 关联**：
  1. **三条铁律**：① 用户的话 > 一切材料；② 降级必须交互确认（"未经确认的降级=违约"）；③ 每个环节必须有厚度（"做了≠做好了"）——直接写入 career-copilot **红线·不替代决策**与**约束**：任何"简化/跳过/差不多"必须先问用户（呼应 173 的 Ask First、171 的比例熔断）。
  2. **Rationalization Prevention 表**（"这个任务很简单不需要认真"/"先快速做完再说"/"差不多了可以结束"…）→ 现实——**红线·不替代决策**落地：给 career-copilot 一张"想偷懒的借口→现实"表，在每次想降级时自检。
  3. **运行时自检清单（状态信号→该做什么）**："连续 3 步没展示中间产出→停，汇报进展""想跳过某步没告诉用户→停，问"——**2.0 working memory / 闸门**：把"状态→纠正动作"做成可机检清单。
  4. **Rule 4 会话记忆管理**："长任务每 3-4 步写 daily memory；感觉遗忘就 Read 回忆"——**记忆模块 session 交接单**的操作化：career-copilot 应在长会话中周期性落盘关键上下文，正是 2.0 要强化的。
- **相关性：5** — 铁律 + 借口表 + 自检清单，是把"认真不偷懒"变成可机检纪律的直接范本。

---

## 175. setup-matt-pocock-skills（工程 skill 初始化脚手架）

- **一句话**：为工程 skill 搭建 issue tracker / triage 标签 / 领域文档布局，prompt 驱动、先探索后确认。
- **可借鉴手法 + 关联**：
  1. **Leading words**："每段先给推荐答案，让用户一个词接受；只在选择真分叉时才给一行解释"——**路由/交互**：career-copilot 在澄清时应默认给推荐项（"建议先匹配，可以吗？"），减少用户决策负担，服务"不替代决策但降低摩擦"。
  2. **Explore→Present→Confirm→Write，从不假设**——**规划模块**：改动 career-profile 等重大状态前先展示再写（呼应 166/171）。
  3. **triage 标签词汇（needs-triage/needs-info/ready-for-agent/ready-for-human/wontfix）**——可借作**记忆事件日志**的状态枚举雏形（待分诊/待信息/可自动/需人工/不做）。
- **相关性：2** — leading words 有用但整体偏工程脚手架，迁移面窄。

---

## 176. shipping-and-launch（上线发布）

- **一句话**：上线前 checklist + 分阶段灰度 + feature flag 开关 + 回滚阈值（绿/黄/红）。
- **可借鉴手法 + 关联**：
  1. **Rollout Decision Thresholds（绿=前进/黄=hold 调查/红=回滚）**——**闸门 verdict 量化**：career-copilot 的匹配/投递建议可用三色阈值（如薪资达标=绿、部分达标=黄、硬伤=红）决定前进/暂停/停止。
  2. **Feature flag = kill switch + 回滚计划**——**暂停点/闸门**：career-copilot 的"暂停点"本质就是 feature flag：可随时关、可回滚到上一步。
  3. **Pre-launch checklist（分域全绿才发布）**——**verify_output 闸门**：投递前 checklist（JD 已核验/简历未越界/隐私已脱敏）全绿才放行。
  4. **Common Rationalizations 表 + Red Flags**——同 173/174 的借口/红旗范式，可并入 career-copilot 的统一失败模式清单。
- **相关性：3** — 三色阈值 + kill switch 隐喻对暂停点有启发，但整体偏 DevOps。

---

## 177. skill-engineering（Skill 工程全生命周期）★高相关

- **一句话**：按意图路由到 create/improve/evolve/audit/evaluate… 自动推进但有明确确认点，带 JourneySession 交接与写后回滚。
- **可借鉴手法 + 关联**：
  1. **能力路由（意图→动作映射）+ "一次只问会改变结果的必要问题，通常 1 个最多 3 个"**——**路由**：career-copilot 软路由可借鉴其"意图词→模块"映射表的显式化，并限制澄清提问数量。
  2. **确认点契约**："写入/安装/Global/外部副作用必须停在明确确认点""create 默认只预览，--apply 才写"——**闸门/红线·不绕过工具**：任何对 career-profile.md/外部系统的写操作前必须显式确认（呼应 173 LLM06、171）。
  3. **停止点清单（Stop conditions）**——可直接作为 career-copilot **闸门停止条件**的模板（缺实质改变方案的输入/目标冲突/source-plan 漂移/无失败模式契约…）。
  4. **JourneySession + 恢复后先展示 handoff 摘要，不让用户重述**——**记忆 session 交接单**：跨会话恢复时先给一屏摘要，正是 career-context.md 的用途。
  5. **"写后验证失败自动回滚，成功返回安全撤销入口" + drift 检测（source/plan/candidate 不得漂移）**——**记忆版本化 + 闸门**：改动后校验，漂移则回滚；对应 166 的 append 不覆盖。
  6. **用户输出只答三件事：结果是什么/对你有什么影响/下一步是否需你决定**——**路由输出纪律**：career-copilot 给用户看的要极简，技术细节折进"技术详情"。
  7. **eval 三分离**：结构健康/证据覆盖/真实任务效用分开；"没有 baseline/holdout/真实 rollout 时明确写'尚未验证实际效果'"——**evals/自检**：career-copilot 的 evals/ 应区分这三类，不得把静态分当效果分（呼应 180）。
- **相关性：5** — 路由映射 + 确认点 + 停止点 + JourneySession + 写后回滚 + eval 三分离，几乎覆盖 career-copilot 的治理骨架。

---

## 178. skillhub-daily（SkillHub 每日推荐）

- **一句话**：扫描 SkillHub 全站，基于用户痛点 × 分类交叉匹配做精准推荐，多通道存储。
- **可借鉴手法 + 关联**：
  1. **痛点驱动路由 + 痛点→分类映射表 + 记忆扫描优先级（最近 3 天日志 > 长期记忆）**——**路由/记忆**：career-copilot 的软路由也可维护一张"用户表述→模块"映射；记忆读取优先级（近期事件日志 > career-profile.md > context）可借鉴其分层。
  2. **"不能硬编码痛点列表""不能在输出暴露用户个人信息或 API 密钥"**——**红线·不泄露隐私**：推荐类/总结类输出脱敏。
  3. **"何时不应触发"清单**——可补 career-copilot 的**路由拒触发**条件。
- **相关性：2** — 痛点映射与记忆优先级有参考价值，但整体偏推荐系统，核心手法弱。

---

## 179. skills（目录）

- **一句话**：该条目是 skills 聚合目录，无独立 SKILL.md。
- **可借鉴手法 + 关联**：无正文可分析，跳过。
- **相关性：0** — 无 SKILL.md，不计入审计。

---

## 180. skill-scorer（Skill 全方位评测）

- **一句话**：100 分 5 维度 rubric 评测 skill 质量，强调"用证据打分而非感觉"。
- **可借鉴手法 + 关联**：
  1. **5 维度 rubric + 权重（Business Value 25 / Reliability 20 / Writeup 25 / Market Fit 15 / Runtime Cost 15）**——可直接作为 career-copilot **evals/** 的自评框架：把"求职价值/可靠性(红线守住率)/写作质量/拟合度/运行成本"量化，给每个分附证据行号。
  2. **Trigger accuracy："会不该触发时触发吗？不该触发时触发了吗？"**——**路由验证**：career-copilot 的软路由必须有"误触发/漏触发"测试用例，进 evals/。
  3. **Quick/Deep/Automated 三模式 + "Every score must cite specific lines or behaviors"**——**evals 分级**：轻量自测 + 深度审计 + 脚本基线，且分数必须可辩护（呼应 177 eval 三分离、182 证据打分）。
  4. **"A skill is good because it reliably delivers value when invoked, not because it is clever."**——可作为 career-copilot 2.0 的设计信条。
- **相关性：4** — 给 evals/ 一套现成 rubric 与"触发准确率"测试维度。

---

## 181. source-driven-development（源驱动开发）

- **一句话**：每个框架相关决策必须回到官方文档并引用，训练数据会过时，不验证就标 UNVERIFIED。
- **可借鉴手法 + 关联**：
  1. **来源层级（官方文档 > 官方博客 > Web 标准 > 兼容性；绝不为首要源引用 SO/博客/AI 摘要/训练数据）**——**匹配 fetch_jobs / 行业知识**：岗位要求、公司信息优先取官方 JD/官网，不取二手博客或模型记忆。
  2. **UNVERIFIED 显式标记**："Honesty about what you couldn't verify is more valuable than false confidence"——**红线·不确定必须说**的实操：无法核验的字段标 [未核验] 而非编。
  3. **Rationalization Prevention 表 + Red Flags**——同 173/174，统一进 career-copilot 失败模式清单。
  4. **冲突即显式摆出，不静默选一个**——**闸门冲突处理**（同 172）。
- **相关性：3** — 来源层级 + UNVERIFIED 标记对"不编造"有用，但偏工程代码场景。

---

## 182. source-verification-ledger（源核验账本）★最高相关

- **一句话**：强制一级源坐实 + 判定分类账（R 表）+ Over-Claim 自查 + 外部材料红线（单源禁出）。
- **可借鉴手法 + 关联**：
  1. **一级源坐实（GitHub 读 raw README/file:line，文章重读原文，不信任博客转述）**——**匹配/简历**：任何"用户做过 X""岗位要求 Y"都要回到原始材料（简历原文/JD 原文）锚定，不继承模型自己的转述。
  2. **Verdict 分类学 CONFIRMED / CONFIRMED(caveat) / PARTIAL(机制降级) / MISREPRESENTED→已校正 / UNSUPPORTED**——**闸门 verdict 枚举 + 匹配结论标注**：每条匹配/竞争力结论带一种 verdict，部分成立要标 caveat（如"匹配的是方向不是具体技能"）。
  3. **Over-Claim Self-Check 四陷阱**：修辞当测量 / 同构当佐证 / 偷换论题 / 结论过满——**红线·不编造经历 + 不确定必须说**的具名化：简历/匹配里"大幅提升""高度匹配""完全胜任"等词要过这四面镜子。
  4. **External-Material Red Line（单源未独立复现禁止进入外部材料）**——**简历模块硬红线**：未独立的单一来源数字/成就不得写进投出去的简历（外部材料），内部可标 [单源未复现]。
  5. **Iron Laws**：审计先于分刀 / 全绿≠无虫 / 改对文件 / 用户指令>一切——前两条是**闸门**哲学（verify 通过≠无问题，仍要跑 Over-Claim 自查；改文件前先审计），后两条是**红线·不替代决策 / 不绕过工具**。
  6. **命题 cells + 内联 caveat 标签（如 (§11.7 R6：R@5≠QA)）**——**记忆/匹配**：每条结论内联来源引用与 caveat，正是 function-to-claim-to-source（161）的账本版。
- **相关性：5** — verdict 分类 + Over-Claim 四陷阱 + 单源红线 + Iron Laws，是"不编造/不确定必须说/verify 闸门"最完整的外部范式。

---

# 本切片最值得借鉴的 5 条（摘要）

1. **rw-research-passport 的交接状态文件范式（166）**——把 career-context.md 明确定位为"指针+状态的交接 passport 而非全文记忆库"：稳定 ID、判断必须锚材料或标[推断]、未知项不自动关闭、交接只传所需 ID、原始材料变化旧判断失效、append 不覆盖 + 配 `validate` 脚本做 session-start 硬闸门。这是跨会话记忆与 session 交接单最对位的成形实现。

2. **rw-research-router 的"按瓶颈不按文件类型路由 + 新手一次一问"（169）**——直接修正 career-copilot 软意图路由：用户说"改简历"可能是"先匹配"的瓶颈；首次触发只问"手上有简历/JD/还是空白"，"不知道"时给最小入口，主模块一次只选一个、次要进队列。

3. **security-and-hardening 的 LLM 四原则 + 三级边界 + 借口表（173）**——把 5 条红线落成代码级边界：LLM01 提示注入（JD/简历文本可能注入"忽略红线"）、LLM06 工具最小权限+不可逆动作确认、LLM10 消耗上限；三级 Always/Ask/Never 充实四级约束；Rationalization Prevention 表做成"自我欺骗借口→现实"清单。

4. **rw-revision-patch 的 hash 锚定 + 比例熔断 + "校验不背书内容"（171）**——简历模块的防越界机制：锁定原稿 hash，单轮改动超阈值（如 60%）必须显式批准；precondition 失败整批停；原文件不覆盖；"局部替换"不得伪装成"重写"。

5. **source-verification-ledger 的 verdict 分类 + Over-Claim 四陷阱 + 单源外部红线（182）**——给 verify 闸门与"不编造/不确定必须说"一套可操作语言：每条结论带 CONFIRMED/caveat/PARTIAL/UNSUPPORTED 判定；"修辞当测量/同构当佐证/偷换论题/结论过满"四面镜子筛过度声称；未独立复现的单源数字禁止进入投出去的简历。

> 补充高价值（并列第 6）：rw-research-referee 的"先审最强结论 + 四级 verdict 通过/修改/重做/停止"（168）与 skill-engineering 的"确认点 + 停止点清单 + JourneySession 恢复摘要 + eval 三分离"（177），可作为 verify 闸门的红队自审与治理骨架直接并入。
==================================================
## 切片 8（skills_list.txt 第 183-203 行）
==================================================
# Career-Copilot 技能审计 · Part 8

> 对 21 个已安装 AI-agent 技能的深度源码审计，目标是抽取可迁移到 `career-copilot`（求职全链路 Agent）的元模式。
> 目标技能结构回顾（便于关联）：
> - 5 能力模块：匹配(matching) / 面试(interview) / 简历(resume) / 记忆(memory) / 规划(planning)
> - 5 红线：不编造经历 / 不替代决策 / 不泄露隐私 / 不绕过工具 / 不确定必须说
> - 约束分级：HARD > REQUIRED > RELAXABLE
> - Python 管线：gen_profile → fetch_jobs → pre_filter → smart_score → post_judge → verify_output → assess_competitiveness（含 pause points 与 verify gates）
> - 跨会话记忆：career-context.md(~200tok) / career-profile.md(~2000tok) / event JSONL；session-start 读、session-end 写 handoff
> - references/ 按需按段加载；含 evals/ 与 tests/

---

## 1. spec-driven-development
- **一句话**：在写任何代码前先写结构化规格（objective/commands/structure/style/testing/boundaries），用「SPECIFY→PLAN→TASKS→IMPLEMENT」四级门控，每级都需人工 review 才放行。
- **可借鉴的具体手法 + 关联**：
  - **三栏边界系统 Always / Ask first / Never** —— 与 career-copilot 的约束分级 **HARD>REQUIRED>RELAXABLE** 是同一思想的两种表述。可直接把「Never」档映射到 HARD 红线（如「绝不编造经历」「绝不代发投递」），把「Ask first」映射到 REQUIRED（如「改求职方向前先确认」），「Always」映射到 RELAXABLE。建议把 spec-driven 的 Boundaries 模板直接套进 verify gates 的每个 pause point。
  - **Phase 门控 + 每级 Human review** —— 对应管线每个 Python 步骤后的 **verify gate / pause point**。可借鉴其「Do not advance to next phase until current one is validated」的硬性措辞，强化 `verify_output` 之前的阻断语义。
  - **Surface assumptions immediately（把假设显式列成清单让用户纠正）** —— 直接支撑红线 **不确定必须说**。gen_profile 阶段应强制产出一份「ASSUMPTIONS I'M MAKING」清单（如学历/经验起止/目标城市），在推进前先让用户确认，而非默默填坑。
  - **Reframe vague requirement as success criteria（把"更快"重构为可测指标）** —— 适用于 `assess_competitiveness`：把"竞争力如何"转成具体、可测的通过条件（如匹配度≥X%、关键缺口≤Y 项）。
- **相关性：5** —— 边界三栏与门控流程几乎可 1:1 映射到现有约束分级与 verify gates，是最直接的参考。

## 2. storage-analyzer
- **一句话**：只读磁盘扫描后做 🟢可自动清理 / 🟡需人工判断 / 🔴谨慎清理 三级分类，生成可折叠交互报告，删除动作只展示、默认不执行。
- **可借鉴的具体手法 + 关联**：
  - **🟢🟡🔴 三色决策分级** —— 与 career-copilot 的 **三档约束 / 三档风险** 同源。可直接复用为「简历修改建议」的分级呈现：🟢可直接采用 / 🟡需你确认 / 🔴不建议（如整段删掉真实经历）。让 `verify_output` 与 resume 模块的输出自带风险灯。
  - **铁律：全程只读、删除命令只展示不执行** —— 对应红线 **不绕过工具 / 不替代决策**。求职 Agent 不该静默代用户点「投递/发送」，应只生成待办+可逆操作入口（如同 storage-analyzer 的「移到废纸篓」按钮）。建议给 `gen_profile`/`fetch_jobs` 也立一条「只读优先、写操作先确认」铁律。
  - **安全模型：三套白名单 + realpath 校验 + 必须在 $HOME 内 + 每次点击 confirm** —— 对应红线 **不泄露隐私 / 不绕过工具**。career-copilot 调用本地文件（career-profile.md、生成的简历 docx）时应加路径边界校验，防止越权读写用户磁盘。
  - **结论先行摘要（总可释放 + 最该先清 2–3 项 + 风险最高一项）** —— 对应 `assess_competitiveness` 与 session-end 摘要的「leading words / 结论先行」口吻，直接可套。
  - **估算必须标注清楚（"约 14 GB"）** —— 对应 **不确定必须说**：竞争力分数、薪资区间等一律标「估算」。
- **相关性：5** —— 三色分级 + 铁律只读 + 只展示不执行的「安全模型」完美对应约束分级与多条红线。

## 3. storm-research
- **一句话**：用斯坦福 STORM 四步法（5 专家视角→矛盾图→合成简报→同行评审含置信度评分）在单会话内做多视角研究。
- **可借鉴的具体手法 + 关联**：
  - **5 专家视角（实践者/学者/怀疑者/经济学家/历史学家）** —— 直接强化 **面试(interview)** 模块：模拟面试/反向提问时可轮换视角出题；也可用于 `assess_competitiveness` 的「多角色评估候选人」（HR 视角、业务主管视角、 skeptic 视角）。
  - **矛盾图 + 找出「所有视角都同意的（很可能为真）」与「没有任何视角提到的（盲区）」** —— 对应 **不确定必须说** 与 anti-hallucination：把「共识」当高置信结论、把「盲区」显式标注为不确定，避免编造。
  - **Step 4 同行评审带置信度评分（高/中/低）** —— 可嵌入 `post_judge` / `verify_output`：每条判断附置信度，低于「中」强制进入「不确定必须说」分支。
  - **填 ROLE 才给可执行建议** —— 对应 **规划(planning)** 模块：先锁定用户求职角色（校招/社招/转行）再给建议，否则建议空泛。
- **相关性：4** —— 多视角+置信度+盲区识别对面试与评估模块增益明显，但需适配求职语境。

## 4. tdd
- **一句话**：红→绿→重构循环；强调「只在预约定好的 seam 处测试」「期望值必须来自独立真相源」「先做最小实现」。
- **可借鉴的具体手法 + 关联**：
  - **Test only at pre-agreed seams（写测试前先确认被测边界）** —— 对应 `verify_output`：在评估简历/匹配结果前，先和用户约定「验收 seam」（哪些字段必须真实、哪些维度要打分），避免测了错误的地方。
  - **期望值必须来自独立真相源，禁止与代码同源自证（tautological 反模式）** —— 直接支撑 **不编造经历 / 红线**：verify 阶段校验简历经历时，真值必须回到 career-profile.md 或用户原始输入，绝不能拿「模型自己生成的内容」当证明（自证通过=假通过）。
  - **Tracer bullet / vertical slices（一次一测试一实现）** —— 对应管线**逐步推进**的 pause point 节奏，避免一次性大改。
- **相关性：4** —— 「独立真相源 / 禁止自证」是 verify_output 防幻觉的核心范式，直接可落地。

## 5. teach
- **一句话**：把学习状态持久化到工作区多文件（MISSION/learning-records/RESOURCES/NOTES），用「最近发展区」适配难度，强调「绝不信任参数化知识、所有结论带引用」。
- **可借鉴的具体手法 + 关联**：
  - **跨会话状态多文件分层（MISSION=为什么 / learning-records=非显然洞见 / NOTES=偏好）** —— 直接对应 career-copilot 的 **跨会话记忆架构**（career-context.md + career-profile.md + event JSONL）。可借鉴其「learning-records 类似 ADR，记录未来需修订的非显然教训」来设计 event JSONL 的事件 schema（每条=一个可复核的决策/转变）。
  - **Never trust your parametric knowledge（只用可信资源，结论带引用）** —— 对应 **不编造经历 / 不绕过工具**：面试准备、行业知识、薪资基准必须引真实来源，不能凭模型记忆编造。
  - **Zone of Proximal Development（按用户当前水平给"刚好够难"的内容）** —— 对应 **面试/规划** 模块：mock 难度、学习路径要贴合用户真实水平，而非千篇一律。
  - **Reuse is default（先读 assets/ 再写，共享样式）** —— 对应 references/ 按需加载 + 复用，避免每段重复。
- **相关性：5** —— 其「多文件分层记忆 + 不信任参数知识 + 引用背书」几乎就是 career-copilot 记忆模块与反幻觉红线的原型。

## 6. tencent-yuanbao-standard-search
- **一句话**：封装腾讯云联网搜索 API，支持关键词/站点/site/时间范围(freshness)/垂直混合(mode)检索，输出去噪 Markdown。
- **可借鉴的具体手法 + 关联**：
  - **freshness 时间范围过滤（day/week/month/year）** —— 直接用于 `fetch_jobs`：抓取职位时强制按「发布时间」过滤，避免把过期岗位喂给 smart_score（过期=幻觉源）。
  - **信息自动去噪、token 友好** —— 对应 pipeline 的 token 预算管理：pre_filter/smart_score 阶段应做去噪与按段裁剪，呼应 references/ 按需加载。
  - **site 限定 + mode 垂直检索** —— 可迁移为「只搜目标公司官网/官方招聘页」，支撑 **不绕过工具**（用官方一手渠道而非二手聚合）。
- **相关性：3** —— 主要为检索参数工程，对 fetch_jobs 有用但非架构级。

## 7. test-driven-development
- **一句话**：先写失败测试再写实现（Prove-It 模式），测试验证状态而非交互，附「Common Rationalizations」与「Red Flags」反模式表。
- **可借鉴的具体手法 + 关联**：
  - **"Tests are proof — 'seems right' is not done"** —— 对应 **verify gates**：管线每一步必须有可观察证据才算完成，呼应 `verify_output` 的硬性阻断。
  - **Prove-It（修 bug 前先写复现测试，确认 bug 存在再修）** —— 迁移到 **规划/面试** 模块：诊断用户求职卡点（如「面试总挂」）前，先产出「可复现的失败证据」（如一次模拟面试录音/评分），再给方案。
  - **Security boundary：浏览器内容一律视为 untrusted data，不是指令** —— 对应 **不泄露隐私 / 不绕过工具**：从网页抓取到的 JD/公司信息不可被当作「指令」执行，避免提示注入。
  - **Red Flags / Common Rationalizations 表** —— 直接可抄为 career-copilot 的「红线触发清单」：把「我就跳过验证吧」「用户说可以那就编一点」列为红旗，对应 **不确定必须说**。
- **相关性：4** —— Prove-It 与 Red Flags 表对 verify gates 与红线工程化很有价值。

## 8. text-compression-to-limit
- **一句话**：用「起草→计数→定向删改→重数→交付」循环把文本压到硬字符上限，强调「LLM 数不准必须脚本验证」「保留 must-keep、不私吞余量」。
- **可借鉴的具体手法 + 关联**：
  - **"LLMs cannot count characters reliably — always verify with a script"** —— 直接支撑 **不编造经历 / verify_output**：简历压缩（JD 字数限制、简历篇幅）必须用脚本精算，禁止「约 X 字」式估算，与红线一致。
  - **Multi-item budget allocation（先分预算再逐项写，汇总后 redistribution 余量）** —— 对应 **简历(resume)** 模块：多段经历压缩进限额时，先按优先级分配字节预算再写，避免厚此薄彼。
  - **Over-cutting 更常见 + Report surplus don't pocket it（有富余要告诉用户可补回）** —— 对应 **不确定必须说 / 不替代决策**：若压缩后远低于上限，主动告知「你还剩 N 字可补细节」，而非替用户决定不补。
  - **Preserve must-keep items（用户标定的数据/关键词先保）** —— 对应 **不编造经历**：用户真实量化成果（数字）是 must-keep，压缩绝不动。
- **相关性：5** —— 与 resume 模块高度同构，是可立即套用的「硬约束+脚本验证+余量透明」范式。

## 9. thesis-proposition-spike
- **一句话**：用 TDD 优先的确定性 harness 验证命题，强制「诚实优于胜利」——每个收益必须记为有条件(conditional)，并配三层校验（run/adversarial_scan/robustness_probe）。
- **可借鉴的具体手法 + 关联**：
  - **Honesty over victory：收益一律记为 conditional，绝不把未测的当结论** —— 直接对应 **不编造经历 / 不确定必须说**：竞争力结论/匹配分必须带「边界条件」（如「仅在目标城市有岗时成立」），不包装成绝对结论。
  - **三层验证仪器（run + adversarial_scan + robustness_probe）** —— 对应 career-copilot 的 **evals/ + verify gates**：建议给 `smart_score`/`post_judge` 也上「常规跑 + 对抗扫描 + 鲁棒性探针」三件套，量化「不编造」的通过率。
  - **Never compute a metric from itself（禁止循环自证）** —— 与 tdd 同源，强化 verify_output 的「独立真值」原则。
  - **Audit before cutting（Green≠无 bug，先重跑绿套件再改）** —— 对应管线「改简历/改方向前先回看已验证的 profile 快照」。
- **相关性：5** —— conditional 诚实模式 + 三层校验是 eval/自我审查模块的最佳范本。

## 10. to-spec
- **一句话**：把当前对话综合成规格（PRD）发布到 tracker，**不访谈用户、只综合已知**，强调用领域词汇、写 Out of Scope、避免会过时的路径。
- **可借鉴的具体手法 + 关联**：
  - **Don't interview — synthesize what you already know** —— 对应 **记忆(memory)** 模块：进入新会话先读 career-context/profile 综合，而非重复问用户已知信息。
  - **显式 Out of Scope 段** —— 对应 **不替代决策 / 规划**：每次给出求职规划时列出「本次不做的事」（如暂不做薪资谈判），防止越界与过度承诺。
  - **用项目领域词汇（glossary）** —— 对应 references/ 与 tone 一致性：简历/面试话术需贴合用户行业术语。
  - **不写具体文件路径/代码片段（易过时）** —— 对应 progressive disclosure：skill 内只留可长期成立的抽象，路径细节外置。
- **相关性：3** —— 偏「综合+边界声明」，对规划与记忆模块有中等的借鉴价值。

## 11. to-tickets
- **一句话**：把计划拆成 tracer-bullet 垂直切片，每张票声明 blocking edges，沿 frontier 推进，发布前先 quiz 用户确认粒度与依赖。
- **可借鉴的具体手法 + 关联**：
  - **Tracer-bullet vertical slices + blocking edges / frontier** —— 对应 **管线依赖 DAG**：gen_profile→fetch_jobs→pre_filter→… 本身就是阻塞链，可显式建模「frontier=当前可执行的下一步」，pause point 即 frontier 推进前的确认点。
  - **Quiz the user 再发布（粒度/依赖是否正确）** —— 对应 **不替代决策 / pause points**：长任务规划在落地前让用户确认拆分，而非自主全跑。
  - **Acceptance criteria 每张票** —— 对应 verify gates：每个 pipeline 步骤给出可勾选的验收标准。
  - **Wide refactor 用 expand–contract 而非强塞切片** —— 对应「大改求职方向」时的安全迁移策略（先并排新方向、再分批切换、最后弃旧）。
- **相关性：4** —— 垂直切片+frontier+验收标准对管线步骤化与规划模块很实用。

## 12. triage
- **一句话**：把 issue/PR 推过「category + state」状态机，每步先 verify claim、需要时 grill，跨会话恢复先读旧 notes 不重复问。
- **可借鉴的具体手法 + 关联**：
  - **category+state 角色状态机 + 显式状态迁移** —— 对应 career-copilot 的 **软意图路由 → 5 模块**：把「匹配/面试/简历/记忆/规划」做成可判定状态，并用状态机约束非法跃迁（如未建 profile 不能进面试）。
  - **AI 生成声明（"This was generated by AI during triage"）** —— 对应 **不泄露隐私 / 透明**：Agent 给出的求职建议/简历草稿应带「AI 生成，请自审」水印式声明，呼应红线。
  - **verify claim 先于任何 grill（复现 bug / 跑测试确认）** —— 对应 verify gates：处理用户「我的简历没回应」前，先验证（如模拟投递/对照 JD）再下结论。
  - **resuming previous session：读旧 notes、不重问已解决** —— 直接对应 **跨会话 handoff**（session-start 读 career-context/event JSONL，不重复问已知）。
  - **.out-of-scope/ 知识库（拒绝过的请求持久化，新请求先比对照）** —— 对应红线边界：把「用户曾拒绝/不做的求职动作」持久化，避免反复越界。
- **相关性：5** —— 状态机+跨会话恢复+AI 声明+out-of-scope 库，是意图路由与 handoff 的现成范本。

## 13. using-agent-skills
- **一句话**：元技能——按开发阶段做技能发现与路由，并列出 6 条「全时不可协商」操作行为（显假设/管困惑/敢反驳/求简/守范围/要验证）与 10 条 Failure Modes。
- **可借鉴的具体手法 + 关联**：
  - **阶段决策树式技能发现** —— 对应 career-copilot 的 **软意图路由 → 5 模块**：把「来了一个任务先判阶段再派模块」显性化，正是其路由器的元模板。
  - **Surface Assumptions / Manage Confusion（STOP 命名困惑、给取舍、等解决）** —— 直接对应 **不确定必须说**：遇矛盾（JD 要求与用户经历不符）先停、点名、问，而非猜。
  - **Push Back When Warranted（不做 yes-machine，谄媚是失败模式）** —— 对应 **不替代决策 / 不编造经历**：用户想夸大经历时，Agent 应直说风险而非附和。
  - **Verify, Don't Assume + Failure Modes to Avoid 列表** —— 对应 **verify gates** 与红线触发清单，可直接把其 10 条 failure modes 改写为求职场景红旗。
  - **Maintain Scope Discipline（只碰被要求的，不擅自重构/加功能）** —— 对应 **不绕过工具 / 不替代决策**。
- **相关性：5** —— 它是「红线+路由+验证+失败模式」的总纲，几乎是 career-copilot 行为准则的母本。

## 14. vm-error-recovery
- **一句话**：读诊断状态文件按 errorKey 查表给出 A/B/C 三级恢复指引，全程不暴露内部细节、按平台给话术、永远提供升级路径。
- **可借鉴的具体手法 + 关联**：
  - **errorKey 查表式分类（A 简单重试 / B 需特定操作 / C 用户无法修）** —— 对应 **triage/优先级分级** 与约束三档：把求职流程中的异常（如「岗位消失」「资料缺失」「平台风控」）做成查表路由。
  - **Never expose internal details（只说"安全工作区"）** —— 对应 **不泄露隐私 / tone 一致性**：对用户的解释用产品化口吻，不吐内部实现/工具名。
  - **Always offer escalation path（解决不了就引导求助）** —— 对应 **不替代决策**：Agent 处理不了（如涉及真实账号操作）时明确交还用户。
  - **Fallback：诊断文件缺失时的通用步骤** —— 对应 **记忆模块缺失降级**：session-start 读不到 career-context.md 时的兜底流程。
  - **Avoid unnecessary alarm（安抚式话术）** —— tone 一致性：求职焦虑场景下用「通常可解决」而非「严重失败」。
- **相关性：4** —— 查表分级+不暴露内部+升级路径，对错误处理与红线解释很有用。

## 15. wayfinder
- **一句话**：把超大任务画成共享「地图」（Destination + Decisions-so-far 索引 + Fog of war + Out of scope），逐张决策票推进，地图是索引不是仓库，一次最多解一张票。
- **可借鉴的具体手法 + 关联**：
  - **The map is an index, not a store（决策只存一处、地图只摘要+链接）** —— 对应 **progressive disclosure / references 按需加载**：career-copilot 的 career-context.md 应是索引式 handoff，细节外置到各模块文件。
  - **Fog of war（故意不完整，能精确提问才建票，否则留 fog）** —— 对应 **不确定必须说**：求职规划里「还看不清的方向」显式标为 fog，不强行切细分，避免伪造确定感。
  - **Out of scope 永不毕业（frontier 停在 destination）** —— 对应 **不替代决策 / 规划**：明确划出本次不做的事。
  - **HITL vs AFK 票 + claim before work** —— 对应 **pause points / 不替代决策**：需用户拍板的事标记为 HITL，Agent 不代答（如「是否接受降薪 offer」）。
  - **一次最多解一张票 + Decisions-so-far 索引** —— 对应 **跨会话 handoff**：每解一步就回写索引，session-end 的 handoff 即「Decisions so far」。
- **相关性：5** —— 地图/索引/雾/手off 模式与 career-copilot 的记忆与规划架构高度同构。

## 16. web-access
- **一句话**：像人一样带目标浏览，先定成功标准、每步结果当证据、方向错立即换路；坚持一手来源优于二手、警惕「多源循环印证假象」；站点经验按需加载且只记已验证事实。
- **可借鉴的具体手法 + 关联**：
  - **过程校验：结果当证据非二元信号；「搜不到≠方法不对，可能目标不存在」；别在同一方式反复重试** —— 对应 **verify gates / 不编造经历**：fetch_jobs 找不到岗时，要能区分「方法问题」与「确实无岗」，不编造匹配结果，对应 **不确定必须说**。
  - **一手来源优于二手 + 循环印证假象（多媒引用同一错误）=假证据** —— 对应 **verify_output** 反幻觉核心：公司信息/薪资以官网一手为准，搜索聚合只是定位工具不可当证明（与 tdd 的「独立真值」同源）。
  - **站点经验 references/site-patterns：按需加载、只写已验证事实、标日期当"提示非保证"** —— 对应 **references/ 按需加载 + 不编造**：把各招聘平台抓取经验外置，且保持 epistemic humility（可能有效非保证），呼应 **不确定必须说**。
  - **子 Agent prompt 目标导向而非步骤指令（避免动词暗示手段）** —— 对应 **规划/任务分解**：给子 Agent/模块下指令说目标不说手段，减少假设错误。
  - **登录判断核心：「目标内容拿到了吗？」** —— 证据导向，对应 verify gates 的「可观察完成标准」。
- **相关性：5** —— 一手来源/循环印证假象/证据导向/经验外置，集中命中反幻觉与 verify gates。

## 17. wechat-article-extractor
- **一句话**：用 end-marker 地标法稳健切片正文（避免脆弱正则截断），references 按需加载，含无浏览器兜底、9 条已知陷阱表、透明出网声明与 skill.contract.yaml 边界契约。
- **可借鉴的具体手法 + 关联**：
  - **End-Marker 定位法（用稳定地标 js_pc_qr_code 而非贪心正则）** —— 对应 **fetch_jobs / pre_filter** 解析 JD/列表：用稳定锚点切片，避免把职位描述截断（健壮解析范式）。
  - **references 按需加载（JS 片段/陷阱拆到 references/）** —— 与 career-copilot 的 **references/ 按段加载** 完全一致，验证该模式正确。
  - **无浏览器 Python 兜底** —— 对应 **不绕过工具 / 优雅降级**：主路径（浏览器）不可用时退到脚本路径，管线不中断。
  - **9 条已知陷阱表 + 验证清单（正文非空/标题匹配/图片 200/end-marker 命中）** —— 对应 **failure-mode list + verify gates**：`fetch_jobs` 抽取后应跑同类校验清单。
  - **透明出网声明 + skill.contract.yaml 边界契约** —— 对应 **不泄露隐私 / 红线**：明确声明访问了哪些域、读不传凭证，是边界契约范本。
- **相关性：4** —— 地标解析+按需加载+陷阱表+边界契约，对 fetch_jobs 与 references 设计很实用。

## 18. wechat-publisher
- **一句话**：一键把 Markdown 发到公众号草稿箱，强制 frontmatter，关键能力靠「实测发现」反文档，发布前留「人工后台审核」环节，含错误→解法排查表。
- **可借鉴的具体手法 + 关联**：
  - **人工后台审核再发布（审核发布步骤）** —— 直接对应 **不替代决策 / pause points**：简历定稿、投递动作前必须留「用户审核」闸，Agent 不替用户点发送。
  - **实测发现 ≠ 文档（title/cover 必填，文档说可省）** —— 对应 **verify_output**：以实测为准、不盲信文档/假设，恰是「独立真值」的体现。
  - **故障排查表（错误→解法）** —— 对应 **failure-mode list**：求职管线的常见报错（登录失效/限流/格式错）建同类表。
- **相关性：3** —— 主要是「人工审核闸 + 实测反文档」，对 pause point 与 verify 有中等启发。

## 19. writing-great-skills
- **一句话**：讲「如何让 stochastic 系统产出可预测过程」的元技能：信息层级阶梯 + progressive disclosure、每步 completion criterion、leading words、单源真理、6 类 failure modes（含 Negation 反模式）。
- **可借鉴的具体手法 + 关联**：
  - **Router skill 模式（多 user-invoked 技能用 1 个路由器命名并分配）** —— 直接解释并验证 career-copilot 的 **「单技能 + 软意图路由 → 5 模块」** 架构；它就是教科书式 router。
  - **Progressive disclosure / 信息层级阶梯（in-skill step → in-skill ref → external ref）** —— 与 career-copilot 的 **references/ 按需加载** 完全一致，且给出「何时外置」的判据（只部分分支用到才指针化）。
  - **Completion criterion 必须 checkable/exhaustive，模糊标准诱发 premature completion** —— 对应 **verify gates**：每个 pipeline 步骤（gen_profile…assess_competitiveness）都要有可勾选的完成标准，否则会「假性完成」。
  - **Leading words（用预训练已有词锚定行为，如 red/fog of war/tracer bullet）** —— 对应 **tone 一致性**：建议 career-copilot 固化一组 leading words（如「红线 verify gate pause point」）贯穿始终，提升各模块行为一致性。
  - **Negation 反模式（"别想大象"反而强化；禁止只在无法正面表述时保留，且要配替代动作）** —— 对 **5 红线** 表述极关键：红线尽量正面写（如「只使用已核实经历」而非仅「不编造」），确需禁止时配「该怎么做」。
  - **6 failure modes（Premature completion / Duplication / Sediment / Sprawl / No-op / Negation）** —— 可直接作为 career-copilot SKILL 的定期自检清单。
- **相关性：5** —— 几乎是 career-copilot 架构（router + 渐进披露 + 完成标准 + 红线表述）的设计手册。

## 20. xiaohongshu-note-image-ocr
- **一句话**：浏览器被风控时改抓原始 HTML 解析 __INITIAL_STATE__，OCR 时要求「看不清写[不清]绝不编造」，含计数预期、首张抽检等验证。
- **可借鉴的具体手法 + 关联**：
  - **OCR 不确定处写 [不清] 而非编造 + "always say when uncertain instead of filling gaps"** —— 直击 **不确定必须说 / 不编造经历**：任何抽取/转录（JD 解析、经历识别）遇模糊必须显式标不确定，禁止脑补。
  - **Browser block ≠ inaccessible，换原始 HTML 路径** —— 对应 **不绕过工具 / 优雅降级**：主抓取被拦时换兜底路径，对应管线 fallback。
  - **Count imageList.length before OCR（先知预期数量）** —— 对应 **verify gates**：解析职位列表前先确认「预期 N 条」，便于事后校验缺失。
  - **Spot-check first result before processing all** —— 对应 **verify gates** 的抽样验证：批量处理前先验证首条。
- **相关性：4** —— 「不确定就标[不清]绝不编造」是红线的最佳口号级实现，验证与降级也有用。

## 21. xlsx
- **一句话**：电子表强制「用公式不用硬编码字面量」，保存后必须 recalc 并扫描错误码，硬性要求「每个写死数字都引数据来源」。
- **可借鉴的具体手法 + 关联**：
  - **用公式不用硬编码字面（MANDATORY, ZERO EXCEPTIONS）** —— 对应 **smart_score / verify_output**：竞争力评分必须是可审计的公式/规则，禁止把模型「算出的数字」直接烤进结论；保持可追溯、可复算。
  - **recalculate 后必须 inspect JSON 修错误（#REF!/#DIV/0!…）** —— 对应 **verify gates**：评分管线产出后强制跑校验，0 错误才放行。
  - **Document hard-codes：cite data source for every hard-coded figure** —— 对应 **不编造经历 / 透明**：简历/评估里每个写死的数字都要标来源（用户原文/官方 JD），杜绝无源编造。
  - **No circular references（禁止循环引用）** —— 与 tdd/thesis 的「禁止自证」同源，强化 verify 独立性。
  - **Centralise assumptions in labelled cells** —— 对应 **单源真理**：评分权重/阈值集中可配置，不在代码里散落。
- **相关性：4** —— 「公式化评分 + 强制 recalc 校验 + 硬写数字必引源」是 smart_score/verify_output 审计友好的直接范本。

---

## 跨技能高频元模式汇总（供后续落地）
1. **约束三档 / 三色分级**：spec-driven(Always/Ask/Never)、storage-analyzer(🟢🟡🔴)、vm-error-recovery(A/B/C) 三者互相印证 career-copilot 的 HARD>REQUIRED>RELAXABLE 与风险灯设计。
2. **独立真值 / 禁止自证**：tdd、thesis-proposition-spike、web-access(循环印证假象)、xlsx(公式化+引源) 共同指向 verify_output 必须「回到 career-profile.md / 官方一手源」校验。
3. **渐进披露 / 索引而非仓库**：writing-great-skills、wayfinder(map=index)、wechat-article-extractor、web-access(site-patterns) 一致验证 references/ 按需加载 + career-context 做索引式 handoff。
4. **完成标准 / verify gates / Red Flags**：spec-driven(completion criteria)、test-driven(Red Flags + Rationalizations)、using-agent-skills(10 Failure Modes)、writing-great-skills(6 failure modes)、wechat-article-extractor(陷阱表) 共同构成「红线触发清单 + 每步可勾选验收」的可抄写法。
5. **不确定必须说 / 绝不编造**：storm(置信度+盲区)、text-compression(余量透明)、xiaohongshu([不清]不编造)、thesis(conditional 诚实)、web-access(经验当提示非保证) 提供多种「epistemic humility」措辞模板。
6. **不替代决策 / 人工闸**：storage-analyzer(只展示不执行)、wechat-publisher(人工审核发布)、wayfinder(HITL 票)、vm-error-recovery(升级路径) 一致要求「写/投/决」动作前留用户确认。
7. **跨会话 handoff**：teach(多文件状态)、triage(读旧 notes 不重问)、wayfinder(Decisions-so-far) 直接支撑 session-start 读 / session-end 写 handoff。
8. **红线表述用正面词 + 配替代动作**：writing-great-skills 的 Negation 反模式，建议改写 5 红线（尤其「不编造经历」→「只使用已核实经历」）。

（技能计数：21；审计完成）
# career-copilot 深度审计 · 补遗（补全轮次补齐的 2 个遗漏 skill）

> 以下 2 个 skill 在首轮 8 切片分配时因边界错位被漏读（row 130 落在切片 5/6 缝隙、row 147 在切片 6 内被跳过），于补全轮次补读。格式与其余切片一致。

---

## 1. pm-toolkit-review-resume
- **一句话**：PM 简历评审 skill——对照 10 条最佳实践（含 XYZ+S 公式、JD 定向改写、结构顺序、量化优先）逐条给"评价+修改建议"，并强调"先给最高影响力改动"。
- **可借鉴的具体手法 + 关联**：
  - **XYZ+S 公式（Accomplished X, measured by Y, by doing Z, specifically S）**——这是简历模块"质量契约"的最直接落地：**`smart_score` / 简历生成必须强制每条成就子弹走 X(成就)/Y(指标)/Z(动作)/S(情境)**，与前面 verify 闸门的"成就必须有数字"契约完全同构，可作为简历 verify 的硬标准。
  - **Tailor to Specific Job（从 JD 抽取 5–10 个关键词，按相关度重排子弹）**——直接迁移到 **`smart_score` / 匹配模块**：简历不是万能稿，应按目标 JD 关键词对齐与重排；匹配 verdict 可反向检查"简历关键词覆盖 JD 要求的比例"。
  - **Avoid personal pronouns / Show don't tell / Metrics matter most / 6–10 秒可扫读**——简历生成的**硬性文案纪律**，直接支撑**红线 1 不编造经历**（每句必须可落地、可量化、不空话）。
  - **逐条"评价(working/fix) + 具体改写 + 直接引述原文"结构**——`post_judge` 给简历反馈时的标准输出骨架；**Prioritize highest-impact changes first** 对应 post_judge 的"改动按影响力排序"。
  - **PO vs PM 标题校准**——迁移到简历"标准职位名"校验：用户若头衔非常规，给出现实化建议而非照抄。
- **相关性：5** — 这是与 career-copilot「简历模块」对位度最高的现成 skill，XYZ+S + JD 定向 + 10 条清单应直接并入简历 verify 契约。

## 2. pm-product-discovery-prioritize-features
- **一句话**：特性优先级排序 skill——按 Impact/Effort/Risk/Strategic-alignment 四轴评估，用 Opportunity Score(重要性×不满意度) 与 ICE/RICE 打分，输出 Top5 + 理由 + 权衡 + 被弃选项。
- **可借鉴的具体手法 + 关联**：
  - **Opportunity Score = Importance × (1 − Satisfaction)，且"优先问题/机会而非方案"**——迁移到 **规划/匹配模块**：帮用户定投哪些公司前，先把"职业缺口"当 opportunity 打分（重要性×未满足度），而非直接跳到"投方案"；呼应 idea-refine「先定问题再定方案」。
  - **ICE / RICE 四轴打分（Impact × Confidence × Ease [× Reach]）**——可作为 **`assess_competitiveness` 的量化评分卡**替代单一"匹配度 %"：每个目标岗位按影响力/信心/难度/触达打分，输出更可解释。
  - **Risk 轴 = "哪些假设待验证"**——直接绑定 **红线 5 不确定必须说** 与前面"假设显式化"模式：竞争力评估里的不确定性必须作为待验证假设列出，不藏。
  - **Top5 + 排名 + 理由 + 权衡 + 被弃选项及原因**——规划模块的**标准输出结构**（呼应 idea-refine「Not Doing 列表」：不仅给推荐，还显式说"不推荐什么、为什么"）。
- **相关性：4** — 四轴评估 + ICE/RICE + Top5-with-tradeoffs 结构，是规划/竞争力模块最缺的"可解释打分"与"显式取舍"范式。

> 补遗说明：至此 203 个已安装 skill 全部被深入读取并逐条提取可迁移机制，无遗漏。
==================================================
# 跨切片总鉴：可迁移元模式与落地优先级

> 以下是对 8 个切片（共 203 个 skill）高频可迁移机制的归并。每条都标注「对应 career-copilot 的哪一块」与「优先级」。优先级说明：P0=立刻能补的结构性缺口；P1=明显增强可靠性/体验；P2=锦上添花或特定场景才用。

---

## 一、验证闸门（verify gates）—— 出现频率最高的元模式

几乎每个高质量 skill 都有一道「能变红、基于客观契约、报真实结果」的闸门，career-copilot 的 `verify_output.py` / `post_judge` 目前只是"跑通即过"，应升级：

- **P0 · 闸门能变红 + No-Fake-Completion**：来自 ci-cd-and-automation（门不可跳过、每门后 VERIFY、零错误标准）、browser-testing-with-devtools（UNTRUSTED 边界）、e2e-llm-channel-verify（计数代理/真实命中数）、gzh-design（0-ERROR 校验）。→ `verify_output` 失败时必须结构化回报（哪个 step、什么契约没满足），绝不能"脚本没报错就当成功"。
- **P0 · 基于契约而非感觉**：来自 deai-writing 四层自检、doubt-driven-development 契约式对抗审查、diagnosing-bugs 变红反馈环。→ 把 `smart_score` / `post_judge` 的"质量达标"定义成可测契约（如：成就必须有数字 or 被用户确认、动词不得堆砌、结论不得无依据）。
- **P1 · 改动比例熔断**：来自 rw-revision-patch（锁定原稿 hash，单轮改动超阈值如 60% 必须显式批准；"局部替换"不得伪装成"重写"）。→ 简历模块改稿前锁 hash，大改需用户确认，原文件不覆盖。
- **P1 · 红队自审 + 治理骨架**：来自 rw-research-referee（先审最强结论 + 四级 verdict 通过/修改/重做/停止）、skill-engineering（确认点 + 停止点清单 + eval 三分离）。→ 在 verify 闸门后加一道"自我反驳"环节。

---

## 二、防编造 / 事实核验（anti-hallucination）—— 与红线 1、5 直接绑定

- **P0 · 前提来源标注（把红线嵌进推理链）**：来自 comprehensive-thinking（对 verdict 强制给"最强反方"，每条前提标为 事实/推测/迁移/权威/脑补，只对事实类下结论）。→ 匹配/竞争力 verdict 必须标注前提来源类型，推测类不得当结论。
- **P0 · 单源外部红线**：来自 source-verification-ledger（未独立复现的单一来源数字/成就禁止进入"外部材料"即投出去的简历，内部可标 [单源未复现]）。→ 简历模块硬规则：单源数字不进对外简历。
- **P0 · 独立真值 / 禁止自证**：来自 tdd、thesis-proposition-spike、web-access（循环印证假象）、xlsx（公式化 + 必引源）。→ `verify_output` 必须回到 `career-profile.md` / 官方一手源校验，杜绝"模型自证通过"式幻觉。
- **P1 · Over-Claim 四陷阱**：来自 source-verification-ledger（修辞当测量 / 同构当佐证 / 偷换论题 / 结论过满）。→ 简历/匹配里"大幅提升""高度匹配""完全胜任"等词要过这四面镜子。
- **P1 · 集群判定法（cluster of tells）**：来自 humanizer（单个 em dash 不算证据，多个 AI 痕迹一起出现才是供词）。→ 不要用孤立信号判某段经历可疑，而是"成就无数字 + 动词堆砌 + 时间空泛"一起出现才触发追问。
- **P1 · Theatre-trap + 一手核实**：来自 extern-article-absorption、econ-write、cv-latex-layout、context-engineering。→ 任何结论须指向真实字段；外部数据先核实再引用。

---

## 三、红线工程化（red-line engineering）—— 把 5 条红线从"口号"变"可执行"

- **P0 · 正面改写红线（Negation 反模式）**：来自 writing-great-skills（"不要想大象"反而强化大象；禁止语要配"该怎么做"）。→ 把 5 红线尽量正面改写，如「不编造经历」→「只使用已核实经历」；确需禁止时配正面行为。
- **P0 · 三档约束同源印证 + 风险灯**：来自 spec-driven-development（Always/Ask/Never）、storage-analyzer（🟢🟡🔴）、vm-error-recovery（A/B/C）、security-and-hardening（三级 Always/Ask/Never）。→ 充实并统一 HARD>REQUIRED>RELAXABLE 的呈现为"风险灯"，直接套进简历修改建议与 verify gate。
- **P1 · 自我欺骗借口表（Rationalization Prevention）**：来自 security-and-hardening（借口→现实 对照表）。→ 做成"自我欺骗借口→现实"清单，在运行时自检。
- **P1 · Red Flags / Failure Modes 表**：来自 using-agent-skills、test-driven、wechat-article-extractor。→ 把 5 红线做成"触发清单"，命中即停。

---

## 四、跨会话记忆 / handoff —— 让 career-context / career-profile 真正可用

- **P0 · 交接 passport 模型（指针 + 状态，非全文堆料）**：来自 rw-research-passport（稳定 ID、判断必须锚材料或标[推断]、未知项不自动关闭、交接只传所需 ID、原始材料变化旧判断失效、append 不覆盖 + `validate` 脚本做 session-start 硬闸门）。→ 把 career-context.md 明确定位为"指针+状态的交接 passport"，配 `validate` 脚本。
- **P0 · fork vs continue 二分**：来自 ask-matt（显式区分"开新会话带 handoff 文件"与"同会话 compact"，并设定落盘时机）。→ session 生命周期明确两种模式。
- **P1 · 标准 handoff 范式**：来自 handoff、git Save-point、html-deploy、documentation-and-adrs、domain-modeling（session-end 写 handoff、脱敏、两级指针、append-only 事件 JSONL）。→ 固化 session-end 写交接单的字段。
- **P1 · 毕业/晋升机制**：来自 neat-freak（稳定事实从事件日志晋升进 profile，原日志缩成指针）。→ 给 career-copilot 加"毕业"机制，控制 profile 体积。
- **P2 · 索引式渐进披露**：来自 writing-great-skills、wayfinder（map=index）、teach、triage（Decisions-so-far 式交还，而非仓库式堆料）。→ references/ 按需加载 + career-context 做"到目前为止的决策"交还。

---

## 五、意图路由（intent routing）—— 软路由要显式化

- **P0 · 决策表 + 易混淆场景表**：来自 ima-skills（模块决策表 + 易混淆场景路由表 + 跨模块任务必须读两个子模块）。→ career-copilot 当前是软意图路由，最该补这种显式消歧表（如"帮我看看这个岗位"→匹配 vs "帮我改下简历"→简历 vs "我该投还是等"→规划），跨模块任务必须加载双方 references。
- **P1 · 按瓶颈不按文件类型路由 + 新手一次一问**：来自 rw-research-router（用户说"改简历"可能是"先匹配"的瓶颈；首次触发只问最小入口）。→ 修正软路由：首次触发只问"手上有简历/JD/还是空白"，主模块一次只选一个、次要进队列。
- **P1 · 软路由结构化**：来自 deai-writing 场景路由、find-skills 先查能力、docx 决策矩阵、create-skill 触发词描述。→ 把"soft intent"升级为可测试"意图→模块"路由表，模糊时显式告知所走模块。

---

## 六、人工闸 / pause points —— 强化"不替代决策"

- **P0 · 写/投/决 前留确认点**：来自 storage-analyzer（只展示不执行）、wechat-publisher（人工审核再发布）、wayfinder（HITL 票）、vm-error-recovery（升级路径）、agent-browser-core / browser-skill（敏感动作前强制人工确认 + 记录范围）。→ 简历"写入/投递/替用户做决定"动作前必须留用户确认点，并捕获用户显式 outcome（继续/放弃/超时）。
- **P1 · 决策权归用户 + 假设显式化 + 披露未覆盖**：来自 fundamental-thinking、grill-me、genuine-discourse、find-skills（高 stakes 建议给 A/B trade-off、显式列假设、受限时声明未覆盖维度）。→ 规划/匹配建议必须给权衡、列假设、声明未覆盖。

---

## 七、其他高频可借机制（按模块速查）

- **匹配/竞争力模块**：hv-analysis 双轴框架（纵向成长轨迹 + 横向同期比对 + 交汇洞察）、assess_competitiveness 直接套用；来源优先级（一手>二手，多源循环印证假象警告）强化 fetch_jobs / gen_profile。
- **规划模块**：idea-refine「Not Doing 列表」（显式列"这阶段不投什么/不盲目海投"，呼应不替代决策）；domain-modeling 术语表（GLOSSARY.md）消除歧义；grilling 循环（质疑约束/依赖/形状）用于面试模拟对抗式反问。
- **面试模块**：improve-codebase-architecture / grill-me 的对抗式反问；diagnosing-bugs 变红反馈环用于模拟面试的"答错即停"信号。
- **简历模块**：pm-toolkit-review-resume 的 XYZ+S 公式（做了什么 X + 如何做 Y + 量化结果 Z + 技能 S）；rw-claim-audit 式"主张→来源→判定→闸门"带退出码（PASS=0/REVIEW=1/BLOCK=2）。
- **工具纪律**：CNKI 系列"直达不点链接"、knownTags 白名单校验、防误报阻塞判定、会话相关 URL 不可缓存——迁移为"工具调用前校验 + 防误报阻塞 + 不缓存敏感上下文"通用纪律。
- **语气/一致性**：rational-skepticism 四层提问、strategy-red-team「Fails if ___」、paper-audit 委员会（匹配官/真实性官/竞争力官）多视角——用于 verify 后的多视角复核。
- **优雅降级**：browser 系列"不可信数据边界 + 回退路径"——迁移为 pipeline 某 step 失败时的降级而非硬崩。

---

## 八、落地优先级汇总（建议实现顺序）

| 优先级 | 优化项 | 落到 career-copilot 的位置 |
|---|---|---|
| P0 | 红线正面改写（Negation 反模式） | `SKILL.md` 红线章节 |
| P0 | verify 闸门能变红 + 基于契约 + 报真实结果 | `scripts/verify_output.py` / `post_judge` |
| P0 | 前提来源标注（事实/推测/迁移/权威/脑补） | 匹配/竞争力 verdict 生成 |
| P0 | 单源外部红线（未复现数字不进对外简历） | 简历模块硬规则 |
| P0 | 意图路由决策表 + 易混淆场景表 | `SKILL.md` 路由章节 |
| P0 | 跨会话 passport（指针+状态）+ validate 脚本 | `career-context.md` + `session-start` |
| P0 | 写/投/决 前人工确认点 | pause points |
| P1 | 三档约束→风险灯呈现 | 约束章节 + 简历建议 |
| P1 | 改动比例熔断（锁 hash） | 简历改稿 |
| P1 | Red Flags / Failure Modes / 借口表 | 运行时自检 |
| P1 | fork vs continue 二分 | session 生命周期 |
| P1 | 按瓶颈路由 + 新手一次一问 | 软路由修正 |
| P1 | Over-Claim 四陷阱 + 集群判定法 | 文案/经历核验 |
| P1 | 红队自审（先审最强结论） | verify 后环节 |
| P2 | 毕业/晋升机制（控制 profile 体积） | 记忆管理 |
| P2 | 索引式渐进披露 | references/ 加载 |
| P2 | 优雅降级而非硬崩 | pipeline 错误处理 |

> 说明：本总鉴与上方 8 个切片互为索引——切片是"逐 skill 取证"，总鉴是"跨 skill 归纳"。实现时建议先挑 P0 中"结构性缺口"类（红线改写、verify 闸门、意图路由表、passport），因为这些能一次性补齐多个 P1 的底座。
