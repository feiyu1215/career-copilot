#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 8.3 智能投递时机建议 — first_seen 追踪 + 时机建议（纯本地、零 LLM）。

功能：
  - 以「归一化岗位标题」为稳定身份，跨轮持久化每个岗位首次出现的时间 first_seen_at
  - 基于 first_seen_at 与当前时间，给出投递紧迫度建议：
      * fresh ：刚挂出（< fresh_window_h 小时）→ 「建议 X 小时内投递」
      * normal：仍有效（介于 fresh 与 stale 之间）
      * stale ：可能已关闭/下架（> stale_days 天）

设计要点：
  - 岗位身份用 normalize_key(title)（复用 diff_watch.normalize_title），
    避免同一岗位因序号变化（JOB_3↔JOB_7）而丢失首见时间。
  - store 以「追加/覆盖」语义持久化到 JSON 文件，失败容错、不阻断主流程。
  - 所有时间函数支持注入 now（测试可确定性验证）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 默认阈值（可调）
DEFAULT_FRESH_WINDOW_H = 48      # 48 小时内视为「新鲜，建议尽快投递」
DEFAULT_STALE_DAYS = 7           # 超过 7 天视为「可能已关闭」


# --------------------------------------------------------------------------- #
# 归一化（岗位身份）
# --------------------------------------------------------------------------- #
def normalize_key(title: str) -> str:
    """归一化岗位标题，作为跨轮稳定的身份键。"""
    try:
        from diff_watch import normalize_title
        return normalize_title(title)
    except Exception:
        # 兜底：diff_watch 不可用时自行归一化（与 diff_watch.normalize_title 同语义）
        t = (title or "").lower().strip()
        t = re.sub(r"\(.*?\)", " ", t)        # 去掉括号内容
        t = re.sub(r"[\s\-_/]+", " ", t)      # 空白/连字符统一为空格
        return t.strip()


# --------------------------------------------------------------------------- #
# store 读写
# --------------------------------------------------------------------------- #
def load_store(path: str) -> dict:
    """读取 first_seen store，返回 {normalized_key: first_seen_at_iso}。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("first_seen"), dict):
            return data["first_seen"]
        return {}
    except Exception:
        return {}


def save_store(path: str, store: dict) -> None:
    """持久化 first_seen store。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"first_seen": store}, ensure_ascii=False, indent=2),
                 encoding="utf-8")


# --------------------------------------------------------------------------- #
# 记录
# --------------------------------------------------------------------------- #
def record_first_seen(store: dict, jobs: list[dict],
                      now: Optional[datetime] = None) -> tuple[dict, dict]:
    """记录一轮岗位的首见时间。

    - 新键（首次出现）写入 now（默认当前时间）
    - 已有键（再次出现）保留原始 first_seen_at

    Returns:
        (store, map)：更新后的 store 与 {job_id: first_seen_at} 映射
    """
    if now is None:
        now = datetime.now()
    now_iso = now.isoformat()
    fs_map: dict[str, str] = {}
    for job in jobs:
        key = normalize_key(job.get("title", ""))
        if not key:
            continue
        if key not in store:
            store[key] = now_iso
        fs_map[job.get("job_id", "")] = store[key]
    return store, fs_map


# --------------------------------------------------------------------------- #
# 时机建议
# --------------------------------------------------------------------------- #
def timing_advice(first_seen_at: Optional[str],
                  now: Optional[datetime] = None,
                  fresh_window_h: int = DEFAULT_FRESH_WINDOW_H,
                  stale_days: int = DEFAULT_STALE_DAYS) -> Optional[dict]:
    """基于 first_seen_at 给出投递时机建议。无 first_seen_at 返回 None。"""
    if not first_seen_at:
        return None
    if now is None:
        now = datetime.now()
    try:
        seen = datetime.fromisoformat(first_seen_at)
    except Exception:
        return None

    delta_h = (now - seen).total_seconds() / 3600.0
    days_since = delta_h / 24.0
    hours_since = int(delta_h)
    hours_remaining = max(0, int(fresh_window_h - delta_h))

    if delta_h < fresh_window_h:
        urgency = "fresh"
        label = f"建议 {hours_remaining}h 内投递（新挂出 {hours_since}h）"
    elif days_since > stale_days:
        urgency = "stale"
        label = f"挂出 {days_since:.0f}d，可能已关闭/下架"
    else:
        urgency = "normal"
        label = f"已挂出 {days_since:.0f}d，仍可正常投递"

    return {
        "urgency": urgency,
        "label": label,
        "first_seen_at": first_seen_at,
        "hours_since": hours_since,
        "days_since": round(days_since, 1),
        "hours_remaining": hours_remaining,
    }


def render_timing_badge(job: dict, now: Optional[datetime] = None) -> str:
    """渲染岗位卡片上的时机徽标（无 first_seen_at 返回空字符串）。"""
    advice = timing_advice(job.get("first_seen_at"), now=now)
    if not advice:
        return ""
    cls = {
        "fresh": "badge-urgent",
        "normal": "badge-timing",
        "stale": "badge-stale",
    }.get(advice["urgency"], "badge-timing")
    icon = {"fresh": "⏰", "normal": "🟡", "stale": "💤"}.get(advice["urgency"], "")
    return (f'<span class="{cls}">{_esc(icon)} {_esc(advice["label"])}</span>')


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 8.3 first_seen 追踪与时机建议")
    sub = ap.add_subparsers(dest="cmd")

    p_rec = sub.add_parser("record", help="记录一轮 jobs_raw 的首见时间")
    p_rec.add_argument("--jobs-raw", required=True, help="jobs_raw.txt 路径")
    p_rec.add_argument("--store", required=True, help="first_seen store JSON 路径")
    p_rec.add_argument("--date", default=None, help="首见时间 YYYY-MM-DD（默认现在）")

    p_adv = sub.add_parser("show", help="查看某首见时间的时机建议")
    p_adv.add_argument("--first-seen-at", required=True, help="ISO 时间戳")
    p_adv.add_argument("--now", default=None, help="当前时间 ISO（默认现在）")

    args = ap.parse_args(argv)

    if args.cmd == "record":
        from smart_score import parse_jobs_raw
        jobs = parse_jobs_raw(args.jobs_raw)
        now = datetime.fromisoformat(args.date) if args.date else datetime.now()
        store = load_store(args.store)
        store, fs_map = record_first_seen(store, jobs, now=now)
        save_store(args.store, store)
        print(f"[first_seen] 已记录 {len(fs_map)} 个岗位首见时间 → {args.store}")
        for jid, fs in fs_map.items():
            print(f"  {jid}: {fs}")
        return 0

    if args.cmd == "show":
        fs_at = args.first_seen_at
        now = datetime.fromisoformat(args.now) if args.now else datetime.now()
        advice = timing_advice(fs_at, now=now)
        print(json.dumps(advice, ensure_ascii=False, indent=2) if advice
              else "无 first_seen_at")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
