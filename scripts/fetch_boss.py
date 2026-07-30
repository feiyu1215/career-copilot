#!/usr/bin/env python3
"""
fetch_boss.py — BOSS直聘岗位抓取（薄封装 + 可插拔后端）

设计定位（对齐 career-copilot 升级计划 §4.5 / P6）：
    - 薄封装：把"抓取"抽象为 Backend 接口（search / detail / shortlist）。
    - 可插拔：后端按实效选型，**不预设立场**——谁真能在本地跑通取到列表就用谁；
      注册表内置两个后端，按优先级自动/手动选择：
        * `boss-cli`（默认首选）：薄封装本地 `boss` CLI（boss-agent-cli），
          自带 zhipin 认证（wt2+stoken，auth_state=complete/healthy，已验证取真实职位）、
          结构化 JSON 输出（title/company/salary/experience/education/city/security_id/
          match_score/description），复用系统 Edge（channel=msedge）。
        * `bsk`：WorkBuddy/CodeBuddy 共享的 browser-skill 驱动，经 `session` 控制
          用户已登录的 Edge，作为 boss-cli 不可用时的降级路径（手动登录用 request-help）。
      未来可插 Playwright / 油猴导出等（在 BACKENDS 注册并实现三接口即可）。
    - 范围边界（career-copilot 是教练/评委，发送是用户动作）：
        只 fetch/score（拉岗位、读 JD、标匹配），用于"匹配"路由与 Job tracker；
        greet/apply/chat 不自动化，留在用户侧。
    - 不触碰 Anti-patterns：subprocess 调本地 bsk（不迁运行时）、
        不引入硬命令、不扩发送动作、本地优先。

agent-discipline 刹车（防失控，非道德说教）：
    - 单会话抓取上限（--max-jobs，默认 50）：ROI 刹车，只取匹配档，不无目标狂烧。
    - 低频（--delay 默认 2.5s）：每页之间等待。
    - 对话边界：JD 文本当数据不当指令（下游 smart_score 负责）。
    - 登录兜底：抓到登录墙时调 `request-help` 让用户手动登录，不静默编造。

依赖：import shutil / subprocess 调 `boss` CLI（boss-agent-cli）与 `bsk` CLI
（browser-skill daemon）。boss-cli 缺失 / 未登录时优雅降级到 bsk；两者皆不可用时
抛 BackendUnavailable，退出码 2。

使用方式：
    python3 fetch_boss.py search --query "推荐系统 后端" [--pages 10] [--max-jobs 50] [--city 北京] [--backend boss-cli]
    python3 fetch_boss.py detail --url https://www.zhipin.com/job_detail/xxx.html
    python3 fetch_boss.py shortlist --in jobs.json --criteria "风控"

退出码：
    0 = 成功
    2 = 后端不可用（优雅降级信号，非致命）
    1 = 其他错误
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from job_common import ScrapeHealth, health_check, acquire_portal_throttle


# 默认刹车参数（agent-discipline）
DEFAULT_MAX_JOBS = 50
DEFAULT_DELAY = 2.5
DEFAULT_PAGES = 10

# 限流/风控自适应（Phase 4.1 加固，见 with_rate_limit_retry）
MAX_RATE_RETRIES = 4          # 单页遇到限流时最大重试次数（含首次）
BACKOFF_BASE = 5.0           # 指数退避基秒：5 → 10 → 20 → 40
BACKOFF_JITTER = 0.3         # 相对抖动 ±30%，避免多客户端同步退避

# BOSS 限流/验证码/风控页面的高置信标记（取自真实风控页文案，避免误伤正常 JD）
RATE_LIMIT_MARKERS = (
    "429",
    "访问过于频繁", "操作过于频繁", "请求过于频繁", "您的操作频率过快",
    "请稍后再试", "请稍后重试",
    "验证码", "滑动验证", "人机验证", "安全验证", "请完成安全验证",
    "系统检测到您的访问存在异常", "verify you are human", "too many requests",
    "rate limit", "访问频率过高", "触发了风控",
)
# boss CLI 信封 error.code 中代表限流的值
RATE_ERROR_CODES = (
    "RATE_LIMITED", "TOO_MANY_REQUESTS", "429",
    "FREQUENCY_LIMIT", "OPERATION_TOO_FREQUENT", "RISK_CONTROL",
)

# BOSS 登录态失效的 error.code（用于显式"重新登录"提示，区别于其它错误）
AUTH_ERROR_CODES = ("AUTH_REQUIRED", "LOGIN_REQUIRED", "TOKEN_EXPIRED", "SESSION_EXPIRED")


# BOSS 直聘搜索 URL 模板（{page} 由 search 循环替换；{q} 由本脚本转义）
BOSS_SEARCH_TEMPLATE = "https://www.zhipin.com/web/geek/search?query={q}&page={page}"


class BackendUnavailable(Exception):
    """后端缺失或不可用——优雅降级信号（非致命）。"""


class RateLimited(BackendUnavailable):
    """限流/风控触发且重试耗尽——仍属「优雅降级信号」，但语义更明确。

    由调用方（main）按 BackendUnavailable 统一处理（exit 2），但保留子类型
    便于上层区分「暂时被限流」与「后端彻底不可用」。
    """


def detect_rate_limit(text: str) -> bool:
    """高置信判定一段文本是否来自 BOSS 限流/验证码/风控页面。

    仅匹配 RATE_LIMIT_MARKERS 中的「强信号」短语，避免误伤正常 JD 文案
    （例如 JD 里提到「技术验证」「经验验证」不会触发）。
    大小写不敏感。
    """
    if not text:
        return False
    low = text.lower()
    return any(m.lower() in low for m in RATE_LIMIT_MARKERS)


def _backoff_delay(attempt: int, base: float, jitter: float) -> float:
    """第 attempt 次重试（attempt 从 1 起）的指数退避秒数，含 ±jitter 抖动。"""
    delay = base * (2 ** (attempt - 1))
    if jitter > 0:
        delay += delay * jitter * (random.random() * 2 - 1)  # ±jitter
    return max(0.0, delay)


def with_rate_limit_retry(
    attempt_fetch: Callable[[], tuple[object, bool]],
    *,
    max_attempts: int = MAX_RATE_RETRIES,
    base: float = BACKOFF_BASE,
    jitter: float = BACKOFF_JITTER,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """对单页抓取做「限流自愈」封装。

    attempt_fetch() 必须返回 (result, is_rate_limited: bool)。当 is_rate_limited
    为 True 时，按指数退避（base, base*2, base*4...）重试，最多 max_attempts 次；
    耗尽则抛 RateLimited（BackendUnavailable 子类）。返回成功时的 result。

    设计要点：退避与「是否限流」由 attempt_fetch 自行判定（因 boss-cli 与 bsk
    两种后端的限流信号形态不同：前者看信封 error.code / 文本，后者看 HTML 风控页）。
    sleep 默认 time.sleep，便于测试时替换为无阻塞桩。
    """
    last_result = None
    for attempt in range(1, max_attempts + 1):
        result, rate_limited = attempt_fetch()
        last_result = result
        if not rate_limited:
            return result
        if attempt < max_attempts:
            sleep(_backoff_delay(attempt, base, jitter))
    raise RateLimited(
        f"BOSS 抓取连续 {max_attempts} 次触发限流/风控（验证码/429），"
        f"建议：降低频率、检查登录态、待风控解除后再试"
    )


@dataclass
class Job:
    title: str = ""
    company: str = ""
    salary: str = ""
    location: str = ""
    url: str = ""
    raw: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "salary": self.salary,
            "location": self.location,
            "url": self.url,
            "raw": self.raw,
        }


_URL_RE = re.compile(r"^\[URL\](.*?)\[/URL\]\n?", re.DOTALL)


def normalize_job(raw_text: str) -> Job:
    """把含 [URL] 的 BOSS 卡片文本块解析为结构化 Job（离线可测，向后兼容）。

    启发式字段映射：BOSS 不同卡片布局不同，行序需本地微调；
    但 [URL] 前缀解析与 raw 全文保留是确定性的，下游 smart_score 可完整解析 raw。
    """
    text = raw_text.strip()
    url = ""
    m = _URL_RE.match(text)
    if m:
        url = m.group(1).strip()
        text = text[m.end():]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return Job(
        title=lines[0] if len(lines) > 0 else "",
        company=lines[1] if len(lines) > 1 else "",
        salary=lines[2] if len(lines) > 2 else "",
        location=lines[3] if len(lines) > 3 else "",
        url=url,
        raw=raw_text.strip(),
    )


def _grab(fragment: str, pattern: str) -> str:
    """在 HTML 片段里取第一个捕获组（去掉空白）。"""
    m = re.search(pattern, fragment, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_boss_search_html(html: str) -> list[Job]:
    """从 BOSS 搜索结果 HTML 解析岗位卡片（按实效，选择器需本地微调）。

    做法：定位所有 /job_detail/ 详情链接 → 取链接前后上下文片段 →
    去标签后抽取 job-name/company-name/salary/job_area 等常见 BOSS class，
    全文保留到 raw 供 smart_score 完整解析。返回按 URL 去重的 Job 列表。
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    link_re = re.compile(r'href="(/job_detail/[^"?#]+)"')
    for m in link_re.finditer(html):
        url = "https://www.zhipin.com" + m.group(1)
        if url in seen:
            continue
        seen.add(url)
        # 卡片内容一般在 <a href> 之后：优先向前取，避免串到上一张卡片
        after = html[m.end(): m.end() + 1800]
        before = html[max(0, m.start() - 800): m.start()]

        def grab_near(pat: str) -> str:
            return _grab(after, pat) or _grab(before, pat)

        title = grab_near(r'class="job-name"[^>]*>(?:<[^>]+>)?([^<]+)') or grab_near(
            r'job-name-text">([^<]+)'
        )
        company = grab_near(r'class="company-name"[^>]*>(?:<[^>]+>)?([^<]+)')
        salary = grab_near(r'class="salary"[^>]*>(?:<[^>]+>)?([^<]+)')
        location = grab_near(r'class="job_area"[^>]*>(?:<[^>]+>)?([^<]+)') or grab_near(
            r'class="job-card-text"[^>]*>(?:<[^>]+>)?([^<]+)'
        )
        frag = html[max(0, m.start() - 800): m.end() + 1800]
        text = re.sub(r"<[^>]+>", " ", frag)
        text = re.sub(r"\s+", " ", text).strip()
        jobs.append(
            Job(
                title=title,
                company=company,
                salary=salary,
                location=location,
                url=url,
                raw=text,
            )
        )
    return jobs


@runtime_checkable
class Backend(Protocol):
    name: str

    def available(self) -> bool: ...
    def search(self, query: str, pages: int, delay: float) -> list[Job]: ...
    def detail(self, url: str) -> str: ...
    def shortlist(self, jobs: list[Job], criteria: str) -> list[Job]: ...


class BaseBackend:
    """默认实现：shortlist 与后端无关，子类继承即可。"""

    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def search(self, query: str, pages: int, delay: float) -> list[Job]:
        raise NotImplementedError

    def detail(self, url: str) -> str:
        raise NotImplementedError

    def shortlist(self, jobs: list[Job], criteria: str) -> list[Job]:
        crit = (criteria or "").strip().lower()
        if not crit:
            return list(jobs)
        return [
            j
            for j in jobs
            if crit in (j.title + " " + j.company + " " + j.raw).lower()
        ]


class BskBackend(BaseBackend):
    """bsk 后端：WorkBuddy/CodeBuddy 共享的 browser-skill 驱动，控制已登录的 Edge。

    机制：bsk daemon 已连接浏览器 → `session start` 建会话 →
    `navigate`/`get-html`/`evaluate` 驱动该会话的标签页；登录墙用 `request-help`
    让用户手动完成。完全本地、不迁运行时。
    """

    name = "bsk"

    def __init__(self, session: str | None = None):
        self.bsk = self._find_bsk()
        # 允许通过环境变量 / 构造参数固定 session，跳过 list/start
        self._session = session or os.environ.get("BSK_SESSION")

    @staticmethod
    def _find_bsk() -> str:
        p = shutil.which("bsk")
        return p or "bsk"

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.bsk, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise BackendUnavailable(
                f"找不到 bsk CLI：{self.bsk}（请确认 WorkBuddy/CodeBuddy 的 browser-skill 已安装且 daemon 在跑）"
            ) from e

    def available(self) -> bool:
        # daemon 必须运行 + 至少有一个浏览器已连接
        try:
            res = self._run("status", "--json", timeout=10)
        except BackendUnavailable:
            return False
        if res.returncode != 0:
            return False
        try:
            data = json.loads(res.stdout)
        except Exception:
            return False
        browsers = data.get("browsers") or []
        return len(browsers) > 0

    def _ensure_session(self) -> str:
        if self._session:
            return self._session
        # 先列现有会话
        res = self._run("session", "list", "--json", timeout=10)
        sid = None
        if res.returncode == 0:
            try:
                data = json.loads(res.stdout)
                if isinstance(data, list) and data:
                    sid = (data[0] or {}).get("id")
                elif isinstance(data, dict) and data.get("sessions"):
                    sid = (data["sessions"][0] or {}).get("id")
            except Exception:
                pass
        if not sid:
            # 对（单个）已连接浏览器建新会话
            res = self._run("session", "start", "--json", timeout=30)
            if res.returncode != 0:
                raise BackendUnavailable(f"bsk session start 失败: {res.stderr.strip()}")
            try:
                data = json.loads(res.stdout)
                sid = (
                    (data.get("id"))
                    or (data.get("session") or {}).get("id")
                    or (data[0].get("id") if isinstance(data, list) and data else None)
                )
            except Exception:
                raise BackendUnavailable("无法解析 bsk session start 输出")
        if not sid:
            raise BackendUnavailable("无法获得 bsk session（浏览器可能未连接）")
        self._session = sid
        return sid

    def _is_login_wall(self, session: str) -> bool:
        """检测当前页是否为 BOSS 登录墙（需用户手动登录）。"""
        res = self._run(
            "evaluate", "document.body.innerText", "--session", session,
            "--quiet", timeout=20,
        )
        if res.returncode != 0:
            return False
        text = (res.stdout or "").lower()
        return any(
            k in text
            for k in ("登录boss", "扫码登录", "密码登录", "请登录", "login")
        )

    def _ask_login(self, session: str) -> None:
        """请用户在浏览器中手动登录（不静默编造）。"""
        self._run(
            "request-help",
            "--session", session,
            "--prompt", "请在浏览器中登录 BOSS 直聘（账号密码或扫码），登录完成后此窗口会自动继续抓取。",
            "--title", "需要登录 BOSS 直聘",
            timeout=600,
        )

    def search(self, query: str, pages: int, delay: float) -> list[Job]:
        if not self.available():
            raise BackendUnavailable(
                "bsk 后端不可用：daemon 未运行或无已连接浏览器。"
                "请先启动 bsk daemon 并在 Edge 中连接 browser-skill 扩展。"
            )
        session = self._ensure_session()
        base_url = BOSS_SEARCH_TEMPLATE.format(q=urllib.parse.quote(query), page=1)
        jobs: list[Job] = []
        seen: set[str] = set()
        state = {"navigated": False}
        for page in range(1, pages + 1):
            url = re.sub(r"page=\d+", f"page={page}", base_url)
            acquire_portal_throttle("boss")  # [7.2] 按 portals.yaml 主动节流
            # 导航只在首次进行（登录墙检测亦仅首屏）；限流重试时复用已加载页面直接取 HTML
            html = self._fetch_html_with_retry(session, url, state)
            if html is None:
                continue
            for job in parse_boss_search_html(html):
                if job.url and job.url not in seen:
                    seen.add(job.url)
                    jobs.append(job)
            time.sleep(delay)
        return jobs

    def _fetch_html_with_retry(self, session, url, state: dict) -> str | None:
        """单页取 HTML + 限流自愈（指数退避重试）。

        返回成功时的 HTML 字符串；限流（detect_rate_limit 命中风控页）时交给
        with_rate_limit_retry 重试；导航/取 HTML 失败保持原语义立即抛
        BackendUnavailable。state["navigated"] 保证导航仅执行一次。
        """

        def attempt() -> tuple[str, bool]:
            if not state["navigated"]:
                nav = self._run(
                    "navigate", url, "--session", session,
                    "--wait-until", "networkidle", "--quiet", timeout=40,
                )
                if nav.returncode != 0:
                    raise BackendUnavailable(f"导航失败: {url} -> {nav.stderr.strip()}")
                # 首屏检测登录墙，必要时请用户登录后重导航
                if self._is_login_wall(session):
                    self._ask_login(session)
                    self._run(
                        "navigate", url, "--session", session,
                        "--wait-until", "networkidle", "--quiet", timeout=40,
                    )
                state["navigated"] = True
            time.sleep(self.delay)
            html_res = self._run("get-html", "--session", session, "--quiet", timeout=30)
            if html_res.returncode != 0:
                raise BackendUnavailable(f"取页面 HTML 失败: {html_res.stderr.strip()}")
            html = html_res.stdout or ""
            return (html, detect_rate_limit(html))

        return with_rate_limit_retry(attempt)

    def detail(self, url: str) -> str:
        if not self.available():
            raise BackendUnavailable("bsk 后端不可用")
        session = self._ensure_session()
        nav = self._run(
            "navigate", url, "--session", session,
            "--wait-until", "networkidle", "--quiet", timeout=40,
        )
        if nav.returncode != 0:
            raise BackendUnavailable(f"导航失败: {url}")
        if self._is_login_wall(session):
            self._ask_login(session)
            self._run(
                "navigate", url, "--session", session,
                "--wait-until", "networkidle", "--quiet", timeout=40,
            )
        res = self._run(
            "evaluate", "document.body.innerText", "--session", session,
            "--quiet", timeout=20,
        )
        if res.returncode != 0:
            raise BackendUnavailable(f"取 JD 文本失败: {res.stderr.strip()}")
        return (res.stdout or "").strip()


class BossCliBackend(BaseBackend):
    """boss-agent-cli 后端（首选）：薄封装本地 `boss` CLI。

    按实效选型确定的首选后端：boss-agent-cli 自带 zhipin 认证（wt2 + stoken，
    auth_state=complete/healthy，已验证返回真实职位）、结构化 JSON 输出
    （title/company/salary/experience/education/city/security_id/match_score/
    description 等），并复用系统 Edge（channel=msedge）。本脚本只拼参数、subprocess
    调 `boss search/detail`、解析 JSON 信封、映射为 Job——不迁运行时、不碰发送动作。

    风险：boss-agent-cli 的 site-packages 补丁会被 `pip install --upgrade` 覆盖，
    升级后 search() 会抛 BackendUnavailable，调用方自动降级到 bsk。

    subprocess 捕获 stdout（非 TTY）→ display.is_json_mode 返回 True → 自动输出
    JSON 信封；敏感字段已由 output.redact_sensitive 脱敏，可安全捕获。
    """

    name = "boss-cli"

    def __init__(self, city: str | None = None):
        self.boss = self._find_boss_cli()
        self.city = city

    @staticmethod
    def _find_boss_cli() -> str:
        p = shutil.which("boss")
        if p:
            return p
        # 回退：独立 CPython 的 Scripts 目录（boss-agent-cli 装在这）
        cand = os.path.join(os.path.dirname(sys.executable), "Scripts", "boss.exe")
        if os.path.exists(cand):
            return cand
        return "boss"

    def _run(self, *args, timeout=120):
        try:
            return subprocess.run(
                [self.boss, *args], capture_output=True, text=True, timeout=timeout
            )
        except FileNotFoundError as e:
            raise BackendUnavailable(f"找不到 boss CLI：{self.boss}") from e

    @staticmethod
    def _parse_env(stdout: str) -> dict:
        try:
            env = json.loads(stdout)
        except Exception:
            return {}
        return env if isinstance(env, dict) else {}

    def available(self) -> bool:
        # 仅判断 boss CLI 是否可达 + 调 `status` 是否返回 ok。
        # 细粒度登录态（auth_state / logged_in）缺失会在 search() 时以
        # AUTH_REQUIRED 暴露并抛 BackendUnavailable，由调用方降级。
        try:
            res = self._run("status", timeout=20)
        except BackendUnavailable:
            return False
        if res.returncode != 0:
            return False
        env = self._parse_env(res.stdout)
        return bool(env.get("ok"))

    def auth_health(self) -> dict:
        """返回 boss CLI 登录态健康度（供 main 打印 + 快速反馈）。

        与 available() 的区别：available() 只回答「CLI 是否可达+ok」，
        auth_health() 进一步读出 auth_state / logged_in，给出人类可读结论，
        并在「可能过期/不完整」时给出明确的重新登录指引。
        """
        try:
            res = self._run("status", timeout=20)
        except BackendUnavailable as e:
            return {"ok": False, "state": "unreachable", "message": str(e)}
        if res.returncode != 0:
            return {
                "ok": False, "state": "error",
                "message": f"boss status 退出码 {res.returncode}: {res.stderr.strip()}",
            }
        env = self._parse_env(res.stdout)
        if not env.get("ok"):
            return {"ok": False, "state": "logged_out", "message": "boss CLI 未登录"}
        data = env.get("data") or {}
        state = data.get("auth_state") or ("complete" if data.get("logged_in") else "incomplete")
        healthy = state in ("complete", "healthy", "ok")
        msg = (
            "登录态正常"
            if healthy
            else f"登录态可能过期/不完整（auth_state={state}）："
                 f"请重新 `boss login` 或重启 boss-edge-cdp 常驻 Edge 复用已登录会话"
        )
        return {"ok": healthy, "state": state, "message": msg}

    def search(self, query, pages, delay):
        if not self.available():
            raise BackendUnavailable(
                "boss-agent-cli 不可用：未登录或 boss CLI 缺失。"
                "请先 `boss login`（按需 `boss-edge-cdp` 起 9222 Edge），或在网页端收集后用 smart_score 评估。"
            )
        jobs: list[Job] = []
        seen: set[str] = set()
        for page in range(1, pages + 1):
            acquire_portal_throttle("boss")  # [7.2] 按 portals.yaml 主动节流
            env = self._fetch_page_with_retry(query, page)
            items = env.get("data") or []
            for it in items:
                job = self._map_item(it)
                if job.url and job.url not in seen:
                    seen.add(job.url)
                    jobs.append(job)
            time.sleep(delay)
            pag = env.get("pagination") or {}
            if pag.get("has_more") is False:
                break
        return jobs

    def _fetch_page_with_retry(self, query: str, page: int) -> dict:
        """单页 `boss search` + 限流自愈（指数退避重试）。

        返回成功时的 JSON 信封（dict）。限流（RATE_ERROR_CODES 或响应文本命中
        detect_rate_limit）时交给 with_rate_limit_retry 重试；登录态失效
        （AUTH_ERROR_CODES）立即抛出明确的「重新登录」提示，不重试（非瞬态）；
        其它失败保持原语义立即抛 BackendUnavailable。
        """

        def attempt() -> tuple[dict, bool]:
            args = ["search", query, "--page", str(page), "--no-cache"]
            if self.city:
                args += ["--city", self.city]
            res = self._run(*args, timeout=120)
            env = self._parse_env(res.stdout)
            if res.returncode != 0 or not env.get("ok"):
                err = env.get("error") or {}
                code = err.get("code")
                if code in AUTH_ERROR_CODES:
                    raise BackendUnavailable(
                        f"BOSS 登录态已失效（{code}）：请重新 `boss login`"
                        f"（或重启 boss-edge-cdp 常驻 Edge 复用已登录会话），再重试。"
                    )
                text = (res.stderr or "") + " " + json.dumps(env, ensure_ascii=False)
                if code in RATE_ERROR_CODES or detect_rate_limit(text):
                    return (env, True)  # 限流：触发退避重试
                raise BackendUnavailable(
                    f"boss search 失败 [{code}]: {err.get('message') or res.stderr.strip()}"
                )
            return (env, False)

        return with_rate_limit_retry(attempt)

    @staticmethod
    def _map_item(it: dict) -> Job:
        def g(*keys: str) -> str:
            for k in keys:
                v = it.get(k)
                if v:
                    return str(v)
            return ""

        url = g("url")
        if not url:
            sid = g("security_id") or g("encryptJobId") or g("jobId")
            if sid:
                url = f"https://www.zhipin.com/job_detail/{sid}.html"
        text_parts = [
            g("title"), g("company"), g("salary"),
            g("location", "city", "cityName"),
            g("experience", "jobExperience"),
            g("education", "jobDegree"),
        ]
        desc = g("description")
        raw = " | ".join(p for p in text_parts if p)
        if desc:
            raw = (raw + "\n" + desc).strip()
        return Job(
            title=g("title", "jobName"),
            company=g("company", "brandName"),
            salary=g("salary", "salaryDesc"),
            location=g("location", "city", "cityName"),
            url=url,
            raw=raw,
        )

    @staticmethod
    def _security_id_from(url: str) -> str:
        m = re.search(r"/job_detail/([^?#]+)", url)
        return m.group(1) if m else url.strip()

    def detail(self, url: str) -> str:
        if not self.available():
            raise BackendUnavailable("boss-agent-cli 不可用")
        sid = self._security_id_from(url)
        res = self._run("detail", sid, "--no-cache", timeout=60)
        if res.returncode != 0:
            raise BackendUnavailable(f"boss detail 失败: {res.stderr.strip()}")
        env = self._parse_env(res.stdout)
        if not env.get("ok"):
            err = env.get("error") or {}
            raise BackendUnavailable(
                f"boss detail 失败 [{err.get('code')}]: {err.get('message')}"
            )
        d = env.get("data") or {}
        return d.get("description") or json.dumps(d, ensure_ascii=False)


# 可插拔后端注册表
# 顺序即默认优先级：boss-cli 首选，bsk 作为降级；get_backend 默认选首个。
BACKENDS: dict[str, type] = {"boss-cli": BossCliBackend, "bsk": BskBackend}


def get_backend(name: str = "boss-cli") -> BaseBackend:
    if name not in BACKENDS:
        raise BackendUnavailable(f"未知后端: {name}（可用: {list(BACKENDS)}）")
    return BACKENDS[name]()


def search_jobs(
    query: str,
    backend_name: str = "boss-cli",
    pages: int = DEFAULT_PAGES,
    delay: float = DEFAULT_DELAY,
    max_jobs: int = DEFAULT_MAX_JOBS,
    base_url: str | None = None,
    city: str | None = None,
) -> list[Job]:
    """编排层：选后端 → 可用性检查 → 抓取 → ROI 刹车截断（强制，与后端无关）。"""
    backend = get_backend(backend_name)
    if city and hasattr(backend, "city"):
        backend.city = city
    if not backend.available():
        raise BackendUnavailable(
            f"后端 '{backend_name}' 不可用：请检查 boss CLI 登录 / bsk daemon，"
            f"或在网页端手动收集后用 smart_score 评估"
        )
    jobs = backend.search(query, pages, delay)
    # ROI 刹车：单会话只取匹配档，不无目标狂烧
    if max_jobs and max_jobs > 0:
        jobs = jobs[:max_jobs]
    return jobs


def _load_jobs_json(path: str) -> list[Job]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fields = ("title", "company", "salary", "location", "url", "raw")
    return [Job(**{k: d.get(k, "") for k in fields}) for d in data]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="BOSS直聘岗位抓取（薄封装 + 可插拔后端；只拉 JD 不代投）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="按关键词翻页拉岗位")
    p_search.add_argument("--query", required=True, help="搜索关键词")
    p_search.add_argument("--pages", type=int, default=DEFAULT_PAGES, help="最大页数（默认 10）")
    p_search.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="每页等待秒数（默认 2.5）")
    p_search.add_argument("--max-jobs", type=int, default=DEFAULT_MAX_JOBS, help="单会话截断上限（默认 50，0=不限制）")
    p_search.add_argument("--backend", default="boss-cli", help="后端名（默认 boss-cli；可选 bsk）")
    p_search.add_argument("--city", default=None, help="城市筛选（仅 boss-cli 后端；如 北京）")
    p_search.add_argument("--session", default=None, help="复用已有 bsk session id（可选，仅 bsk 后端）")
    p_search.add_argument("--output", default="./boss_jobs.json", help="输出 JSON 路径")

    p_detail = sub.add_parser("detail", help="读单条 JD 文本")
    p_detail.add_argument("--url", required=True, help="岗位详情页 URL")
    p_detail.add_argument("--backend", default="boss-cli", help="后端名（默认 boss-cli；可选 bsk）")
    p_detail.add_argument("--session", default=None, help="复用已有 bsk session id（可选，仅 bsk 后端）")

    p_short = sub.add_parser("shortlist", help="按关键词本地筛选")
    p_short.add_argument("--in", dest="in_file", required=True, help="search 产出的 JSON")
    p_short.add_argument("--criteria", required=True, help="筛选关键词")
    p_short.add_argument("--output", default="./boss_shortlist.json", help="输出 JSON 路径")

    args = parser.parse_args(argv)

    if args.cmd == "search":
        jobs: list[Job] = []
        bot_blocked = False
        try:
            jobs = search_jobs(
                args.query,
                backend_name=args.backend,
                pages=args.pages,
                delay=args.delay,
                max_jobs=args.max_jobs,
                city=args.city,
            )
        except RateLimited as e:
            # 限流/风控触发且重试耗尽：记录健康（疑似被封），仍写出空结果便于后续审计
            bot_blocked = True
            print(f"[WARN] {e}")
        except BackendUnavailable as e:
            print(f"[WARN] {e}")
            return 2
        out = [j.to_dict() for j in jobs]
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        # —— Phase 4.1 健康度串联 ——
        n_fetched = len(out)
        hc = health_check(n_fetched, 0, 0, portal="boss", bot_blocked=bot_blocked)
        for w in hc["warnings"]:
            print(f"[HEALTH] {w}")
        health_path = Path(args.output).resolve().parent / "scrape_health.json"
        sh = ScrapeHealth.load(health_path)
        rec = sh.record("boss", n_fetched)
        sh.save()
        if rec["suspected_blocked"]:
            print(f"[HEALTH] {rec['message']}")

        print(f"已写入 {n_fetched} 个岗位 → {args.output}")
        return 0

    if args.cmd == "detail":
        backend = get_backend(args.backend)
        if args.session:
            backend._session = args.session
        try:
            text = backend.detail(args.url)
        except BackendUnavailable as e:
            print(f"[WARN] {e}")
            return 2
        print(text)
        return 0

    if args.cmd == "shortlist":
        jobs = _load_jobs_json(args.in_file)
        res = BaseBackend().shortlist(jobs, args.criteria)
        out = [j.to_dict() for j in res]
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"筛选后 {len(out)} 个岗位 → {args.output}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
