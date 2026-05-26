# Skill 演化日志

> 加载时机：当 skill-evolution-manager 更新 Skill 时参考，或需要查阅历史决策时。

## 最近一次结构性改动（2025-05-25）

基于 easyslides skill 架构审视，引入约束分级体系和执行边界。SKILL.md 当前 ~182 行。核心改动：
- 新增**约束分级声明**（HARD > REQUIRED > RECOMMENDED > RELAXABLE），所有规则标注 `[H]`/`[R]`/`[Rec]`/`[Rel]`
- "绝对不要"5 条增加**归因**（为什么存在）和**豁免条件**（何时可跳过）
- 新增**纯推理 Stop Conditions**：无简历对话 3 轮预算 + 方向探索 2 轮预算
- matching-guide.md 新增**跨会话恢复协议**（Phase A 恢复期 / Phase B 按需加载）
- onboarding-guide.md 新增**方向探索收敛规则**
- 运行时自检按严重度重排序（H → R → Rec）
- 详细方案见 `notes/easyslides-inspired-upgrade-plan.md`

## 上一次结构性改动

SKILL.md 从 306 行精简到 ~162 行。核心改动：
- 基于 Karpathy/Mnilax 12 规则思想重写：负面约束优先（"不要做X" > "请小心"）
- "全局约束"改为"红线"：5 条负面声明（不编造/不替代决策/不泄露隐私/不绕过工具/不确定时必须说）
- "运行时自检 9 条 + 错误思维 9 条"合并为"绝对不要"5 条高频防线
- 匹配哲学从 5 条合并为 3 条核心原则
- 移除文件结构树（agent 需要时 ls）
- User-Learned Best Practices 移到本文件
- 新增"环境约束"段记录 CLI 参数变化（pre_filter config、timeout、retry 策略）

## User Preferences

- SKILL.md 按 agent 阅读时机分块组织，而非按内容类型
- 操作经验集中管理（后台运行+Sanity Check+降级路径+经验沉淀），不散落在多处
- 脚本后台运行必须用 is_background: true + 轮询策略，不可前台等待超 60s
- SKILL.md 中引用的代码事实（JSON 字段路径、默认值、错误标记）必须经过 verification 确认与代码一致
- 新增内容需从两个第一性原理审视：(A)是否提升判断质量或可靠性 (B)是否修复真实/高概率认知故障
- Skill 三层架构：思考框架（通用决策闭环）> 匹配哲学（领域判断经验）> 具体实现工具集（脚本+流程）
- 暂停点的交互深度应随用户方向确定性动态调整，不是千人一面的'展示等确认'
- examples/ 中的样本文件应在流程描述的关键位置被引用，而不是只存在于文件结构列表中
- 代码改动以'用户可感知的可靠性提升'为第一性原理：隐蔽的 fallback 比显式报错更危险
- 思考框架独立于脚本可用性：即使所有脚本不可用，框架和纯推理能力依然能帮助用户
- SKILL.md 约束章节的依赖信息应与 check_env.py 实际检测逻辑保持同步
- 新功能开发应在合并前编写端到端测试脚本（构造 mock 数据 → 调函数 → assert 输出）
- 跨文件数据传递需确保 pipeline 每一跳都有对应的传播代码，每跳独立可验证

## Known Fixes & Workarounds (Active)

- fetch_jobs.py CATDESK 路径已改用 _find_catdesk() 自动检测
- fetch_jobs.py 超时判定已改为 (jobs, success_flag) 返回，区分真空页和超时
- generate_report.py job-card 已添加 id 属性
- fetch_jobs.py PRESETS 中 JS selector 以 [URL]...[/URL]\n 前缀格式写入
- smart_score.py parse_jobs_raw 正确提取 URL 并从 text 中移除标记
- generate_report.py f-string 内嵌条件表达式引号嵌套已用三引号外层处理
- assess_competitiveness.py assess_single 返回 dict 包含 job_id 字段
- check_env.py 已更新为多 Provider 方式 + 网络连通性检测（HEAD 请求，5s 超时）
- diff_watch.py 已增加 provider 属性透传 + "上次监测"时间显示
- pre_filter.py 新增 config 参数：include_intern / include_outsource / max_year_requirement
- smart_score.py 新增 CLI：--include-intern / --include-outsource / --max-year-requirement / --resume / --stage2-concurrency
- llm_client.py 新增 timeout=120 + _compute_retry_wait（AuthError不重试，RateLimit尊重retry-after，Timeout 2s重试）
- smart_score.py fallback 分从 50 改为 30，增加 is_fallback 标记
- post_judge.py CORE_TEAM_SIGNALS 拆为 GENERIC_CORE_SIGNALS + profile["core_team_signals"]
- smart_score.py 新增 checkpoint 机制（_save_checkpoint / _load_checkpoint / _clean_checkpoints）
- smart_score.py JSON 解析统一为 4 层恢复策略（_parse_json + _parse_json_array）

## Custom Instruction Injection

- 实验验证方法：用子 agent 真实执行完整 pipeline，观察约束遵循情况
- 每次写入 SKILL.md 的代码事实必须 grep 源代码验证
- 设计原则：Skill = 思考框架 + 判断依据 + 当前最佳实现工具集
- 改进标准：改了之后用户体验或系统可靠性是否显著提升

## Reference 文件加载时机

- `matching-guide.md`：当路由到匹配模块且需要执行 pipeline/处理异常/查看命令参考时加载
- `interview-prep.md`：当路由到面试模块时加载
- `resume-guide.md`：当路由到简历模块时加载
- `career-memory.md`：当需要读写职业记忆、理解事件格式、或首次初始化记忆系统时加载
- `onboarding-guide.md`：当用户方向不明确、冷启动、说"不知道从哪开始"时加载
- `evolution-log.md`：当 skill-evolution-manager 更新时参考
