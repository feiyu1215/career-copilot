<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# Career Copilot × mailplugin-feature-dev 对标分析（Benchmark）

> 来源：企业微信团队文章《AI代码生成率94%：我们用一个 Skill 跑通需求开发全流程》（2026-07-20）
> 目的：判断 mailplugin-feature-dev 的设计思路对 career-copilot 是否有借鉴意义
> 记录日期：2026-07-20

## 一句话结论

**有借鉴意义，但主要是「验证架构走对了路」+「补几个形式化缺口」，而不是引入新概念。** career-copilot 已独立采用 mailplugin 绝大部分套路，两边殊途同归。

## 架构对标：你更像 mailplugin，不是 RW

- **mailplugin** = 1 个 skill + 8 阶段流水线 + 红线 + 交接单
- **career-copilot** = 1 个 skill + 软意图路由 + 红线 + 交接单
- **RW Research Skill** = 18 个 skill + 硬路由器（不适合单 skill 内聚项目）

→ **mailplugin 才是正确对标范本**；career-copilot 2.0 方案里「不拆多 skill、不加显式 /command」的决定完全正确。RW 那套多 skill 硬路由恰恰不适合本项目。

## 已有能力对照（已 converged）

| mailplugin 核心套路 | career-copilot 现状 | 状态 |
|---|---|---|
| 红线机制（触发即停） | SKILL.md「红线」5 条 + 运行时自检 | ✅ 已有，且更细（[H]/[R]/[Rec]/[Rel] 四级） |
| 约束分级（Critical/Standard） | HARD>REQUIRED>RECOMMENDED>RELAXABLE | ✅ 已有 |
| 分阶段流水线 + 暂停点 | Pipeline Step0-5 + 暂停点 + verify_output.py | ✅ 已有 |
| 跨会话记忆 | career-context.md + career-profile.md + 事件日志 JSONL | ✅ 比 mailplugin 还成熟 |
| 脚本做数据 / LLM 做判断 | scripts/ 做评分抓取，模型做语义 | ✅ 已有 |
| 按需加载、逐步收窄 | references 按章节 TOC 按需加载 | ✅ 已有 |
| eval / behavior-tests | evals/ + tests/ | ✅ 已有 |

## 真正可借鉴的 4 点（按性价比）

### 🔴 P0 — 红线外置成结构化文件
现状：红线散在 SKILL.md 散文里。
借鉴：抽成单一真源 `red_lines.yaml`（Critical/Standard 分级）+ 标准化报错模板 `⛔ 触发红线 CC-XX`，配 `check_red_lines.py`，让红线可被机器检查、好维护，而非靠模型记散文。

### 🔴 P0/P1 — 知识防漂移检查（求职领域特别值）
现状：`diff_watch.py` 只盯「新增岗位」，**不盯「知识过期」**。
借鉴：加 `check_references_stale.py`（哈希 + 时间基线），监控 company-research / 市场假设 / 薪资带是否过期。求职领域知识过期极快，这条尤其值得做。

### 🟡 P1 — 把「阶段完成」做成确定性闸门
现状：已有 verify_output.py，但各阶段「完成」多半还是 prompt 里说要暂停。
借鉴：mailplugin 的退出码 / sentinel 文件思路，让下一阶段在没有确定性完成信号时拒绝运行——小补，但更稳。

### ⚪ P2 — 统一 halt 模板
所有红线触发用同一套 `⛔ 触发红线 CC-XX：<标题> / 当前情形 / 建议处理` 格式，便于 grep 与日志。

## 不要借鉴（会伤到你们）

- ❌ 显式 /command 或拆成多个 skill（2.0 已正确拒绝）
- ❌ 五步定位法 / Figma-TAPD-模拟器集成（领域不相关）
- ❌ 硬关键词翻译表（会钝化刻意保留的灵活意图路由）

## 后续选项

1. 起草 `red_lines.yaml` + 标准化 halt 模板，并说明怎么接进现有 SKILL.md
2. 写 `check_references_stale.py` 脚本（含哈希基线逻辑）
3. 本文件（benchmark 已落地）
