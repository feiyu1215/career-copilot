"""fetch_jobs_nowcoder.py — 牛客网（校招/社招）多门户后端。

requests + 轻量 stdlib HTML 解析（来自 job_common.parse_html_tree，零 bs4 依赖）
抓取牛客网公开职位，输出 JOB_MATCHER_FORMAT v1。

属 Phase 4.2「实习僧启用 + 牛客网适配」：新增牛客网来源。
牛客网职位页为 React SPA，服务端 HTML 多为壳；本模块采用「启发式选择器 +
优雅降级」：命中职位卡片则提取，否则返回空并告警（不崩溃），待本地微调。

注意：选择器为「启发式，待本地微调」——目标站点 DOM/接口变更时需同步调整；
无网络 / 无 requests 时优雅降级（exit 2）。默认 portals.yaml 中 enabled=false，
启用前请先本地联网验证选择器。
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from job_common import (  # noqa: E402
    ScrapeHealth,
    acquire_portal_throttle,
    health_check,
    html_find_anchors,
    html_first_anchor,
    html_iter,
    html_text_by_class,
    parse_html_tree,
    save_jobs_format,
)

BASE = "https://www.nowcoder.com"
SEARCH = f"{BASE}/search"

# 限流/风控自愈（对齐 fetch_boss / shixiseng Phase 4.1/4.2）
MAX_RETRIES = 4
BACKOFF_BASE = 5.0
BACKOFF_JITTER = 0.3

RATE_LIMIT_MARKERS = (
    "访问过于频繁", "请稍后再试", "验证码", "安全验证", "人机验证",
    "滑动验证", "429", "too many requests", "verify you are human", "robot",
)
AUTH_WALL_MARKERS = ("请登录", "登录后查看", "访问被拒绝", "访问受限", "network-error", "页面不存在")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
]

# 卡片识别：class 含以下任一关键字视为「一个岗位卡片」
_CARD_CLASS_KEYWORDS = ("job-card", "recruit", "position", "job-item", "post-item", "rec-job")
# 职位详情链接特征
_JOB_HREF_MARKERS = ("/jobs/", "/position/")


def _load_http():
    try:
        import requests  # 延迟导入，缺包时优雅降级
    except ImportError as e:
        raise RuntimeError(
            "缺少依赖 requests：pip install requests 后重试（牛客网后端需要）"
        ) from e
    return requests


def _backoff(attempt: int, base: float = BACKOFF_BASE, jitter: float = BACKOFF_JITTER) -> float:
    return base * (2 ** (attempt - 1)) * (1 + random.uniform(-jitter, jitter))


def _is_rate_limit(html: str) -> bool:
    low = html.lower()
    return any(m.lower() in low for m in RATE_LIMIT_MARKERS)


def _is_auth_wall(html: str) -> bool:
    low = html.lower()
    return any(m.lower() in low for m in AUTH_WALL_MARKERS)


def _is_card(node) -> bool:
    return any(node.has_class(kw) for kw in _CARD_CLASS_KEYWORDS)


def _is_job_href(href: str) -> bool:
    return any(m in href for m in _JOB_HREF_MARKERS)


def parse_jobs(html: str) -> list[dict]:
    """解析牛客网搜索结果页 → 结构化岗位列表。

    策略：先按卡片容器提取，退化到扫描所有 /jobs/、/position/ 链接。
    URL 去重。SPA 壳页（无卡片）返回空（由上层告警，待本地微调）。
    """
    root = parse_html_tree(html)
    jobs: list[dict] = []
    seen: set[str] = set()

    # 策略 1：结构化卡片
    for node in html_iter(root):
        if node.tag == "a" or not _is_card(node):
            continue
        a = None
        for m in _JOB_HREF_MARKERS:
            a = html_first_anchor(node, m)
            if a is not None:
                break
        if a is None:
            continue
        url = a.attrs.get("href", "")
        if not url.startswith("http"):
            url = BASE + url
        if url in seen:
            continue
        title = a.full_text()
        if not title:
            continue
        company = html_text_by_class(node, "company") or html_text_by_class(node, "comp")
        location = (html_text_by_class(node, "city") or html_text_by_class(node, "area")
                    or html_text_by_class(node, "region") or html_text_by_class(node, "addr"))
        salary = html_text_by_class(node, "money") or html_text_by_class(node, "salary")
        jobs.append({
            "title": title, "url": url,
            "company": company, "location": location, "salary": salary,
            "description": "",
        })
        seen.add(url)

    # 策略 2：退化扫描所有职位详情链接
    if not jobs:
        for a in html_find_anchors(root, ""):
            href = a.attrs.get("href", "")
            if not _is_job_href(href):
                continue
            url = href if href.startswith("http") else BASE + href
            if url in seen:
                continue
            title = a.full_text()
            if not title:
                continue
            jobs.append({"title": title, "url": url,
                         "company": "", "location": "", "salary": "", "description": ""})
            seen.add(url)
    return jobs


def to_block(job: dict) -> str:
    block = f"[URL]{job['url']}[/URL]\n{job['title']}"
    extra: list[str] = []
    if job.get("company"):
        extra.append(job["company"])
    tail = " | ".join(x for x in (job.get("location", ""), job.get("salary", "")) if x)
    if tail:
        extra.append(tail)
    if extra:
        block += "\n" + "\n".join(extra)
    if job.get("description"):
        block += "\n" + job["description"]
    return block


def _fetch_page(http, page: int, query: str, sleep=time.sleep):
    """抓取单页；命中限流/风控/登录墙返回 None（上层当作风控处理）；传输错误抛异常。"""
    acquire_portal_throttle("nowcoder")  # [7.2] 按 portals.yaml 主动节流（每页一次）
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            params = {"type": 2, "subType": 2, "query": query, "pageNo": page}
            r = http.get(SEARCH, params=params, timeout=15,
                         headers={"User-Agent": random.choice(USER_AGENTS)})
            r.raise_for_status()
        except Exception:
            if attempt < MAX_RETRIES:
                sleep(_backoff(attempt))
                continue
            raise
        html = r.text
        if _is_rate_limit(html):
            if attempt < MAX_RETRIES:
                sleep(_backoff(attempt))
                continue
            return None
        if _is_auth_wall(html):
            return None
        return html
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="牛客网职位抓取（JOB_MATCHER_FORMAT v1）")
    ap.add_argument("--query", required=True, help="搜索关键词")
    ap.add_argument("--pages", type=int, default=3, help="翻页数量")
    ap.add_argument("--max-jobs", type=int, default=0, help="最多抓取条数（0=不限）")
    ap.add_argument("--output", default="jobs_raw_nowcoder.txt", help="v1 输出路径")
    args = ap.parse_args(argv)

    try:
        http = _load_http()
    except RuntimeError as e:
        print(f"[ERR] {e}", file=sys.stderr)
        return 2

    all_jobs: list[dict] = []
    bot_blocked = False
    for page in range(1, args.pages + 1):
        try:
            html = _fetch_page(http, page, args.query)
        except Exception as e:
            print(f"[WARN] 牛客网第{page}页请求失败：{e}", file=sys.stderr)
            break
        if html is None:
            bot_blocked = True
            print("[WARN] 牛客网触发限流/风控/登录墙，停止翻页", file=sys.stderr)
            break
        page_jobs = parse_jobs(html)
        if not page_jobs:
            print(f"[WARN] 牛客网第{page}页解析为空（SPA 壳页或 DOM 变更，待本地微调）", file=sys.stderr)
        all_jobs.extend(page_jobs)
        if args.max_jobs and len(all_jobs) >= args.max_jobs:
            all_jobs = all_jobs[:args.max_jobs]
            break

    blocks = [to_block(j) for j in all_jobs]
    n = save_jobs_format(blocks, args.output, datetime.now().isoformat(timespec="seconds"))

    # 抓取健康度（对齐 4.1）
    hc = health_check(n, 0, 0, portal="nowcoder", bot_blocked=bot_blocked)
    if not hc["ok"]:
        for w in hc["warnings"]:
            print(f"[HEALTH] {w}", file=sys.stderr)
    sh = ScrapeHealth.load(Path("scrape_health.json"))
    rec = sh.record("nowcoder", n)
    if rec["suspected_blocked"]:
        print(f"[HEALTH] 牛客网疑似被风控/封禁（连续 {rec['consecutive_empty']} 次空）", file=sys.stderr)
    sh.save()

    if n:
        print(f"[OK] 牛客网抓取 {n} 条 -> {args.output}")
    else:
        print("[INFO] 牛客网未抓到数据（SPA 壳页/待本地联网 + 微调选择器）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
