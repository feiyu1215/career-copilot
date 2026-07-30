# 建档引导流程（Setup Guide）

> 对应意图路由：**建档**（触发词：帮我建档 / 第一次用 / 初始化 / setup）。
> 目的：让一个新用户从零在 5 步内产出**可用的 profile**，从而能跑通后续的抓取 → 评分 → 生成链路。
> 执行引擎：`scripts/setup_wizard.py`（本流程是它对 agent 的结构化引导说明）。

## 何时走建档（而非引导/规划）

- 用户**已经能说出**「我要投 XX 方向 / 这是我的简历」→ 走建档（执行动作）。
- 用户连方向都模糊（「我不知道投什么」）→ 走**引导/规划**，不要强行建档。
- 已有 `boundary_profile.json` → 直接 `--profile-json ... --skip-profile` 复用，不必重新生成。

## 6 步引导流程

### Step 1 — 询问求职方向
确认方向锚点，取值之一：`应届` / `社招` / `实习` / `转型`。
- 用户已说 → 直接采用。
- 未说 → 用带默认（`社招`）的问题确认，**不要预设**。
- 落点：`setup_wizard.py --direction <方向>`。

### Step 2 — 收集简历
三种来源，按优先级：
1. 简历文件：`--resume path.pdf`（gen_profile 支持 .pdf/.txt）。
2. 粘贴文本：`--resume-text "..."`（向导写入临时文件再喂给 gen_profile）。
3. 口述经历：交互模式下让用户直接粘贴多行经历文本，同样走临时文件。
- 非交互模式**必须**提供 `--resume` 或 `--resume-text`，否则报错（不臆造简历）。

### Step 3 — 生成 profile
调用 `gen_profile.py`（`scripts/setup_wizard.py` 内部通过 `generate_profile` + `generate_summary`）：
- 产出 `boundary_profile.json`（结构化画像：技能/经历/方向锚点/硬性约束）。
- 产出 `candidate_summary.txt`（自然语言摘要，供用户快速核对）。
- 这一步**需要 LLM + 网络**（走 `OPENAI_*` 或 `LLM_PROVIDER` 配置）。

### Step 4 — 展示并确认方向锚点
打印 `candidate_summary.txt` 给用户，确认方向锚点是否准确：
- 确认 → 继续。
- 不准确 → 让用户手动编辑 `boundary_profile.json`（向导不强行改写，避免覆盖 LLM 判断）。
- 非交互 / `--yes` 模式默认视为确认。

### Step 5 — 询问目标 portal 偏好，写入 portals.yaml
问用户要抓哪些门户（如 `boss,linkedin,shixiseng`）：
- 落点：`--portals boss,linkedin`，向导**外科手术式**修改 `config/portals.yaml` 的 `enabled` 开关（保留注释与格式）。
- 默认只**启用**列出的门户，未列出的保持原状（不 clobber）。
- 加 `--disable-others` 时，未列出的门户一律置 `enabled: false`。
- 用户留空 → 不改 `portals.yaml`，沿用现有默认。

### Step 6 — 跑一次环境自检
执行 `scripts/check_env.py`，确认：
- LLM 环境变量 / 包 / 网关连通性（建档与评分的前提）。
- **LaTeX 引擎**（lualatex/xelatex/pdflatex，编译 PDF 硬依赖）+ **python-docx**（DOCX 降级路径）。
- 有任何 ✗ → 展示修复建议；非交互模式不阻断建档（profile 已产出），但应提示用户先修环境再跑后续链路。

### Step 7（可选）— 开启竞争力闭环

若想让「记录面试结果」自动驱动竞争力重评并在周报展示，设一个环境变量指向竞争力快照库：

```bash
# 例如在 ~/.bashrc / profile 中加入（路径自定，需持久存在）
export CAREER_COMPETITIVENESS_STORE="$HOME/.catpaw/career-copilot/competitiveness-store.json"
```

- 设好后，任何 `career_log.py append --type interview_done` 都会自动重评竞争力（写入该 store）。
- 跑 `run_pipeline.py` / `generate_report.py` 时，若给 `--competitiveness-store`（或已设上述环境变量）即自动渲染「竞争力动态评估」段；再加 `--competitiveness-provider agnes`（或 `LLM_PROVIDER=agnes`）即叠加 agnes 教练式叙述。
- 字段模板与示例见 `references/interview-done-template.md`。

## 验收标准（来自升级计划）

- 新用户说「帮我建档」，agent 按本流程引导，**5 步内**产出可用的 `boundary_profile.json` + `candidate_summary.txt`。
- `check_env.py` 输出清晰的环境状态表（每项依赖 ✓/✗）。

## 快速命令

```bash
# 最常见：有简历文件 + 明确方向 + 指定门户
python scripts/setup_wizard.py --resume my_resume.pdf --direction 社招 --portals boss,linkedin --yes

# 无文件，直接粘贴文本
python scripts/setup_wizard.py --resume-text "$(cat resume.txt)" --direction 实习 --yes

# 复用已有 profile，只改 portal 偏好
python scripts/setup_wizard.py --profile-json data/boundary_profile.json --skip-profile --portals boss,shixiseng --yes
```
