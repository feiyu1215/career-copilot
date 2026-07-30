# Career Copilot · 实现状态与进展评估报告

> 评估日期：2026-07-30
> 评估方法：源码逐文件核对 + git 提交历史 + 工作树状态 + **实跑测试套件（530 passed）**
> 评估对象：`D:\57709\Desktop\Apple\美团\career-copilot-copy`

---

## 一、结论速览

| 维度 | 结论 |
|------|------|
| **成熟度** | 核心求职闭环（岗位匹配 → 面试准备 → 简历优化 → 职业记忆）**生产可用**，工程化水平很高 |
| **代码规模** | 47 个 `scripts/*.py`、70 个测试文件、约 **530 个单测全绿**；22 个 `references/`、6 个 `config/`、4 个 LaTeX 模板 |
| **质量门禁** | 测试全绿；4 处历史 bug 全部修复并提交；审计发现的 3 处 bug 已修复 |
| **⚠️ 最大风险** | **当前工作树 149 个文件未提交**（+4306 / −1745 行），属"开发完成未入库"状态；文档严重滞后 |
| **文档滞后** | `FILE_GUIDE.md` 记录 21 个脚本，实际磁盘 **47 个**；`SKILL.md` 引用与部分脚本现状需同步 |

**一句话**：功能层面已达"可用且扎实"的 MVP+，但处在**大一轮未提交改动**的收尾期，当务之急是 commit/push 与文档对齐。

---

## 二、当前已完成的功能

### A. 岗位匹配引擎（核心，已稳定）
- **六阶段评分 pipeline**（`smart_score.py`）：粗筛 → 校准 → 精排(listwise) → 全局重排 → 确定性后处理 → 验证。
- **确定性兜底**：`pre_filter.py`（学历/年限/语言/地域硬门槛）+ `post_judge.py`（英语/核心团队/技术依赖惩罚 + A 档比例上限 25%）。
- **配置与 Prompt 外部化**（T8）：`config/pipeline.yaml` + `config/prompts.yaml`，代码默认值兜底零回归。
- **熔断与 JSON 自愈**：Stage1 熔断用 `failed/processed`（已修复小批量被稀释）；四层 JSON 解析恢复 + `is_fallback` 透明标记（bug M2 已修）。
- **Checkpoint / 恢复**：`--resume` 断点续跑（注意：fresh 运行崩溃点在 checkpoint 写入前，已由测试 `test_run_pipeline_e2e.py` 守住）。

### B. 多门户 JD 抓取（扩展中，未提交）
- 已落地脚本：`fetch_jobs`（catdesk 路线）、`fetch_jobs_feishu`（飞书 ATS Playwright 拦截）、`fetch_boss`（多后端可插拔）、`fetch_jobs_linkedin`、`fetch_jobs_shixiseng`、`fetch_jobs_nowcoder`。
- 共享库 `job_common.py`（+600 行）统一去重/健康检查/mass-posting/内推链接/质量闸门；`batch_fetch.py` 多门户批量；`verify_fetch_quality.py` 废卡拦截；`config/portals.yaml` 配置 rate_limit 合规刹车。

### C. 简历定向优化（Tier1 诊断 + Tier2 实物生成，未提交）
- **Tier1**：`resume-guide.md` 方法论（表述问题 vs 能力缺失、STAR、ATS 关键词）。
- **Tier2 实物生成闭环**（未提交批次）：`build_cv.py`（LaTeX/`build_cv_docx.py` 双路线）、`drafter_reviewer.py`（Drafter-Reviewer 双轨，4 硬契约 + Over-Claim 熔断）、`verify_ats.py`（ATS 门禁：页数==2 / 联系方式字面 / 无 cid 乱码 / JD 关键词覆盖）、`manage_template.py` + `templates/*.tex`（cn-compact / cn-professional / en-single-col / cover-letter）、`relevance_trim.py`（相关性裁剪）。

### D. 面试准备 / 职业记忆 / 竞争力
- `interview-prep.md`、`career-memory.md`；`career_log.py` v2（事件信封 + 逐类 schema + 内存索引 + trace/expire，含 `expires_at` 时序感知）；`job_tracker.py`（申请/结果闭环 + stats 漏斗）；`assess_competitiveness.py`（竞争力评级 + `needs_review` 诚实降级，bug m9 已修）；`competitiveness_tracker.py`/`trend_analyzer.py`/`calibration_feedback.py`/`first_seen.py`。

### E. 诚实护栏与评测体系（已落地）
- **JD 零信任**（`jd_guard.py`）：禁止执行 JD 内嵌指令，清洗 + 扫描报告。
- **软契约机制化**（`verify_lens.py`）：对白 transcript 确定性 WARNING 检查（①③④），不钝化灵活性。
- **评测脚手架**（`evals/`）：LLM-judge 动态评测 + 门禁（`run_dynamic_eval`）、盲评（`blind_eval_runner`）、合成消融（`run_ablation`）、Golden Cases（`evals/golden/`）、回归对比 + 交叉验证（T11/T12）。
- **轻量分发**：`lite/SKILL.md` + `references/chatgpt-lite.md`（诚实声明"无机制保证"）。

### F. 工程卫生 / 合规
- `llm_client.py` 多 Provider（friday/sub2api/nvidia/agnes）+ Failover + 冷却 + 重试分类；`cache.py` 语义缓存；`trace.py`/`log_utils.py` 可观测；`tools/security_guards.py` + `.github/workflows/ci.yml` 安全门禁；`LEGAL_DISCLAIMER.md` + `notes/security-checklist.md` 合规。

---

## 三、待完成 / 进行中的部分

1. **🔴 未提交的工作树（最高优先）**：149 个文件、+4306/−1745 行改动尚未 `git commit`/`push`。这是"多门户抓取 + Tier2 简历实物生成 + JD 零信任"这一大轮迭代的收尾，测试已全绿，但**未入库即存在丢失/漂移风险**。
2. **🟠 文档对齐**：`FILE_GUIDE.md` 严重滞后（21 vs 47 脚本）；`SKILL.md`、README 需随未提交批次同步（README 已在未提交树中被重写 −206 行）。
3. **🟡 评测硬门禁受限**：`agnes` 跨 run 方差大、`nvidia` 免费端点 503/hang → `make eval` 只能作 advisory（`--skip-on-error`），**无法作可靠硬 CI 阻断**（已知限制，非 bug）。
4. **🟡 旧路线图遗留的 aspirational 项**（多已过时/被取代，未显式关闭）：Prompt 版本化、全局 Semaphore 共享限流、Pipeline 显式 Schema 校验（`schema.py`）、记忆关联推理、`--ab-test`。这些在 `skilllens_upgrade_plan`（已归档至 notes/archive/skilllens_upgrade_plan.archived.md）之后多数不再活跃，已正式归档。
5. **🟡 BOSS 抓取运行时依赖**：`fetch_boss.py` 的可用后端依赖外部 `bsk daemon` / `boss-cli` 与已登录 Edge 会话；抽象基类 `BaseBackend` 的 `NotImplementedError` 是正常多态设计（子类已实现），**非功能缺口**，但真实可用性取决于运行环境是否具备该浏览器会话。

---

## 四、已知问题 / Bug（含历史修复）

### 已修复（有测试守护，不再复现）
- **审计 CRITICAL**：`run_pipeline` Stage1 返回值未解包 → fresh 运行必崩（已修 + `test_run_pipeline_e2e.py` 守住）。
- **审计 MEDIUM**：`generate_report.py` 动态字段未 HTML 转义（XSS/结构破坏，已修 + `test_generate_report` XSS 用例）。
- **审计 LOW**：`career_log query --company` 文案"模糊"与实际"精确"不符（已修）。
- **bug-review 9 项**（M1–M4 可移植/一致性 + m5–m9 文档/逻辑）：scholar `.env` 硬编码、L4 兜底 fallback 失效、死特性 `core_team_signals`、friday env 命名错位、C7 门槛注释、docstring 漂移、verify_lens 标签、fetch 空尾页误计失败、assess 静默默认 → **全部修复并补测试（129 passed）**。

### 当前状态（无已知未修代码级 bug）
- **测试全绿（530 passed）**，未提交批次含约 330 个新增测试。
- **无活动 TODO / 未完成 NotImplementedError**（已逐一核实：均为抽象基类方法或注释/脱敏/模板占位说明）。

### 非代码风险（需关注）
- **工作树脏但未提交**（149 文件）——丢失/环境依赖风险。
- **bus factor = 1**：单维护者（bus factor 视图已诚实标注）。
- **文档滞后**导致新接手者难以快速建立认知。

---

## 五、整体进度评估

**进度评分：约 85–90%（核心闭环）/ 大轮扩展约 95% 代码完成但 0% 入库）**

- 设计哲学清晰（模型判断 + 代码约束、方向锚定、Listwise、确定性兜底）；约束分级 + 软契约机制化在同类 skill 中属上乘。
- 工程化扎实：配置/Prompt 外置、Failover、缓存、Trace、Checkpoint、ATS 门禁、安全/合规门禁一应俱全。
- 评测体系（动态评测 + 盲评 + 消融 + 回归 + 交叉验证）远超一般个人项目。

**最该做的三件事**：
1. **立即 commit + push** 当前 149 文件工作树（先 `git stash` 备份防丢失），把"多门户 + Tier2 简历生成 + JD 零信任"这一轮落库。
2. **同步文档**：刷新 `FILE_GUIDE.md`（脚本清单 21→47）、`SKILL.md` 路由、`README`，消除滞后。
3. **清理旧路线图**：将 `notes/archive/improvement-roadmap.archived.md` 中已被取代的条目正式标记归档，避免误导。

> 备注：本评估基于 `git` 已提交历史至 `4624d2b`，叠加未提交工作树（截至 2026-07-30 实跑 530 passed）。如需把本报告作为正式交付物纳入版本库，可告诉我，我会追加到 `notes/` 并提交。
