<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# Career Copilot 安全审查清单

> 审查日期：2026-07-21 | 审查方法：全量代码走查（scripts/ + .env/.gitignore + 记忆系统 + LLM 链路） | 范围：PII/安全审查（P2-1）

## 1. API 密钥管理

| 检查项 | 状态 | 证据 |
|--------|------|------|
| `.env` 已 gitignore | ✅ | `.gitignore:1` `# 环境变量（含 API Key）` + `.env` |
| `.env.example` 仅占位符 | ✅ | 全部值为 `your-xxx-here` / 空字符串 |
| `llm_client.py` 从环境变量读 key | ✅ | `os.environ.get("XXX_API_KEY", "")` — 模块级变量，不落地磁盘 |
| `run_dynamic_eval.py` 从环境变量读 key | ✅ | 同样 `os.environ.get` 模式 |
| `check_env.py` 校验连通性 | ✅ | 仅尝试简单 completion 调用，不显式暴露 key 值 |
| key 不打印到 stdout/stderr | ⚠️ LOW | `llm_client.py:168-169` 重试时 `print(f"{type(e).__name__}: {e}")` 打印异常对象；标准 OpenAI SDK 异常消息不含 API key。**实测确认**：无泄露 |

**结论**：API 密钥管理无缺陷。`.env` 全链 gitignored，代码只读环境变量不落地。

---

## 2. 简历数据处理链路（gen_profile.py → smart_score.py）

**gen_profile.py**：

| 检查项 | 状态 | 证据 / 说明 |
|--------|------|-------------|
| 简历全文发往外部 LLM | ⚠️ DOCUMENTED | L220-225: `client.chat(user=f"以下是候选人的简历：\n\n{resume_text}")` → 完整简历文本（含姓名/学校/公司/项目详情）发送到用户选择的 provider |
| 文本长度截断 | ✅ | L217-218: 超过 6000 字截断 |
| candidate_summary.txt 同样发 LLM | ⚠️ DOCUMENTED | L262-267: generate_summary 也发简历全文 |
| 输出文件 gitignored | ✅ | `boundary_profile.json` + `candidate_summary.txt` 在 `.gitignore` |

**smart_score.py（及 pre_filter / post_judge）**：

| 检查项 | 状态 | 说明 |
|--------|------|------|
| profile 数据发给 LLM | ⚠️ DOCUMENTED | Stage 1 粗筛传 candidate_summary.txt；Stage 2 精排传完整 boundary_profile.json |
| JD 数据发给 LLM | ✅ | JD 是公开信息，不属 PII |
| scored_results.json gitignored | ✅ | `.gitignore` 包含 |

**LLM 传输隐私的核心权衡**：

> gen_profile.py 必须把简历全文发送到 LLM 才能生成结构化 profile。这是产品设计上的固有权衡，不是 bug。
>
> 风险由 provider 选择决定：
> - **friday（内部平台）** → 数据不出企业内部网络，风险最低
> - **agnes / nvidia / sub2api（外部 provider）** → 简历数据传至第三方服务器
>
> SKILL.md L29 的隐私承诺侧重记忆系统（"禁止记录……到记忆系统"），未覆盖 LLM 传输阶段。**建议在 SKILL.md 或文档中显式声明此权衡**，让用户知情选择 provider。

---

## 3. 记忆系统（career_log.py + career-profile.md）

### career_log.py 敏感信息防御

| 检查项 | 状态 | 模式 / 说明 |
|--------|------|------------|
| 手机号检测 | ✅ | `\b\d{11}\b` |
| 身份证检测 | ✅ | `\b\d{17}[0-9Xx]\b` |
| API key / secret / token / password / bearer / sk-xxx | ✅ | 大小写不敏感，含 `sk-[A-Za-z0-9]` |
| 常见敏感词（身份证/手机号/住址/银行卡/密码/密钥/验证码/cookie） | ✅ | 大小写不敏感 |
| 写入前强制调用 check_sensitive | ✅ | `cmd_append()` L226，违反则 `raise ValueError` |
| 数据体量限制 | ✅ | `MAX_DATA_CHARS=5000` |
| 遗忘机制 | ✅ | `cmd_forget()` 需 `--confirm` 标志 |
| 存储位置 | ✅ | `~/.catpaw/career-copilot/` — 本地磁盘，不在 git 仓库内 |
| **email 地址检测** | ❌ MISSING | `SENSITIVE_PATTERNS` 不含 email 正则（`\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b`）— 简历中 email 极为常见 → **建议立即补充** |
| 中文姓名检测 | ⚠️ KNOWN LIMIT | 中文姓名无法用正则可靠检测（无特征 pattern），属已知局限 |

### career-profile.md 自动生成

| 检查项 | 状态 |
|--------|------|
| 从事件日志聚合生成，不含原始简历文本 | ✅ |
| 仅含结构化统计（角色/方向/公司/优势/待提升/洞察） | ✅ |

---

## 4. 输出文件与版本控制

| 文件 | git 状态 | PII 风险 | 说明 |
|------|---------|---------|------|
| `.env` | gitignored ✅ | 密钥 | 最高优先级排除 |
| `boundary_profile.json` | gitignored ✅ | 含学校/专业/雇主名 | 结构化画像，无姓名/电话/email |
| `candidate_summary.txt` | gitignored ✅ | 含教育/经历的压缩文本 | 可能残留姓名 |
| `scored_results.json` | gitignored ✅ | 仅含岗位评分，无简历数据 | |
| `report.html` | gitignored ✅ | 仅含岗位卡片 | |
| `jobs_raw.txt` | gitignored ✅ | JD 原文 | JD 是公开信息 |
| `career-log.jsonl` | 不在 git 仓库 ✅ | 含面试结果/公司名 | 在 `~/.catpaw/` 外 |
| `career-profile.md` | 不在 git 仓库 ✅ | 含方向/公司/优劣势 | 在 `~/.catpaw/` 外 |
| **eval_results_dynamic*.json** | **未 gitignored** ⚠️ | 低（stub 数据） | 含 LLM 生成的摘要与评分。当前 11 个文件均为 stub（假简历），无泄露风险。**但规则缺失**：若未来用真实简历跑 eval → JSON 残留 git 跟踪 → **建议 .gitignore 加 `evals/eval_results_dynamic*.json`** |

---

## 5. 隐私承诺对照（SKILL.md L29）

SKILL.md 红线："不泄露隐私：禁止记录具体薪资数字、面试官真名、身份证号、完整 JD 原文到记忆系统。"

| 承诺项 | 代码级防御 | prompt 级防御 | 状态 |
|-------|-----------|-------------|------|
| 具体薪资数字 | ❌ 无 regex | ✅ SKILL.md HARD 红线，Agent 强制遵守 | ⚠️ LOW（纯软约束） |
| 面试官真名 | ❌ 无 regex | ✅ 同上 | ⚠️ LOW（纯软约束） |
| 身份证号 | ✅ career_log.py regex | ✅ | ✅ PASS（硬防御） |
| 完整 JD 原文 | ❌ 无 regex；MAX_DATA_CHARS=5000 可容纳 | ✅ 同上 | ⚠️ LOW（纯软约束） |

**结论**：4 项隐私承诺中，仅「身份证号」有代码级硬防御；其余 3 项依赖 Agent 遵守 SKILL.md（prompt 级软强制）。这与 skill 设计哲学一致（软路由优先于硬化命令），但安全评估中应标注为**已知残余风险**。

---

## 6. 整体风险矩阵

| # | 风险 | 等级 | 影响 | 可被利用 | 整改 |
|---|------|------|------|---------|------|
| R1 | 简历文本发送至外部 LLM provider | MEDIUM | 第三方可见简历全文（姓名/学校/公司/项目） | 取决于 provider 的数据处理政策 | 文档声明 + 推荐内部 provider |
| R2 | career_log.py 缺 email 检测 | MEDIUM | 用户可能在 memory 中误存 email | 低（需 agent 违反 HARD 红线 + log 未拒绝） | **补 1 行 email 正则** |
| R3 | 薪资/姓名/面试官真名仅 prompt 级防御 | LOW | 若 agent 违反红线 → 记忆被污染 | 低（HARD 红线是 agent 最高约束） | 暂缓（与软路由哲学一致；需硬化用 verify_lens） |
| R4 | eval results 未 gitignored | LOW | 若用真实数据跑 eval → git 跟踪 | 极低（当前全是 stub） | **.gitignore 补 1 行规则** |
| R5 | llm_client.py 错误日志理论上可能暴露 URL | LOW | 异常对象打印到 stderr | 极低（OpenAI SDK 不暴露 key 在异常消息中） | 监控，无需改动 |
| R6 | 记忆文件无加密 at rest | INFO | 本地磁盘文件但明文存储 | 极小（需物理/远程访问本机） | 不属 PII 审计范围 |

---

## 7. 推荐整改（按优先级）

| 优先级 | 项 | 工程量 | 理由 |
|--------|-----|--------|------|
| **P1** | `career_log.py` `SENSITIVE_PATTERNS` 补 email 正则 | 1 行 | 简历中 email 极为常见且高度可识别；正则精确可靠 |
| **P2** | `.gitignore` 加 `evals/eval_results_dynamic*.json` | 1 行 | 当前 stub 数据无害，但规则缺失可能未来引入真实数据 |
| P2 | 文档：LLM 传输简历隐私声明（SKILL.md 或本文档） | ~3 行 Markdown | 让用户知情选择 provider；非安全补丁，属透明度改进 |
| P3 | 薪资/姓名/JD 原文 → 代码级兜底 | 设计级改动（verify_lens 新增检查项或 career_log 加 regex） | 与软路由哲学冲突；当前 HARD 红线 + verify_lens(W1/W2/W3) 已有间接覆盖；需求驱动时再硬化 |
| INFO | 记忆文件 at-rest 加密 | 架构级改动 | 超范围（需加密库 + 密钥管理）；对桌面端应用非必要 |

---

## 8. 审计结论

**总体评级：LOW RISK（低风险）**

- API 密钥管理无缺陷（`.env` 全链 gitignored）。
- 记忆系统有敏感信息扫描（手机/身份证/key）+ 写入前拦截 + 遗忘机制，缺一项 email 检测（P1，1 行可修）。
- 简历发送到 LLM 是产品固有权衡（非 bug），建议在文档中声明。
- 隐私承诺的软约束（prompt 级防御）与 skill「软路由优先于硬化命令」的哲学一致，代码级兜底已覆盖最可机检的项（身份证号），**已知残余风险可接受**。
- 无 P0 级安全缺陷。
