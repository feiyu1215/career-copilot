# 增量 2 · P6 BOSS 直聘抓取（fetch_boss.py）

## Objective
为 career-copilot 的「匹配」路由与 Job tracker 增加 BOSS 直聘岗位拉取能力。采用**薄封装 + 可插拔后端**：默认 `boss-cli` 后端（薄封装本地 `boss` CLI，自带 zhipin 认证 + 结构化 JSON），`bsk` 作为降级后端；后端抽象为统一接口，按实效选型，缺后端优雅降级。

## 为什么（对齐计划 §4.5 / 路线图 P6）
- 上游岗位源越广，匹配路由越有用。BOSS 直聘是求职者侧主流站点。
- 不重写抓取逻辑 → 复用 `fetch_jobs.py`（关注点分离、不迁运行时）。
- 后端按实效选型、不预设立场：谁真能在本地跑通取到列表就用谁（boss-cli / bsk / 油猴导出 / Playwright…），留可切换口子。

## 范围边界（角色定义，非道德说教）
- **只 fetch/score**：`search`/`detail` 拉岗位、读 JD，喂给匹配路由与 `smart_score`。
- **不自动化发送**：`greet`/`apply`/`chat` 不实现、不代发——career-copilot 是教练/评委，发送是用户动作。
- 因此本增量不触碰任何 Anti-pattern：subprocess 调本地 boss/bsk（不迁运行时）、不引入硬命令、不扩发送动作、本地优先。

## 接口（三接口抽象）
- `search(query, pages, delay) -> list[Job]`：按关键词翻页拉岗位，返回结构化 `Job`。
- `detail(url) -> str`：读单条 JD 文本。
- `shortlist(jobs, criteria) -> list[Job]`：按关键词本地筛选（模块级工具，与后端无关）。

## 设计要点
- `Job` dataclass：title/company/salary/location/url/raw。`normalize_job()` 把 `fetch_jobs` 的 `[URL]…[/URL]` 文本块解析为 `Job`（离线可测）。
- `BaseBackend`：实现默认 `shortlist`；`BossCliBackend`（默认首选）实现 `search`/`detail`，subprocess 调 `boss` CLI（`boss search` 解析 JSON 信封 → `Job`），`bsk` 作为降级后端（`BskBackend` 经 `session` 控制已登录 Edge，`parse_boss_search_html()` 解析 `get-html` 卡片）。
- `BACKENDS` 注册表 + `get_backend(name)` 可插拔；未知后端抛 `BackendUnavailable`（优雅降级）。
- **agent-discipline 刹车**（防失控）：`--max-jobs`（ROI 刹车，默认 50，编排层强制截断）、`--delay`（低频，默认 2.5s）、对话边界（JD 文本当数据）。

## 依赖与降级
- 运行需 `boss-cli`（独立 CPython 的 `Scripts\boss.exe`，`boss login` 已登录）或 `bsk` daemon + 已连接浏览器 + 已登录 BOSS。两者皆缺失时不崩溃：抛 `BackendUnavailable`，调用方回退到「贴链接用 `smart_score` 评估」。

## Testing（离线可测，CI 友好）
`tests/test_fetch_boss.py` 覆盖：
- `normalize_job` 解析含 `[URL]` 的 BOSS 卡片 → 各字段正确；缺 URL 时 `url=""`。
- `shortlist` 按关键词筛选；空条件返回全部。
- 可插拔注册表含 `boss-cli`（默认）与 `bsk`；未知后端抛 `BackendUnavailable`。
- **优雅降级**：monkeypatch `BossCliBackend._find_boss_cli` / `BskBackend._find_bsk` 为不存在路径 → `available()==False`、`search()` 抛 `BackendUnavailable`。
- **刹车**：FakeBackend 返回 100 条，`search_jobs(max_jobs=10)` 截断 ≤10，`max_jobs=0` 表示不限制。

## 不能在此环境实测（标注，非伪造）
- 真实 BOSS 抓取（boss-cli + 已登录 Edge + 反爬存活）需用户本地验证。后端选型只看：反爬存活率、输出结构化程度、维护成本。
- BOSS 卡片字段映射（title/company/salary/location 行序）为启发式，需按真实卡片布局本地微调；`raw` 全文保留供 `smart_score` 完整解析。

## Success Criteria
- 4 个离线测试类全过（EXIT=0）。
- `scripts/fetch_boss.py` 可被 `python fetch_boss.py search --query ...` 调用；boss-cli/bsk 缺失时退出码 2 且不抛未捕获异常。
- `fetch_jobs.py` 新增 `boss` 预设且 `--preset boss` 可用。
