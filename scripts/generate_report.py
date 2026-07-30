#!/usr/bin/env python3
"""
generate_report.py — 从 scored_results.json 生成交互式 HTML 报告

使用方式：
    python3 generate_report.py \
        --input scored_results.json \
        --profile boundary_profile.json \
        --output report.html \
        [--decision-context decision_context.json]

输入：
  - scored_results.json: smart_score.py 的输出
  - boundary_profile.json: 候选人画像（用于展示方向信息）
  - decision_context.json（可选）: assess_competitiveness.py 的输出，有则在卡片上显示投递定位

输出：
  - 单个自包含的 HTML 文件（含内联 CSS/JS，可直接浏览器打开）
"""

from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from report_assets import REPORT_CSS, REPORT_JS
import html


def _esc(value) -> str:
    """HTML 转义：元素体与属性上下文都安全（quote=True 同时转义引号）。"""
    return html.escape("" if value is None else str(value), quote=True)


def render_competitiveness_section(store_path: str, career_log_path: str = None, provider: str = None) -> str:
    """Phase 8.2：「竞争力动态」段落（delta 报告 + 雷达图叠加）。无数据返回空串。
    provider 给定（如 "agnes"）时叠加教练式自然语言叙述；失败静默回退，不影响确定性报告。"""
    try:
        from competitiveness_tracker import (load_store, previous_period, compute_delta,
                                             render_delta_report, render_radar_overlay)
        store = load_store(store_path)
        if not store:
            return ""
        periods = sorted(store.keys())
        current = store[periods[-1]]
        previous = store.get(previous_period(current["period"]))
        gap_events = []
        if career_log_path:
            from competitiveness_tracker import load_events
            gap_events = load_events(career_log_path)
        delta = compute_delta(current, previous, gap_events)
        report_md = render_delta_report(delta, current=current)
        radar = render_radar_overlay(current, previous)
        # Phase 9.1：可选地接入 agnes 教练式叙述（失败静默回退，不影响确定性报告）
        narrative_html = ""
        if provider:
            try:
                from competitiveness_tracker import enrich_narrative
                narrative = enrich_narrative(report_md, provider=provider)
                if narrative:
                    narrative_html = (
                        f'<div class="comp-narrative"><strong>🤖 教练建议</strong>'
                        f'<p>{_esc(narrative)}</p></div>'
                    )
            except Exception:
                narrative_html = ""
        return f'''
  <div class="competitiveness-section">
    <h2>📈 竞争力动态评估（Phase 8.2）</h2>
    {narrative_html}
    <div class="comp-grid">
      <div class="comp-report"><pre>{report_md}</pre></div>
      <div class="comp-radar">{radar}</div>
    </div>
  </div>'''
    except Exception as e:
        return f'<!-- competitiveness section 渲染失败: {e} -->'


def build_optional_sections(*, history_store=None, trend_store=None,
                             competitiveness_store=None, competitiveness_provider=None,
                             career_log_path=None, now=None):
    """按给定 store 路径加载并渲染三段可选智能分析，加载失败各自静默跳过。

    返回 (history_funnel, trend_html, comp_html)，未提供或失败时对应项为 None。
    供 generate_report.main 与 run_pipeline 的 report 阶段共用，确保周报贯通一致。
    """
    history_funnel = None
    if history_store:
        try:
            from calibration_feedback import compute_tier_funnel, load_applications
            history_funnel = compute_tier_funnel(load_applications(history_store))
        except Exception as e:
            print(f"  ⚠ 历史转化漏斗加载失败，跳过: {e}", file=sys.stderr)
    trend_html = None
    if trend_store:
        try:
            from trend_analyzer import load_store, analyze_trend, render_trend_html
            trend_html = render_trend_html(analyze_trend(load_store(trend_store)))
        except Exception as e:
            print(f"  ⚠ 市场趋势洞察加载失败，跳过: {e}", file=sys.stderr)
    comp_html = None
    if competitiveness_store:
        try:
            # career_log_path 缺省时自动对齐 career_log.py 的默认日志位置，
            # 使面试数据（interview_done）能进入竞争力 delta 的归因（Phase 9.3 闭环）。
            if career_log_path is None:
                try:
                    from career_log import LOG_FILE
                    career_log_path = str(LOG_FILE)
                except Exception:
                    career_log_path = None
            comp_html = render_competitiveness_section(
                competitiveness_store, career_log_path, provider=competitiveness_provider)
        except Exception as e:
            print(f"  ⚠ 竞争力动态评估加载失败，跳过: {e}", file=sys.stderr)
    return history_funnel, trend_html, comp_html


def generate_html(data: dict, profile: dict, decision_context: dict = None,
                 history_funnel: dict = None, trend_html: str = None, now=None,
                 comp_html: str = None) -> str:
    """生成完整的 HTML 报告

    history_funnel: 可选，来自 calibration_feedback.compute_tier_funnel 的输出，
    用于在报告中渲染「历史转化漏斗（真实投递反馈）」段落。
    """
    # 构建 job_id → positioning 映射（如有 decision_context）
    positioning_map = {}
    if decision_context:
        for item in decision_context.get("assessments", []):
            jid = item.get("job_id", "")
            if jid:
                positioning_map[jid] = {
                    "positioning": item.get("positioning", ""),
                    "confidence": item.get("confidence", 0),
                }

    # 提取信息
    role_type = profile.get("role_type", "候选人")
    direction_anchors = profile.get("direction_anchors", [])
    direction_text = " / ".join(direction_anchors) if direction_anchors else "AI 产品"

    tier_a = data.get("recommendations", {}).get("tier_A", [])
    tier_b = data.get("recommendations", {}).get("tier_B", [])
    tier_c = data.get("recommendations", {}).get("tier_C", [])
    summary = data.get("summary", {})
    new_count = sum(1 for t in (tier_a, tier_b, tier_c) for j in t if j.get("is_new"))
    pipeline = data.get("pipeline", {})

    generated_at = data.get("generated_at", datetime.now().isoformat())
    total_jobs = pipeline.get("stage1", {}).get("total_jobs", 0)
    top_k = pipeline.get("stage1", {}).get("top_k", 0)
    direction_anchor = pipeline.get("direction_anchor", direction_text)

    # Stage 1 全量分数分布（用于漏斗可视化）
    s1_scores = data.get("stage1_all_scores", [])

    # 历史转化漏斗（真实投递反馈，Phase 6.1）
    history_funnel_html = render_history_funnel(history_funnel)

    # Phase 8.1 市场趋势洞察
    trend_section_html = trend_html if trend_html else ''

    # Phase 8.2 竞争力动态评估
    comp_section_html = comp_html if comp_html else ''

    # 生成岗位卡片 HTML

    tier_a_cards = "\n".join(render_job_card(j, "A", positioning_map, now=now) for j in tier_a)
    tier_b_cards = "\n".join(render_job_card(j, "B", positioning_map, now=now) for j in tier_b)
    tier_c_cards = "\n".join(render_job_card(j, "C", positioning_map, now=now) for j in tier_c)

    # 漏斗数据
    s1_time = pipeline.get("stage1", {}).get("wall_time", 0)
    s15_time = pipeline.get("stage1_5", {}).get("wall_time", 0)
    s2_time = pipeline.get("stage2", {}).get("wall_time", 0)
    total_time = s1_time + s15_time + s2_time

    html = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>岗位匹配报告 — {_esc(role_type)}</title>
<style>
{REPORT_CSS}
</style>
</head>
<body>

<div class="container">
  <!-- Header -->
  <div class="report-header">
    <h1>岗位匹配报告</h1>
    <p class="subtitle">{_esc(role_type)} · {_esc(generated_at[:10])}</p>
    <div class="direction-tags">
      {"".join(f'<span class="direction-tag">{_esc(a)}</span>' for a in direction_anchors[:4])}
    </div>
  </div>

  <!-- Stats -->
  <div class="stats-bar">
    <div class="stat-card">
      <div class="stat-value">{total_jobs}</div>
      <div class="stat-label">总岗位数</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{top_k}</div>
      <div class="stat-label">进入精排</div>
    </div>
    <div class="stat-card green">
      <div class="stat-value">{summary.get('tier_A', 0)}</div>
      <div class="stat-label">A档 · 强烈推荐</div>
    </div>
    <div class="stat-card amber">
      <div class="stat-value">{summary.get('tier_B', 0)}</div>
      <div class="stat-label">B档 · 可以考虑</div>
    </div>
    <div class="stat-card gray">
      <div class="stat-value">{summary.get('tier_C', 0)}</div>
      <div class="stat-label">C档 · 迁移较远</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-value">{new_count}</div>
      <div class="stat-label">本周新增</div>
    </div>
  </div>

  <!-- Funnel -->
  <div class="funnel">
    <h2>匹配漏斗</h2>
    <div class="funnel-steps">
      <div class="funnel-step"><span class="num">{total_jobs}</span> 全量 JD</div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step">Stage 1 粗筛 ({s1_time:.0f}s)</div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step"><span class="num">{top_k}</span> Top K</div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step">Stage 1.5 辨别知识 ({s15_time:.0f}s)</div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step">Stage 2 精排 ({s2_time:.0f}s)</div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step"><span class="num">{summary.get('tier_A', 0)}</span> A档</div>
    </div>
    <p style="margin-top: 0.75rem; font-size: 0.8rem; color: var(--text-secondary);">
      总耗时 {total_time:.0f}s · 方向锚定: {_esc(direction_anchor)}
    </p>
  </div>

  <!-- Filter tabs -->
  <div class="filter-tabs">
    <button class="filter-tab active" data-filter="all">全部 ({len(tier_a) + len(tier_b) + len(tier_c)})</button>
    <button class="filter-tab" data-filter="A">A档 ({len(tier_a)})</button>
    <button class="filter-tab" data-filter="B">B档 ({len(tier_b)})</button>
    <button class="filter-tab" data-filter="C">C档 ({len(tier_c)})</button>
  </div>

  <!-- Tier A -->
  {'<div class="tier-section" data-tier-section="A"><h2>🟢 A档 — 强烈推荐</h2>' + tier_a_cards + '</div>' if tier_a else ''}

  <!-- Tier B -->
  {'<div class="tier-section" data-tier-section="B"><h2>🟡 B档 — 可以考虑</h2>' + tier_b_cards + '</div>' if tier_b else ''}

  <!-- Tier C -->
  {'<div class="tier-section" data-tier-section="C"><h2>⚪ C档 — 迁移较远</h2>' + tier_c_cards + '</div>' if tier_c else ''}

  <!-- 历史转化漏斗（真实投递反馈，Phase 6.1） -->
  {history_funnel_html}

  <!-- 市场趋势洞察（Phase 8.1） -->
  {trend_section_html}

  <!-- 竞争力动态评估（Phase 8.2） -->
  {comp_section_html}

  <!-- Footer -->
  <div class="report-footer">
    <p>由 Career Copilot 生成 · {_esc(generated_at[:10])}</p>
    <p>Stage 1: {_esc(pipeline.get("stage1", dict()).get("model", "?"))} · Stage 2: {_esc(pipeline.get("stage2", dict()).get("model", "?"))}</p>
  </div>
</div>

<script>
{REPORT_JS}
</script>

</body>
</html>'''

    return html


def render_history_funnel(funnel: dict) -> str:
    """渲染「历史转化漏斗」段落（来自 calibration_feedback.compute_tier_funnel 的输出）。

    无投递数据（rows 为空）时返回空串，不显示该段。
    """
    if not funnel:
        return ""
    rows = funnel.get("rows", [])
    if not rows:
        return ""

    trs = []
    for r in rows:
        t = r.get("tier") or "—"
        trs.append(
            "<tr>"
            f'<td>{_esc(t)}</td>'
            f'<td>{r.get("n", 0)}</td>'
            f'<td>{r.get("reached", 0)}</td>'
            f'<td>{r.get("interview", 0)}</td>'
            f'<td>{r.get("offer", 0)}</td>'
            f'<td>{r.get("applied_rate", 0):.0%}</td>'
            f'<td>{r.get("interview_rate", 0):.0%}</td>'
            f'<td>{r.get("offer_rate", 0):.0%}</td>'
            "</tr>"
        )
    rows_html = "\n".join(trs)
    return f'''
  <div class="history-funnel" style="margin-top: 1.5rem;">
    <h2>历史转化漏斗（真实投递反馈）</h2>
    <table style="width:100%; border-collapse: collapse; font-size: 0.85rem;">
      <thead>
        <tr style="text-align:left; border-bottom: 2px solid #e5e7eb; color: #6b7280;">
          <th>Tier</th><th>建档</th><th>投递</th><th>面试</th><th>offer</th>
          <th>投递率</th><th>面试率</th><th>offer率</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <p style="margin-top: 0.75rem; font-size: 0.8rem; color: var(--text-secondary);">
      有效投递 {funnel.get('total_reached', 0)} · 总 offer {funnel.get('total_offer', 0)} ·
      整体 offer 率 {funnel.get('overall_offer_rate', 0):.1%}
      （数据来源：job_tracker.json；样本不足时仅供参考）
    </p>
  </div>'''


def render_job_card(job: dict, tier: str, positioning_map: dict = None, now=None) -> str:
    from first_seen import render_timing_badge
    positioning_map = positioning_map or {}
    tier_colors = {"A": "#059669", "B": "#d97706", "C": "#6b7280"}
    tier_labels = {"A": "强烈推荐", "B": "可以考虑", "C": "迁移较远"}
    tier_bg = {"A": "#ecfdf5", "B": "#fffbeb", "C": "#f9fafb"}
    color = tier_colors.get(tier, "#6b7280")
    label = tier_labels.get(tier, tier)
    bg = tier_bg.get(tier, "#f9fafb")

    reasons_html = "".join(f'<li>{_esc(r)}</li>' for r in job.get("match_reasons", []))
    risks_html = "".join(
        f'<span class="risk-tag">{_esc(r)}</span>' for r in job.get("risks", [])
    )
    advice = job.get("advice", "")
    score = job.get("score", 0)
    s1_score = job.get("stage1_score", 0)
    title = job.get("title", "未知岗位")
    job_id = job.get("job_id", "")
    job_url = job.get("url", "")
    dept = job.get("department", "")
    loc = job.get("location", "")
    meta_parts = [p for p in [dept, loc] if p]
    meta_text = " · ".join(_esc(p) for p in meta_parts) if meta_parts else ""

    # 投递定位标签（如有 decision_context）
    pos_info = positioning_map.get(job.get("job_id", ""), {})
    positioning = pos_info.get("positioning", "")

    # 构建条件标签（英语/核心团队/技术依赖）
    cond_tags = []
    if positioning:
        pos_labels = {"stretch": "🎯 冲刺", "match": "✅ 稳妥", "safe": "🛡️ 保底"}
        pos_colors = {"stretch": "#dc2626", "match": "#059669", "safe": "#2563eb"}
        cond_tags.append(
            f'<span class="cond-tag" style="border-color:{pos_colors.get(positioning, "#6b7280")};'
            f'color:{pos_colors.get(positioning, "#6b7280")};">'
            f'{_esc(pos_labels.get(positioning, positioning))}</span>'
        )
    eng_req = job.get("english_requirement", "")
    if eng_req:
        eng_label_map = {"fluent": "🌐 英语流利", "preferred": "🌐 英语优先", "implicit": "🌐 国际化"}
        cond_tags.append(f'<span class="cond-tag tag-eng">{_esc(eng_label_map.get(eng_req, eng_req))}</span>')
    if job.get("is_core_team"):
        cond_tags.append('<span class="cond-tag tag-core">⭐ 核心团队</span>')
    if job.get("is_tech_strong"):
        cond_tags.append('<span class="cond-tag tag-tech">💻 技术依赖</span>')
    cond_tags_html = f'<div class="card-tags">{" ".join(cond_tags)}</div>' if cond_tags else ""

    # 构建标题：如果有 URL，标题可点击跳转
    if job_url:
        title_html = f'<a href="{_esc(job_url)}" target="_blank" rel="noopener" class="job-title-link" onclick="event.stopPropagation();">{_esc(title)}</a>'
    else:
        title_html = _esc(title)

    return f'''
        <div class="job-card" id="{_esc(job_id)}" data-tier="{tier}" style="border-left: 4px solid {color}; background: {bg};">
          <div class="card-header">
            <div class="card-title-row">
              <h3 class="job-title">{title_html}</h3>
              <div class="score-badge" style="background: {color}; color: white;">
                {score:.0f}
              </div>
            </div>
            <div class="job-id-row">
              <span class="job-id-label">{_esc(job_id)}</span>
              {f'<a href="{_esc(job_url)}" target="_blank" rel="noopener" class="job-link" onclick="event.stopPropagation();">查看原始岗位 ↗</a>' if job_url else ''}
            </div>
            {f'<div class="job-meta">{meta_text}</div>' if meta_text else ''}
            <div class="tier-label" style="color: {color};">{label}</div>
            {cond_tags_html}
            {f'<span class="badge-new">🆕 本周新增</span>' if job.get("is_new") else ''}
            {render_timing_badge(job, now=now) if job.get("first_seen_at") else ''}
          </div>
          <div class="card-body">
            <div class="reasons">
              <strong>匹配理由：</strong>
              <ul>{reasons_html}</ul>
            </div>
            {f'<div class="risks"><strong>风险：</strong>{risks_html}</div>' if risks_html else ''}
            {f'<div class="advice"><strong>建议：</strong>{_esc(advice)}</div>' if advice else ''}
            <div class="scores-detail">
              <span class="s1-score">初筛分: {s1_score:.0f}</span>
              <span class="s2-score">精排分: {score:.0f}</span>
            </div>
          </div>
        </div>'''



def main():
    parser = argparse.ArgumentParser(description="从 scored_results.json 生成 HTML 报告")
    parser.add_argument("--input", required=True, help="scored_results.json 路径")
    parser.add_argument("--profile", required=True, help="boundary_profile.json 路径")
    parser.add_argument("--output", required=True, help="输出 HTML 文件路径")
    parser.add_argument("--decision-context", default=None,
                       help="decision_context.json 路径（可选，assess_competitiveness 输出）")
    parser.add_argument("--history-store", default=None,
                       help="job_tracker.json 路径（可选，渲染「历史转化漏斗」真实投递反馈）")
    parser.add_argument("--trend-store", dest="trend_store", default=None,
                       help="trend_store.json 路径（可选，渲染「市场趋势洞察」Phase 8.1）")
    parser.add_argument("--competitiveness-store", dest="competitiveness_store", default=None,
                       help="competitiveness_store.json 路径（可选，渲染「竞争力动态」Phase 8.2）")
    parser.add_argument("--competitiveness-provider", dest="competitiveness_provider", default=None,
                       help="竞争力段接入 agnes 教练式叙述（可选，如 agnes；不给则纯确定性离线）")
    parser.add_argument("--career-log", dest="career_log", default=None,
                        help="职业日志路径（默认自动读取 career_log.LOG_FILE，用于竞争力 delta 的面试归因）；可选")
    args = parser.parse_args()

    # 文件存在检查
    input_path = Path(args.input)
    profile_path = Path(args.profile)

    if not input_path.exists():
        print(f"✗ 输入文件不存在: {input_path}", file=sys.stderr)
        print(f"  请先运行 smart_score.py 生成 scored_results.json", file=sys.stderr)
        sys.exit(1)
    if not profile_path.exists():
        print(f"✗ 画像文件不存在: {profile_path}", file=sys.stderr)
        print(f"  请先运行 gen_profile.py 生成 boundary_profile.json", file=sys.stderr)
        sys.exit(1)

    # 加载数据（带 JSON 解析保护）
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"✗ scored_results.json 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"✗ boundary_profile.json 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 结构基础校验
    if "recommendations" not in data:
        print(f"✗ scored_results.json 缺少 'recommendations' 字段", file=sys.stderr)
        print(f"  该文件可能不是 smart_score.py 的有效输出，请检查", file=sys.stderr)
        sys.exit(1)

    # 加载 decision_context（可选）
    decision_context = None
    if args.decision_context:
        dc_path = Path(args.decision_context)
        if dc_path.exists():
            try:
                decision_context = json.loads(dc_path.read_text(encoding="utf-8"))
                print(f"  已加载投递策略: {dc_path}")
            except json.JSONDecodeError:
                print(f"  ⚠ decision_context.json 解析失败，跳过", file=sys.stderr)

    # Phase 9.2：贯通三智能段（历史漏斗 / 趋势洞察 / 竞争力动态），各自失败静默跳过
    history_funnel, trend_html, comp_html = build_optional_sections(
        history_store=args.history_store,
        trend_store=args.trend_store,
        competitiveness_store=args.competitiveness_store,
        competitiveness_provider=args.competitiveness_provider,
        career_log_path=args.career_log,
        now=datetime.now(),
    )
    if args.history_store and history_funnel is not None:
        print(f"  已加载历史转化漏斗: {args.history_store}")
    if args.trend_store and trend_html is not None:
        print(f"  已加载市场趋势洞察: {args.trend_store}")
    if args.competitiveness_store and comp_html is not None:
        print(f"  已加载竞争力动态评估: {args.competitiveness_store}"
              + (f" + agnes 教练叙述（{args.competitiveness_provider}）" if args.competitiveness_provider else ""))

    # 生成报告
    html = generate_html(data, profile, decision_context, history_funnel, trend_html,
                         now=datetime.now(), comp_html=comp_html)

    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"✓ 报告已生成: {output_path}")
    print(f"  A档: {data.get('summary', {}).get('tier_A', 0)} | "
          f"B档: {data.get('summary', {}).get('tier_B', 0)} | "
          f"C档: {data.get('summary', {}).get('tier_C', 0)}")


if __name__ == "__main__":
    main()
