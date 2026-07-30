#!/usr/bin/env python3
"""trend_analyzer.py — 岗位市场趋势感知（Phase 8.1，纯本地、零 LLM）

数据源：多轮 jobs_raw.txt 快照（由 diff_watch / run_pipeline 累积到 trend_store.json）。
能力：
  1. capture_snapshot: 解析一轮 jobs_raw，提取总岗位数 / 方向分布 / 高频关键词命中率 / 岗位标题清单。
  2. analyze_trend: 对比最新轮与参考轮（默认上一轮；支持按周环比），输出数量环比、方向漂移、关键词漂移。
  3. render_trend_html: 生成自包含 HTML 片段（总量折线图 + 方向分布条形 + 关键词漂移表），供 generate_report 嵌入。

设计原则：
  - 全部确定性计算，不依赖 LLM，可在 CI 中离线回归。
  - 方向分类与关键词命中均为基于词表的子串匹配，结果稳定、可解释。
  - 快照库同时保留 job_titles，可作为 Phase 8.3「投递时机 / first_seen 跟踪」的数据基础。

CLI:
  python trend_analyzer.py --capture <jobs_raw.txt> --store <trend_store.json> [--date YYYY-MM-DD]
  python trend_analyzer.py --analyze --store <trend_store.json> [--output analysis.json] [--weeks N]
  python trend_analyzer.py --render --store <trend_store.json> --output trend.html [--weeks N]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 方向分类词表（按标题匹配，命中即归为该方向；顺序即优先级）
# ---------------------------------------------------------------------------
DIRECTION_GROUPS: list[tuple[str, list[str]]] = [
    # 显式角色名词优先于软性关键词，避免「后端 + 推荐系统」被误判为算法
    ("后端开发", ["后端", "back-end", "backend", "服务端", "server", "go语言", "golang",
               "微服务", "分布式", "java后端", "python后端"]),
    ("前端/客户端", ["前端", "front-end", "frontend", "web", "react", "vue", "android",
                 "ios", "客户端", "小程序", "移动端"]),
    ("算法/机器学习", ["算法", "机器学习", "machine learning", "深度学习", "deep learning",
                  "推荐", "搜索算法", "nlp", "natural language", "cv", "计算机视觉",
                  "大模型", "llm", "ai算法", "ai 算法"]),
    ("数据/分析", ["数据", "data", "数仓", "bi", "数据分析", "etl", "数据科学",
               "data scientist", "数据工程师", "数据开发"]),
    ("产品", ["产品", "product manager", "产品经理", "product owner"]),
    ("运营/增长", ["运营", "operation", "growth", "增长", "用户运营", "内容运营", "活动运营"]),
    ("测试/质量", ["测试", "qa", "质量", "测试开发", "测试工程师"]),
    ("设计", ["设计", "ux", "ui", "交互", "视觉设计"]),
]

DIRECTION_LABELS = [label for label, _ in DIRECTION_GROUPS]

# ---------------------------------------------------------------------------
# 技术/要求关键词词表（用于命中率漂移；大小写不敏感子串匹配）
# ---------------------------------------------------------------------------
TECH_KEYWORDS: list[str] = [
    "python", "java", "go", "golang", "c++", "javascript", "typescript", "rust", "php",
    "sql", "mysql", "postgresql", "redis", "mongodb", "kafka", "elasticsearch", "clickhouse",
    "docker", "kubernetes", "k8s", "微服务", "分布式", "云原生", "devops",
    "机器学习", "深度学习", "大模型", "llm", "nlp", "推荐系统", "计算机视觉", "强化学习",
    "pytorch", "tensorflow", "spark", "flink", "hadoop", "etl",
    "react", "vue", "spring", "node", "前端", "android", "ios",
    "数据分析", "ab测试", "增长", "数据建模",
]

DEFAULT_TOP_KEYWORDS = 15


# ---------------------------------------------------------------------------
# 方向与关键词匹配
# ---------------------------------------------------------------------------
def classify_direction(title: str) -> str:
    """根据标题将岗位归类到单个方向；无命中归为『其他』。"""
    if not title:
        return "其他"
    low = title.lower()
    for label, kws in DIRECTION_GROUPS:
        for kw in kws:
            if kw.lower() in low:
                return label
    return "其他"


def keyword_hit_rate(jobs: list[dict], keyword: str) -> float:
    """返回在全部岗位中命中该关键词的比例（0~1）。"""
    if not jobs:
        return 0.0
    kw = keyword.lower()
    hits = 0
    for j in jobs:
        text = f"{j.get('title', '')} {j.get('full_text', '')}".lower()
        if kw in text:
            hits += 1
    return hits / len(jobs)


# ---------------------------------------------------------------------------
# 快照捕获与存储
# ---------------------------------------------------------------------------
def build_snapshot(jobs: list[dict], date_str: str | None = None) -> dict:
    """基于内存中已解析的岗位列表生成该轮市场快照（供 diff_watch / run_pipeline 直接调用）。"""
    total = len(jobs)
    direction_counts = dict(Counter(classify_direction(j.get("title", "")) for j in jobs))
    keyword_rates = {kw: round(keyword_hit_rate(jobs, kw), 4) for kw in TECH_KEYWORDS}
    job_titles = [j.get("title", "") for j in jobs]
    snap_date = date_str or date.today().isoformat()
    return {
        "date": snap_date,
        "total": total,
        "direction_counts": direction_counts,
        "keyword_rates": keyword_rates,
        "job_titles": job_titles,
    }


def capture_snapshot(jobs_raw_path: str, date_str: str | None = None) -> dict:
    """解析一轮 jobs_raw 文件，生成该轮市场快照。"""
    from smart_score import parse_jobs_raw

    jobs = parse_jobs_raw(jobs_raw_path)
    return build_snapshot(jobs, date_str=date_str)


def load_store(store_path: str) -> dict:
    p = Path(store_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"snapshots": []}


def append_snapshot(store_path: str, snapshot: dict) -> dict:
    """将一轮快照追加（或按日期覆盖）到 trend_store.json。"""
    store = load_store(store_path)
    snaps = store.get("snapshots", [])
    existing = {s.get("date"): i for i, s in enumerate(snaps)}
    if snapshot["date"] in existing:
        snaps[existing[snapshot["date"]]] = snapshot  # 同日重跑 → 覆盖
    else:
        snaps.append(snapshot)
    snaps.sort(key=lambda s: s.get("date", ""))
    store["snapshots"] = snaps
    Path(store_path).parent.mkdir(parents=True, exist_ok=True)
    Path(store_path).write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return store


# ---------------------------------------------------------------------------
# 趋势分析
# ---------------------------------------------------------------------------
def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def analyze_trend(store: dict, weeks: int | None = None) -> dict:
    """对比最新轮与参考轮，输出数量 / 方向 / 关键词漂移。

    weeks 为 None → 参考轮取上一轮（环比上一轮）。
    weeks 给定   → 参考轮取日期 <= 最新轮 - weeks*7 天的最近一轮（周环比）。
    """
    snaps = sorted(store.get("snapshots", []), key=lambda s: s.get("date", ""))
    if len(snaps) < 2:
        return {
            "enough": False,
            "snapshots": len(snaps),
            "reason": "需要至少 2 轮快照才能分析趋势",
        }

    latest = snaps[-1]
    ref = None
    if weeks:
        latest_d = _parse_date(latest["date"])
        cutoff = latest_d - timedelta(weeks=weeks)
        candidates = [s for s in snaps[:-1] if _parse_date(s["date"]) <= cutoff]
        ref = candidates[-1] if candidates else snaps[-2]
    else:
        ref = snaps[-2]

    total_delta = latest["total"] - ref["total"]
    total_pct = (total_delta / ref["total"]) if ref["total"] else 0.0

    # 方向漂移
    dir_keys = set(latest["direction_counts"]) | set(ref["direction_counts"])
    direction_drift = {}
    for k in sorted(dir_keys):
        lv = latest["direction_counts"].get(k, 0)
        rv = ref["direction_counts"].get(k, 0)
        direction_drift[k] = {"latest": lv, "ref": rv, "delta": lv - rv}

    # 关键词漂移（按绝对变化降序）
    kw_keys = set(latest["keyword_rates"]) | set(ref["keyword_rates"])
    keyword_drift = []
    for k in kw_keys:
        lr = latest["keyword_rates"].get(k, 0.0)
        rr = ref["keyword_rates"].get(k, 0.0)
        keyword_drift.append({
            "keyword": k,
            "latest_rate": lr,
            "ref_rate": rr,
            "delta": round(lr - rr, 4),
        })
    keyword_drift.sort(key=lambda x: abs(x["delta"]), reverse=True)

    # 总量时间序列（供折线图）
    series = [{"date": s["date"], "total": s["total"]} for s in snaps]

    # first_seen：本轮出现但参考轮未见过的岗位标题
    ref_titles = set(ref.get("job_titles", []))
    first_seen = [t for t in latest.get("job_titles", []) if t and t not in ref_titles]

    return {
        "enough": True,
        "latest_date": latest["date"],
        "ref_date": ref["date"],
        "mode": f"{weeks}周环比" if weeks else "环比上一轮",
        "total_latest": latest["total"],
        "total_ref": ref["total"],
        "total_delta": total_delta,
        "total_pct": round(total_pct, 4),
        "direction_drift": direction_drift,
        "keyword_drift": keyword_drift,
        "top_keywords": keyword_drift[:DEFAULT_TOP_KEYWORDS],
        "series": series,
        "first_seen": first_seen,
        "snapshots": len(snaps),
    }


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------
def _escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _line_chart_svg(series: list[dict], width: int = 640, height: int = 200) -> str:
    """生成内联 SVG 折线图（总量随时间变化）。"""
    if len(series) < 2:
        return ""
    pad = 36
    totals = [s["total"] for s in series]
    tmin, tmax = min(totals), max(totals)
    span = (tmax - tmin) or 1
    n = len(series)
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    def x(i: int) -> float:
        return pad + (inner_w * i / (n - 1)) if n > 1 else pad + inner_w / 2

    def y(v: int) -> float:
        return pad + inner_h * (1 - (v - tmin) / span)

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(totals))
    labels = []
    for i, s in enumerate(series):
        lx = x(i)
        labels.append(
            f'<text x="{lx:.1f}" y="{height - pad + 16}" font-size="10" '
            f'text-anchor="middle" fill="#57534e">{_escape(s["date"][5:])}</text>'
        )
        labels.append(
            f'<text x="{lx:.1f}" y="{y(s["total"]) - 6:.1f}" font-size="10" '
            f'text-anchor="middle" fill="#059669">{s["total"]}</text>'
        )
    grid = (
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#e7e5e4"/>'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#e7e5e4"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="岗位总量趋势">'
        f'{grid}'
        f'<polyline fill="none" stroke="#059669" stroke-width="2" points="{pts}"/>'
        f'<circle cx="{x(n-1):.1f}" cy="{y(totals[-1]):.1f}" r="3.5" fill="#059669"/>'
        f'{"".join(labels)}'
        f'</svg>'
    )


def render_trend_html(analysis: dict) -> str:
    """返回趋势 section 的 HTML 片段；数据不足时返回空串。"""
    if not analysis.get("enough"):
        return ""

    total_d = analysis["total_delta"]
    total_pct = analysis["total_pct"]
    pct_sign = "+" if total_pct >= 0 else ""
    delta_cls = "green" if total_d >= 0 else "amber"
    delta_txt = f'{total_d:+d} ({pct_sign}{total_pct * 100:.1f}%)'

    # 方向分布条形
    dir_rows = []
    for label, d in sorted(analysis["direction_drift"].items(),
                           key=lambda kv: kv[1]["latest"], reverse=True):
        dlt = d["delta"]
        dcls = "green" if dlt > 0 else ("amber" if dlt < 0 else "gray")
        dtxt = f'{dlt:+d}' if dlt else "±0"
        dir_rows.append(
            f'<div class="trend-row">'
            f'<span class="trend-label">{_escape(label)}</span>'
            f'<span class="trend-bar" style="width:{max(d["latest"], 1) * 6}px"></span>'
            f'<span class="trend-num">{d["latest"]}</span>'
            f'<span class="trend-delta {dcls}">{dtxt}</span>'
            f'</div>'
        )
    direction_html = "".join(dir_rows)

    # 关键词漂移表（取 Top）
    kw_rows = []
    for k in analysis.get("top_keywords", []):
        if k["delta"] == 0:
            continue
        dcls = "green" if k["delta"] > 0 else "amber"
        sign = "+" if k["delta"] >= 0 else ""
        kw_rows.append(
            f'<tr>'
            f'<td>{_escape(k["keyword"])}</td>'
            f'<td>{k["ref_rate"] * 100:.0f}%</td>'
            f'<td>{k["latest_rate"] * 100:.0f}%</td>'
            f'<td class="{dcls}">{sign}{k["delta"] * 100:.0f}pp</td>'
            f'</tr>'
        )
    keyword_html = (
        '<table class="trend-table"><thead><tr>'
        '<th>关键词</th><th>上期命中率</th><th>本期命中率</th><th>漂移</th>'
        '</tr></thead><tbody>' + "".join(kw_rows) + '</tbody></table>'
        if kw_rows else '<p class="trend-empty">暂无显著关键词漂移</p>'
    )

    first_seen = analysis.get("first_seen", [])
    fs_html = ""
    if first_seen:
        items = "".join(f"<li>{_escape(t)}</li>" for t in first_seen[:10])
        more = len(first_seen) - 10
        if more > 0:
            items += f"<li>…等 {more} 个</li>"
        fs_html = (
            '<div class="trend-sub"><h4>本轮新增岗位（vs 参考轮）</h4>'
            f'<ul class="trend-fs">{items}</ul></div>'
        )

    chart = _line_chart_svg(analysis["series"])
    chart_html = f'<div class="trend-chart">{chart}</div>' if chart else ""

    return f"""
<section class="trend-section">
  <h2>📈 市场趋势洞察 <span class="trend-mode">（{_escape(analysis["mode"])}：{_escape(analysis["ref_date"])} → {_escape(analysis["latest_date"])}）</span></h2>
  <div class="stats-bar">
    <div class="stat-card {delta_cls}">
      <div class="stat-value">{analysis["total_latest"]}</div>
      <div class="stat-label">本轮岗位总量</div>
    </div>
    <div class="stat-card {delta_cls}">
      <div class="stat-value">{delta_txt}</div>
      <div class="stat-label">总量环比变化</div>
    </div>
    <div class="stat-card gray">
      <div class="stat-value">{len(analysis.get("series", []))}</div>
      <div class="stat-label">累计快照轮数</div>
    </div>
  </div>
  {chart_html}
  <div class="trend-grid">
    <div class="trend-sub">
      <h4>方向分布（条长=本轮数，括号=环比 Δ）</h4>
      {direction_html}
    </div>
    <div class="trend-sub">
      <h4>高频要求关键词漂移（Top）</h4>
      {keyword_html}
    </div>
  </div>
  {fs_html}
</section>
"""


def render_full_html(store: dict, weeks: int | None = None) -> str:
    """生成独立完整的趋势报告页（--render 模式）。"""
    analysis = analyze_trend(store, weeks=weeks)
    body = render_trend_html(analysis) if analysis.get("enough") else (
        '<p class="trend-empty">数据不足：需要至少 2 轮快照才能分析趋势。</p>'
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>岗位市场趋势</title>
<style>{_FULL_CSS}</style></head>
<body><div class="container">
<div class="report-header"><h1>📈 岗位市场趋势感知</h1>
<p class="subtitle">基于多轮 jobs_raw 快照的离线趋势分析（Phase 8.1）</p></div>
{body}
<div class="report-footer">由 trend_analyzer.py 生成 · 纯本地计算</div>
</div></body></html>"""


_FULL_CSS = """
:root{--bg:#fafaf9;--card-bg:#fff;--text:#1c1917;--text-secondary:#57534e;
--border:#e7e5e4;--accent-green:#059669;--accent-amber:#d97706;--accent-gray:#6b7280;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans SC",sans-serif;
background:var(--bg);color:var(--text);line-height:1.6;padding:2rem 1rem;}
.container{max-width:900px;margin:0 auto;}
.report-header{text-align:center;margin-bottom:2rem;padding:2rem;background:var(--card-bg);
border-radius:12px;box-shadow:0 1px 3px rgba(28,25,23,.08);}
.report-header h1{font-size:1.6rem;font-weight:700;}
.subtitle{color:var(--text-secondary);margin-top:.5rem;}
.trend-section{background:var(--card-bg);border-radius:12px;padding:1.5rem 2rem;margin-bottom:2rem;
box-shadow:0 1px 3px rgba(28,25,23,.08);}
.trend-section h2{font-size:1.2rem;font-weight:600;margin-bottom:1rem;}
.trend-mode{font-size:.75rem;color:var(--text-secondary);font-weight:400;}
.stats-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:1.5rem;}
.stat-card{background:var(--bg);border-radius:8px;padding:1rem;text-align:center;}
.stat-card .stat-value{font-size:1.6rem;font-weight:700;}
.stat-card .stat-label{font-size:.78rem;color:var(--text-secondary);margin-top:.25rem;}
.stat-card.green .stat-value{color:var(--accent-green);}
.stat-card.amber .stat-value{color:var(--accent-amber);}
.stat-card.gray .stat-value{color:var(--accent-gray);}
.trend-chart{margin:1rem 0;}
.trend-grid{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;}
.trend-sub h4{font-size:.9rem;font-weight:600;margin-bottom:.6rem;color:var(--text-secondary);}
.trend-row{display:flex;align-items:center;gap:.5rem;font-size:.82rem;margin-bottom:.3rem;}
.trend-label{width:90px;flex-shrink:0;}
.trend-bar{height:10px;background:var(--accent-green);border-radius:4px;display:inline-block;}
.trend-num{font-weight:700;width:28px;}
.trend-delta.green{color:var(--accent-green);}
.trend-delta.amber{color:var(--accent-amber);}
.trend-delta.gray{color:var(--accent-gray);}
.trend-table{width:100%;border-collapse:collapse;font-size:.8rem;}
.trend-table th,.trend-table td{padding:.35rem .5rem;text-align:left;border-bottom:1px solid var(--border);}
.trend-table th{color:var(--text-secondary);font-weight:600;}
.trend-table td.green{color:var(--accent-green);font-weight:600;}
.trend-table td.amber{color:var(--accent-amber);font-weight:600;}
.trend-empty{color:var(--text-secondary);font-size:.85rem;font-style:italic;}
.trend-fs{margin:.25rem 0 0 1.2rem;color:var(--text-secondary);font-size:.82rem;}
.report-footer{text-align:center;padding:1.5rem;color:var(--text-secondary);font-size:.8rem;}
@media(max-width:640px){.trend-grid{grid-template-columns:1fr;}.container{padding:.5rem;}}
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="岗位市场趋势感知（Phase 8.1）")
    ap.add_argument("--capture", metavar="JOBS_RAW", help="解析一轮 jobs_raw 并追加到 store")
    ap.add_argument("--store", metavar="TREND_STORE", help="trend_store.json 路径")
    ap.add_argument("--date", default=None, help="快照日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--analyze", action="store_true", help="分析趋势并输出 JSON")
    ap.add_argument("--render", action="store_true", help="生成独立趋势 HTML 页")
    ap.add_argument("--output", default=None, help="--analyze/--render 的输出文件")
    ap.add_argument("--weeks", type=int, default=None, help="周环比窗口（默认环比上一轮）")
    args = ap.parse_args(argv)

    if args.capture and args.store:
        snap = capture_snapshot(args.capture, date_str=args.date)
        store = append_snapshot(args.store, snap)
        print(f"[trend] 已捕获 {snap['date']} 快照：{snap['total']} 个岗位 → {args.store} "
              f"（累计 {len(store['snapshots'])} 轮）")
        return 0

    if args.store and (args.analyze or args.render):
        store = load_store(args.store)
        if args.render:
            html = render_full_html(store, weeks=args.weeks)
            out = args.output or "trend_report.html"
            Path(out).write_text(html, encoding="utf-8")
            print(f"[trend] 已生成趋势报告：{out}")
            return 0
        analysis = analyze_trend(store, weeks=args.weeks)
        out = args.output or "trend_analysis.json"
        Path(out).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[trend] 已输出分析：{out}（enough={analysis.get('enough')}）")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
