# 会话生命周期（强制步骤）

> 本文件从 SKILL.md 拆出，按需加载。触发时机：每次会话开始（session-start）和结束（session-end）时读取。

对应 Skill 2.0 的 **Working Memory + Hooks** 思想：用一份轻量上下文让每次会话秒级进入状态，用强制收尾避免跨会话丢上下文。**不钝化 AI 灵活性**——本 skill 仍是单 skill、靠理解意图路由，绝不引入显式命令。

## session-start（开始必做）`[R]`

- 第 1 步：读取 `~/.catpaw/career-copilot/career-context.md`（~200 tokens：当前阶段 / 焦点公司 / 截止日 / 上次操作 / 待办），掌握当前状态以便智能提问。
- **第 1.5 步（passport 新鲜度校验）`[R]`**：读取 context 后，检查是否过期——(a) 距「上次操作」超过 **7 天**；或 (b) `career-profile.md` 的修改时间晚于 context 生成时间（profile 已变）；或 (c) 用户上一轮说过"换了方向 / 更新了简历"。任一命中 → 提示"context 可能已过时，建议重建（选项 c）"，**不要盲目沿用旧状态做决策**。
- 第 2 步：**动手前先向用户确认读取范围**（一句即可，不阻塞——用户直接说话即视为选默认「用便利贴继续」）。提供三选一：
  - **(a) 用便利贴继续**（默认，~200 tokens，秒级进入）
  - **(b) 读全量档案** — 读 `career-profile.md`（~2000 tokens）
  - **(c) 重新读一遍 / 重建** — 当 profile 可能已变、或 context 已过时，重读全量并刷新 context
- **新用户 / 无 context**（`career-context.md` 不存在）：无可选范围，直接读全量 `career-profile.md`（profile 也不存在则走 onboarding 建立档案），并告知用户。
- **会话中途**用户说"读全量 / 重新读 / 看完整文档"等 → 立即执行，效率让位于用户意图。
- 文件不存在且 profile 已有时，按 `references/career-context.template.md` 从 `career-profile.md` 初始化一份 context（供后续会话复用）。
- 对**模糊 / 跨场景**输入（如"我该怎么找工作"），按 SKILL.md「意图路由」的**模糊输入**规则用 1 个问题确认方向——**不预设命令、不强行归类**。
- 需要更多历史细节再筛事件日志，**不要一次读全部**。

## session-end（收尾必做）`[R]`

- 关键操作（匹配完成 / 面试记录 / 简历修改 / 规划产出 / 对齐结论 / 调研结果）后，调用 `scripts/career_log.py` 写入职业事件日志。
- **更新 `career-context.md` 为结构化交接单**（字段见 `references/career-context.template.md`），至少覆盖四块：
  - **状态**：当前阶段 / 焦点公司进度 / 关键截止
  - **已决策**：本次对齐模式产出的关键结论（如「方向定大厂后端」）
  - **待决策**：悬而未决、下次需用户拍板的点
  - **下一步**：1–3 件具体动作（同步进「待办」）
- 现有 `evolution-log`（站点经验 → `memory_write`）并入此收尾流程。
- **申请/结果闭环（P5）**：若本次会话产生了真实投递或结果（面试/offer/拒信），调 `scripts/job_tracker.py add/apply/update` 记入 `notes/job-tracker.json`；定期跑 `stats` 看 tier/来源转化，回灌投放策略。与 career_log（记事件）互补。
- 不写日志、不更新 context = 本次会话视为未完成，下次来会丢失进度。
- **[Rec] 评估数据采集（生产盲评 enabler，可选 / 需用户显式授权）**：若用户同意把本次会话（脱敏后）纳入质量盲评数据集，把本轮对话整理成 `[{role,text}, ...]`，调用 `evals/collect_transcript.py`（或 `collect_session()` 函数）落盘到 `evals/transcripts/<phase>/<before|after>/`。
  - 默认 `before_or_after=after`（契约已硬化后的产出）；仅当用户已确认无 PII 才 `--no-redact`（默认脱敏，复用 `career_log.SENSITIVE_PATTERNS`）。
  - **诚实边界**：采集**可选 + 显式授权**，无平台 hook 时由用户/运营导出对话 JSONL 后调用；落盘的 transcript 已被 `.gitignore` 排除、**不进版本库**，仅本地积累供未来 `--live` 盲评得 before/after Δ。
  - 不授权 = 不采集，绝不静默记录（呼应红线「不泄露隐私」）。
