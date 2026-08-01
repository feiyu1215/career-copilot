#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_jobs_feishu.py — 飞书 ATS 校招/社招岗位批量抓取（Playwright XHR 拦截版）

========================================================================
适用场景
========================================================================
所有使用「飞书招聘 ATS」(*.jobs.feishu.cn) 的公司招聘站点，例如：
    - 蔚来      nio.jobs.feishu.cn
    - 以及其它接入飞书招聘 SaaS 的企业（字节系/新势力车企/互联网公司等）

为什么需要这个脚本（与 fetch_jobs.py 的关系）：
    fetch_jobs.py 依赖 catdesk-browser + CSS 选择器，对「SPA + 前端签名 API」
    的站点（飞书 ATS 就是）不友好——岗位数据走 /api/v1/... 接口返回 JSON，
    列表 DOM 里只有壳，正文由 JS 异步填充，且请求带前端计算的 _signature，
    直接反编译签名成本极高。

    本脚本与 fetch_jobs.py **并列共存、互不影响**：
      - fetch_jobs.py  → catdesk-browser 路线（字节/美团/阿里官网等 DOM 友好站点）
      - fetch_jobs_feishu.py → Playwright 拦截路线（飞书 ATS 类 SPA + 签名 API）
    两者都输出同一份 JOB_MATCHER_FORMAT v1，下游 smart_score / diff_watch /
    generate_report 零改动直接消费。

========================================================================
工作原理（让 SPA 自己算签名，绕开反编译）
========================================================================
  1. Playwright 启动 Chromium，打开用户给的「列表页 URL」。
  2. page.on("response") 拦截 /api/v1/search/job/posts 响应 →
     拿到岗位列表（id / title / url / category / city ...）。
  3. 翻页：直接导航到带 current=N 的列表 URL（每次导航 SPA 重新算签名），
     继续拦截，直到某页返回数量 < limit 为止（无需预先知道总页数）。
  4. 详情：复用浏览器会话里最近一次 list 请求的
        - _signature（query 参数，来自拦截到的请求 URL）
        - x-csrf-token（请求头）
        - Cookie（同源 fetch 自动带，credentials:include）
     通过 page.evaluate(fetch) 直接打 /api/v1/job/posts/{id}，
     拿到比列表更完整的 JD 正文（data.job_post_detail）。
  5. 组装为标准 JOB_MATCHER_FORMAT v1（带 [URL] 前缀）→ 落盘。

========================================================================
依赖（可选依赖，未安装时给出明确提示）
========================================================================
    pip install playwright
    playwright install chromium        # 首次需下载 Chromium

========================================================================
用法
========================================================================
  # 基本：丢一个飞书 ATS 列表页链接进来即可
  python3 fetch_jobs_feishu.py \
      --url "https://nio.jobs.feishu.cn/campus/?project=...&functionCategory=..." \
      --output ./jobs_raw.txt

  # 调试/快速预览：只抓前 20 个，且只用列表 description（不抓详情）
  python3 fetch_jobs_feishu.py --url "..." --output ./jobs_raw.txt \
      --max-jobs 20 --no-detail

  # 想看浏览器在干什么（默认无头）
  python3 fetch_jobs_feishu.py --url "..." --output ./jobs_raw.txt --no-headless

参数：
  --url              飞书 ATS 列表页 URL（必填）。会保留其中的 project /
                    functionCategory 等过滤参数，只对 current/limit 做翻页控制。
  --output          输出文件路径（默认 ./jobs_raw_feishu.txt）
  --max-jobs        最多抓取的岗位数（默认 0 = 不限制）
  --no-detail       跳过详情接口，只用列表自带 description（更快，但 JD 较简略）
  --limit           每页条数（默认 200，飞书 ATS 单页上限约 200）
  --headless/--no-headless  是否无头（默认无头）
  --timeout         单请求/单页等待超时秒数（默认 60）
  --max-concurrency 详情并发数（默认 5）
  --delay           翻页之间的最小间隔秒数（默认 0.5，避免触发风控）
  --resume          从断点续传（中途 Ctrl+C 后继续，读取 feishu_checkpoint.json）
  --checkpoint      断点检查点文件路径（默认 feishu_checkpoint.json）
  --pipeline-config pipeline 配置文件路径（从中读取 user_agent，默认 config/pipeline.yaml）

示例：
  # 第一次跑（中途 Ctrl+C 中断）
  python3 fetch_jobs_feishu.py --url "..." --output ./jobs_raw.txt
  # 从断点继续（同一 --output，自动跳过已抓岗位/详情）
  python3 fetch_jobs_feishu.py --url "..." --output ./jobs_raw.txt --resume


输出格式（与 fetch_jobs.py 完全一致，下游零改动）：
    # JOB_MATCHER_FORMAT v1 generated_at=<ISO> total_jobs=<N>
    --- JOB 1 ---
    [URL]<岗位网页链接>[/URL]
    <标题>
    <部门> | <城市> | <岗位类型> | <职能类别>
    <JD 正文 / 职责 / 要求>

    --- JOB 2 ---
    ...
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import random
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ============================================================
# 输出格式：与 fetch_jobs.py 的 _save_jobs 保持一致（JOB_MATCHER_FORMAT v1）
# 说明：这里刻意「复制」而非 import，保证本脚本可独立运行、不耦合 catdesk 路线。
# ============================================================

def _save_jobs(jobs: list[str], output_file: str) -> None:
    """将岗位文本列表保存为 JOB_MATCHER_FORMAT v1。"""
    out_dir = os.path.dirname(os.path.abspath(output_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        timestamp = datetime.datetime.now().isoformat()
        f.write(f"# JOB_MATCHER_FORMAT v1 generated_at={timestamp} total_jobs={len(jobs)}\n")
        for i, job in enumerate(jobs, 1):
            f.write(f"--- JOB {i} ---\n{job}\n\n")


# ============================================================
# T15：增强支撑（重试 / 断点检查点 / User-Agent 配置化）
# ============================================================

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


async def fetch_with_retry(fn, *, retries: int = 3, base_delay: float = 1.0,
                           max_delay: float = 30.0):
    """异步重试（指数退避 + jitter）。

    fn 为零参可等待调用（返回结果或抛异常）。全部耗尽返回 None，
    与 _fetch_detail 的失败语义一致（不中止整体抓取，只标记该 JD 失败）。
    """
    for attempt in range(retries):
        try:
            return await fn()
        except Exception:
            if attempt == retries - 1:
                break
            wait = min(base_delay * (2 ** attempt), max_delay) * random.uniform(0.5, 1.5)
            await asyncio.sleep(wait)
    return None


@dataclass
class FeishuCheckpoint:
    """断点续传状态：当前已完成页码 + 已发现岗位 + 已抓详情 ID。"""
    page_no: int = 1
    job_items: list[dict] = field(default_factory=list)
    fetched_detail_ids: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "page_no": self.page_no,
                "job_items": self.job_items,
                "fetched_detail_ids": self.fetched_detail_ids,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, s: str) -> "FeishuCheckpoint":
        d = json.loads(s)
        return cls(
            page_no=d.get("page_no", 1),
            job_items=d.get("job_items", []),
            fetched_detail_ids=d.get("fetched_detail_ids", []),
        )

    @staticmethod
    def save(path: str, cp: "FeishuCheckpoint") -> None:
        Path(path).write_text(cp.to_json(), encoding="utf-8")

    @staticmethod
    def load(path: str) -> "FeishuCheckpoint":
        return FeishuCheckpoint.from_json(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def exists(path: str) -> bool:
        return Path(path).exists()


def _load_user_agent(config_path: str = "config/pipeline.yaml") -> str:
    """从 config/pipeline.yaml 读取 user_agent（顶层或 feishu.user_agent）。

    缺 yaml / 缺文件 / 缺字段时退回默认 UA，绝不因配置缺失而崩溃。
    """
    try:
        import yaml
    except ImportError:
        return DEFAULT_USER_AGENT
    p = Path(config_path)
    if not p.exists():
        return DEFAULT_USER_AGENT
    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return DEFAULT_USER_AGENT
    if not isinstance(cfg, dict):
        return DEFAULT_USER_AGENT
    ua = cfg.get("user_agent")
    if not ua and isinstance(cfg.get("feishu"), dict):
        ua = cfg["feishu"].get("user_agent")
    return ua or DEFAULT_USER_AGENT


# ============================================================
# 飞书 ATS 抓取器
# ============================================================


# ============================================================
# 工具函数
# ============================================================

def _host_of(url: str) -> str:
    """提取 URL 的 host（用于校验飞书域名、构造 API base）。"""
    return urllib.parse.urlparse(url).netloc or ""


def _list_url_for_page(base_url: str, page: int, limit: int) -> str:
    """在列表 URL 上设置 current / limit 翻页参数，保留其它过滤参数。"""
    parts = urllib.parse.urlparse(base_url)
    q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    q["current"] = [str(page)]
    q["limit"] = [str(limit)]
    new_query = urllib.parse.urlencode(q, doseq=True)
    return urllib.parse.urlunparse(parts._replace(query=new_query))


def _ci_get(d: dict, *keys: str, default: Any = None) -> Any:
    """字典大小写不敏感的 key 查找（飞书字段名可能大小写不一）。"""
    if not isinstance(d, dict):
        return default
    lower = {k.lower(): k for k in d.keys()}
    for k in keys:
        lk = k.lower()
        if lk in lower:
            return d[lower[lk]]
    return default


def _clean(text: Any) -> str:
    """把可能的 None / 数字 / 列表统一成可读字符串。"""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        return "\n".join(str(x) for x in text if x)
    return str(text).strip()


def _strip_html(text: str) -> str:
    """极简去 HTML 标签（飞书 JD 偶发富文本残留）。"""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|li|tr|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ============================================================
# 飞书 ATS 抓取器
# ============================================================

class FeishuJobCrawler:
    """基于 Playwright 的飞书 ATS 岗位抓取器。"""

    LIST_PATH = "/api/v1/search/job/posts"
    DETAIL_PATH_TMPL = "/api/v1/job/posts/{}"

    def __init__(
        self,
        url: str,
        limit: int = 200,
        timeout: int = 60,
        no_detail: bool = False,
        max_jobs: int = 0,
        max_concurrency: int = 5,
        delay: float = 0.5,
    ):
        self.base_list_url = url
        self.limit = limit
        self.timeout = timeout
        self.no_detail = no_detail
        self.max_jobs = max_jobs
        self.max_concurrency = max_concurrency
        self.delay = delay

        # T15：断点续传状态
        self.pipeline_config: str = "config/pipeline.yaml"
        self.checkpoint_path: str = "feishu_checkpoint.json"
        self._resume_page: int = 1
        self._last_list_page: int = 1
        self._fetched_detail_ids: set[str] = set()

        # 运行时由拦截填充
        self.api_base: str = ""            # https://<host>
        self.latest_sig: str = ""          # 最近一次 list 请求的 _signature
        self.latest_csrf: str = ""         # 最近一次 list 请求的 x-csrf-token
        self.detail_query: str = ""        # 复用的 query（去掉 current/limit）
        self._captured_list: dict = {}     # url -> parsed json（按页）
        self._list_event = None            # asyncio.Event，等待某次 list 响应
        self._pending_list_key: Optional[str] = None

        # 抓取结果：job_id -> 合并后的 dict
        self.jobs: dict[str, dict] = {}

    # ---------- 拦截回调 ----------
    async def _on_response(self, response) -> None:
        """page.on('response') 异步回调：捕获 list 接口的 JSON。

        说明：Playwright 的 response.body() 是协程，必须 await。
        这里用 async 回调直接 await 读取（Playwright 会缓冲响应体，读取安全），
        并按「当前页 key 快照」存储，避免多页导航对共享状态的竞态。
        """
        try:
            req_url = response.url
            if self.LIST_PATH not in req_url:
                return
            # 区分 list 与 detail（detail 由 fetch 直接打，不走拦截）
            if re.search(r"/api/v1/job/posts/\d+", req_url):
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return

            # 记录签名 / csrf / query 供详情复用
            parsed = urllib.parse.urlparse(req_url)
            q = urllib.parse.parse_qs(parsed.query)
            sig = _ci_get(q, "_signature")
            if sig:
                self.latest_sig = sig[0] if isinstance(sig, list) else sig
            req_headers = response.request.headers
            csrf = _ci_get(req_headers, "x-csrf-token")
            if csrf:
                self.latest_csrf = csrf
            # 去掉分页参数，保留其余（portal_type/portal_entrance/project...）
            q_filtered = {k: v for k, v in q.items() if k.lower() not in ("current", "limit")}
            self.detail_query = urllib.parse.urlencode(q_filtered, doseq=True)
            self.api_base = f"{parsed.scheme}://{parsed.netloc}"

            # 当前页 key 快照（避免在回调执行时已切到下一页）
            key_snapshot = self._pending_list_key
            try:
                data = json.loads(await response.body())
            except Exception:
                data = None
            if key_snapshot is not None:
                self._captured_list[key_snapshot] = data
            if self._list_event is not None:
                self._list_event.set()
        except Exception as e:  # 拦截回调绝不能抛异常中断抓取
            print(f"  [WARN] 拦截回调异常: {e}")

    # ---------- 断点续传 ----------
    def _init_resume(self, resume: bool, checkpoint_path: str) -> None:
        self.checkpoint_path = checkpoint_path
        if resume and FeishuCheckpoint.exists(checkpoint_path):
            cp = FeishuCheckpoint.load(checkpoint_path)
            self._resume_page = cp.page_no
            self._fetched_detail_ids = set(cp.fetched_detail_ids)
            for it in cp.job_items:
                jid = str(_ci_get(it, "id") or _ci_get(it, "job_post_id") or "")
                if jid:
                    self.jobs[jid] = it
            print(f"  [resume] 从断点恢复：page_no={self._resume_page}, "
                  f"已发现 {len(self.jobs)} 个岗位，已抓详情 {len(self._fetched_detail_ids)} 个")
        else:
            self._resume_page = 1
            self._fetched_detail_ids = set()

    def _save_checkpoint(self) -> None:
        # 存列表项时剔除 _detail，避免检查点文件膨胀
        items = [{k: v for k, v in it.items() if k != "_detail"} for it in self.jobs.values()]
        cp = FeishuCheckpoint(
            page_no=self._last_list_page,
            job_items=items,
            fetched_detail_ids=sorted(self._fetched_detail_ids),
        )
        try:
            FeishuCheckpoint.save(self.checkpoint_path, cp)
        except Exception as e:
            print(f"  [WARN] 检查点保存失败: {e}")

    # ---------- 主流程 ----------
    async def run(self, headless: bool = True, resume: bool = False,
                  checkpoint_path: str = "feishu_checkpoint.json"):
        self._init_resume(resume, checkpoint_path)
        from playwright.async_api import async_playwright  # 懒导入

        ua = _load_user_agent(self.pipeline_config)  # T15：UA 从 config/pipeline.yaml 读取
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                locale="zh-CN",
                user_agent=ua,
            )
            page = await context.new_page()
            page.on("response", self._on_response)

            # 真实浏览器闭包：导航到某页并返回列表 items / 抓单个详情
            async def navigate(page_no: int):
                url = _list_url_for_page(self.base_list_url, page_no, self.limit)
                self._pending_list_key = f"p{page_no}"
                self._list_event = asyncio.Event()
                self._captured_list[self._pending_list_key] = None
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                except Exception as e:
                    print(f"导航异常: {e}")
                    return None
                try:
                    await asyncio.wait_for(self._list_event.wait(), timeout=self.timeout)
                except asyncio.TimeoutError:
                    print("超时未捕获 list 接口（可能已登录态失效或站点结构变化）")
                    return None
                return _extract_list_items(self._captured_list.get(self._pending_list_key))

            async def fetch(jid: str):
                return await self._fetch_detail(page, jid)

            await self._drive_crawl(navigate, fetch)
            await browser.close()

        return self._build_job_texts()

    async def _drive_crawl(self, navigate, fetch) -> None:
        """核心抓取编排（列表翻页 + 详情），与具体传输无关，便于单测。

        navigate(page_no) -> list[dict] | None（None 表示本页导航失败）
        fetch(job_id)     -> detail dict | None
        """
        # ---- 1. 翻页抓列表 ----
        self._last_list_page = self._resume_page
        page_no = self._resume_page
        guard = 1
        consecutive_empty = 0
        while True:
            items = await navigate(page_no)
            if items is None:
                break  # 导航异常，结束列表抓取
            if not items:
                consecutive_empty += 1
                print(f"空（连续 {consecutive_empty}）")
                if consecutive_empty >= 2:
                    print("  [STOP] 连续 2 页为空，判定抓取完毕")
                    break
            else:
                consecutive_empty = 0
                added = 0
                for it in items:
                    jid = str(_ci_get(it, "id") or _ci_get(it, "job_post_id") or "")
                    if not jid or jid in self.jobs:
                        continue
                    self.jobs[jid] = it
                    added += 1
                print(f"+{added} 新增（本页 {len(items)} 条），累计 {len(self.jobs)}")
                self._last_list_page = page_no
                self._save_checkpoint()  # 每完成一页即存盘，支持断点续传
                if self.max_jobs and len(self.jobs) >= self.max_jobs:
                    print(f"  [STOP] 已达 --max-jobs={self.max_jobs} 上限")
                    break
                # 本页未满，说明到底了
                if len(items) < self.limit:
                    print(f"  [STOP] 本页 {len(items)} < limit {self.limit}，判定到底")
                    break

            # 翻页推进 & 限速
            page_no += 1
            guard += 1
            if guard > 200:  # 极端保护
                print("  [STOP] 已达 200 页保护上限")
                break
            if self.delay:
                await asyncio.sleep(self.delay)

        # ---- 2. 抓详情 ----
        if self.no_detail:
            print("  [跳过详情] --no-detail 已设，仅用列表 description")
            return
        if not self.latest_sig:
            print("  [WARN] 未捕获到 _signature，详情接口可能无法调用；将退回列表 description")
            return

        # 重新导航一次以刷新 _signature / csrf（避免详情请求时签名过期）
        await navigate(1)

        job_ids = [j for j in self.jobs if j not in self._fetched_detail_ids]
        if self.max_jobs:
            job_ids = job_ids[: self.max_jobs]

        print("-" * 60)
        print(f"抓取详情：{len(job_ids)} 个岗位"
              f"（并发 {self.max_concurrency}，已跳过 {len(self._fetched_detail_ids)} 个已抓取）")
        sem = asyncio.Semaphore(self.max_concurrency)
        ok = 0
        fail = 0

        async def _one(jid: str) -> None:
            nonlocal ok, fail
            async with sem:
                # T15：单 JD 重试（3 次，指数退避 + jitter）
                detail = await fetch_with_retry(lambda: fetch(jid), retries=3, base_delay=1.0)
                if detail is not None:
                    self.jobs[jid]["_detail"] = detail
                    self._fetched_detail_ids.add(jid)
                    ok += 1
                else:
                    fail += 1
                self._save_checkpoint()  # 每完成一个详情即存盘，支持断点续传

        await asyncio.gather(*[_one(jid) for jid in job_ids])
        print(f"  详情完成：成功 {ok}，失败 {fail}")


    async def _fetch_detail(self, page, job_id: str) -> Optional[dict]:
        """复用签名 + csrf + Cookie 直接打详情接口。"""
        if self.detail_query:
            query = self.detail_query
        else:
            query = f"portal_type=6&portal_entrance=1&_signature={self.latest_sig}"
        url = f"{self.api_base}{self.DETAIL_PATH_TMPL.format(job_id)}?{query}"

        js = """
        async (args) => {
            const url = args[0];
            const csrf = args[1];
            try {
                const resp = await fetch(url, {
                    method: "GET",
                    headers: {
                        "website-path": "campus",
                        "accept-language": "zh-CN",
                        "x-csrf-token": csrf,
                        "accept": "application/json"
                    },
                    credentials: "include"
                });
                return await resp.text();
            } catch (e) {
                return JSON.stringify({"__fetch_error__": String(e)});
            }
        }
        """
        try:
            raw = await page.evaluate(js, [url, self.latest_csrf])
        except Exception:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
        if isinstance(data, dict) and data.get("__fetch_error__"):
            return None
        detail = _extract_detail(data)
        return detail

    def _build_job_texts(self) -> list[str]:
        """把 self.jobs 转成 JOB_MATCHER_FORMAT 文本块列表。"""
        texts: list[str] = []
        seen: set[str] = set()
        for jid, item in self.jobs.items():
            detail = item.get("_detail")
            text = _build_job_text(item, detail)
            h = _dedup_hash(text)
            if h in seen:
                continue
            seen.add(h)
            texts.append(text)
        return texts


# ============================================================
# 响应解析（兼容字段名大小写/结构差异）
# ============================================================

def _extract_list_items(data: Optional[dict]) -> list[dict]:
    """从 list 响应里提取岗位列表（兼容 data.job_post_list / data.list / data.records）。"""
    if not isinstance(data, dict):
        return []
    d = _ci_get(data, "data") or {}
    if not isinstance(d, dict):
        d = {}
    for key in ("job_post_list", "jobPostList", "list", "records", "items"):
        items = _ci_get(d, key)
        if isinstance(items, list) and items:
            return items
    # 有些响应直接把数组放在 data 下
    if isinstance(d.get("job_post_list"), list):
        return d["job_post_list"]
    return []


def _extract_detail(data: Optional[dict]) -> Optional[dict]:
    """从 detail 响应里提取 job_post_detail。"""
    if not isinstance(data, dict):
        return None
    d = _ci_get(data, "data") or {}
    if not isinstance(d, dict):
        d = {}
    detail = _ci_get(d, "job_post_detail", "jobPostDetail")
    if isinstance(detail, dict):
        return detail
    # 有些站点 detail 就直接是 data 本身
    if any(k in d for k in ("description", "responsibilities", "requirements", "job_content")):
        return d
    return None


# ============================================================
# 组装 JD 文本（输出格式与 fetch_jobs.py 对齐）
# ============================================================

def _first_url(item: dict, detail: Optional[dict]) -> str:
    """优先从详情/列表里找岗位网页链接，用于 [URL] 前缀。"""
    for src in (detail or {}, item):
        for key in ("url", "link", "job_url", "jobUrl", "share_url", "shareUrl",
                    "post_url", "detail_url", "web_url", "pc_url"):
            v = _ci_get(src, key)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return ""


def _build_job_text(item: dict, detail: Optional[dict]) -> str:
    """把一个岗位（列表项 + 详情）拼成一段 JD 文本。"""
    # 标题
    title = _clean(_ci_get(item, "name", "title", "job_name", "jobName", "position_name")) \
        or _clean(_ci_get(detail or {}, "name", "title", "job_name")) \
        or "未命名岗位"

    # 元信息行
    department = _clean(_ci_get(item, "department_name", "department", "dept_name")) \
        or _clean(_ci_get(detail or {}, "department_name", "department"))
    city = _clean(_ci_get(item, "city", "city_name", "location", "work_city")) \
        or _clean(_ci_get(detail or {}, "city", "city_name", "location"))
    job_type = _clean(_ci_get(item, "job_type", "jobType", "employment_type")) \
        or _clean(_ci_get(detail or {}, "job_type", "jobType"))
    category = _clean(_ci_get(item, "category_name", "function_category_name", "category")) \
        or _clean(_ci_get(detail or {}, "category_name", "category"))

    meta_parts = [p for p in (department, city, job_type, category) if p]
    meta_line = " | ".join(meta_parts)

    # 正文：优先详情，回退列表
    def _body(src: dict) -> str:
        chunks = []
        desc = _strip_html(_clean(_ci_get(src, "description", "job_content", "content")))
        resp = _strip_html(_clean(_ci_get(src, "responsibilities", "duty", "job_responsibility")))
        req = _strip_html(_clean(_ci_get(src, "requirements", "requirement", "job_requirement")))
        if desc:
            chunks.append(desc)
        if resp:
            chunks.append("【岗位职责】\n" + resp)
        if req:
            chunks.append("【任职要求】\n" + req)
        return "\n\n".join(chunks).strip()

    body = _body(detail) if detail else ""
    if not body:
        body = _body(item)
    if not body:
        body = _clean(_ci_get(item, "description")) or "（无可用 JD 正文，建议人工补充）"

    # 拼装
    url = _first_url(item, detail)
    lines = []
    if url:
        lines.append(f"[URL]{url}[/URL]")
    lines.append(title)
    if meta_line:
        lines.append(meta_line)
    lines.append(body)
    return "\n".join(lines).strip()


def _dedup_hash(text: str) -> str:
    clean = re.sub(r"^\[URL\].*?\[/URL\]\n?", "", text, flags=re.S)
    return hashlib.md5(clean[:200].encode("utf-8")).hexdigest()


# ============================================================
# CLI
# ============================================================

def _check_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="飞书 ATS 校招岗位批量抓取（Playwright 拦截版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", required=True, help="飞书 ATS 列表页 URL（*.jobs.feishu.cn）")
    parser.add_argument("--output", default="./jobs_raw_feishu.txt", help="输出文件路径")
    parser.add_argument("--max-jobs", type=int, default=0, help="最多抓取岗位数（0=不限制）")
    parser.add_argument("--no-detail", action="store_true", help="跳过详情接口，只用列表 description")
    parser.add_argument("--limit", type=int, default=200, help="每页条数（默认 200）")
    parser.add_argument("--timeout", type=int, default=60, help="单页/单请求超时秒数")
    parser.add_argument("--max-concurrency", type=int, default=5, help="详情并发数")
    parser.add_argument("--delay", type=float, default=0.5, help="翻页最小间隔秒数")
    parser.add_argument("--headless", dest="headless", action="store_true", default=True)
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.add_argument("--resume", action="store_true",
                        help="从 feishu_checkpoint.json 断点续传（中途 Ctrl+C 后继续）")
    parser.add_argument("--checkpoint", default="feishu_checkpoint.json",
                        help="断点检查点文件路径（默认 feishu_checkpoint.json）")
    parser.add_argument("--pipeline-config", default="config/pipeline.yaml",
                        help="pipeline 配置文件路径（从中读取 user_agent 等，默认 config/pipeline.yaml）")
    args = parser.parse_args()

    # 校验 host
    host = _host_of(args.url)
    if "jobs.feishu.cn" not in host:
        print(f"[ERROR] 该脚本仅适用于飞书 ATS 站点（host 需含 'jobs.feishu.cn'），当前 host={host}")
        print("        若为其它站点，请使用 fetch_jobs.py（catdesk-browser 路线）。")
        sys.exit(1)

    # 校验 playwright
    if not _check_playwright():
        print("[ERROR] 未安装 playwright，请先执行：")
        print("        pip install playwright && playwright install chromium")
        sys.exit(1)

    crawler = FeishuJobCrawler(
        url=args.url,
        limit=args.limit,
        timeout=args.timeout,
        no_detail=args.no_detail,
        max_jobs=args.max_jobs,
        max_concurrency=args.max_concurrency,
        delay=args.delay,
    )
    crawler.pipeline_config = args.pipeline_config

    try:
        texts = asyncio.run(
            crawler.run(headless=args.headless, resume=args.resume, checkpoint_path=args.checkpoint)
        )
    except KeyboardInterrupt:
        print("\n[中断] 用户取消（检查点已落盘，可用 --resume 续传）")
        texts = crawler._build_job_texts()
    except Exception as e:
        print(f"[ERROR] 抓取异常: {e}")
        texts = crawler._build_job_texts()

    if not texts:
        print("\n[提示] 未抓取到任何岗位，可能原因：")
        print("  1. 列表页需要登录 → 先在浏览器登录，或用已登录的浏览器上下文")
        print("  2. URL 不是飞书 ATS 列表页 → 确认 host 为 *.jobs.feishu.cn 且含招聘列表")
        print("  3. 站点结构变化 → 检查拦截到的接口路径是否为 /api/v1/search/job/posts")
        _save_jobs(texts, args.output)
        sys.exit(1)

    _save_jobs(texts, args.output)
    print("=" * 60)
    print(f"完成！总计 {len(texts)} 个岗位 → {args.output}")
    print("=" * 60)
    print("下一步：")
    print(f"  python3 smart_score.py --jobs {args.output} --profile <画像> \\")
    print("      --summary <摘要> --output scored.json --provider <provider>")


if __name__ == "__main__":
    main()
