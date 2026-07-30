#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Career Copilot 职业记忆管理脚本

管理 JSONL 格式的职业记忆日志，支持事件追加、条件查询、快照生成。

存储位置：
- 主日志：~/.catpaw/career-copilot/career-log.jsonl
- 快照：~/.catpaw/career-copilot/career-profile.md

用法：
    python3 career_log.py init
    python3 career_log.py append --type interview_done --data '{"company":"字节","role":"AI产品","result":"pass"}'
    python3 career_log.py profile
    python3 career_log.py query --type interview_done --limit 5
    python3 career_log.py query --company 字节 --days 30
    python3 career_log.py trace --company 字节 --limit 20
    python3 career_log.py expire --older-than-days 365
    python3 career_log.py refresh-profile
    python3 career_log.py stats
    python3 career_log.py forget --confirm

每条事件自动带信封字段（T14）：
    - event_id：UUID4，全局唯一
    - session_id：单次进程/会话 ID（可用环境变量 CAREER_SESSION_ID 关联）
    - status：active / expired / superseded（expire 命令可置 expired）
    - expires_at：默认保留期（RETENTION_DAYS=365 天）后的过期时间戳
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

BASE_DIR = Path(os.getenv("CAREER_COPILOT_DIR", Path.home() / ".catpaw" / "career-copilot"))
LOG_FILE = BASE_DIR / "career-log.jsonl"
PROFILE_FILE = BASE_DIR / "career-profile.md"

VALID_TYPES = {
    "match_round",
    "interview_prep",
    "interview_done",
    "resume_update",
    "offer_received",
    "decision",
    "reflection",
    "profile_update",
}

# 触发快照刷新的事件类型
REFRESH_TRIGGERS = {"match_round", "interview_done", "offer_received", "decision"}

# ── T14：Career Log v2 新增 ──
VALID_STATUSES = {"active", "expired", "superseded"}

# 事件保留期（天）：超过后状态可被 expire 标记为 expired（记忆时序感知）
RETENTION_DAYS = 365

# 单次进程内共享的 session_id；可通过环境变量 CAREER_SESSION_ID 跨进程关联
SESSION_ID = os.environ.get("CAREER_SESSION_ID") or uuid.uuid4().hex

# 逐类 schema：约束「必填字段」，缺失则拒绝写入（与敏感信息检查一致的 fail-fast 哲学）
EVENT_SCHEMAS: dict[str, dict] = {
    "match_round":     {"required": ["direction_anchors"]},
    "interview_prep":  {"required": ["company", "role"]},
    "interview_done":  {"required": ["company", "result"]},
    "resume_update":   {"required": ["version"]},
    "offer_received":  {"required": ["company"]},
    "decision":        {"required": ["company", "choice"]},
    "reflection":      {"required": ["insights"]},
    "profile_update":  {"required": []},
}

SENSITIVE_PATTERNS = [
    re.compile(r"(?<!\d)\d{11}(?!\d)"),           # 手机号（CJK 相邻也匹配，不依赖 \b 词边界）
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),    # 身份证（同上，CJK 相邻也匹配）
    re.compile(r"(?i)api[_-]?key|secret|token|password|authorization|bearer|sk-[A-Za-z0-9_-]+"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # email 地址
    re.compile(r"(?i)身份证|手机号|住址|银行卡|密码|密钥|验证码|cookie"),
]

# ⚠️ 已知局限（defense-in-depth，非硬保证，切勿作为唯一隐私屏障）：
# 1) `sk-[A-Za-z0-9_-]+` 已整串遮 OpenAI/Agnes 类 `sk-` 长 key（含 `sk-proj-…` 带 dash 格式；P1 已修：原为 `sk-[A-Za-z0-9]` 只遮首字符）。
# 2) api_key|secret|token|password|authorization|bearer 仅遮「词」不遮「值」，
#    如 `Bearer eyJ...` 只遮 Bearer 一词、token 整串泄露。强保证需值捕获正则或外部 DLP。
# 调用方须知：本表是兜底脱敏，生产 transcript 仍须先人工确认无 PII 再使用 --no-redact。

MAX_DATA_CHARS = 5000

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def expires_at_iso() -> str:
    """默认保留期后的过期时间戳（isoformat，秒精度）。"""
    return (_now() + timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")


def check_sensitive(text: str) -> None:
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            raise ValueError("检测到疑似敏感信息，已拒绝写入")


def read_all_events() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    events = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def validate_event(event_type: str, data: dict) -> None:
    """T14：逐类 schema 校验。缺失必填字段即拒绝（fail-fast）。"""
    schema = EVENT_SCHEMAS.get(event_type)
    if schema is None:
        return  # 未知类型由调用方在 VALID_TYPES 检查，这里不重复
    missing = [f for f in schema.get("required", []) if f not in data]
    if missing:
        raise ValueError(
            f"事件类型 '{event_type}' 缺少必填字段: {missing}。"
            f"所需字段: {schema['required']}"
        )


def write_event(event: dict) -> None:
    """写入一条事件。T14：自动补齐信封字段（event_id/session_id/status/expires_at）。"""
    event.setdefault("event_id", uuid.uuid4().hex)
    event.setdefault("session_id", SESSION_ID)
    event.setdefault("status", "active")
    event.setdefault("expires_at", expires_at_iso())
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────
# T14：内存索引（by_type / by_company / by_status）
# ──────────────────────────────────────────────

class EventIndex:
    """对一批事件建立内存索引，支持按 type/company/status 交查询，O(1) 命中。"""

    def __init__(self, events: list[dict]):
        self.by_type: dict[str, list[dict]] = defaultdict(list)
        self.by_company: dict[str, list[dict]] = defaultdict(list)
        self.by_status: dict[str, list[dict]] = defaultdict(list)
        for e in events:
            self.by_type[e.get("type")].append(e)
            c = e.get("company")
            if c:
                self.by_company[c].append(e)
            self.by_status[e.get("status", "active")].append(e)

    def query(self, type: str | None = None, company: str | None = None,
              status: str | None = None) -> list[dict]:
        """返回同时满足各条件（AND）的事件，按时间倒序。"""
        pools = []
        if type is not None:
            pools.append(self.by_type.get(type, []))
        if company is not None:
            pools.append(self.by_company.get(company, []))
        if status is not None:
            pools.append(self.by_status.get(status, []))
        if not pools:
            # 无过滤 → 返回全部事件，按时间倒序
            all_events = [e for lst in self.by_type.values() for e in lst]
            return sorted(all_events, key=lambda e: e.get("timestamp", ""), reverse=True)
        if len(pools) == 1:
            result = list(pools[0])
        else:
            # dict 不可哈希 → 用对象身份 id() 求交（兼容无 event_id 的旧日志）
            id_sets = [{id(e) for e in pool} for pool in pools]
            common = set.intersection(*id_sets)
            result = [e for e in pools[0] if id(e) in common]
        return sorted(result, key=lambda e: e.get("timestamp", ""), reverse=True)


def build_index() -> EventIndex:
    return EventIndex(read_all_events())


# ──────────────────────────────────────────────
# 快照生成
# ──────────────────────────────────────────────

def generate_profile(events: list[dict]) -> str:
    """从事件日志聚合生成 career-profile.md"""

    # 统计
    type_counts = Counter(e.get("type") for e in events)
    interview_results = [e for e in events if e.get("type") == "interview_done"]
    pass_count = sum(1 for e in interview_results if e.get("result") == "pass")
    total_interviews = len(interview_results)

    # 最新方向
    match_rounds = [e for e in events if e.get("type") == "match_round"]
    direction = "未确定"
    if match_rounds:
        latest = match_rounds[-1]
        anchors = latest.get("direction_anchors", [])
        if anchors:
            direction = "、".join(anchors[:3])

    # 活跃公司
    recent_companies = set()
    for e in reversed(events[-50:]):
        company = e.get("company")
        if company:
            recent_companies.add(company)
        if len(recent_companies) >= 5:
            break

    # 高频优势和待提升
    strengths: Counter = Counter()
    weaknesses: Counter = Counter()
    for e in events:
        if e.get("type") == "match_round":
            for m in e.get("top_matches", []):
                for r in m.get("match_reasons", []):
                    strengths[r] += 1
                for r in m.get("risks", []):
                    weaknesses[r] += 1
        if e.get("type") == "interview_done":
            for w in e.get("weak_points", []):
                weaknesses[w] += 1

    # 关键洞察
    insights = []
    for e in reversed(events):
        if e.get("type") == "reflection":
            for ins in e.get("insights", []):
                insights.append(ins)
        if e.get("type") == "interview_done":
            for l in e.get("learnings", []):
                insights.append(l)
        if len(insights) >= 5:
            break

    # 当前阶段推断
    offer_count = type_counts.get("offer_received", 0)
    if offer_count > 0:
        stage = "决策（已有 offer）"
    elif total_interviews > 0:
        stage = "面试中"
    elif match_rounds:
        stage = "投递/探索"
    else:
        stage = "初始"

    # 生成 markdown
    lines = [
        "# Career Profile（自动生成，勿手动编辑）",
        "",
        f"> 最后更新：{now_iso()}",
        "",
        "## 当前状态",
        f"- 阶段：{stage}",
        f"- 目标方向：{direction}",
        f"- 活跃公司：{', '.join(recent_companies) if recent_companies else '暂无'}",
        "",
        "## 能力画像摘要",
        f"- 核心优势：{', '.join(s for s, _ in strengths.most_common(5)) if strengths else '待积累'}",
        f"- 待提升：{', '.join(s for s, _ in weaknesses.most_common(5)) if weaknesses else '待积累'}",
        "",
        "## 求职历程统计",
        f"- 匹配轮次：{type_counts.get('match_round', 0)}",
        f"- 面试次数：{total_interviews}",
        f"- 面试通过率：{pass_count}/{total_interviews} ({pass_count*100//total_interviews}%)" if total_interviews > 0 else "- 面试通过率：暂无数据",
        f"- 简历版本：{type_counts.get('resume_update', 0)}",
        f"- Offer 数：{offer_count}",
        "",
        "## 关键洞察",
    ]
    if insights:
        for ins in insights[:5]:
            lines.append(f"- {ins}")
    else:
        lines.append("- 暂无（完成面试复盘后自动积累）")

    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────
# 命令实现
# ──────────────────────────────────────────────

def cmd_init() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text("", encoding="utf-8")
    if not PROFILE_FILE.exists():
        profile = generate_profile([])
        PROFILE_FILE.write_text(profile, encoding="utf-8")
    print(f"initialized: {BASE_DIR}")
    print(f"  log: {LOG_FILE}")
    print(f"  profile: {PROFILE_FILE}")


def cmd_append(event_type: str, data_str: str, competitiveness_store: str | None = None) -> None:
    if event_type not in VALID_TYPES:
        print(f"error: invalid type '{event_type}'. Valid: {sorted(VALID_TYPES)}")
        sys.exit(1)

    if len(data_str) > MAX_DATA_CHARS:
        print(f"error: data too long ({len(data_str)} chars, max {MAX_DATA_CHARS})")
        sys.exit(1)

    check_sensitive(data_str)

    try:
        data = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}")
        sys.exit(1)

    validate_event(event_type, data)

    event = {"type": event_type, "timestamp": now_iso(), **data}
    write_event(event)
    print(f"appended: {event_type} at {event['timestamp']} (event_id={event['event_id']}, status={event['status']})")

    # 触发快照刷新
    if event_type in REFRESH_TRIGGERS:
        events = read_all_events()
        profile = generate_profile(events)
        PROFILE_FILE.write_text(profile, encoding="utf-8")
        print("profile refreshed")

    # Phase 8.2：interview_done 后自动重评竞争力（opt-in：需显式路径或环境变量；任何失败均跳过）
    comp_store = competitiveness_store or os.environ.get("CAREER_COMPETITIVENESS_STORE")
    if event_type == "interview_done" and comp_store:
        try:
            from competitiveness_tracker import recompute_after_event
            current, delta = recompute_after_event(event, career_log_path=str(LOG_FILE), store_path=comp_store)
            print(f"[competitiveness] 已重评竞争力（{current['period']}） → {comp_store}")
            if delta is not None:
                print(f"[competitiveness] 较 {delta['from_period']} 总评 {delta['overall_delta']:+.1f}")
        except Exception as e:
            print(f"[competitiveness] 重评失败（跳过）: {e}")


def cmd_profile() -> None:
    if not PROFILE_FILE.exists():
        print("profile not found. Run 'init' first.")
        sys.exit(1)
    print(PROFILE_FILE.read_text(encoding="utf-8"))


def cmd_query(
    event_type: str | None,
    company: str | None,
    limit: int,
    days: int | None,
) -> None:
    idx = build_index()

    events = idx.query(type=event_type, company=company, status=None)

    if days:
        cutoff = _now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat(timespec="seconds")
        events = [e for e in events if e.get("timestamp", "") >= cutoff_str]

    # 最新的在前（idx.query 已倒序，这里再裁 limit）
    events = events[:limit]

    if not events:
        print("no matching events found")
        return

    for e in events:
        print(json.dumps(e, ensure_ascii=False, indent=2))
        print("---")
    print(f"total: {len(events)} events")


def cmd_trace(company: str | None, event_type: str | None, limit: int) -> None:
    """T14：时间线追踪——按公司/类型梳理事件脉络（含 event_id / status）。"""
    idx = build_index()
    events = idx.query(type=event_type, company=company, status=None)
    events = events[:limit] if limit else events

    if not events:
        print("no matching events found")
        return

    print(f"# Trace（company={company}, type={event_type}, {len(events)} events）")
    for e in events:
        ts = e.get("timestamp", "?")
        et = e.get("type", "?")
        eid = e.get("event_id", "?")[:8]
        status = e.get("status", "active")
        extra = e.get("company") or e.get("role") or ""
        print(f"- [{ts}] {et} | id={eid} | {status} | {extra}")
    print(f"total: {len(events)} events")


def cmd_expire(older_than_days: int | None, company: str | None) -> None:
    """T14：将满足条件的 active 事件标记为 expired（记忆时序感知）。"""
    events = read_all_events()
    changed = 0
    cutoff_str = None
    if older_than_days is not None:
        cutoff = _now() - timedelta(days=older_than_days)
        cutoff_str = cutoff.isoformat(timespec="seconds")

    for e in events:
        if e.get("status", "active") != "active":
            continue
        if cutoff_str is not None and e.get("timestamp", "") >= cutoff_str:
            continue
        if company is not None and e.get("company") != company:
            continue
        e["status"] = "expired"
        changed += 1

    if changed == 0:
        print("no events to expire")
        return

    # 整体回写（保留 event_id 等其它字段）
    LOG_FILE.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        encoding="utf-8",
    )
    print(f"expired {changed} event(s)")


def cmd_refresh_profile() -> None:
    events = read_all_events()
    profile = generate_profile(events)
    PROFILE_FILE.write_text(profile, encoding="utf-8")
    print(f"profile refreshed ({len(events)} events processed)")


def cmd_stats() -> None:
    events = read_all_events()
    if not events:
        print("no events recorded yet")
        return

    type_counts = Counter(e.get("type") for e in events)
    status_counts = Counter(e.get("status", "active") for e in events)
    timestamps = [e.get("timestamp", "") for e in events if e.get("timestamp")]

    print(f"total events: {len(events)}")
    print(f"time range: {min(timestamps)} → {max(timestamps)}" if timestamps else "")
    print(f"\nby status:")
    for s, c in status_counts.most_common():
        print(f"  {s}: {c}")
    print("\nby type:")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    companies = set()
    for e in events:
        if c := e.get("company"):
            companies.add(c)
    if companies:
        print(f"\ncompanies mentioned: {', '.join(sorted(companies))}")


def cmd_forget(confirm: bool) -> None:
    if not confirm:
        print("error: pass --confirm to delete all career memory")
        sys.exit(1)
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    if PROFILE_FILE.exists():
        PROFILE_FILE.unlink()
    print(f"all career memory deleted from {BASE_DIR}")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Career Copilot 职业记忆管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化记忆存储")

    append_p = sub.add_parser("append", help="追加一条事件")
    append_p.add_argument("--type", required=True, help=f"事件类型: {sorted(VALID_TYPES)}")
    append_p.add_argument("--data", required=True, help="JSON 格式的事件数据")
    append_p.add_argument("--competitiveness-store", dest="competitiveness_store", default=None,
                          help="Phase 8.2 竞争力快照库路径；interview_done 后自动重评（默认读环境变量 CAREER_COMPETITIVENESS_STORE）")

    sub.add_parser("profile", help="显示当前画像快照")

    query_p = sub.add_parser("query", help="按条件查询事件")
    query_p.add_argument("--type", default=None, help="按事件类型筛选")
    query_p.add_argument("--company", default=None, help="按公司名精确筛选（需与记录中的公司名完全一致）")
    query_p.add_argument("--limit", type=int, default=10, help="返回条数上限（默认10）")
    query_p.add_argument("--days", type=int, default=None, help="只看最近N天")

    sub.add_parser("refresh-profile", help="重新生成画像快照")
    sub.add_parser("stats", help="显示统计信息")

    trace_p = sub.add_parser("trace", help="时间线追踪（按公司/类型梳理事件脉络）")
    trace_p.add_argument("--company", default=None, help="按公司名筛选")
    trace_p.add_argument("--type", dest="trace_type", default=None, help="按事件类型筛选")
    trace_p.add_argument("--limit", type=int, default=50, help="返回条数上限（默认50）")

    expire_p = sub.add_parser("expire", help="将满足条件的 active 事件标记为 expired")
    expire_p.add_argument("--older-than-days", type=int, default=None, help="仅过期早于 N 天的事件")
    expire_p.add_argument("--company", default=None, help="仅过期指定公司的事件")

    forget_p = sub.add_parser("forget", help="删除所有记忆")
    forget_p.add_argument("--confirm", action="store_true", help="确认删除")

    args = parser.parse_args()

    try:
        if args.cmd == "init":
            cmd_init()
        elif args.cmd == "append":
            cmd_append(args.type, args.data, getattr(args, "competitiveness_store", None))
        elif args.cmd == "profile":
            cmd_profile()
        elif args.cmd == "query":
            cmd_query(args.type, args.company, args.limit, args.days)
        elif args.cmd == "refresh-profile":
            cmd_refresh_profile()
        elif args.cmd == "stats":
            cmd_stats()
        elif args.cmd == "trace":
            cmd_trace(args.company, args.trace_type, args.limit)
        elif args.cmd == "expire":
            cmd_expire(args.older_than_days, args.company)
        elif args.cmd == "forget":
            cmd_forget(args.confirm)
    except ValueError as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
