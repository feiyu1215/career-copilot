<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# 产出质量代理评测协议（Proxy Quality Eval Protocol）

> **用途**：为 P2-3「产出质量代理评测」提供**可执行的评测方法学**。本文件先固化「动机 + 数据格式 + 盲评 rubric + 执行流程」，待生产环境积累真实用户 transcript 后即可直接套用跑，无需重新设计。
>
> **哲学依据**：(A) 提供「产出质量」的独立代理证据（补 `self-eval-bias-template` B1 三重同源缺陷）；(B) 修复「只靠作者自评证明可靠」的高概率偏差故障。
>
> **隐私红线**：不碰真实 offer 数据；transcript 收集时脱敏（去姓名/电话/email/薪资，复用 P2-1 的 `career_log.py` SENSITIVE_PATTERNS 思路）。
>
> **当前状态**：✅ 方法学已落地（本文）；⏸ 真实数据收集 + 盲评跑分 = 待生产环境积累 transcript 后执行（见第七节）。

---

## 一、为什么需要代理评测（动机）

- `skilllens_deep_review.md` 是**三重同源零独立**（自评人 = 作者 = 出题人 = 阅卷人），其「可靠」结论对外可信度有限（self-eval-bias-template B1）。
- M4 动态回归是「自己出题、自己阅卷」，证明的是「该模型（agnes-2.0-flash）能 follow 本 skill」，**≠ 跨模型 / 跨时间可靠**。
- 产出质量代理评测 = 用**真实用户 transcript** + **盲评**（人类专家 或 LLM-as-judge）量化 before/after 的契约遵循度与简历质量，作为 (A) 的独立代理证据，不依赖作者自评。

**与现有 eval 的关系（互补，不重复）**：

| 评测 | 数据 | 证明什么 | 状态 |
|------|------|---------|------|
| `evals.json` + `run_dynamic_eval.py` | 合成 / minimal 输入 | 契约可被机器验（机制验证） | ✅ 已建 |
| **本协议（代理评测）** | 真实用户 transcript | 真实产出质量确实提升（外部证据） | ⏸ 方法学已定，数据待积 |

---

## 二、数据格式（transcript schema）

真实用户 transcript = 一次真实会话中 user / agent 的完整对白。收集时按 JSONL 落盘（格式与 P0 `verify_lens.py` 输入一致，可直接复用其 WARNING 检查）：

```jsonl
{"role":"user","text":"..."}
{"role":"agent","text":"..."}
```

**收集要求**：

- **来源**：生产运行（CatDesk / OpenClaw skill 真实使用），**非合成**。
- **脱敏**：写入前过 `career_log.py` 的 `SENSITIVE_PATTERNS`（手机 / 身份证 / email / key），并人工确认无姓名 / 薪资数字。
- **标签**：每条 transcript 附元数据——`session_id` + `phase`（匹配 / 面试 / 简历 / 记忆）+ `before_or_after`（契约硬化前 / 后）+ `model`（实际用的 provider/model）。
- **数量目标**：每 phase ≥ 10 条 before + 10 条 after（小样本即可显趋势；不求大样本）。
- **落盘位置**：`evals/transcripts/<phase>/<before|after>/*.jsonl`（已确认 `evals/eval_results_dynamic*.json` 被 `.gitignore` 排除，transcript 同理不入库，防 PII 泄露）。

---

## 三、盲评维度与 rubric

盲评者（人类专家 或 LLM-as-judge）对每条 transcript 按以下维度打分，**不看 before/after 标签**（防确认偏差 B2）：

| 维度 | 定义 | 评分(0–2) | 对应契约 |
|------|------|----------|---------|
| D1 前提来源标注 | 强断言 / 结论是否带 `[事实]`/`[推测]`/`[脑补]` | 0=全缺 1=部分 2=全带 | ①③④ |
| D2 单源红线 | 对外简历硬数字是否标 `[事实]`、未引入未复现数字 | 0=违例 1=有但弱 2=合规 | resume-guide 单源红线 |
| D3 Over-Claim 镜面 | 是否有绝对化保证 / 对自报简历下确定性终审 | 0=有违例 1=有但克制 2=无违例 | Over-Claim 四陷阱 |
| D4 改稿熔断 | 高改写场景是否前置声明熔断策略（锁 hash / >60% 暂停） | 0=无 1=部分 2=完整前置 | resume-guide 安全护栏 |
| D5 简历质量 | 改后简历的表述精度 / 量化 / ATS 适配（**仅简历 phase**） | 0=低 1=中 2=高 | resume-guide STAR |
| D6 可证伪结构 | 是否给「你具备 X、缺口 Z、置信度」而非空泛延后 | 0=无 1=部分 2=完整 | lens 不分回合 |

**聚合**：每条 transcript 得 0–12 分（D1–D4、D6 各 0–2；D5 仅在简历 phase 计入并归一到 0–12）。phase 内 before 均值 vs after 均值 → 计算 Δ 与趋势。

---

## 四、执行流程

1. **收集**：按第二节落盘真实 transcript（脱敏 + 标签）。
2. **盲评**：专家 或 LLM-judge 按 rubric 打分（**严格屏蔽 before/after 标签**）。
   - LLM-judge 复用 `run_dynamic_eval.py` 的 `JUDGE_SYS` 思路（含「Over-Claim 判定细则」），但 prompt 改为「按 D1–D6 逐项打 0–2」；**judge 用与生成侧不同的 provider** 以降低同源（仍非完全独立，须在报告声明）。
3. **聚合**：before 均值 vs after 均值，算 Δ + 趋势方向。
4. **报告**：出 `evals/proxy-quality-eval-report.md`，**顶部必须填 `self-eval-bias-template` 的独立性声明 + 偏差自检**（B1 必须标「judge 与生成可能同源」）。

---

## 五、API 与密钥

- **生成侧**：用户生产运行时的 provider（agnes / nvidia / friday）——不归本评测管，评测只消费已落盘的 transcript。
- **judge 侧**：复用现有 `.env`——`career-copilot-copy/.env`（NVIDIA key）或 `scholar-agent-public.working-20260707/.env`（Agnes key）；脚本内 `os.environ.get` 读取，不落盘。
- 不新增密钥；沿用现有 `.gitignore` 排除规则（transcript / eval_results 均不入库）。

---

## 六、与现有评测体系的定位

- `evals/evals.json` + `run_dynamic_eval.py` = **合成 / minimal 输入的契约回归**（机制验证，SYNTHETIC→LLM-REAL）。
- 本协议 = **真实 transcript 的质量代理**（外部证据，LLM-REAL）。
- 二者互补：前者证明「契约可被机器验」，后者证明「真实产出质量确实提升」。缺任一都不足以对外宣称「可靠」。

---

## 七、待办（数据到位后执行）

- [ ] 收集 ≥10 before + ≥10 after transcript / phase（生产环境积累）
- [ ] 跑盲评（专家 或 LLM-judge，屏蔽 before/after 标签）
- [ ] 出 `evals/proxy-quality-eval-report.md`（含 `self-eval-bias-template` 头部）
- [ ] 把 Δ 并入 `skilllens_deep_review.md` 的分数副作用证据
- [ ] 若 judge 与生成同源 → 在报告 B1 显式标注，结论降级为「代理证据」而非「独立验证」
