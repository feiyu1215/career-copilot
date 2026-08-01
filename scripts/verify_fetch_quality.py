#!/usr/bin/env python3
"""
verify_fetch_quality.py — 抓取结果质量守门（Phase 4.3）的契约化校验 CLI

对齐 verify_ats.py / verify_output.py 的「确定性检查（无 LLM）」风格：
对一批抓取结果逐条准入校验，拦截字段缺失 / 占位符 / 损坏 URL / 批内重复的废卡，
只放行能进入下游（smart_score / diff_watch / job_tracker）的有效记录。

检查项（契约号 [QG#]）：
  [QG1] MISSING_TITLE     标题缺失/空
  [QG2] MISSING_COMPANY   公司缺失/空（--allow-missing-company 可放宽）
  [QG3] MISSING_IDENTITY  既无 URL 又无（公司+标题），无法定位/去重
  [QG4] INVALID_URL       URL 形态损坏（含空白 / 占位符 / 死链）
  [QG5] PLACEHOLDER       标题或公司为占位符（无信息量）
  [QG6] DUPLICATE         批内重复（同一条岗位出现多次）
  [W-Q1..3] 软警告（薪资/地点/JD 缺失），不硬失败

输入：JSON（list[dict] 或 {"jobs": [...]}）或 v1 文本块（--- JOB N ---）。
退出码：
  0 = 全部通过（含仅 [W] 软警告）
  1 = 存在硬拦截 [QG#]，或拒绝率超过 --max-reject-rate
  2 = 输入无法读取/解析

使用方式：
  python3 verify_fetch_quality.py --input jobs_raw.json
  python3 verify_fetch_quality.py --input batch_jobs.txt --max-reject-rate 0.1
  python3 verify_fetch_quality.py --input jobs.json --allow-missing-company --report qg.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from job_common import load_jobs_format, quality_gate  # noqa: E402

_URL_RE = re.compile(r"\[URL\](.*?)\[/URL\]", re.S)


def _read_records(input_path: str) -> list[dict] | None:
    """读取岗位记录；返回 list[dict] 或 None（读取/解析失败）。"""
    p = Path(input_path)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    # 先尝试 JSON
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        data = None
    if data is not None:
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            jobs = data.get("jobs")
            if isinstance(jobs, list):
                return [d for d in jobs if isinstance(d, dict)]
        # JSON 但结构无法识别
        return None
    # 回退 v1 文本块解析
    blocks = load_jobs_format(p)
    if not blocks:
        raw = text.strip()
        if raw:
            blocks = [raw]
    out: list[dict] = []
    for b in blocks:
        title, url, company, location = "", "", "", ""
        jd_lines: list[str] = []
        for ln in b.split("\n"):
            s = ln.strip()
            if not s:
                continue
            low = s.lower()
            if low.startswith("company:"):
                company = s[len("company:"):].strip()
                continue
            if low.startswith("location:"):
                location = s[len("location:"):].strip()
                continue
            m = _URL_RE.search(s)
            if m and not url:
                url = m.group(1).strip()
                continue
            if not title:
                title = s
            else:
                jd_lines.append(s)
        out.append({"title": title, "url": url, "company": company,
                    "location": location, "jd": "\n".join(jd_lines)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="抓取结果质量守门（Phase 4.3）")
    ap.add_argument("--input", required=True, help="岗位记录文件（JSON 或 v1 文本）")
    ap.add_argument("--allow-missing-company", action="store_true",
                    help="放宽 [QG2]：允许公司缺失（部分门户无公司字段）")
    ap.add_argument("--max-reject-rate", type=float, default=0.0,
                    help="最大可接受的拒绝率（0.0=任何硬拦截都失败，默认严苛）")
    ap.add_argument("--report", default=None, help="写出守门报告 JSON 的路径")
    ap.add_argument("--source", default="", help="记录来源标识（用于身份键/报告）")
    ap.add_argument("--max-warning-rate", type=float, default=None,
                    help="软警告率（软警告总数/总条数）上限；超过则告警（默认不限制）")
    ap.add_argument("--warnings-fatal", action="store_true",
                    help="软警告率超 --max-warning-rate 时一并判定为失败（exit 1）")
    args = ap.parse_args(argv)

    records = _read_records(args.input)
    if records is None:
        print(f"[verify_fetch_quality] 无法读取/解析输入：{args.input}", file=sys.stderr)
        return 2

    result = quality_gate(records, source=args.source,
                          require_company=not args.allow_missing_company)
    st = result["stats"]
    accepted, rejected = st["accepted"], st["rejected"]
    warning_rate = st.get("warning_rate", 0.0)

    print(f"[verify_fetch_quality] 总计 {st['total']} 条 | "
          f"通过 {accepted} | 拦截 {rejected} | 接受率 {st['accept_rate']:.0%}",
          file=sys.stderr)
    for code, cnt in st["by_code"].items():
        print(f"  [硬拦截] {code}: {cnt} 条", file=sys.stderr)
    if st["warnings"]:
        print(f"  [软警告] {st['warnings']}（告警率 {warning_rate:.0%}）", file=sys.stderr)

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({
            "stats": st,
            "warning_rate": warning_rate,
            "rejected": [{"reason_codes": [r["code"] for r in it["reasons"]],
                          "record": it["record"]} for it in result["rejected"]],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[verify_fetch_quality] 报告 → {args.report}", file=sys.stderr)

    # 硬拦截：任何 [QG#] 且拒绝率超阈值 → 失败
    if rejected and st["accept_rate"] < (1.0 - args.max_reject_rate):
        return 1
    # 软警告阈值（可选致命）
    if args.max_warning_rate is not None and warning_rate > args.max_warning_rate:
        msg = (f"软警告率 {warning_rate:.0%} 超门限 {args.max_warning_rate:.0%}："
               f"{st['warnings']}")
        if args.warnings_fatal:
            print(f"[verify_fetch_quality] 软警告超门限（致命）：{msg}", file=sys.stderr)
            return 1
        print(f"[verify_fetch_quality] 软警告超门限（非致命）：{msg}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
