# Career Copilot

> AI Agent Skill：求职全链路智能助手，为 [CatDesk](https://github.com/nicepkg/catpaw) or Openclaw 设计。

Career Copilot 是一个结构化的 AI Agent Skill，覆盖求职过程中的**岗位匹配 → 简历优化 → 面试准备 → 职业记忆**完整闭环。

## 核心能力

**岗位智能匹配**：六阶段评分 pipeline（粗筛 → 校准 → 精排 → 重排 → 后处理 → 验证），从数百个 JD 中精准筛选最匹配的岗位，输出 A/B/C 三档推荐。

**简历定向优化**：基于匹配结果中的 risks 逆向优化简历——区分"表述问题"和"能力缺失"，给出针对性的 STAR 重写建议。

**面试深度准备**：从 JD + 匹配 risks 逆向推导面试考点，生成结构化准备清单（技术面/行为面/向面试官提问）。

**跨会话记忆**：JSONL 事件日志 + 画像快照，跨会话维护求职进展、面试经验、偏好变化。

## 快速开始

### 一步式安装

```bash
pip install -r requirements.txt && python3 scripts/check_env.py
```

环境要求：Python ≥ 3.9 + 一个 OpenAI 兼容的 LLM API。`check_env.py` 会检测依赖是否齐全、网络是否可达。

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API 配置
```

### 作为 CatDesk Skill 使用

将本目录放入 `~/.catpaw/skills/career-copilot/`，CatDesk 会自动识别并加载。

### 独立使用 Scripts

```bash
# 环境检测
python3 scripts/check_env.py

# 从简历生成能力画像
python3 scripts/gen_profile.py --resume ./resume.pdf --output ./boundary_profile.json

# 批量抓取 JD
python3 scripts/fetch_jobs.py --base-url "https://..." --pages 5 --output ./jobs_raw.txt

# 六阶段评分
python3 scripts/smart_score.py \
  --jobs ./jobs_raw.txt \
  --profile ./boundary_profile.json \
  --summary ./candidate_summary.txt \
  --output ./scored_results.json

# 验证输出（12 项断言检查）
python3 scripts/verify_output.py --input ./scored_results.json

# 生成交互式 HTML 报告
python3 scripts/generate_report.py --input ./scored_results.json --output ./report.html
```

## 目录结构

```
career-copilot/
├── SKILL.md                     # Skill 主定义（路由、约束、哲学）
├── requirements.txt             # Python 依赖声明
├── references/
│   ├── matching-guide.md        # Pipeline 完整执行指南
│   ├── interview-prep.md        # 面试准备方法论
│   ├── resume-guide.md          # 简历优化框架
│   ├── career-memory.md         # 记忆系统规范
│   ├── onboarding-guide.md      # 冷启动引导（方向不明确时）
│   └── evolution-log.md         # Skill 演化日志与用户偏好
├── examples/
│   ├── boundary_profile_example.json  # 能力画像示例
│   └── scored_results_example.json    # 评分结果示例
├── evals/
│   ├── evals.json               # Skill 评测用例（7 条）
│   ├── eval_results.json        # Desk Review 评测结果
│   └── skilllens_report.md      # SkillLens Deep Review 报告
├── scripts/
│   ├── llm_client.py            # 共享 LLM 客户端（多 Provider）
│   ├── check_env.py             # 环境检测（含网络连通性）
│   ├── gen_profile.py           # 画像生成
│   ├── fetch_jobs.py            # JD 批量抓取
│   ├── smart_score.py           # 六阶段评分 pipeline
│   ├── pre_filter.py            # 确定性预过滤（被 smart_score 调用）
│   ├── post_judge.py            # 确定性后处理（被 smart_score 调用）
│   ├── verify_output.py         # 12 项回归断言检查
│   ├── generate_report.py       # HTML 报告生成
│   ├── assess_competitiveness.py # 投递难度评估
│   ├── diff_watch.py            # 增量监测（新岗位检测）
│   └── career_log.py            # 职业记忆管理
├── tests/
│   ├── test_pre_filter.py       # pre_filter 单元测试
│   └── test_post_judge.py       # post_judge 单元测试
├── notes/
│   ├── improvement-roadmap.md   # 改进路线图（规划参考）
│   ├── implementation-plan.md   # 实施方案（规划参考）
│   ├── easyslides-inspired-upgrade-plan.md  # EasySlides 架构启发升级计划
│   └── external-resources-reading-notes.md  # 外部资源研读笔记
├── .env.example                 # 环境变量模板
└── .gitignore
```

## 设计哲学

1. **模型负责判断力，代码负责约束力** — LLM 做评估和推理，确定性代码做规则兜底
2. **方向锚定 + 行业知识注入** — 不依赖 LLM 的泛化理解，显式注入行业辨别知识
3. **先粗后精，分层控成本** — 便宜模型全量粗筛，强模型只处理 Top K
4. **Listwise > Pointwise** — 对比排序强制拉开分差
5. **确定性后处理兜底** — 英语/学历/技术栈约束 100% 由代码保证

## LLM Provider 配置

本项目支持任何 OpenAI 兼容接口。内置两个 Provider 槽位（`internal` / `external`），通过环境变量配置：

| 环境变量 | 用途 |
|----------|------|
| `LLM_PROVIDER` | 默认 Provider（`internal` 或 `external`） |
| `LLM_BASE_URL` | internal 的 API base URL |
| `LLM_API_KEY` | internal 的认证 Key |
| `EXTERNAL_BASE_URL` | external 的 API base URL |
| `EXTERNAL_API_KEY` | external 的 API Key |

也可通过 `--provider` 参数在命令行中切换。

## License

GPL-3.0 — 衍生作品必须同样开源。详见 [LICENSE](./LICENSE)。
