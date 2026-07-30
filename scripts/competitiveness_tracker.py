"""Phase 8.2 竞争力动态评估（纯本地、零 LLM 确定性内核 + 可选 agnes 增强）。

为什么：assess_competitiveness.py 当前是单次快照（评估「投递难度」）。本模块追踪
「候选人自身竞争力」随时间的变化——每次 interview_done 事件后自动重评，对比上次
快照，产出维度级 delta 报告与雷达图叠加（本月 vs 上月）。

设计要点：
- 维度分采用「累计证据」模型：基线 50 + 各 interview_done 事件的 strong_points/weak_points
  关键词命中累加，clamp 到 0-100。某月的快照 = 该月及之前所有事件累计；与上月快照之差
  即「本月新增面试证据」带来的竞争力变化（与「相比上月 +15%」语义一致）。
- 雷达图 / delta 报告完全离线、确定性、可测，是主交付。
- agnes 自然语言叙述为可选增强：传入 --provider agnes 才调用；任何失败（含网络不可达）
  都回退到确定性叙述，绝不阻塞。

用法（CLI）：
  python competitiveness_tracker.py record  [--career-log PATH] [--store PATH] [--period YYYY-MM]
  python competitiveness_tracker.py show    [--store PATH]
  python competitiveness_tracker.py radar   [--store PATH] [--out FILE]
  python competitiveness_tracker.py report  [--store PATH] [--provider agnes]  # 打印 delta 报告
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# career_log 提供默认日志路径（仅单向依赖；career_log 不反向 import 本模块，避免循环）。
try:
    from career_log import LOG_FILE as DEFAULT_CAREER_LOG
except Exception:  # 独立运行时退化
    DEFAULT_CAREER_LOG = Path.home() / ".catpaw" / "career-copilot" / "career-log.jsonl"

DEFAULT_STORE = Path.home() / ".catpaw" / "career-copilot" / "competitiveness_store.json"

# career_log 默认时区 +08:00（时间戳带该偏移）。统一用 timezone 对象，避免 naive/aware 比较崩溃。
TZINFO = timezone(timedelta(hours=8))

# —— 候选人竞争力维度表（与面试反馈常见维度对齐）——
DIMENSIONS: list[str] = [
    "系统设计",
    "算法与数据结构",
    "工程实现",
    "业务理解",
    "沟通表达",
    "项目经验",
]

# 维度关键词（用于把 strong_points / weak_points 自由文本映射到维度）。不命中则归入自由备注。
DIMENSION_KEYWORDS: dict[str, list[str]] = {
    "系统设计": ["系统设计", "架构", "system design", "分布式", "高并发", "扩容", "微服务"],
    "算法与数据结构": ["算法", "数据结构", "leetcode", "刷题", "动态规划", "图论", "贪心"],
    "工程实现": ["工程", "编码", "代码", "实现", "debug", "bug", "质量", "测试", "ci", "重构"],
    "业务理解": ["业务", "产品", "增长", "商业化", "指标", "转化", "用户", "营收"],
    "沟通表达": ["沟通", "表达", "presentation", "汇报", "协作", "leadership", "领导力", "英语"],
    "项目经验": ["项目", "实习", "经历", "落地", "成果", "业绩", "产出"],
}

BASELINE = 50          # 每个维度的起始分
STRONG_GAIN = 8        # 单条 strong_point 命中某维度的最大加分（每月每维度封顶，避免重复累加）
WEAK_PENALTY = 6       # 单条 weak_point 命中某维度的最大扣分
PER_EVENT_DIM_CAP = 8  # 单事件内单维度净变化封顶，避免单场面试把维度拉爆
TZ = timedelta(hours=8)  # 兼容保留（仅用于文档/旧引用）


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now()


def parse_ts(ts) -> datetime:
    """解析 career_log 的 ISO 时间戳；失败时返回 epoch。"""
    if ts is None:
        return datetime(1970, 1, 1)
    if isinstance(ts, datetime):
        return ts
    s = str(ts).strip()
    if not s:
        return datetime(1970, 1, 1)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # 退而求其次：截断到秒
        try:
            return datetime.fromisoformat(s.split(".")[0].replace("Z", ""))
        except ValueError:
            return datetime(1970, 1, 1)


def to_period(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def period_end(period: str) -> datetime:
    """某月最后一刻（带 +08:00 时区，与事件时间戳偏移一致，避免 naive/aware 比较崩溃）。"""
    year, month = (int(x) for x in period.split("-"))
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=TZINFO)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=TZINFO)
    return nxt - timedelta(seconds=1)


def map_to_dimensions(text: str) -> list[str]:
    """把一段自由文本映射到命中的维度（不区分大小写、子串匹配）。"""
    if not text:
        return []
    low = str(text).lower()
    hits = []
    for dim, kws in DIMENSION_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in low:
                hits.append(dim)
                break
    return hits


def load_events(log_path) -> list[dict]:
    """读取 career_log JSONL（独立实现，避免反向依赖 career_log 运行时）。"""
    p = Path(log_path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --------------------------------------------------------------------------- #
# 快照构建（累计证据模型）
# --------------------------------------------------------------------------- #
def build_snapshot(events: list[dict], *, as_of: datetime | None = None,
                   period: str | None = None) -> dict:
    """由 interview_done 事件累计构建某一时点的竞争力快照。

    events：已按时间窗过滤好的事件列表（调用方负责只传 <= as_of 的事件）。
    维度分 = BASELINE + 所有事件 strong/weak 命中累计，clamp 0-100。
    """
    as_of = as_of or _now()
    period = period or to_period(as_of)
    score = {d: float(BASELINE) for d in DIMENSIONS}

    interviews = [e for e in events if e.get("type") == "interview_done"]
    for ev in interviews:
        per_dim_net = {d: 0.0 for d in DIMENSIONS}
        for sp in ev.get("strong_points", []) or []:
            for dim in map_to_dimensions(sp):
                per_dim_net[dim] += STRONG_GAIN
        for wp in ev.get("weak_points", []) or []:
            for dim in map_to_dimensions(wp):
                per_dim_net[dim] -= WEAK_PENALTY
        # 单事件单维度封顶，避免一场面试拉爆
        for dim in DIMENSIONS:
            net = max(-PER_EVENT_DIM_CAP, min(PER_EVENT_DIM_CAP, per_dim_net[dim]))
            score[dim] = max(0.0, min(100.0, score[dim] + net))

    dims_out = OrderedDict((d, round(score[d], 1)) for d in DIMENSIONS)
    n = len(interviews)
    passed = sum(1 for e in interviews if str(e.get("result", "")).lower() == "pass")
    pass_rate = round(passed / n, 3) if n else None

    return OrderedDict([
        ("period", period),
        ("as_of", as_of.isoformat()),
        ("dimensions", dims_out),
        ("overall", round(sum(dims_out.values()) / len(DIMENSIONS), 1)),
        ("n_interviews", n),
        ("pass_rate", pass_rate),
    ])


def events_up_to(log_path, end_dt: datetime) -> list[dict]:
    evs = load_events(log_path)
    return [e for e in evs if parse_ts(e.get("timestamp")) <= end_dt]


# --------------------------------------------------------------------------- #
# period store（按月持久化快照）
# --------------------------------------------------------------------------- #
def load_store(store_path) -> dict:
    p = Path(store_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_store(store_path, store: dict) -> None:
    p = Path(store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def previous_period(period: str) -> str | None:
    year, month = (int(x) for x in period.split("-"))
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def store_snapshot(store: dict, snapshot: dict) -> dict:
    """把快照写入 store（按 period 覆盖），返回新 store。"""
    store = dict(store)
    store[snapshot["period"]] = snapshot
    return store


# --------------------------------------------------------------------------- #
# delta 计算 + 报告
# --------------------------------------------------------------------------- #
def attribute_reasons(gap_events: list[dict]) -> dict[str, list[str]]:
    """把两快照之间的面试事件归因到维度（用于 delta 理由文本）。"""
    reasons: dict[str, list[str]] = {d: [] for d in DIMENSIONS}
    for ev in gap_events:
        if ev.get("type") != "interview_done":
            continue
        for sp in ev.get("strong_points", []) or []:
            for dim in map_to_dimensions(sp):
                if sp not in reasons[dim]:
                    reasons[dim].append(sp)
        for wp in ev.get("weak_points", []) or []:
            for dim in map_to_dimensions(wp):
                if wp not in reasons[dim]:
                    reasons[dim].append(wp)
    return reasons


def compute_delta(current: dict, previous: dict | None,
                  gap_events: list[dict] | None = None) -> dict | None:
    """计算 current vs previous 的维度 delta。无 previous 时返回 None。"""
    if previous is None:
        return None
    reasons = attribute_reasons(gap_events or [])
    dims = {}
    for dim in DIMENSIONS:
        frm = float(previous["dimensions"][dim])
        to = float(current["dimensions"][dim])
        d = round(to - frm, 1)
        if d > 0:
            signal = "up"
        elif d < 0:
            signal = "down"
        else:
            signal = "flat"
        r = reasons.get(dim, [])
        if signal == "flat":
            reason_text = "持平（本月无相关新信号）"
        else:
            tag = "面试反馈正向" if signal == "up" else "面试反馈负向"
            reason_text = f"基于{tag}" + (f"：{', '.join(r)}" if r else "")
        dims[dim] = OrderedDict([
            ("from", frm), ("to", to), ("delta", d),
            ("signal", signal), ("reason", reason_text),
        ])
    overall_delta = round(float(current["overall"]) - float(previous["overall"]), 1)
    ups = sorted([(d, v["delta"]) for d, v in dims.items() if v["signal"] == "up"],
                 key=lambda x: -x[1])
    downs = sorted([(d, v["delta"]) for d, v in dims.items() if v["signal"] == "down"],
                   key=lambda x: x[1])
    return OrderedDict([
        ("from_period", previous["period"]),
        ("to_period", current["period"]),
        ("overall_delta", overall_delta),
        ("dimensions", dims),
        ("top_up", [{"dim": d, "delta": v} for d, v in ups[:2]]),
        ("top_down", [{"dim": d, "delta": v} for d, v in downs[:2]]),
    ])


def render_delta_report(delta: dict | None, *, current: dict | None = None,
                        narrative: str | None = None) -> str:
    """渲染 delta 报告的 Markdown 文本（确定性；narrative 为可选的 LLM 增强段）。"""
    lines = []
    if narrative:
        lines.append(f"> {narrative}")
        lines.append("")
    if delta is None:
        if current:
            lines.append(f"**{current['period']} 竞争力快照（首次记录，暂无上月可比）**")
            for dim in DIMENSIONS:
                lines.append(f"- {dim}：{current['dimensions'][dim]}")
            lines.append(f"- 总评：{current['overall']}（{current['n_interviews']} 场面试，"
                         f"通过率 {current['pass_rate'] if current['pass_rate'] is not None else '—'}）")
        return "\n".join(lines)
    lines.append(f"**竞争力变化（{delta['from_period']} → {delta['to_period']}）**")
    lines.append(f"- 总评：{_fmt(current['overall'])}（较上月 {delta['overall_delta']:+.1f}）")
    for dim in DIMENSIONS:
        v = delta["dimensions"][dim]
        arrow = "▲" if v["signal"] == "up" else ("▼" if v["signal"] == "down" else "＝")
        lines.append(f"- {dim}：{_fmt(v['from'])} → {_fmt(v['to'])} "
                     f"（{v['delta']:+.1f} {arrow}）｜{v['reason']}")
    if delta["top_up"]:
        lines.append(f"- 上升最快：{'、'.join(f'{x['dim']} {x['delta']:+.1f}' for x in delta['top_up'])}")
    if delta["top_down"]:
        lines.append(f"- 下降最多：{'、'.join(f'{x['dim']} {x['delta']:+.1f}' for x in delta['top_down'])}")
    return "\n".join(lines)


def _fmt(x) -> str:
    return f"{x:.1f}"


# --------------------------------------------------------------------------- #
# 雷达图叠加（自包含 SVG，无外部依赖）
# --------------------------------------------------------------------------- #
def render_radar_overlay(current: dict, previous: dict | None,
                         *, size: int = 420, max_val: float = 100.0) -> str:
    """渲染本月 vs 上月的竞争力雷达图（SVG）。"""
    n = len(DIMENSIONS)
    cx = size / 2
    cy = size / 2
    r = size / 2 - 56  # 留白给标签
    rings = [0.25, 0.5, 0.75, 1.0]

    def point(i: int, val: float):
        ang = -90 + 360.0 * i / n
        rad = (val / max_val) * r
        import math
        x = cx + rad * math.cos(math.radians(ang))
        y = cy + rad * math.sin(math.radians(ang))
        return x, y

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
             f'viewBox="0 0 {size} {size}" role="img" aria-label="竞争力雷达图">']
    # 网格环
    for rg in rings:
        pts = " ".join(f"{point(i, rg * max_val)[0]:.1f},{point(i, rg * max_val)[1]:.1f}"
                       for i in range(n))
        parts.append(f'<polygon points="{pts}" fill="none" stroke="#e5e7eb" stroke-width="1"/>')
    # 轴线 + 标签
    for i, dim in enumerate(DIMENSIONS):
        x, y = point(i, max_val)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke="#e5e7eb" stroke-width="1"/>')
        lx, ly = point(i, max_val + 14)
        anchor = "middle"
        if lx < cx - 5:
            anchor = "end"
        elif lx > cx + 5:
            anchor = "start"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" fill="#374151" '
                     f'text-anchor="{anchor}">{dim}</text>')
    # 上月多边形（灰虚线）
    if previous is not None:
        prev_pts = " ".join(f"{point(i, previous['dimensions'][DIMENSIONS[i]])[0]:.1f},"
                            f"{point(i, previous['dimensions'][DIMENSIONS[i]])[1]:.1f}"
                            for i in range(n))
        parts.append(f'<polygon points="{prev_pts}" fill="rgba(148,163,184,0.18)" '
                     f'stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="5,4"/>')
    # 本月多边形（蓝实线）
    cur_pts = " ".join(f"{point(i, current['dimensions'][DIMENSIONS[i]])[0]:.1f},"
                       f"{point(i, current['dimensions'][DIMENSIONS[i]])[1]:.1f}"
                       for i in range(n))
    parts.append(f'<polygon points="{cur_pts}" fill="rgba(37,99,235,0.18)" '
                 f'stroke="#2563eb" stroke-width="2"/>')
    # 顶点圆点
    for i in range(n):
        x, y = point(i, current['dimensions'][DIMENSIONS[i]])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="#2563eb"/>')
    # 图例
    ly = size - 14
    if previous is not None:
        parts.append(f'<rect x="12" y="{ly - 10}" width="14" height="8" fill="rgba(148,163,184,0.5)" '
                     f'stroke="#94a3b8"/>')
        parts.append(f'<text x="32" y="{ly - 3}" font-size="11" fill="#475569">上月（{previous["period"]}）</text>')
        parts.append(f'<rect x="170" y="{ly - 10}" width="14" height="8" fill="rgba(37,99,235,0.5)" '
                     f'stroke="#2563eb"/>')
        parts.append(f'<text x="190" y="{ly - 3}" font-size="11" fill="#1e40af">本月（{current["period"]}）</text>')
    else:
        parts.append(f'<rect x="12" y="{ly - 10}" width="14" height="8" fill="rgba(37,99,235,0.5)" '
                     f'stroke="#2563eb"/>')
        parts.append(f'<text x="32" y="{ly - 3}" font-size="11" fill="#1e40af">本月（{current["period"]}）</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 可选 agnes 增强（容错降级，绝不阻塞确定性内核）
# --------------------------------------------------------------------------- #
def enrich_narrative(delta_report: str, *, provider: str | None = None,
                     model: str | None = None) -> str | None:
    """调用 agnes 生成一段自然语言教练式总结；任何失败都返回 None（回退确定性报告）。"""
    if not provider:
        return None
    try:
        from llm_client import LLMClient
        client = LLMClient(provider=provider, model=model, use_cache=False)
        system = (
            "你是一名求职竞争力教练。基于候选人竞争力变化报告，用 1-2 句中文给候选人"
            "一句可行的下一步提升建议（不要简单复述报告中的数字，要给出行动方向）。"
        )
        resp = asyncio.run(client.chat(system=system, user=delta_report, max_tokens=120))
        text = resp.strip() if isinstance(resp, str) else str(resp).strip()
        return text or None
    except Exception:
        # 网络不可达 / 凭据缺失 / 模型不可用 —— 一律优雅降级
        return None


# --------------------------------------------------------------------------- #
# 重评入口（被 career_log 钩子与 CLI 共用）
# --------------------------------------------------------------------------- #
def recompute_after_event(event: dict, *, career_log_path, store_path) -> tuple[dict, dict | None]:
    """在 interview_done 事件后重评竞争力：写 store、返回 (current_snapshot, delta)。

    确定性、同步、可测。agnes 增强在 report 命令里单独触发，不在此处，避免钩子阻塞。
    """
    dt = parse_ts(event.get("timestamp")) or _now()
    period = to_period(dt)
    end = period_end(period)
    evs = events_up_to(career_log_path, end)
    current = build_snapshot(evs, as_of=end, period=period)

    store = load_store(store_path)
    prev_period = previous_period(period)
    previous = store.get(prev_period)
    gap_events = [e for e in evs if parse_ts(e.get("timestamp")) > period_end(prev_period)]
    delta = compute_delta(current, previous, gap_events)

    store = store_snapshot(store, current)
    save_store(store_path, store)
    return current, delta


def snapshot_for_period(store: dict, period: str) -> dict | None:
    return store.get(period)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Phase 8.2 竞争力动态评估")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="重评某月快照并写入 store（默认最新事件所在月）")
    p_rec.add_argument("--career-log", default=str(DEFAULT_CAREER_LOG))
    p_rec.add_argument("--store", default=str(DEFAULT_STORE))
    p_rec.add_argument("--period", default=None, help="YYYY-MM，默认最新 interview_done 事件所在月")

    p_show = sub.add_parser("show", help="打印最新两期快照与 delta 报告")
    p_show.add_argument("--store", default=str(DEFAULT_STORE))
    p_show.add_argument("--career-log", default=str(DEFAULT_CAREER_LOG))

    p_radar = sub.add_parser("radar", help="导出雷达图 SVG")
    p_radar.add_argument("--store", default=str(DEFAULT_STORE))
    p_radar.add_argument("--out", default=None, help="输出 .svg 文件路径（默认打印到 stdout）")

    p_rep = sub.add_parser("report", help="打印 delta 报告（可选 agnes 增强）")
    p_rep.add_argument("--store", default=str(DEFAULT_STORE))
    p_rep.add_argument("--career-log", default=str(DEFAULT_CAREER_LOG))
    p_rep.add_argument("--provider", default=None, help="自然语言增强的 LLM provider（如 agnes）；不填则纯确定性")
    p_rep.add_argument("--model", default=None)

    return ap


def main(argv=None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.cmd == "record":
        log_path = args.career_log
        evs_all = load_events(log_path)
        interviews = [e for e in evs_all if e.get("type") == "interview_done"]
        if not interviews:
            print(f"[competitiveness] 未找到 interview_done 事件：{log_path}")
            return 0
        if args.period:
            period = args.period
        else:
            period = to_period(parse_ts(max(interviews, key=lambda e: parse_ts(e.get("timestamp"))).get("timestamp")))
        # 取该月任意事件触发重评（用该月最后时刻对应的事件作 trigger 占位）
        trigger = max((e for e in interviews if to_period(parse_ts(e.get("timestamp"))) == period),
                      key=lambda e: parse_ts(e.get("timestamp")))
        current, delta = recompute_after_event(trigger, career_log_path=log_path, store_path=args.store)
        print(f"[competitiveness] 已记录 {current['period']} 快照 → {args.store}")
        print(render_delta_report(delta, current=current))
        return 0

    if args.cmd == "show":
        store = load_store(args.store)
        if not store:
            print(f"[competitiveness] store 为空：{args.store}")
            return 0
        periods = sorted(store.keys())
        current = store[periods[-1]]
        previous = store.get(previous_period(current["period"]))
        gap_events = load_events(args.career_log)
        delta = compute_delta(current, previous, gap_events)
        print(render_delta_report(delta, current=current))
        return 0

    if args.cmd == "radar":
        store = load_store(args.store)
        if not store:
            print(f"[competitiveness] store 为空：{args.store}")
            return 1
        periods = sorted(store.keys())
        current = store[periods[-1]]
        previous = store.get(previous_period(current["period"]))
        svg = render_radar_overlay(current, previous)
        if args.out:
            Path(args.out).write_text(svg, encoding="utf-8")
            print(f"[competitiveness] 雷达图 → {args.out}")
        else:
            print(svg)
        return 0

    if args.cmd == "report":
        store = load_store(args.store)
        if not store:
            print(f"[competitiveness] store 为空：{args.store}")
            return 0
        periods = sorted(store.keys())
        current = store[periods[-1]]
        previous = store.get(previous_period(current["period"]))
        gap_events = load_events(args.career_log)
        delta = compute_delta(current, previous, gap_events)
        narrative = enrich_narrative(render_delta_report(delta, current=current),
                                     provider=args.provider, model=args.model)
        print(render_delta_report(delta, current=current, narrative=narrative))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
