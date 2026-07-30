# Career Copilot

> AI Agent Skill：求职全链路智能助手，覆盖 **岗位匹配 → 简历优化 → 面试准备 → 职业记忆** 完整闭环。
> 本仓库刻意保留为 GitHub 入口；skill 运行时以 `SKILL.md` 为准（`SKILL.md` 已含完整安装/配置/目录结构/设计哲学，与本文档同步）。

## 5 分钟 Quick Start

```
1. 装依赖：      pip install -r requirements.txt   （或 uv sync）
2. 配环境：      cp .env.example .env   → 填入 LLM_API_KEY + 至少一个 provider（friday/sub2api/nvidia/agnes）
3. 验环境：      python scripts/check_env.py        （确认依赖 ✓ + LLM 网关可达 + LaTeX 引擎就绪）
4. 建档：        对 agent 说「帮我建档」             （setup_wizard 交互式生成 boundary_profile.json + candidate_summary.txt）
5. 匹配岗位：    对 agent 说「帮我匹配岗位」         （六阶段 pipeline 跑出 A/B/C 三档推荐）
```

- 第 4 步指引见 `references/setup-guide.md`；第 5 步详解见 `references/matching-guide.md`。
- 目录结构、设计哲学、Provider 配置、各脚本职责 —— 见 `SKILL.md` 与 `FILE_GUIDE.md`（开发者手册）。

## 合规使用声明（Portal 抓取）

> 本项目是**个人求职教练/评委**，不是爬虫武器。抓取层已内置多重合规刹车，使用前应知悉并遵守：

- **仅个人用途**：用于你自己找工作的岗位匹配与复盘，**不得**批量采集、转售、商业爬取或任何侵犯目标站点权益的行为。
- **尊重 rate_limit**：`config/portals.yaml` 为每个门户配置了 `rate_limit`（如 boss 30 请求/分、linkedin 10 请求/分）。抓取脚本每次对外请求前会按此配置**主动节流**（token bucket），请**不要**调高到突破目标站点 Robots/ToS 容忍度。
- **遵守目标站点 ToS / Robots**：各门户（`zhipin` / `linkedin` / `shixiseng` / `nowcoder` / `catdesk` 等）的服务条款优先；若站点明确禁止自动化访问，请只走其官方 API 或人肉浏览。
- **不碰发送动作**：`greet` / `apply` / `chat` 等联系/投递动作**永不自动化**，始终留在用户侧手动完成（career-copilot 只做 fetch/score）。
- **账号与隐私**：登录态、Cookie、PII 仅存本地，未经授权不上传；详见 `LEGAL_DISCLAIMER.md`。
- **触发风控即停**：一旦命中限流/验证码（429 / 访问过于频繁），脚本会指数退避并停止翻页，请降低频率、检查登录态、待风控解除后再试。

## 核心能力

- **岗位智能匹配**：六阶段评分 pipeline（粗筛 → 校准 → 精排 → 重排 → 后处理 → 验证），从数百个 JD 精准筛选，输出 A/B/C 三档推荐。
- **简历定向优化**：基于匹配 risks 逆向改写简历 —— 区分「表述问题」与「能力缺失」，给出 STAR 重写建议；外企场景支持 `--cover-letter` 求职信。
- **面试深度准备**：从 JD + risks 逆向推导考点，生成技术面/行为面/向面试官提问清单（`references/interview-prep.md`）。
- **跨会话记忆**：JSONL 事件日志 + 画像快照，跨会话维护进展、面试经验、偏好变化（`references/career-memory.md`）。
- **技能升级概览（Upskill Brief）**：聚合匹配/竞争力产物为「方向性缺口概览」，喂给外部 AI 出学习计划（不搜网络、不生成课程表）。
- **行为画像（Behavioral Profile）**：PI/DISC/MBTI 速查 + JD↔行为风格映射，让简历/求职信/面试自带行为优势。

## 一键式脚本（独立使用）

```bash
python scripts/check_env.py                 # 环境检测
python scripts/gen_profile.py --resume ./resume.pdf --output ./boundary_profile.json   # 简历→画像
python scripts/fetch_jobs.py --base-url "https://..." --total-pages 5 --output ./jobs_raw.txt  # JD 抓取
python scripts/smart_score.py --jobs ./jobs_raw.txt --profile ./boundary_profile.json \
    --summary ./candidate_summary.txt --output ./scored_results.json   # 六阶段评分
python scripts/verify_output.py --input ./scored_results.json          # 12 项契约断言
python scripts/generate_report.py --input ./scored_results.json --output ./report.html  # 交互式 HTML 报告
```

多门户抓取（BOSS/飞书/实习僧/LinkedIn，开关在 `config/portals.yaml`）与各进阶脚本用法，
见 `references/job-fetch.md` / `FILE_GUIDE.md`。

## 设计哲学

1. **模型负责判断力，代码负责约束力** —— LLM 做评估推理，确定性代码做规则兜底
2. **方向锚定 + 行业知识注入** —— 显式注入行业辨别知识，不依赖 LLM 泛化
3. **先粗后精，分层控成本** —— 便宜模型全量粗筛，强模型只处理 Top K
4. **Listwise > Pointwise** —— 对比排序强制拉开分差
5. **确定性后处理兜底** —— 英语/学历/技术栈约束 100% 由代码保证

## License

GPL-3.0 —— 衍生作品必须同样开源。详见 [LICENSE](./LICENSE)。
