<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# 飞书 ATS 抓取踩坑笔记（fetch_jobs_feishu.py）

> 维护者参考。记录 `scripts/fetch_jobs_feishu.py` 背后的飞书招聘 ATS 接口规律与坑。
> 适用：`*.jobs.feishu.cn`（蔚来 `nio.jobs.feishu.cn` 等接入飞书招聘 SaaS 的站点）。

---

## 1. 为什么不能直接用 fetch_jobs.py（catdesk 路线）

飞书 ATS 是**典型的 SPA + 前端签名 API**：

- 列表页 DOM 里只有壳，岗位数据由 JS 异步调用 `/api/v1/...` 接口返回 JSON 后填充；
- 请求带前端 JS 实时计算的 `_signature` 参数，且依赖 `x-csrf-token` + Cookie；
- catdesk-browser + CSS 选择器拿不到完整 JD，也绕不过 `_signature`。

→ 改用 Playwright **拦截 XHR**：让 SPA 自己算签名，我们只读它发出的接口返回。
  这是「复用浏览器已建立的合法会话」而非「破解签名」，稳定且零维护签名算法。

---

## 2. 接口规律（实测）

### API base
- **真实 base 是 `https://{host}/api/v1/...`**，不是 `/campus/api/v1/...`。
- `campus` 是**请求头** `website-path: campus`，不是 URL 路径段。
  （早期按 `/campus/api/v1/...` 打会 404 "no available cache"。）

### 必需请求头
| Header | 值 | 说明 |
|---|---|---|
| `website-path` | `campus` | 区分校招/社招站点的关键头 |
| `accept-language` | `zh-CN` | 否则可能返回英文或空 |
| `x-csrf-token` | Cookie 里的 csrf token | 从拦截到的请求头里取，详情接口必带 |

### 必需 query 参数
| Param | 值 | 说明 |
|---|---|---|
| `portal_type` | `6` | 校园招聘门户类型 |
| `portal_entrance` | `1` | 入口标识 |
| `_signature` | JS 计算 | **不要尝试反编译**，让 SPA 算 |

### 列表接口
- `GET /api/v1/search/job/posts`
- 响应：`data.job_post_list`（数组）。字段可能有 `id / name / department_name / city / job_type / category_name / url / description(摘要)`。
- **翻页用 `current` 参数，不要 `offset`**：
  - `offset` 被 SPA 忽略，永远返回第一页（曾因此一次拿到 400 条 = 200×2 重复页）；
  - `current=1` → 200 条，`current=2` → 剩余条数。配合 `limit=200`。
- 停止条件：某页返回数 `< limit` → 到底。

### 详情接口
- `GET /api/v1/job/posts/{id}`
- 响应：完整 JD 嵌套在 **`data.job_post_detail`**（比列表 `description` 更全）。
- 详情请求**复用**列表请求捕获到的 `_signature` + `x-csrf-token` + Cookie，用 `page.evaluate(fetch)` 同源打。
  - 同一会话内签名可复用，但有过期风险 → 脚本在抓详情前会**重新导航一次列表页刷新 `_signature`**。
  - 若详情仍失败（返回空/非预期结构），脚本退回用列表 `description`，不阻塞整体。

---

## 3. 字段名之乱（防御式解析）

飞书不同租户的字段名不一致，脚本统一做了**大小写不敏感 + 驼峰/蛇形双写**兜底：

- 列表：`job_post_list` / `jobPostList`；`name` / `title` / `job_name`；`department_name` / `department`；`city` / `city_name` / `location`；`url` / `job_url` / `share_url` / `web_url` / `pc_url`。
- 详情：`job_post_detail` / `jobPostDetail`；`description` / `job_content`；`responsibilities` / `duty`；`requirements` / `requirement`。
- JD 正文偶有 HTML（`<p>`/`<br>`/富文本），组装前做轻量去标签。

---

## 4. 输出格式契约（关键）

输出与 `fetch_jobs.py` **完全一致**的 `JOB_MATCHER_FORMAT v1`，保证 `smart_score.py` / `diff_watch.py` 零改动消费：

```
# JOB_MATCHER_FORMAT v1 generated_at=<ISO> total_jobs=<N>
--- JOB 1 ---
[URL]<岗位网页链接>[/URL]
<标题>
<部门> | <城市> | <岗位类型> | <职能类别>
<JD 正文 / 职责 / 要求>

--- JOB 2 ---
...
```

- `[URL]...[/URL]` 前缀供 `smart_score` 提取岗位来源链接（生成报告可点击）。
- 标题单独成行（smart_score 取首行作 title）；城市放前 200 字符内（smart_score 据此推断 location）。
- 去重：按 `id`（飞书全局唯一），且按正文 MD5 二次去重。

---

## 5. 运行依赖与限制

```bash
pip install playwright
playwright install chromium     # 首次需下载 Chromium
```

- 默认无头；`--no-headless` 可观察浏览器。
- 列表页若需登录，先在浏览器登录再把 Cookie 注入，或在已登录的上下文运行（脚本只读同源 Cookie）。
- `--max-jobs` / `--no-detail` 用于调试与快速预览。
- 本脚本**不修改** `fetch_jobs.py`，二者并列共存、共用下游。

---

## 6. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| 抓到 0 条 | host 不是 `*.jobs.feishu.cn`；或列表页需登录；或站点改了接口路径（检查是否仍为 `/api/v1/search/job/posts`） |
| 数量翻倍/重复 | 误用了 `offset` 翻页 → 已改为 `current`，正常不会出现 |
| 详情为空但列表有 | `_signature` 过期 → 脚本已做「抓详情前重新导航刷新签名」；仍失败则退回列表 `description` |
| 输出 JD 很短 | 该站点列表 `description` 本就简略，且详情接口未返回更多 → 属站点数据本身，建议人工补 |
| 登录态失效 | 用已登录浏览器上下文，或先 `page.goto` 登录再抓 |
