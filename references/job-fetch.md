# 多门户抓取编排（job-fetch）

career-copilot 的多门户抓取编排（job-fetch），落地为并列 fetcher 家族。
目标：在保留已验证的 BOSS 路线基础上，把 **LinkedIn / 实习僧 / 通用 WebSearch 兜底**
纳入统一的多门户编排，并补齐四件套（开关 / 持久去重 / 健康检查 / mass-posting / 内推链接）。

## 架构总览

career-copilot 现有三套 fetcher，本方案在其上**并列扩展**，不改动已测试代码：

| 后端 | 脚本 | 路线 | 状态 |
|---|---|---|---|
| BOSS | `scripts/fetch_boss.py` | boss-cli 首选 + bsk 降级 | 已验证 |
| 通用(catdesk) | `scripts/fetch_jobs.py` | catdesk-browser（字节/美团/阿里/通用预设） | 已验证 |
| 飞书 ATS | `scripts/fetch_jobs_feishu.py` | Playwright XHR 拦截 | 可选 |
| **LinkedIn** | `scripts/fetch_jobs_linkedin.py` | **外部 CLI 优先 + WebSearch 兜底** | 新增 |
| **实习僧** | `scripts/fetch_jobs_shixiseng.py` | **requests 型（探索可行）** | 新增 |
| 通用兜底 | （agent WebSearch+WebFetch） | 无专属后端时 | 新增 |

共享逻辑抽到 `scripts/job_common.py`（纯 stdlib，离线可测）：门户注册表读取、
`SeenJobs` 持久去重、健康检查、mass-posting 检测、内推链接、统一 v1 输出。

## 门户注册表 `config/portals.yaml`

对齐通用门户 `enabled` 开关约定。每项：`enabled / kind / backend / cli / note`。
关闭的门户仅跳过、不删脚本。新增国外门户（Indeed/Glassdoor/各国 board）只需加一项
并写对应 `fetch_jobs_<x>.py`，**架构已可扩展**——但当前不启用（用户确认国外暂不需要）。

## 四件套

1. **enabled 开关**：`load_portals()` / `enabled_portals()` 驱动编排。
2. **持久去重**：`SeenJobs`（seen_jobs.json）跨运行去重，URL 精确 + 标题归一哈希；
   原 `fetch_boss.py` 仅单次 run 内 `seen` 集去重，已补上跨运行层。
3. **健康检查 / 静默腐烂检测**：`health_check()` —— 返回 0 条、空卡片 >50%、
   关键字段缺失 >50% 时告警。
4. **mass-posting 检测**：`detect_mass_posting()` —— 同一公司单轮刷屏 >阈值（默认 5）标记。
5. **内推链接**：`build_referral_links()` 生成 LinkedIn 人脉/职位搜索链接（纯链接，不爬）。

## LinkedIn 后端（外部 CLI 优先 + WebSearch 兜底）

策略与用户确认一致（方案 A）：
- `--mode auto`（默认）：检测到外部 `linkedin-search` CLI（bun cli.ts 风格）即用；
  否则生成 `linkedin_websearch_task.json/.md`，由 agent 执行 WebSearch+WebFetch 后
  `--ingest results.json` 回灌。
- 真实抓取依赖「已登录会话 / 外部 CLI」；脚本**不伪造** LinkedIn 爬虫（踩 ToS 且脆弱）。
- 输出 JOB_MATCHER_FORMAT v1，下游 smart_score 直接消费。

```bash
python scripts/fetch_jobs_linkedin.py --query "推荐算法" --city "上海" --mode auto
# 无 CLI 时：
python scripts/fetch_jobs_linkedin.py --ingest linkedin_websearch_results.json --output jobs_raw.txt
```

## 实习僧后端（探索可行）

GitHub 有成熟先例（`user-sure/shixiseng-spider` 2026、`s0meb0dy3/shixiseng-job-csv`），
属 requests 型、无需登录即可搜公开实习岗。当前实现为 requests+BeautifulSoup 宽松解析，
**选择器为启发式、待本地联网微调**（参考上述仓库）。无网络/无 requests 时优雅降级。
默认在 `portals.yaml` 中 `enabled: false`，需要时在注册表打开。

```bash
python scripts/fetch_jobs_shixiseng.py --query "算法" --city "上海" --output jobs_raw.txt
```

## 国外门户（暂不做）

架构已留扩展位。任何人需要时：在 `portals.yaml` 加一项 + 写 `fetch_jobs_<x>.py`
（建议 requests/CLI + WebSearch 兜底同构），无需改 `job_common.py`。

## 测试

- `tests/test_job_common.py`：覆盖 SeenJobs 去重、mass-posting、内推链接、v1 存读。
- `fetch_jobs_linkedin.py` / `fetch_jobs_shixiseng.py` 为 I/O 型脚本，靠 `--ingest` / 联网验证，
  不纳入离线单测。
