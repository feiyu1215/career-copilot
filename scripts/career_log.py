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
    python3 career_log.py refresh-profile
    python3 career_log.py stats
    python3 career_log.py forget --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
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

SENSITIVE_PATTERNS = [
    re.compile(r"\b\d{11}\b"),                    # 手机号
    re.compile(r"\b\d{17}[0-9Xx]\b"),             # 身份证
    re.compile(r"(?i)api[_-]?key|secret|token|password|authorization|bearer|sk-[A-Za-z0-9]"),
    re.compile(r"(?i)身份证|手机号|住址|银行卡|密码|密钥|验证码|cookie"),
]

MAX_DATA_CHARS = 5000

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


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


def write_event(event: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


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


def cmd_append(event_type: str, data_str: str) -> None:
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

    event = {"type": event_type, "timestamp": now_iso(), **data}
    write_event(event)
    print(f"appended: {event_type} at {event['timestamp']}")

    # 触发快照刷新
    if event_type in REFRESH_TRIGGERS:
        events = read_all_events()
        profile = generate_profile(events)
        PROFILE_FILE.write_text(profile, encoding="utf-8")
        print("profile refreshed")


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
    events = read_all_events()

    if event_type:
        events = [e for e in events if e.get("type") == event_type]

    if company:
        company_lower = company.lower()
        events = [e for e in events if company_lower in json.dumps(e, ensure_ascii=False).lower()]

    if days:
        cutoff = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)
        cutoff_str = cutoff.isoformat(timespec="seconds")
        events = [e for e in events if e.get("timestamp", "") >= cutoff_str]

    # 最新的在前
    events = list(reversed(events[-limit:]))

    if not events:
        print("no matching events found")
        return

    for e in events:
        print(json.dumps(e, ensure_ascii=False, indent=2))
        print("---")
    print(f"total: {len(events)} events")


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
    timestamps = [e.get("timestamp", "") for e in events if e.get("timestamp")]

    print(f"total events: {len(events)}")
    print(f"time range: {min(timestamps)} → {max(timestamps)}" if timestamps else "")
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

    sub.add_parser("profile", help="显示当前画像快照")

    query_p = sub.add_parser("query", help="按条件查询事件")
    query_p.add_argument("--type", default=None, help="按事件类型筛选")
    query_p.add_argument("--company", default=None, help="按公司名筛选（模糊匹配）")
    query_p.add_argument("--limit", type=int, default=10, help="返回条数上限（默认10）")
    query_p.add_argument("--days", type=int, default=None, help="只看最近N天")

    sub.add_parser("refresh-profile", help="重新生成画像快照")
    sub.add_parser("stats", help="显示统计信息")

    forget_p = sub.add_parser("forget", help="删除所有记忆")
    forget_p.add_argument("--confirm", action="store_true", help="确认删除")

    args = parser.parse_args()

    try:
        if args.cmd == "init":
            cmd_init()
        elif args.cmd == "append":
            cmd_append(args.type, args.data)
        elif args.cmd == "profile":
            cmd_profile()
        elif args.cmd == "query":
            cmd_query(args.type, args.company, args.limit, args.days)
        elif args.cmd == "refresh-profile":
            cmd_refresh_profile()
        elif args.cmd == "stats":
            cmd_stats()
        elif args.cmd == "forget":
            cmd_forget(args.confirm)
    except ValueError as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
