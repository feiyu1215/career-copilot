<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# SkillLens Report: career-copilot（深度评测 · 修订版）

> 评测日期：2026-07-21（修订）｜ 评测对象：`career-copilot-copy`（已含 8 契约借鉴 + 软契约主动化 + 飞书 ATS 路线）
> 评测方式：LLM 深度评测（有证据），非脚本启发式基线。
> ⚠️ 本评测为**作者自评**，存在固有独立性缺陷，详见「自评局限与偏差披露」。结论可信度中等，定论为 **Good** 而非 Excellent。原稿 80/100 Excellent 经四框架反向 QA 后下调至 74/100。

## ⚠️ 自评局限与偏差披露（修订新增）

本报告的评分人同时是 skill 作者、M4 动态回归 `expected_output` 的出题人、以及本报告作者——**三重同源，零独立性**。这带来：

1. **M4 4/4 的证明力有限**：是「自己出题、自己阅卷」，证明的是「本模型（agnes-2.0-flash）能 follow 本 skill」，≠「跨模型 / 跨时间可靠」。
2. **确认偏差风险**：Strengths 易偏向自夸，Weaknesses 易被轻描淡写（原稿列 5 条弱点却总分只扣 20 即此症）。
3. **边界凑分风险**：原稿 21+11+10+16+22 恰好=80，恰好压 Excellent 线，对单点 ±1 极度脆弱。
4. **已修正的事实误差**：自动评分脚本（41.8）的 `has_trigger_description`/`has_examples`/`has_references` 误判确凿（中文结构）；但其「文件数 205」源于计入 `.git`。已核实真实工作树 **76 文件（git 跟踪 55）**，原稿「75」为未验证估计，现更正。

## Summary

- **Total Score: 74/100**
- **Verdict: Good（紧贴 Excellent 边界；距 80 线差 6 分）**
- **One-line**: 结构清晰、诚实优先、带 verify 闸门与契约化护栏的求职全链路 skill；唯一真短板是「软契约靠 prompt 强制而非机制保证」，以及对特定运行时 / 单一模型的依赖。

## Pillar Scores

### Business Value (20/25)
求职（匹配 / 简历 / 面试 / 记忆）是高频且高痛点的真实问题，ROI 清晰——更好的匹配与简历表达直接改善求职结果。skill 用「六阶段评分 pipeline + 迁移叙事 + 诚信护栏」给出比裸聊 LLM 更可靠的结构化产出。
- 证据：SKILL.md L3 明确定义「探索→匹配→投递→面试→决策」完整闭环与 30+ 触发词；L26 起「lens 不分回合」把诚信原则前置。
- 扣分：开源免费 + 依赖 CatDesk/OpenClaw 运行时，普通 ChatGPT 用户无法直接即用；且「商业价值」与「市场可达性」在此被合并扣分，逻辑略有混淆（见 Weaknesses #6）。

### Market Fit (11/15)
存在清晰缺口：市面多是「让 LLM 帮你改简历」的零散用法，缺乏「诚实优先 + 可验证 + 不编造」的结构化求职 agent。本 skill 的 verify 闸门、单源红线、Over-Claim 镜面正好补这个洞。需求常年存在（求职是周期性刚需）。
- 证据：references/resume-guide.md 的「禁止单源未复现数字进对外简历」、references/matching-guide.md 的「前提来源标注 [事实]/[推测]/[脑补]」是差异化能力。
- 扣分：部分能力 ChatGPT/Claude 也能做（替代方案存在），故为 Strong 而非 Exceptional。

### Runtime Cost (10/15)
典型运行需多脚本链路：gen_profile → fetch_jobs(_feishu) → smart_score（六阶段）→ generate_report → verify_output，每步含 LLM 调用，全量跑 token/tool-call 偏重。
- 证据：SKILL.md L129-136 的 Pipeline 步骤；但 skill 内置 ⏸ 暂停点（L133/135/136）与「JD≤5 或只讨论单岗不需要跑代码」（matching-guide）做节流。
- 扣分：完整 pipeline 仍偏重，且 fetch_jobs_feishu 依赖 Playwright+Chromium（额外安装成本）。

### Reliability (13/20)  ← 原稿 16，修订下调
机制化护栏扎实：verify_output.py 合同化校验（重写后带 [C#] 契约号、显式暴露 0~15% fallback，不再静默通过）、test_verify_output.py 62 passed、8 条行为契约（前提标注/单源红线/改稿熔断/Over-Claim 等），M4 真 LLM 动态回归 **4/4 通过**。
- 证据：SKILL.md L149/L199 的 verify 硬闸门（「smart_score 完成但没跑 verify → 禁止继续」）；M4 结果（agnes-2.0-flash，11✅95/12✅100/13✅95/14✅95）。
- **最大短板（权重加重）**：软契约（①③④）是 **prompt 强制**而非机制保证——M4 显示未加「主动 lens」时 3/4 失效（1/4 通过），加了硬化才 4/4。即核心安全机制依赖模型遵循度，弱模型或 prompt 漂移可能回退。对 **honesty-first** 产品，此点在该 pillar 至多 Good，故从 16 下调至 13。

### Writeup Quality (20/25)  ← 原稿 22，修订下调
SKILL.md 279 行，触发词丰富（L3）、意图路由表（L46）、5 大能力模式、约束四级 + 风险灯可视化（L24）、⏸ 暂停点、运行时自检；references 11 份详尽；FILE_GUIDE.md 开发者手册 + README 用户文档双轨；易混淆场景软示例（L59-62）。
- 证据：触发词覆盖中英文 + 边界（「不触发：单纯写代码/薪资谈判话术」）；examples 在 matching-guide / resume-guide 大量存在。
- 扣分：「偏密 / 无速览」弱点实际更重——279 行无顶部 TL;DR，新 agent 冷启动成本显著高于 Excellent 档应有水平，故从 22 下调至 20。

## Strengths
1. **诚信护栏是真结构**：单源红线、前提来源标注、Over-Claim 镜面、改稿熔断——不是口号，是可核验的契约，且有 verify 闸门兜底。
2. **软路由不钝化**：单 skill + 自然语言意图路由，拒绝硬编码 /命令，保留灵活性（SKILL.md L68）。
3. **可验证优先**：verify_output.py 合同化 + fallback 显式暴露 + 62 项测试 + M4 真 LLM 回归 4/4。
4. **文档双轨且完整**：README（用户）+ FILE_GUIDE（开发者）+ 11 references，且本次新增飞书路线同步更新了所有相关文档。
5. **主动 lens 硬化**：澄清/延后回合也套契约，堵住了「无输入→延后→契约不触发」的测试设计漏洞。

## Weaknesses
1. **软契约靠 prompt 强制**：①③④ 的可靠性依赖模型遵循度，弱模型或 prompt 漂移会回退（M4 前后 1/4→4/4 即证）。**核心安全机制非机制保证。**
2. **运行时依赖重**：需 CatDesk/OpenClaw + LLM API；飞书路线还需 Playwright+Chromium。
3. **完整 pipeline token/tool-call 偏重**，虽有误流节流但仍非轻量。
4. **SKILL.md 偏密**：279 行无速览，新 agent 冷启动成本高。
5. **市场分发窄**：开源但绑定特定运行时，普通用户上手门槛高。
6. **评测本身局限**：自评无独立性；Business Value 与 Market Fit 的扣分在「运行时依赖」上重复计算；未覆盖 PII/安全、维护 bus factor、真实用户结果、跨模型对比。

## Recommendations（提升分数）
1. **把软契约机制化**（冲 Reliability 13→18）：在 verify_output 或 pre/post hook 里对 ①③④ 做输出级检测（如检测「高度匹配/够了」等断言是否带 [推测] 标签），不纯靠 prompt。
2. **SKILL.md 顶部加 TL;DR**：30 秒速览 + 最小可用路径，降低冷启动成本（Writeup 冲 23+）。
3. **提供运行时无关适配说明**：一份「在 ChatGPT/Claude 里怎么用本 skill 的 prompt 包」降低 Market Fit 门槛（11→13）。
4. **轻量模式**：对 JD≤5 / 单岗场景固化「纯推理路径」，把 Runtime Cost 提到 12+。
5. **跨模型 eval**：M4 动态回归在 GPT/Claude/Kimi 上各跑一遍，暴露 prompt-only 的真实风险面。
6. **持续 eval 守护**：把 M4 动态回归接成每次改 SKILL.md 后的门禁，防软契约回退。
7. **补齐评测盲区**：PII/安全审查、维护性/bus factor 文档、真实用户结果 A/B。

## 边界敏感性声明
总分 74 距 Excellent 线（80）差 6 分。**不建议对外宣称 Excellent**。若后续实证弱模型下软契约回退严重，或 Writeup 补 TL;DR 后维持，定论稳定为 Good（中段）。唯一能进 Excellent 的路径是先完成 Recommendation #1（机制化）+ #2（TL;DR）+ #5（跨模型验证）。

---
*评分原则：每个分数均有具体证据（行号/行为/测试结果）支撑。自动脚本基线因解析中文失败不可信，已剔除；但其文件数误差已据实更正为 76（git 跟踪 55）。本评测为作者自评，结论可信度中等。*
