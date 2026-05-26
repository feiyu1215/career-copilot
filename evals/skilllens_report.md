# SkillLens Report: career-copilot (v2 — post-improvement)

## Summary

- **Total Score: 87/100**
- **Verdict: Excellent**
- One-line: 求职全链路闭环设计精良，红线+降级路径+测试三重保障，是 Technique + Reference 混合型 Skill 的标杆

---

## Pillar Scores

### Business Value (23/25)

career-copilot 解决了一个真实且高频的痛点：技术人员求职时面对大量 JD 的筛选、匹配和准备工作。它不是简单的 "帮我改简历"，而是构建了完整的 探索→匹配→投递→面试→决策 闭环，每个模块都与匹配引擎的数据对接（scored_results.json 的 risks 字段同时驱动简历优化和面试准备）。

核心差异化在于 **匹配驱动** 的设计理念——不是泛泛的建议，而是基于数据（评分、risks、direction_anchors）生成针对性方案。这让 Agent 的输出从 "你可以准备一下分布式相关问题" 升级为 "你的 risk 是缺乏 CRDT/OT 落地经验，建议用即时通讯消息同步→文档协同同步的迁移叙事应对"。

扣 2 分：主要面向中国互联网技术求职者，受众相对垂直，但在此细分市场内 ROI 极高。

### Market Fit (12/15)

在 CatDesk Skill 生态中填补了明确的空缺——没有其他 Skill 同时覆盖 JD 批量抓取 + 智能评分 + 面试准备 + 简历优化。最接近的替代方案是 job-matcher-v3，但它只覆盖匹配评分环节，不涉及面试准备和简历优化。

需求信号强：触发词覆盖了 26+ 种用户表述（从"帮我匹配岗位"到"面试紧张"），说明需求多样且真实。多个用户场景（冷启动、单 JD 评估、全流程 pipeline）都有明确路由。

扣 3 分：依赖外部 LLM Provider（internal/external），增加了使用门槛；部分功能（fetch_jobs.py 的 catdesk-browser 依赖）限制了独立部署。

### Runtime Cost (11/15)

Token 效率设计合理：SKILL.md 仅 120 行（~325 words），按需加载 4 个 reference 文件（329-600 行不等），而非一次全部进入上下文。意图路由表在 SKILL.md 层面完成分流，避免不必要的 reference 加载。

Pipeline 成本控制出色：先粗后精的两阶段评分（便宜模型淘汰 75% → 强模型只处理 top-k），作者估算总成本 ~1 RMB/200 条 JD。`--dry-run` 模式允许预览成本而不实际消耗 token。

后台运行策略和轮询机制避免了长脚本阻塞对话。

扣 4 分：reference 文件偏长（interview-prep.md 600 行、career-memory.md 568 行），一旦加载会显著增加上下文。缺乏 "只加载相关章节" 的更细粒度控制。

### Reliability (18/20)

改进后的可靠性显著提升：

- **57 条 pytest 单元测试** 全绿，覆盖 pre_filter.py 和 post_judge.py 的核心函数
- **7 条 eval 测试用例**（含 4 个 edge case），desk review 通过率 97.9%
- **verify_output.py** 作为 pipeline 的强制检查点（SKILL.md 明确禁止跳过）
- **连续 3 次失败停止** 的硬性规则避免死循环
- **5 条红线** 定义了不可逾越的边界（不编造、不替代决策、不泄露隐私、不绕过工具、不确定时必须说）
- **降级路径** 覆盖了抓取失败、JD 极简、脚本部分失败等场景

扣 2 分：缺乏错误类型分类诊断表（eval #6 发现的 gap）；Sanity Check 规则间缺乏优先级指导（eval #5 发现的 gap）。

### Writeup Quality (23/25)

文档结构清晰，采用 **渐进式加载** 架构（SKILL.md → 4 个 reference files → examples）。

SKILL.md 做到了：用 120 行覆盖红线、思考框架、意图路由、匹配引擎核心、Pipeline 概览、绝对不要、记忆策略和环境约束——信息密度极高但不冗余。

触发描述覆盖 26+ 种用户表述，包含正向触发和排除条件（"不触发：单纯写代码、非求职文档写作..."），精确度高。

每个 reference 文件开头都有 "加载上下文" 指引，明确说明何时需要加载、何时不需要——避免不必要的 token 消耗。

扣 2 分：缺乏专门的冷启动引导参考文件（eval #3 发现的 gap）；SKILL.md 中缺乏沟通语气规范。

---

## Strengths

1. **匹配驱动的模块联动**：scored_results.json 的 risks 字段同时驱动面试准备（JD→考点逆向推导）和简历优化（Risk 诊断→针对性修改），形成了数据驱动的完整闭环，而非孤立的功能堆砌。

2. **红线设计精准且可执行**：5 条红线既具体（"JD 极简 < 3 行正文"、"禁止记录具体薪资数字、面试官真名"）又有判断标准（"100 个 case 答案都一样的判断，写成代码"），不是空洞的 ALWAYS/NEVER。

3. **确定性 + 判断力的分层架构**：Pre-Filter（代码）→ LLM 评分 → Post-Judge（代码），体现了 "模型负责判断力，代码负责约束力" 的设计哲学，且有明确的分界线标准。

4. **降级路径完备且诚实**：从抓取失败到 JD 极简到脚本部分失败，每个降级场景都有明确处理方式，且要求 "不要静默 fallback"——任何降级都必须显式告知用户。

5. **测试覆盖显著增强**：57 条单元测试 + 7 条 eval 用例（含 4 个 edge case）+ verify_output.py 强制检查 + --dry-run 预览模式，构成了多层验证体系。

---

## Weaknesses

1. **冷启动引导缺乏专门参考文件**：对 "不知道从哪开始" 的用户，引导逻辑分散在 SKILL.md 路由表 + matching-guide.md 决策路由 + career-memory.md 阶段定义之间，缺乏一个 onboarding-guide.md 提供系统化引导流程。

2. **Reference 文件偏长**：interview-prep.md（600 行）和 career-memory.md（568 行）一旦加载会消耗大量上下文，且没有更细粒度的 "只加载相关章节" 机制。

3. **错误诊断指导不够具体**：对 timeout、JSONDecodeError、AuthError 等不同错误类型缺乏分类诊断表和对应排查步骤，依赖 Agent 通用推理能力。

4. **外部依赖较重**：依赖 LLM Provider（internal/external）、catdesk-browser、pypdf 等，新用户 onboarding 有一定门槛（虽然 requirements.txt + check_env.py 已缓解）。

---

## Recommendations

1. **(中优先级)** 创建 `references/onboarding-guide.md`，定义冷启动场景的完整引导流程和沟通风格规范
2. **(中优先级)** 在 matching-guide.md 中增加 "常见错误类型及诊断方向" 对照表
3. **(低优先级)** 对 interview-prep.md 和 career-memory.md 增加章节级 TOC，并在 SKILL.md 中增加 "只加载第 X 章" 的指引
4. **(低优先级)** Sanity Check 规则增加优先级注释，避免规则冲突时 Agent 困惑

---

## Score Comparison (Before → After)

| Pillar | Before | After | Delta |
|--------|--------|-------|-------|
| Business Value | 20 | 23 | +3 |
| Market Fit | 10 | 12 | +2 |
| Runtime Cost | 9 | 11 | +2 |
| Reliability | 18 | 18 | → (was already strong, now validated) |
| Writeup Quality | 22 | 23 | +1 |
| **Total** | **79** | **87** | **+8** |

上次评分时 Reliability 18 分但缺乏测试验证；此次虽然分数不变，但底层支撑完全不同——有了 57 条 pytest + 7 条 eval + verify_output + dry-run，18 分的置信度从 "推测可靠" 变为 "验证可靠"。

Business Value +3 主要因为深入分析了匹配驱动的模块联动设计（之前只看了 SKILL.md 表面）。Runtime Cost +2 因为 --dry-run 模式实际填补了之前 "无法预估成本" 的缺陷。
