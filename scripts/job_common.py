"""job_common.py — 多门户抓取的共享逻辑（纯 stdlib，离线可测）。

多门户抓取共享逻辑，落地到 career-copilot 的脚本体系：
- 门户注册表(config/portals.yaml) 的 enabled 开关
- 跨运行持久去重 seen_jobs.json（原 fetch_boss 仅单次 run 内去重，已补跨运行层）
- 健康检查 / 静默腐烂检测
- mass-posting 批量发帖检测
- LinkedIn 内推/人脉搜索链接生成
- 统一 JOB_MATCHER_FORMAT v1 输出（与 fetch_jobs.py / fetch_jobs_feishu.py 同构）
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# 门户注册表
# ---------------------------------------------------------------------------

def _default_portals() -> dict:
    """portals.yaml 缺失/解析失败时的内嵌兜底（保证脚本不崩）。"""
    return {
        "portals": {
            "boss": {"enabled": True, "kind": "boss", "backend": "scripts/fetch_boss.py"},
            "catdesk": {"enabled": True, "kind": "catdesk", "backend": "scripts/fetch_jobs.py"},
            "linkedin": {"enabled": True, "kind": "linkedin", "backend": "scripts/fetch_jobs_linkedin.py", "cli": "linkedin-search"},
            "shixiseng": {"enabled": True, "kind": "shixiseng", "backend": "scripts/fetch_jobs_shixiseng.py"},
            "nowcoder": {"enabled": False, "kind": "nowcoder", "backend": "scripts/fetch_jobs_nowcoder.py"},
        },
        "websearch_fallback": {"enabled": True, "kind": "websearch"},
    }


def load_portals(config_path: str | Path | None = None) -> dict:
    """读取门户注册表；yaml 缺失或解析失败时回退内嵌默认。"""
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config" / "portals.yaml"
    p = Path(config_path)
    if not p.exists():
        return _default_portals()
    try:
        import yaml  # 项目依赖（fetch_jobs_feishu 也用）；缺失则兜底
    except Exception:
        return _default_portals()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if "portals" not in data:
            return _default_portals()
        return data
    except Exception:
        return _default_portals()


def enabled_portals(portals: dict) -> list[str]:
    """返回 enabled=True 的门户名列表（保持声明顺序）。"""
    out = []
    for name, cfg in (portals.get("portals") or {}).items():
        if cfg.get("enabled"):
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# 跨运行持久去重
# ---------------------------------------------------------------------------

@dataclass
class SeenJobs:
    """跨运行持久去重。去重键为「复合身份键」，避免把不同岗位错误合并。

    设计取舍（修复原 title-only 去重的缺陷）：
    - 同公司 + 同岗位名(+同地点) 在不同时间/不同 URL 重发 -> 同一键 -> 去重（正确，
      这是「同一岗位多次出现」应有的收敛）。
    - 不同公司即使岗位名完全相同 -> 不同键 -> 都保留（修复原设计把「腾讯后端开发」
      与「字节后端开发」错误合并成一条的不负责行为）。
    - URL 仍做精确去重，作为身份键之外的强约束。

    注意：seen_jobs.json 必须落在稳定路径（由调用方传入，如 data/seen_jobs.json），
    不能放在临时目录里——否则每次 run 都从空开始，所谓「跨运行持久」只是空话。
    """
    path: Path
    urls: set[str] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: str | Path) -> "SeenJobs":
        p = Path(path)
        obj = cls(path=p)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8") or "{}")
                obj.urls = set(data.get("urls", []))
                obj.keys = set(data.get("keys", []))
                # 兼容旧格式（仅按 title 归一哈希）：并入 keys 但不被新键命中，
                # 仅保证已落盘数据不丢。
                for h in data.get("hashes", []):
                    obj.keys.add(h)
            except Exception:
                obj.urls, obj.keys = set(), set()
        return obj

    @staticmethod
    def _norm(text: str) -> str:
        # NFKC 统一全半角；转小写；折叠空白。保留数字与标点，避免把
        # 「后端开发（北京）」与「后端开发(上海)」误判为同一键。
        if not text:
            return ""
        s = unicodedata.normalize("NFKC", text)
        s = s.lower().strip()
        s = re.sub(r"\s+", " ", s)
        return s

    @staticmethod
    def _key(source: str, company: str, title: str, location: str = "") -> str:
        raw = "|".join([
            SeenJobs._norm(source),
            SeenJobs._norm(company),
            SeenJobs._norm(title),
            SeenJobs._norm(location),
        ])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def seen(self, url: str = "", title: str = "", company: str = "",
             source: str = "", location: str = "") -> bool:
        if url and url in self.urls:
            return True
        if self._key(source, company, title, location) in self.keys:
            return True
        return False

    def add(self, url: str = "", title: str = "", company: str = "",
            source: str = "", location: str = "") -> None:
        if url:
            self.urls.add(url)
        self.keys.add(self._key(source, company, title, location))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"urls": sorted(self.urls), "keys": sorted(self.keys)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# mass-posting 检测（同一公司单次拉取刷屏）
# ---------------------------------------------------------------------------

def detect_mass_posting(records: Iterable[dict], by: str = "company",
                        threshold: int = 5) -> list[dict]:
    """同一公司/键在单轮拉取中发布超过 threshold 条不同岗位 → 标记疑似刷屏。

    records: 含 by 键的 dict 列表（如 {"company": "某厂", "title": "..."}）
    返回: [{"key": ..., "count": ..., "titles": [...]}]
    """
    buckets: dict[str, list[str]] = {}
    for r in records:
        key = (r.get(by) or "").strip()
        if not key:
            continue
        buckets.setdefault(key, []).append(r.get("title", ""))
    flagged = []
    for key, titles in buckets.items():
        if len(titles) > threshold:
            flagged.append({"key": key, "count": len(titles), "titles": titles})
    flagged.sort(key=lambda x: x["count"], reverse=True)
    return flagged


# ---------------------------------------------------------------------------
# 抓取结果质量守门（Phase 4.3）：逐条准入校验
# ---------------------------------------------------------------------------

# 标题/公司命中即视为占位符（无信息量），一律拦截
_PLACEHOLDER_TOKENS = {
    "", ".", "..", "...", "....", ".....",
    "职位", "招聘", "岗位", "标题", "公司", "名称", "暂无", "未知", "未命名",
    "untitled", "null", "none", "n/a", "na", "tbd", "-", "--", "—", "·",
}

# URL 命中即视为不可用（占位/死链/未解析），一律拦截
_URL_PLACEHOLDER_TOKENS = {
    "", "#", "javascript:", "javascript:void(0)", "void(0)", "void",
    "www.example.com", "example.com", "http://", "https://",
    "暂无", "无", "null", "none", "n/a",
}

# 视为「详情页」URL 的强信号（命中即认为 URL 形态 OK）
_DETAIL_HINTS = (
    "job", "jobs", "position", "post", "offer", "career", "recruit",
    "zhiwei", "job_detail", "detail", "vacancy", "apply",
)

_URL_RE = re.compile(r"https?://", re.I)
_WS_RE = re.compile(r"\s")


def _norm_field(v) -> str:
    """把任意字段值归一为可校验字符串（None → 空串，去首尾空白）。"""
    if v is None:
        return ""
    return str(v).strip()


def _looks_like_url(url: str) -> bool:
    """URL 形态是否可当作有效详情链接（宽松：http(s) 或含详情页信号）。"""
    if not url:
        return False
    if _WS_RE.search(url):
        return False  # URL 内含空白 = 解析错位
    if _URL_PLACEHOLDER_TOKENS.__contains__(url.lower()):
        return False
    if _URL_RE.search(url):
        return True
    # 非 http(s) 但出现详情页路径信号（如 /job_detail/xxx），也放行
    low = url.lower()
    return any(h in low for h in _DETAIL_HINTS)


def _is_placeholder(text: str) -> bool:
    if text.lower() in _PLACEHOLDER_TOKENS:
        return True
    # 纯标点/纯空白 也视为占位
    if text and all(ch in " .-_·—–" for ch in text):
        return True
    return False


def _identity_key(rec: dict, source: str) -> str:
    """复合身份键（与 SeenJobs 同构，但不含 source 维度，专注「同一条岗位」。"""
    parts = [
        SeenJobs._norm(source),
        SeenJobs._norm(rec.get("company", "")),
        SeenJobs._norm(rec.get("title", "")),
        SeenJobs._norm(rec.get("location", "")),
        SeenJobs._norm(rec.get("url", "")),
    ]
    return "|".join(parts)


def quality_gate(records: Iterable[dict], *, source: str = "",
                 require_company: bool = True, require_identity: bool = True,
                 drop_duplicates: bool = True) -> dict:
    """逐条质量守门：只放行字段完整、非零信息量的岗位记录进入下游。

    与 Phase 4.1 的 health_check（聚合级「静默腐烂」）互补：
    - health_check 看「整批是不是废了」（0 条 / 空卡 / 字段缺失比例）
    - quality_gate 看「单条能不能用」（标题/公司/URL 有没有、是不是占位符、能不能去重）

    契约号（与 verify_* 家族一致）：
      硬拦截 [QG#]（该条不进入 accepted）：
        [QG1] MISSING_TITLE   标题缺失/空
        [QG2] MISSING_COMPANY 公司缺失/空（require_company=True 时）
        [QG3] MISSING_IDENTITY 既无 URL 又无（公司+标题）可成身份键
        [QG4] INVALID_URL     URL 形态损坏（含空白 / 占位符 / 死链）
        [QG5] PLACEHOLDER     标题或公司为占位符（无信息量）
        [QG6] DUPLICATE       批内重复（drop_duplicates=True 时）
      软警告 [W-Q#]（照常放行，仅记入 stats.warnings）：
        [W-Q1] MISSING_SALARY 薪资缺失
        [W-Q2] MISSING_LOCATION 地点缺失
        [W-Q3] MISSING_JD      JD/描述缺失

    返回：
    {
      "accepted": [dict, ...],
      "rejected": [{"record": dict, "reasons": [{"code","field","message"}]}, ...],
      "stats": {
        "total", "accepted", "rejected", "accept_rate",
        "by_code": {code: count}, "warnings": {code: count}, "duplicate_rejected": int
      }
    }
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    by_code: dict[str, int] = {}
    warn_code: dict[str, int] = {}
    warned_records = 0
    dup_rejected = 0
    seen_keys: set[str] = set()

    for rec in records:
        if not isinstance(rec, dict):
            rejected.append({"record": rec, "reasons": [
                {"code": "QG1", "field": "record",
                 "message": "记录不是 dict（无法解析为岗位）"}]})
            by_code["QG1"] = by_code.get("QG1", 0) + 1
            continue

        title = _norm_field(rec.get("title"))
        company = _norm_field(rec.get("company"))
        url = _norm_field(rec.get("url"))
        location = _norm_field(rec.get("location"))
        salary = _norm_field(rec.get("salary"))
        jd = _norm_field(rec.get("description") or rec.get("jd")
                         or rec.get("raw") or rec.get("summary"))

        reasons: list[dict] = []

        # [QG1] 标题
        if not title:
            reasons.append({"code": "QG1", "field": "title",
                            "message": "标题缺失/空"})
        elif _is_placeholder(title):
            reasons.append({"code": "QG5", "field": "title",
                            "message": f"标题为占位符：{title!r}"})

        # [QG2] 公司
        if not company:
            if require_company:
                reasons.append({"code": "QG2", "field": "company",
                                "message": "公司缺失/空"})
        elif _is_placeholder(company):
            reasons.append({"code": "QG5", "field": "company",
                            "message": f"公司为占位符：{company!r}"})

        # [QG4] URL 形态
        if url and not _looks_like_url(url):
            reasons.append({"code": "QG4", "field": "url",
                            "message": f"URL 形态不可用：{url!r}"})

        # [QG3] 身份键：既无 URL 又无（公司+标题）
        # （require_identity=False 时跳过，用于 run_pipeline 重解析后仅保证 title 即可的场景）
        has_identity = bool(url) or (bool(company) and bool(title))
        if require_identity and not has_identity:
            reasons.append({"code": "QG3", "field": "identity",
                            "message": "既无 URL 又无（公司+标题），无法定位/去重"})

        # 软警告（不拦截）
        _rec_warned = False
        if not salary:
            warn_code["W-Q1"] = warn_code.get("W-Q1", 0) + 1
            _rec_warned = True
        if not location:
            warn_code["W-Q2"] = warn_code.get("W-Q2", 0) + 1
            _rec_warned = True
        if not jd:
            warn_code["W-Q3"] = warn_code.get("W-Q3", 0) + 1
            _rec_warned = True
        if _rec_warned:
            warned_records += 1

        # 硬拦截优先
        if reasons:
            for r in reasons:
                by_code[r["code"]] = by_code.get(r["code"], 0) + 1
            rejected.append({"record": rec, "reasons": reasons})
            continue

        # [QG6] 批内重复（在通过字段校验后判定，避免重复计算）
        if drop_duplicates:
            key = _identity_key(rec, source)
            if key in seen_keys:
                dup_rejected += 1
                by_code["QG6"] = by_code.get("QG6", 0) + 1
                rejected.append({"record": rec, "reasons": [
                    {"code": "QG6", "field": "identity",
                     "message": f"批内重复（身份键 {key}）"}]})
                continue
            seen_keys.add(key)

        accepted.append(rec)

    total = len(accepted) + len(rejected)
    stats = {
        "total": total,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "accept_rate": (len(accepted) / total) if total else 0.0,
        "by_code": by_code,
        "warnings": warn_code,
        "warned_records": warned_records,
        "warning_rate": (warned_records / total) if total else 0.0,
        "duplicate_rejected": dup_rejected,
    }
    return {"accepted": accepted, "rejected": rejected, "stats": stats}


# ---------------------------------------------------------------------------
# 健康检查 / 静默腐烂检测
# ---------------------------------------------------------------------------

def health_check(n_fetched: int, n_empty: int, n_null_fields: int,
                 expected_min: int = 1, *, portal: str = "",
                 bot_blocked: bool = False) -> dict:
    """「静默腐烂」检测：返回空/字段为空比例异常时告警。

    Phase 4.1 扩展：集成门户专项检测——
    - portal="boss" 且 bot_blocked=True 时，追加 BOSS 风控（限流/验证码）告警，
      提示降低频率 / 检查登录态 / 待风控解除。
    - 其余门户保持原语义（暂只做通用静默腐烂检测）。

    keyword-only 参数保证旧调用（位置参数）向后兼容。
    返回: {"ok": bool, "warnings": [...], "silent_rot": bool}
    """
    warnings: list[str] = []
    silent_rot = False
    if n_fetched == 0:
        silent_rot = True
        warnings.append("返回 0 条：后端可能静默腐烂或登录态失效")
    elif n_fetched < expected_min:
        warnings.append(f"返回 {n_fetched} 条 < 期望下限 {expected_min}")
    if n_fetched and n_empty / n_fetched > 0.5:
        silent_rot = True
        warnings.append(f"空卡片占比 {n_empty / n_fetched:.0%}：疑似解析失效")
    if n_fetched and n_null_fields / n_fetched > 0.5:
        silent_rot = True
        warnings.append(f"关键字段缺失占比 {n_null_fields / n_fetched:.0%}：疑似 DOM 变更")
    if portal == "boss" and bot_blocked:
        silent_rot = True
        warnings.append(
            "BOSS 触发限流/风控（验证码/429）：疑似被临时封禁或访问异常；"
            "建议降低频率、检查登录态、待风控解除后再试"
        )
    return {"ok": not warnings, "warnings": warnings, "silent_rot": silent_rot}


# ---------------------------------------------------------------------------
# 抓取健康度持久化（Phase 4.1）：跨运行追踪「连续 N 次空结果 = 疑似被封」
# ---------------------------------------------------------------------------

@dataclass
class ScrapeHealth:
    """跨运行持久的健康度状态：连续返回空结果的次数。

    阈值触发「疑似被封」告警（BOSS 等反爬站点在 IP/账号被风控时，常表现为
    「请求成功但返回 0 条」而非报错）。与单次 health_check 的 silent_rot 互补：
    silent_rot 看单次，ScrapeHealth 看趋势（连续多次才告警，降低误报）。
    """

    path: Path
    state: dict[str, dict] = field(default_factory=dict)  # portal -> {"consecutive_empty": int, "last_run": str}
    threshold: int = 3

    @classmethod
    def load(cls, path: str | Path, threshold: int = 3) -> "ScrapeHealth":
        p = Path(path)
        state: dict[str, dict] = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                state = data.get("portals", {}) if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                state = {}
        return cls(path=p, state=state, threshold=threshold)

    def record(self, portal: str, n_fetched: int) -> dict:
        """记录本次抓取结果，返回告警信息。

        返回: {"consecutive_empty": int, "suspected_blocked": bool, "message": str}
        """
        entry = self.state.get(portal, {"consecutive_empty": 0, "last_run": ""})
        if n_fetched == 0:
            entry["consecutive_empty"] = entry.get("consecutive_empty", 0) + 1
        else:
            entry["consecutive_empty"] = 0
        entry["last_run"] = "run"
        self.state[portal] = entry
        ce = entry["consecutive_empty"]
        if ce >= self.threshold:
            return {
                "consecutive_empty": ce,
                "suspected_blocked": True,
                "message": (
                    f"[{portal}] 连续 {ce} 次抓取返回 0 条：疑似被风控/封禁"
                    f"（非报错但无数据）。建议检查登录态、更换网络/IP、待风控解除后再试"
                ),
            }
        return {"consecutive_empty": ce, "suspected_blocked": False, "message": ""}

    def save(self) -> None:
        out = {"portals": self.state, "threshold": self.threshold}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 轻量 HTML 树解析（stdlib-only，避免 bs4 依赖）
# 供 requests 型后端（shixiseng / nowcoder 等）做字段提取，离线可测。
# ---------------------------------------------------------------------------

class _HTMLNode:
    """极简 DOM 节点：仅服务卡片/链接提取所需。"""

    __slots__ = ("tag", "attrs", "text", "children", "parent")

    def __init__(self, tag: str, attrs, parent: "_HTMLNode | None"):
        self.tag = tag
        self.attrs = dict(attrs) if attrs else {}
        self.text = ""
        self.children: list["_HTMLNode"] = []
        self.parent = parent

    @property
    def classes(self) -> list[str]:
        c = self.attrs.get("class")
        if isinstance(c, str):
            return c.split()
        return list(c or [])

    def has_class(self, kw: str) -> bool:
        return any(kw.lower() in cl.lower() for cl in self.classes)

    def full_text(self) -> str:
        parts: list[str] = []

        def walk(n: "_HTMLNode") -> None:
            if n.text:
                parts.append(n.text)
            for c in n.children:
                walk(c)

        walk(self)
        return "".join(parts).strip()


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _HTMLNode("#root", {}, None)
        self._stack: list[_HTMLNode] = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _HTMLNode(tag, attrs, self._stack[-1])
        self._stack[-1].children.append(node)
        self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _HTMLNode(tag, attrs, self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        # 弹到栈中第一个同 tag 的节点为止（容忍未闭合/错序标签）
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                self._stack[:] = self._stack[:i]
                break

    def handle_data(self, data):
        self._stack[-1].text += data


def parse_html_tree(html: str) -> _HTMLNode:
    """把 HTML 解析为轻量树；返回根节点（tag='#root'）。"""
    tb = _TreeBuilder()
    try:
        tb.feed(html or "")
    except Exception:
        pass
    tb.close()
    return tb.root


def html_iter(root: _HTMLNode):
    """DFS 遍历所有节点（含 root）。"""
    yield root
    for c in root.children:
        yield from html_iter(c)


def html_find_anchors(root: _HTMLNode, href_substr: str) -> list[_HTMLNode]:
    """返回所有 href 含 substr 的 <a> 节点。"""
    return [n for n in html_iter(root)
            if n.tag == "a" and href_substr in (n.attrs.get("href") or "")]


def html_first_anchor(node: _HTMLNode, href_substr: str) -> "_HTMLNode | None":
    for n in html_iter(node):
        if n.tag == "a" and href_substr in (n.attrs.get("href") or ""):
            return n
    return None


def html_find_by_class(root: _HTMLNode, kw: str) -> list[_HTMLNode]:
    return [n for n in html_iter(root) if n.has_class(kw)]


def html_nearest_by_class(node: _HTMLNode, kw: str, max_up: int = 4) -> "_HTMLNode | None":
    """先在 node 后代里找含 kw class 的节点，再向上找祖先（最多 max_up 层）。"""
    for d in html_iter(node):
        if d is not node and d.has_class(kw):
            return d
    cur = node.parent
    depth = 0
    while cur is not None and depth <= max_up:
        if cur.has_class(kw):
            return cur
        cur = cur.parent
        depth += 1
    return None


def html_text_by_class(node: _HTMLNode, kw: str, max_up: int = 4) -> str:
    hit = html_nearest_by_class(node, kw, max_up)
    return hit.full_text() if hit else ""


# ---------------------------------------------------------------------------
# LinkedIn 内推 / 人脉搜索链接（纯链接，不爬）
# ---------------------------------------------------------------------------

def build_referral_links(company: str, role: str = "") -> dict:
    """生成 LinkedIn 人脉/职位搜索链接，供候选人人肉内推，不自动爬。"""
    q_people = f"{company} {role}".strip()
    q_jobs = f"{company} {role} jobs".strip()
    return {
        "people_search": f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(q_people)}",
        "jobs_search": f"https://www.linkedin.com/search/results/content/?keywords={quote_plus(q_jobs)}",
    }


def build_linkedin_websearch_queries(role: str, city: str = "",
                                     track: str = "intern") -> list[str]:
    """WebSearch 兜底用的查询模板（agent 执行 WebSearch+WebFetch 后 --ingest）。"""
    loc = f" {city}".rstrip()
    if track == "intern":
        return [
            f'site:linkedin.com/jobs "{role}"{loc} 实习',
            f'site:linkedin.com/jobs "{role}"{loc} intern',
        ]
    return [
        f'site:linkedin.com/jobs "{role}"{loc}',
        f'"{role}"{loc} 招聘 site:linkedin.com',
    ]


# ---------------------------------------------------------------------------
# 统一 JOB_MATCHER_FORMAT v1 输出 / 读回
# ---------------------------------------------------------------------------

JOB_FORMAT_HEADER = "# JOB_MATCHER_FORMAT v1"


def save_jobs_format(jobs: list[str], output_file: str | Path,
                     generated_at: str = "") -> int:
    """把若干条「单岗位文本块」按 v1 格式写出（与 fetch_jobs.py 同构）。"""
    p = Path(output_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    blocks = [b.strip() for b in jobs if b and b.strip()]
    lines = [JOB_FORMAT_HEADER]
    if generated_at:
        lines.append(f"# generated_at={generated_at}")
    lines.append(f"# total_jobs={len(blocks)}")
    for i, b in enumerate(blocks, 1):
        lines.append("")
        lines.append(f"--- JOB {i} ---")
        lines.append(b)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(blocks)


def load_jobs_format(path: str | Path) -> list[str]:
    """读回 v1 格式，返回单岗位文本块列表。"""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    blocks: list[str] = []
    cur: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("--- JOB "):
            if in_block and cur:
                blocks.append("\n".join(cur).strip())
            cur, in_block = [], True
            continue
        if in_block:
            cur.append(line)
    if in_block and cur:
        blocks.append("\n".join(cur).strip())
    return blocks


# ---------------------------------------------------------------------------
# Phase 7.2 — 抓取合规：按 portals.yaml 的 rate_limit 主动节流（token bucket）
# ---------------------------------------------------------------------------
import threading  # noqa: E402  (模块尾部追加段，导入位置合法)


def parse_rate_limit(spec) -> "tuple[float, float] | None":
    """解析 portals.yaml 的 rate_limit 字段为 (max_requests, period_seconds)。

    支持格式：
        "30 req/min"     -> (30, 60.0)
        "10 req/min"     -> (10, 60.0)
        "1 req/sec"      -> (1, 1.0)
        "5 req/3min"     -> (5, 180.0)
        "20" (纯数字)     -> (20, 60.0)   # 容错：默认每分钟
        "off" / "" / None -> None          # 不节流
    格式不合法同样返回 None。
    """
    if not spec:
        return None
    s = str(spec).strip().lower()
    if s in ("off", "none", "false", "0", "-", "null"):
        return None
    # 支持 "30 req/min"（隐含 1）与 "5 req/3min"（显式量词）两种写法
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*req\s*/\s*(?:(\d+(?:\.\d+)?)\s*)?(min|sec|s|m|h)\s*$", s)
    if not m:
        m2 = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", s)  # 纯数字容错（默认每分钟）
        if m2:
            return (float(m2.group(1)), 60.0)
        return None
    n = float(m.group(1))
    amount = float(m.group(2)) if m.group(2) else 1.0
    unit = m.group(3)
    period = amount * (1.0 if unit in ("sec", "s") else 60.0 if unit in ("min", "m") else 3600.0)
    if n <= 0 or period <= 0:
        return None
    return (n, period)


class RateLimiter:
    """最简 token-bucket 节流器（纯 stdlib，可注入时钟/睡眠以便测试）。

    - 起始装满 max 个令牌；
    - acquire() 有令牌时立即消费并返回 True；
    - 无令牌时阻塞（sleep）到下一个令牌可用后返回 True；
    - block=False 时无可立取令牌直接返回 False（不阻塞）。
    """

    def __init__(self, max_per_period, period=60.0, *, _time=time.time, _sleep=time.sleep):
        self.max = float(max_per_period)
        self.period = float(period)
        self._time = _time
        self._sleep = _sleep
        self._lock = threading.Lock()
        self._tokens = self.max
        self._last = self._time()

    def acquire(self, block: bool = True) -> bool:
        with self._lock:
            now = self._time()
            elapsed = now - self._last
            self._tokens = min(self.max, self._tokens + elapsed * (self.max / self.period))
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            if not block:
                return False
            need = 1 - self._tokens
            wait = need * (self.period / self.max)
            self._sleep(wait)
            self._tokens = 0.0
            self._last = self._time()
            return True

    @property
    def tokens(self) -> float:
        return self._tokens


def make_portal_limiter(portal: str, portals: dict | None = None,
                        _loader=load_portals) -> "RateLimiter | None":
    """读取 portals.yaml 中某 portal 的 rate_limit，返回 RateLimiter；无/关闭返回 None。"""
    if portals is None:
        portals = _loader()
    spec = (((portals.get("portals") or {}).get(portal) or {}).get("rate_limit"))
    parsed = parse_rate_limit(spec)
    if parsed is None:
        return None
    return RateLimiter(*parsed)


_PORTAL_LIMITERS: dict = {}


def acquire_portal_throttle(portal: str, *, portals: dict | None = None,
                            reset: bool = False) -> None:
    """每次对外请求前调用：若该 portal 配置并启用了 rate_limit 则阻塞节流，否则无操作。

    节流器按 portal 缓存（跨多次请求维持同一 token bucket 状态，这才是节流的意义）。
    reset=True 清空缓存（供测试或同进程长跑复用前重置）。
    """
    if reset:
        _PORTAL_LIMITERS.clear()
        return
    lim = _PORTAL_LIMITERS.get(portal)
    if lim is None:
        lim = make_portal_limiter(portal, portals)
        _PORTAL_LIMITERS[portal] = lim  # 含 None → 之后直接跳过
    if lim is not None:
        lim.acquire()


def reset_portal_throttles() -> None:
    """清空跨请求的 portal 节流缓存（测试用）。"""
    _PORTAL_LIMITERS.clear()
