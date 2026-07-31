<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->

<!-- SUPERSEDED: 2026-07-30 归档至 notes/archive/。本文件内容已被实际实现（v2 多门户抓取 / Tier2 简历生成 / Phase 8 系列 / 端到端编排器等）取代，仅作历史参考，不再作为待办来源。 -->

> [SUPERSEDED] 本文档已于 2026-07-30 归档，已移入 `notes/archive/`。内容多为早期规划 / 灵感探索，已被实际实现取代，不再作为活跃待办。当前改进跟踪以 `notes/evolution-log.md` 与 `evals/` 为准。

# career-copilot 升级计划（基于 SkillLens 自评修订版 · 已对齐哲学）

> 来源：对 `skilllens_deep_review.md`（74/100 Good）的四框架反向 QA。
> **目标（已重写）**：以 skill 的设计哲学为唯一判据——(A) 提升判断质量/可靠性；(B) 修复真实/高概率认知故障；隐蔽的 fallback 比显式报错更危险。**SkillLens 分数只是副作用，不是目标。**
> **哲学合规**：本计划已对照 `notes/addition-criteria.md` 审计。初稿有 4 处撞哲学，已修正（见各条「哲学护栏」）。冲突处一律以 skill 既有哲学为准，计划让步。

## 对齐审计（初稿 → 修订）

| 初稿问题 | 哲学判据 | 修订 |
|---|---|---|
| P0 落点 = `verify_output.py` | ①③④ 发生在**对白回合**，不进 `scored_results.json`（类别错误） | 改为 `verify_lens.py`（transcript / 回执级） |
| P1-3 运行时无关包 | 与 P0 自相矛盾（重新引入 prompt-only）；绑定运行时是设计取舍非缺陷 | 降级为 optional minor + 强制「无机制保证」标签 |
| P1-4「输出仍过 verify」 | 纯推理无 `scored_results.json`，`verify_output.py` 跑不了 | 改为 prompt 级 lens 自检 |
| P2-3 真实用户 A/B | skill 不承诺求职结果；A/B 混杂噪声且不直接修故障 (B) | 改为产出质量代理评测 |
| 总目标「冲 Excellent 80」 | 哲学不在乎分数 | 重写为 (A)/(B) 驱动 |

## 优先级总览（(A)/(B) 驱动，分数为副作用）

| 优先级 | 项 | (A)/(B) 依据 | Anti-pattern 检查 | 预期分数副作用 |
|---|---|---|---|---|
| **P0** | 软契约机制化（①③④） | (B) M4 证明未硬化 1/4 失效，prompt 漂移→编造是真实故障 | 不钝化灵活性（warning 模式）✅ 不迁运行时✅ | Reliability 13→17~18 |
| **P1** | SKILL.md TL;DR | minor（降冷启动成本） | 无 | Writeup 20→22~23 |
| **P1** | 跨模型 M4 回归 | (A) 提升可靠性证据；(B) 暴露真实风险 | 无 | 可靠性证据升级 |
| **P1** | 轻量模式固化 | (A) 降误用/降成本 | 不拆 skill✅ | Runtime Cost 10→12 |
| **P1** | 持续 eval 门禁 | (A) 防回退 | 无 | 守护型 |
| **minor** | 运行时无关 lite 包 ✅ 已执行（2026-07-21）+ 已打包分发件 `lite/SKILL.md`（2026-07-21）| 分发，但无机制保证 | 不迁运行时（主 skill 不动）✅ | Market Fit 11→12（限 lite） |
| **minor** | 生产盲评采集 enabler ✅ 已执行（2026-07-21）| 让 `--live` 能积累真数据 | 可选+授权、不静默记录✅ | 守护型 |
| **P2** | PII / 安全审查 ✅ 已执行（2026-07-21）| (B) 真实隐私风险 | 无 | 新增保障 |
| **P2** | 维护性 / bus factor ✅ 已执行（2026-07-21）| minor | 无 | 新增保障 |
| **P2** | 产出质量代理评测 ✅ 方法学已落地 + 路径2 合成消融已跑+干净基线重跑+补跑残余 before null（2026-07-21，before 有效 run 3→5→7 全 fail、case12 补齐、case11r2/13r1 已修复，case14 r2 顽固 null 经 8+12 retry 仍空确认；after 仍 3 null 因 agnes 限流）| (A) 代理证据 | 无 | 验证型 |
| **P2** | 自评偏见模板 ✅ 已执行（2026-07-21）| 方法学 | 无 | 方法学 |

---

## P0：软契约机制化（①③④）→ `verify_lens.py`

**问题**：①③④ 目前 prompt 强制；M4 证明未硬化时 3/4 失效；核心是「对白回合」的契约，不进 pipeline JSON。

**方案（修正后）**：新增 `scripts/verify_lens.py`，作用于**对白 transcript / lens 回执**，做确定性、**warning 模式**检查（不硬阻断，保灵活性）：
- 强断言（「高度匹配 / 肯定能过 / 稳了 / 必中 / 够了」）缺 `[推测]/[脑补]/[事实]` 标签 → WARNING。
- 对外简历 / 陈述硬数字缺 `[事实]` 标注 → WARNING。
- Over-Claim：绝对化词 + 无来源集群 → WARNING（**不做正则判「是否真推测」**，那会钝化判断）。
- 数据来源：agent 在对白回合末附机器可读回执 `<!-- lens:{assertions_tagged:true, overclaim_checked:true} -->`，`verify_lens` 校验；或离线扫 transcript。判断仍在 prompt，机制只做可机检的辅助。

**哲学护栏**：默认 WARNING 非阻断；显式暴露（符「隐蔽 fallback 更危险」）；绝不把判断做成正则。

**验收（可运行证据）**：
- 对抗用例（故意生成未标注强断言）→ warning 必触发。✅（`tests/test_verify_lens.py` 10 passed + 对抗 fixture 实跑）
- 弱模型（非 agnes）上跑 M4，通过率不再回退到 1/4。✅ **LLM-REAL 验收达成（2026-07-21）**：nvidia(deepseek-v4-flash) 跨家族 M4 = 4/4（90/100/95/100）；agnes 复跑 3/4（95/100/95/75，case14 跨 run 不稳定，判为已知方差项非回退）。详见 `notes/audit-borrowing-plan.md` 6.8。

**里程碑 M5**：`verify_lens.py` + lens 回执规范 + 对抗用例 + 弱模型回归。

---

## P1：体验与分发（修正）

### 1. SKILL.md 顶部 TL;DR（minor）✅ 已执行（2026-07-21）
- 「权衡声明」与「红线」之间插入「## 30 秒速览（TL;DR）」：一句话闭环定位 + 单岗匹配 3 步走 + 快路径提示。不引入 /命令、不拆 skill。
- 验证：`tests/test_skill_doc_contracts.py::test_skill_has_tldr` 通过（SKILL.md 含 `30 秒速览` + `单岗匹配` + `3 步走`）。详见 `notes/p1-packaging-prd.md` / `p1-packaging-tickets.md`。

### 2. 跨模型 M4 回归（A/B 证据）✅ 已执行（2026-07-21）
- 复用 `run_dynamic_eval.py`，`EVAL_PROVIDER` 切 `agnes` / `nvidia`，同一 4 例 `expected_output`，出各模型通过率表。
- 结果：**agnes 3/4（95/100/95/75）、nvidia 4/4（90/100/95/100）**。换不同模型家族（DeepSeek）仍 4/4，证明软契约硬化已普遍内化、非只跟 agnes 对暗号。
- ⚠️ **agnes case14 跨 run 不稳定**：6.7 同模型同题 95✅、本轮 75❌（Agent 对自报简历下了"能力缺失"确定性终审，被判 over-claim）。判为已知方差项；跟进见 F1（`audit-borrowing-plan.md` 6.8）。

**G 系列跟进项（2026-07-21）**
- **G1（eval 方法论修正）✅ 已执行**：`run_dynamic_eval.py` 的 `JUDGE_SYS` 增「Over-Claim 判定细则」，显式规定带 `[推测]` 标签 + 置信度的概率化估计不算 over-claim。真实 LLM 复跑验证——nvidia case14 ×2 = 95/95 PASS、agnes case14 ×3 = 45/45/45 FAIL（正确捕获确定性终审）。judge 跨 run/跨 provider 一致，旧同句矛盾消除。详见 `audit-borrowing-plan.md` 6.9 G1 段。**并顺带修复 harness 默认模型不回退 provider `default_model` 的 404 缺陷**：`GEN_MODEL/JUDGE_MODEL` 改为 `os.environ.get(...) or PROVIDERS[provider]["default_model"]` + `[cfg]` 回显；`EVAL_PROVIDER=nvidia` 不设模型现自动用 `deepseek-ai/deepseek-v4-flash`，端到端 case14=95 PASS。
- **G2（验收规则）✅ 已执行**：`evals.json` case14 加 `known_variance: true`；`run_dynamic_eval.py` 增 `summary`+`[gate]`——核心用例全过计入硬门槛，known_variance 用例不计入但要求 judge 跨 run 稳定（不稳=eval 故障→FAIL）。验证：`EVAL_PROVIDER=agnes EVAL_REPEAT=2` 全 4 例 → `core=2/3 known_variance: stable=1 → FAIL`（gate 逻辑正确，抓住核心回归）。⚠️ **G2 验证暴露 case13 跨批次不稳定（95↔45，与 case14 同模式）**：P1-2「agnes 3/4、case13 稳过」是单批次快照脆弱结论。→ **A/B 已执行（2026-07-21，见下）**。详见 `audit-borrowing-plan.md` §6.10 / §6.11。
- **A/B（case13 稳生成）✅ 已执行**：A 探针（`evals/judge_ab_probe.py`）确认**非 judge 误伤**——OLD/NEW 同一 FAIL 输出都判挂（主因③熔断前置声明缺失，与 G1 无关）、同一 PASS 输出都判过 → 失败 100% 源于 agnes 生成方差；B 给 `references/resume-guide.md` 熔断段加合规 few-shot（前置声明在前 + 标准 `[事实]/[推测]/[脑补]` 标签）→ agnes 复跑 case13 稳到 **95/95**（45→95）、case11/12 无回归（95/95）、`[gate] core=3/3 → PASS`。harness `run_one` 同步改 `except BaseException` 兜住 agnes 毛刺。详见 `audit-borrowing-plan.md` §6.11。
- **G3（语义护栏）⛔ 不做**：agnes 不稳是模型层，加护栏会钝化灵活性、撞 Anti-pattern。

### 3. 轻量模式固化（修正描述）✅ 已执行（2026-07-21）
- 决策路由表 L117-118 的「纯推理」→「**纯推理（lite 模式）**」，路由段后补一行定义（不跑脚本、prompt 级 lens 自检覆盖、适用单 JD/JD≤5/快速评估）。其余「纯推理」措辞保持（已含 lite 语义）。
- **修正**：纯推理无 `scored_results.json`，`verify_output.py` 跑不了。lite 的「验证」= prompt 级 lens 自检（运行时自检 L205-206 已覆盖），非脚本校验。
- 验证：`tests/test_skill_doc_contracts.py::test_lite_mode_named_in_routing` 通过（SKILL.md 含 `纯推理（lite 模式）`）。

### 4. 持续 eval 门禁 ✅ 已执行（2026-07-21）
- `run_dynamic_eval.py` 抽纯函数 `compute_summary(results)`（G2 规则，可单测），`main()` 末尾 `sys.exit(0 if gate=="PASS" else 1)`；`__main__` 加 `EVAL_SKIP_ON_ERROR=1`（顶层异常改 exit 0，不红 CI）。新建 `Makefile`：`make test` / `make eval`（agnes+repeat=2）/ `make eval-skip`。`tests/test_eval_gate.py` 5 例覆盖 PASS/core-fail/kv-unstable/kv-unverified（SYNTHETIC-MECHANISM，全量 **80 passed**）。
- ⚠️ **诚实发现（fresh LLM-REAL）**：agnes 真跑 gate → `core=1/3 → FAIL`（GATE_EXIT=1，机制正确）；失败源于 **agnes 跨 run 方差**（case11 95/45、case12 None/60、case13 None/95），**非 skill 回归**——自 B-verify（同会话 3/3 PASS）后未改任何影响生成的代码（仅 doc TL;DR/lite + gate 基建）。nvidia 复跑部分稳定（11/12=95-100）但免费端点 503/hang 在 case13 截断，故也非可靠自动门禁。→ **gate 基建正确且已验证，但当前两模型端点都不足以作可靠硬 CI 阻断**：agnes 不稳、nvidia 端点受限。建议：(a) 聚合规则按 agnes 方差调优（stable+majority）后再硬阻断；(b) nvidia 可达时跑 gate；(c) 暂以 advisory/`--skip` 接入。**未擅自弱化 gate 规则（那会粉饰）**。

**里程碑 M6**：TL;DR + 跨模型回归。 **里程碑 M7**：lite 模式固化。 **里程碑 M8**：eval 门禁接入。

---

## minor：运行时无关 lite 包（已降级 + 诚实标签）

- 抽 `SKILL.md` 核心契约 + lens 成 `references/chatgpt-lite.md` 可粘贴段。
- **强制声明**：「此 lite 包**无 verify 机制保证**，契约仅 prompt 强制，弱模型可能失效；且缺失 fetch_jobs / verify_output 等能力」。不计入冲分主路径，避免与 P0 自相矛盾。
  - **✅ 已执行（2026-07-21 收尾）**：新建 `references/chatgpt-lite.md`（4 契约 + lens 不分回合 + 红线 + 强制「无机制保证」声明），纯文档零 API、零 scripts 依赖；TDD 落地 `tests/test_skill_doc_contracts.py` +3 测试（文件存在 / 含『无机制保证』/ 含 4 契约关键词）全绿，全量 **83 passed** 无回归；`FILE_GUIDE.md` references 段加条目 + bus factor 表 11→12。Scope Drift=CLEAN（未动主 SKILL.md、未加命令、未接运行时）。PRD/Tickets：`notes/lite-package-prd.md` / `notes/lite-package-tickets.md`。

---

## minor：生产盲评采集 enabler（已执行 2026-07-21）

- **动机**：P2-3 路径1 盲评的 `--live` 代码早已完整，但仓库**无生产真实用户 transcript**，故之前只能「用 eval 真输出演练跑通」、算不出 before/after Δ。要让 `--live` 真正积累真数据，缺的不是 judge，而是**可程序化采集入口**。
- **方案**：给 `evals/collect_transcript.py` 增 importable 的 `collect_session(turns,*,phase,before_or_after,model,session_id,redact,out_root)`，返回 `(out_path, record, n_redacted)`；CLI `main()` 重构复用之并加 `--out-root`（测试/重定向）。`evals/transcripts/` 已被 `.gitignore` 排除，落盘不进版本库。
- **SKILL.md 接线**：session-end 增 `[Rec] 评估数据采集（可选 / 需用户显式授权）` 子项——整理本轮对话 turns → 调 `collect_transcript.py`（默认 `after` + 脱敏）；诚实边界写明「可选 + 授权、无 hook 时由用户/运营导出 JSONL 后调用、不授权不采集」。
- **验收（可运行证据）**：TDD `tests/test_collect_transcript.py` 7 测试（落盘+脱敏+非法 phase/boa/空 turns+CLI 复用 collect_session）全绿；`tests/test_skill_doc_contracts.py` 增 4 测试守卫 `lite/SKILL.md` 分发件（存在/frontmatter/无机制保证/4 契约）全绿。全量 **94→105 passed** 无回归。
- **enabler → --live 端到端已实跑（2026-07-22）**：8 条真实 LLM 输出（agnes/nvidia 各 4，eval_results_dynamic*.json 的 after 组）经 `collect_session()` 程序化落盘 `evals/transcripts/<phase>/after/`，再 `uv run --with openai python evals/blind_eval_runner.py --live` 真实盲评 → 结果 **7×12/12 + 1×6/12**（agnes_12 resume D4=0 改稿熔断缺失）；**judge 与上次演练完全一致（agnes_12 仍 6/12）、可复现**，证明 judge 非橡皮图章。报告 `evals/proxy-quality-eval-report.md`（EVIDENCE_TIER=LLM-REAL）增「采集方式（enabler）」段；`blind_eval_runner.py` 顺手修 D5 显示 bug（resume 且 judge 返 null 时打印 `None`→`-`）。全量 105 passed 无回归。
- **诚实局限（不变）**：enabler 让生产数据**可积累**，但可信 before/after Δ 仍待每 phase ≥10 before+10 after 真实 transcript 落地后重跑 `--live`。

---

## P2：盲区补全（修正）

1. **PII / 安全审查（B）✅ 已执行（2026-07-21）**：对照 SKILL.md L29「不泄露隐私」红线，审简历处理链路、`.env` 管理、verify 输出是否含 PII，出 `notes/security-checklist.md`（含 6 域审计 + 风险矩阵 + 2 项整改落地：career_log.py 补 email 正则、.gitignore 加 eval results 排除）。
2. **维护性 / bus factor ✅ 已执行（2026-07-21）**：采用集中「维护信息（bus factor 视图）」表（优于 25 行散落）——覆盖 6 根目录文件 + 14 scripts + 11 references，含 owner / 更新节律 / 复杂度 / 最后核实 四列；honest 标注单维护者（bus factor=1）+ 降低 bus factor 三条待办。注：实际 scripts=14（plan 写 13，含 verify_lens.py）、references=11 中 5 个此前未进 FILE_GUIDE，现已一并纳入。
3. **产出质量代理评测（A，修正自 A/B）✅ 方法学已落地（2026-07-21）**：`notes/proxy-quality-eval-protocol.md` 固化动机 + transcript schema（脱敏/标签/落盘位置）+ 盲评维度 D1-D6 rubric + 执行流程（LLM-judge 复用 JUDGE_SYS、屏蔽 before/after 标签）+ API 密钥复用现有 .env + 与 evals.json 互补定位 + 数据到位后待办。**数据半（真实 transcript）待生产环境积累后跑**，零 API 先闭环方法学一半。
  - **路径2 合成提示消融已跑（2026-07-21，agnes repeat=2）+ 干净基线重跑（同日晚）**：`evals/run_ablation.py` 本地 `run_one`（带生成空/异常重试 `EVAL_NULL_RETRIES` + 退避），复用 `run_dynamic_eval` 的 `JUDGE_SYS`/`SYSTEM_REFS`，对 4 个 contract_adherence 用例分别用 `after`(SKILL.md+3 references) 与 `before`(裸顾问、移除 4 契约) 两套 system 跑同 judge，隔离契约指令因果贡献。首跑（21:43）before 基线被 5/8 生成失败污染 → 干净基线重跑：分块前台（沙箱前台 ~5min 上限，拆 11-12/13-14 合并）+ null_retries=5 + 退避。**重跑后结果：after_overall=0.625 vs before_overall=0.0（case 平均）；before 有效 run 从 3→5→7 且全部 fail（0/7）→ 0.0 更稳健，污染大降；case12 before 从整组缺失变 40/45 双有效 fail（② 单源红线现可对比）；before 经第三次补跑（null_retries=8）后仅 case14 r2 残余 1 个 null（共 7/8 有效），after 仍 3 个 null（首跑遗留未重滚）因当前 agnes 限流重于 21:43 首跑**。逐契约：① ③ 强因果（裸顾问有效 run 全 fail → 硬化通过）、② 强因果且现可对比、④ Over-Claim(known_variance) 两版均 fail=agnes 生成侧 miss 未因契约救回。结论：本跑为 M4/P1-2 之外的**因果隔离补充证据**（同一模型去掉指令就不做契约行为，证明合规靠契约指令非模型天赋），但非真实用户代理、增量有限、且 before 基线经第三跑补跑后仅 case14 r2 残余 1 个 null（8 次重试仍空，顽固），11r2/13r1 已修复，before 现 7 有效 run 全 fail、0.0 极稳健。第四跑再加 12 retry 针对 case14 r2 仍全空，确认顽固毛刺（非未烧够 API）。报告见 `notes/before_after_contrast_report.md`。
4. **自评偏见模板 ✅ 已执行（2026-07-21）**：`notes/self-eval-bias-template.md`（自评元信息 + 独立性声明 3 问 + 偏差自检表 B1-B7 + 强制承诺 + 使用约定），未来自评类报告顶部强制包含。与 `notes/addition-criteria.md` 同源，方法学护栏不新增运行时负担。
5. **P2-3 路径1 盲评脚手架 ✅ 已执行（2026-07-22）**：按 `scholar-dev-process`（Grill→To-Spec→To-Tickets→TDD→Review→Ship）落地 3 文件——`evals/proxy_eval_lib.py`（纯函数 redact_text/build_record/mask_label/aggregate_score，复用 career_log.SENSITIVE_PATTERNS）、`evals/collect_transcript.py`（CLI 脱敏+标签落盘 `evals/transcripts/<phase>/<before|after>/`）、`evals/blind_eval_runner.py`（CLI：`--demo` 内置合成 transcript+stub judge 证明整条 pipeline 接线、**不烧 API、EVIDENCE_TIER=SYNTHETIC-MECHANISM、报告顶部填 self-eval-bias-template、mask_label 防 B2**；`--live` 真实路径代码完整但需生产 transcript+key，数据到位后跑、EVIDENCE_TIER=LLM-REAL）。TDD：`tests/test_proxy_eval.py` 11 测试 red→green；全量 94 passed（83→94，无回归）。**顺带修隐私洞**：career_log.SENSITIVE_PATTERNS 手机/身份证原用 `\b\d{11}\b`，CJK 相邻无词边界会漏脱敏 → 改为 `(?<!\d)\d{11}(?!\d)`（CJK 相邻也匹配，严格更安全，无回归）。**真实跑分（--live）已用现有 eval 真输出演练跑通**（见下条附记）；生产环境真实用户 transcript 仍待积累（每 phase ≥10 before+10 after）后重跑 `--live` 方得可信 before/after Δ。另：BOOTSTRAP 身份设定——仓库无独立 BOOTSTRAP/USER.md，但 SKILL.md 已有 session-start bootstrap；于是在 SKILL.md 加 `## 身份设定（你是谁）` 段声明角色边界、并要求与 `references/chatgpt-lite.md`「你是谁」口径同步（防主 skill 与 lite 身份漂移），FILE_GUIDE 同步加指针。
  - **--live 演练已跑通（2026-07-22）**：用仓库已有 `eval_results_dynamic*.json` 的 **after 组真实 LLM 输出**（nvidia:deepseek-v4-flash + agnes-2.0-flash）造 8 条 transcript，经 `uv run --with openai python evals/blind_eval_runner.py --live` 真实盲评（按用户「q-0 用已有 eval 真输出跑 --live 演练」裁决）。过程中修 3 个真 bug：① 托管 Python 缺 `openai` 依赖 → `ImportError` 被 `_eval_one` 吞掉导致全 0，已加清晰报错（提示 `uv run --with openai`）；② `JUDGE_SYS_PROXY` 示例 schema 含畸形 JSON（`"D5":null或0-2`）→ agnes 返空 → 改为合法 JSON 示例；③ `aggregate_score` 遇 `None`（judge 返 `D5:null`）崩溃 → 改 `int(scores.get(d) or 0)`。另：根治 `llm_client`「import 时快照 env、晚于 import 才注入 .env 致 key 丢失」脆弱点——给 `LLMClient.__init__` 加 `api_key`/`base_url` 显式覆盖参数；`_judge_all` 改整批单事件循环 + 空响应重试（`EVAL_NULL_RETRIES` 默认 6，克制 agnes 限流空 200）。结果：8 条 after 中 7 条 12/12、1 条（agnes_2.0_flash_12 resume）判 6/12（D4 改稿熔断缺失=0、D1/D6 部分），证明 judge 确有区分度、**非橡皮图章**；报告 `evals/proxy-quality-eval-report.md`（EVIDENCE_TIER=LLM-REAL）补「数据来源与边界（演练声明）」段，明示：数据源=eval after 组真输出（非生产真实用户对话）、无 before 组故无 Δ、judge 同源、样本小。证据层级：LLM-REAL。**诚实局限**：本演练仅证明 `--live` 链路在真实 LLM 输出上跑通并产出 D1-D6 分数，不构成 before/after 质量结论；生产 transcript 积累后（每 phase ≥10 before+10 after）重跑 `--live` 方得可信 Δ。**采集入口已就绪**：`collect_transcript.collect_session()` 可程序化落盘 + SKILL.md session-end 可选授权协议（见下「minor：生产盲评采集 enabler」），数据现在可本地积累。

---

## 执行顺序建议

```
M5 (P0 机制化) → M6 (TL;DR + 跨模型) → M7 (lite 模式) → M8 (eval 门禁)
                                 ↘ P2 盲区随 M6–M8 并行
```

- **不要**先搞分发（minor lite 包）而跳过 P0：机制化是 honesty-first 产品的地基，跳过它去优化分发属于「在不可靠之上盖楼」。
- 每个里程碑用**可运行证据**收口（测试通过 / 跨模型报告 / 文档 PR），不靠描述性结论。

## 验收总判（重述为哲学语言）

- P0 完成 → 修复真实认知故障 (B)，跨模型可靠性证据 (A) 升级；Reliability 13→17~18。
- P0+P1 完成 → 可靠性 + 体验 + 分发齐备；若跨模型实证不回退，总分约 80（**但这是副作用，不是目标**）。
- P2 完成 → 补隐私 / 维护 / 代理验证盲区，使「可靠」对外可信（非仅作者自评）。

---

## 全量 bug review 修复记录（2026-07-22，用户拍板「除 P1 外全修，最高标准」）

扫读 eval 脚手架 + enabler + lite + scripts + 主文档后，按 scholar-dev-process Review→Implement 落地：

- **P3 ✅ SKILL.md「绝对不要」段重复编号 3.**：L175/L178 同为 3，后续 4/5 错位；已顺延为 3/4/5/6（连续编号）。
- **P4 ✅ blind_eval_runner._load_provider_env 硬编码绝对路径**：scholar .env 默认位置改可由环境变量 `SCHOLAR_DOTENV` 覆盖，保留原开发机路径作 fallback（向后兼容、非破坏）。生产/CI 用 `SCHOLAR_DOTENV` 指定即可，不再绑死机器。
- **P2 ✅ 测试 test_redact_text_masks_api_key_phrase 假绿修复**：原只断言整串不在输出（sk- 只遮首字符时仍通过）。新增两条强化断言（sk- 前缀、bc123DEF456 后缀均不应残留），**现在会正确 FAIL 暴露 P1 泄露**——最高标准（诚实失败优于假绿）。
- **ℹ️ career_log.SENSITIVE_PATTERNS 已知局限文档化**：新增注释说明 (1) sk- 只遮首字符（P1 待修）、(2) 关键词类只遮词不遮值（Bearer token 整串泄露）；标注本表是 defense-in-depth 非硬保证，强保证需值捕获正则或外部 DLP。
- **P1 ✅（sk- 脱敏泄露）已修**：用户拍板后翻掉。SENSITIVE_PATTERNS 正则 `sk-[A-Za-z0-9]` → `sk-[A-Za-z0-9_-]+`（含 `sk-proj-…`/`sk-ant-…` 带 dash 格式，整串遮）。实证 `sk-abc…`/`sk-proj-…`/`sk-ant-…` 均整串遮为 `***`；全量 **105 passed** 全绿（P2 强化测试随之转绿）。

全部未 commit（延续"暂不 commit"）。

> **📌 当前全量测试状态（2026-07-22 neat-freak 复查锚定）**：上文 P1–P4 review 完成时的快照为 **105 passed**；此后同日的 `bug-review-2026-07-21`（M1–M4 + m5–m9，+24 测试）已落地，故**截至 2026-07-22 实际全量 = 129 passed**（基线 105 → +24）。本文档内其他历史快照（80 / 83 / 94 / 105）均为对应改动当日的计数，非当前总数。
