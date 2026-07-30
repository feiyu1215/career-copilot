#!/usr/bin/env python3
"""检查 notes/ 下文档的评审新鲜度（过期自动视为「待复核」）。

规则：每个 notes/*.md 应在文件头部包含一行
    <!-- last_reviewed: YYYY-MM-DD | review_cycle_days: 90 -->
超过 review_cycle_days 天未评审 → 视为「待复核」；缺该头 → 视为「缺失评审头，待复核」。

用法：
    python scripts/check_notes_freshness.py [notes_dir] [--strict]
    --strict : 存在过期/缺失时退出码为 1（可作为 CI / pre-commit 门禁）。
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "notes"
HEADER_RE = re.compile(r"last_reviewed:\s*(\d{4}-\d{2}-\d{2})")
CYCLE_RE = re.compile(r"review_cycle_days:\s*(\d+)")
TODAY = date.today()


def main(argv=None) -> int:
    args = argv or sys.argv[1:]
    strict = "--strict" in args
    dirs = [a for a in args if not a.startswith("--")]
    base = Path(dirs[0]) if dirs else DEFAULT_DIR

    stale, missing, ok = [], [], []
    for p in sorted(base.glob("*.md")):
        if p.name.endswith(".archived.md"):
            continue  # 已归档文档不纳入评审周期
        text = p.read_text(encoding="utf-8")
        head = text[:2000]  # 只扫头部，避免误读正文里的相同字样
        m_date = HEADER_RE.search(head)
        m_cycle = CYCLE_RE.search(head)
        if not m_date:
            missing.append(p.name)
            continue
        reviewed = datetime.strptime(m_date.group(1), "%Y-%m-%d").date()
        cycle = int(m_cycle.group(1)) if m_cycle else 90
        age = (TODAY - reviewed).days
        if age > cycle:
            stale.append((p.name, reviewed.isoformat(), age, cycle))
        else:
            ok.append(p.name)

    print(f"评审新鲜度检查：{base}  (今天是 {TODAY.isoformat()})")
    print(f"  通过（在周期内）：{len(ok)} 个")
    for n in ok:
        print(f"    ✓ {n}")
    if stale:
        print(f"\n  待复核（已过期）：{len(stale)} 个")
        for n, d, age, cycle in stale:
            print(f"    ⚠ {n}  最后评审 {d}，已 {age} 天（周期 {cycle} 天）")
    if missing:
        print(f"\n  缺失评审头：{len(missing)} 个")
        for n in missing:
            print(f"    ✗ {n}  无 last_reviewed 头")

    if stale or missing:
        print("\n结论：存在待复核文档。请更新其头部 last_reviewed 后重试。")
        return 1 if strict else 0
    print("\n结论：全部文档在评审周期内。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
