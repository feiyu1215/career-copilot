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


def generate_html(data: dict, profile: dict, decision_context: dict = None) -> str:
    """生成完整的 HTML 报告"""
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
    pipeline = data.get("pipeline", {})

    generated_at = data.get("generated_at", datetime.now().isoformat())
    total_jobs = pipeline.get("stage1", {}).get("total_jobs", 0)
    top_k = pipeline.get("stage1", {}).get("top_k", 0)
    direction_anchor = pipeline.get("direction_anchor", direction_text)

    # Stage 1 全量分数分布（用于漏斗可视化）
    s1_scores = data.get("stage1_all_scores", [])

    # 生成岗位卡片 HTML
    def job_card(job: dict, tier: str) -> str:
        tier_colors = {"A": "#059669", "B": "#d97706", "C": "#6b7280"}
        tier_labels = {"A": "强烈推荐", "B": "可以考虑", "C": "迁移较远"}
        tier_bg = {"A": "#ecfdf5", "B": "#fffbeb", "C": "#f9fafb"}
        color = tier_colors.get(tier, "#6b7280")
        label = tier_labels.get(tier, tier)
        bg = tier_bg.get(tier, "#f9fafb")

        reasons_html = "".join(f'<li>{r}</li>' for r in job.get("match_reasons", []))
        risks_html = "".join(
            f'<span class="risk-tag">{r}</span>' for r in job.get("risks", [])
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
        meta_text = " · ".join(meta_parts) if meta_parts else ""

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
                f'{pos_labels.get(positioning, positioning)}</span>'
            )
        eng_req = job.get("english_requirement", "")
        if eng_req:
            eng_label_map = {"fluent": "🌐 英语流利", "preferred": "🌐 英语优先", "implicit": "🌐 国际化"}
            cond_tags.append(f'<span class="cond-tag tag-eng">{eng_label_map.get(eng_req, eng_req)}</span>')
        if job.get("is_core_team"):
            cond_tags.append('<span class="cond-tag tag-core">⭐ 核心团队</span>')
        if job.get("is_tech_strong"):
            cond_tags.append('<span class="cond-tag tag-tech">💻 技术依赖</span>')
        cond_tags_html = f'<div class="card-tags">{" ".join(cond_tags)}</div>' if cond_tags else ""

        # 构建标题：如果有 URL，标题可点击跳转
        if job_url:
            title_html = f'<a href="{job_url}" target="_blank" rel="noopener" class="job-title-link" onclick="event.stopPropagation();">{title}</a>'
        else:
            title_html = title

        return f'''
        <div class="job-card" id="{job_id}" data-tier="{tier}" style="border-left: 4px solid {color}; background: {bg};">
          <div class="card-header">
            <div class="card-title-row">
              <h3 class="job-title">{title_html}</h3>
              <div class="score-badge" style="background: {color}; color: white;">
                {score:.0f}
              </div>
            </div>
            <div class="job-id-row">
              <span class="job-id-label">{job_id}</span>
              {f'<a href="{job_url}" target="_blank" rel="noopener" class="job-link" onclick="event.stopPropagation();">查看原始岗位 ↗</a>' if job_url else ''}
            </div>
            {f'<div class="job-meta">{meta_text}</div>' if meta_text else ''}
            <div class="tier-label" style="color: {color};">{label}</div>
            {cond_tags_html}
          </div>
          <div class="card-body">
            <div class="reasons">
              <strong>匹配理由：</strong>
              <ul>{reasons_html}</ul>
            </div>
            {f'<div class="risks"><strong>风险：</strong>{risks_html}</div>' if risks_html else ''}
            {f'<div class="advice"><strong>建议：</strong>{advice}</div>' if advice else ''}
            <div class="scores-detail">
              <span class="s1-score">初筛分: {s1_score:.0f}</span>
              <span class="s2-score">精排分: {score:.0f}</span>
            </div>
          </div>
        </div>'''

    tier_a_cards = "\n".join(job_card(j, "A") for j in tier_a)
    tier_b_cards = "\n".join(job_card(j, "B") for j in tier_b)
    tier_c_cards = "\n".join(job_card(j, "C") for j in tier_c)

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
<title>岗位匹配报告 — {role_type}</title>
<style>
:root {{
  --bg: #fafaf9;
  --card-bg: #ffffff;
  --text: #1c1917;
  --text-secondary: #57534e;
  --border: #e7e5e4;
  --accent-green: #059669;
  --accent-amber: #d97706;
  --accent-gray: #6b7280;
  --shadow: 0 1px 3px rgba(28, 25, 23, 0.08), 0 1px 2px rgba(28, 25, 23, 0.04);
  --shadow-md: 0 4px 6px rgba(28, 25, 23, 0.07), 0 2px 4px rgba(28, 25, 23, 0.04);
  --radius: 12px;
  --radius-sm: 8px;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  padding: 2rem 1rem;
}}

.container {{
  max-width: 900px;
  margin: 0 auto;
}}

/* Header */
.report-header {{
  text-align: center;
  margin-bottom: 3rem;
  padding: 2.5rem 2rem;
  background: var(--card-bg);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}}

.report-header h1 {{
  font-size: 1.75rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
  color: var(--text);
}}

.report-header .subtitle {{
  font-size: 1rem;
  color: var(--text-secondary);
  margin-bottom: 1.5rem;
}}

.report-header .direction-tags {{
  display: flex;
  justify-content: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}}

.direction-tag {{
  background: #f0fdf4;
  color: var(--accent-green);
  padding: 0.25rem 0.75rem;
  border-radius: 99px;
  font-size: 0.85rem;
  font-weight: 500;
  border: 1px solid #bbf7d0;
}}

/* Stats bar */
.stats-bar {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 1rem;
  margin-bottom: 2.5rem;
}}

.stat-card {{
  background: var(--card-bg);
  border-radius: var(--radius-sm);
  padding: 1.25rem;
  text-align: center;
  box-shadow: var(--shadow);
}}

.stat-card .stat-value {{
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text);
}}

.stat-card .stat-label {{
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-top: 0.25rem;
}}

.stat-card.green .stat-value {{ color: var(--accent-green); }}
.stat-card.amber .stat-value {{ color: var(--accent-amber); }}
.stat-card.gray .stat-value {{ color: var(--accent-gray); }}

/* Funnel */
.funnel {{
  background: var(--card-bg);
  border-radius: var(--radius);
  padding: 1.5rem 2rem;
  margin-bottom: 2.5rem;
  box-shadow: var(--shadow);
}}

.funnel h2 {{
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 1rem;
}}

.funnel-steps {{
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}}

.funnel-step {{
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}}

.funnel-step .num {{
  font-weight: 700;
  font-size: 1.1rem;
  color: var(--text);
}}

.funnel-arrow {{
  color: var(--border);
  font-size: 1.2rem;
}}

/* Filter tabs */
.filter-tabs {{
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}}

.filter-tab {{
  padding: 0.5rem 1rem;
  border-radius: 99px;
  border: 1px solid var(--border);
  background: var(--card-bg);
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.2s;
}}

.filter-tab:hover {{ border-color: var(--accent-green); color: var(--accent-green); }}
.filter-tab.active {{ background: var(--accent-green); color: white; border-color: var(--accent-green); }}
.filter-tab.active-b {{ background: var(--accent-amber); color: white; border-color: var(--accent-amber); }}
.filter-tab.active-c {{ background: var(--accent-gray); color: white; border-color: var(--accent-gray); }}

/* Job cards */
.tier-section {{
  margin-bottom: 2rem;
}}

.tier-section h2 {{
  font-size: 1.2rem;
  font-weight: 600;
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid var(--border);
}}

.job-card {{
  background: var(--card-bg);
  border-radius: var(--radius-sm);
  padding: 1.25rem 1.5rem;
  margin-bottom: 0.75rem;
  box-shadow: var(--shadow);
  transition: box-shadow 0.2s, transform 0.15s;
  cursor: pointer;
}}

.job-card:hover {{
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}}

.card-header {{
  margin-bottom: 0.5rem;
}}

.card-title-row {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}}

.job-title {{
  font-size: 1rem;
  font-weight: 600;
  color: var(--text);
  flex: 1;
}}

.score-badge {{
  min-width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 700;
  flex-shrink: 0;
}}

.job-id-row {{
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.2rem;
}}

.job-id-label {{
  font-size: 0.7rem;
  font-family: "SF Mono", "Fira Code", monospace;
  color: var(--text-secondary);
  background: var(--border);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}}

.job-link {{
  font-size: 0.75rem;
  color: var(--accent-green);
  text-decoration: none;
  font-weight: 500;
}}

.job-link:hover {{
  text-decoration: underline;
}}

.job-title-link {{
  color: inherit;
  text-decoration: none;
}}

.job-title-link:hover {{
  color: var(--accent-green);
  text-decoration: underline;
}}

.job-meta {{
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-top: 0.25rem;
}}

.tier-label {{
  font-size: 0.75rem;
  font-weight: 600;
  margin-top: 0.25rem;
}}

.card-body {{
  display: none;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
  font-size: 0.9rem;
}}

.job-card.expanded .card-body {{ display: block; }}

.reasons ul {{
  margin: 0.25rem 0 0.5rem 1.2rem;
  color: var(--text-secondary);
}}

.reasons li {{ margin-bottom: 0.2rem; }}

.risks {{ margin: 0.5rem 0; }}

.risk-tag {{
  display: inline-block;
  background: #fef2f2;
  color: #dc2626;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.8rem;
  margin-right: 0.4rem;
  margin-bottom: 0.3rem;
}}

.advice {{
  margin-top: 0.5rem;
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-style: italic;
}}

.scores-detail {{
  margin-top: 0.5rem;
  display: flex;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
}}

/* Condition tags (English / Core Team / Tech) */
.card-tags {{
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-top: 0.35rem;
}}

.cond-tag {{
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 500;
}}

.cond-tag.tag-eng {{
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}}

.cond-tag.tag-core {{
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}}

.cond-tag.tag-tech {{
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}}

/* Footer */
.report-footer {{
  text-align: center;
  padding: 2rem;
  color: var(--text-secondary);
  font-size: 0.8rem;
}}

/* Responsive */
@media (max-width: 640px) {{
  body {{ padding: 1rem 0.5rem; }}
  .report-header {{ padding: 1.5rem 1rem; }}
  .report-header h1 {{ font-size: 1.3rem; }}
  .stats-bar {{ grid-template-columns: repeat(2, 1fr); }}
  .funnel-steps {{ flex-direction: column; align-items: flex-start; }}
  .funnel-arrow {{ display: none; }}
}}
</style>
</head>
<body>

<div class="container">
  <!-- Header -->
  <div class="report-header">
    <h1>岗位匹配报告</h1>
    <p class="subtitle">{role_type} · {generated_at[:10]}</p>
    <div class="direction-tags">
      {"".join(f'<span class="direction-tag">{a}</span>' for a in direction_anchors[:4])}
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
      总耗时 {total_time:.0f}s · 方向锚定: {direction_anchor}
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

  <!-- Footer -->
  <div class="report-footer">
    <p>由 Career Copilot 生成 · {generated_at[:10]}</p>
    <p>Stage 1: {pipeline.get("stage1", dict()).get("model", "?")} · Stage 2: {pipeline.get("stage2", dict()).get("model", "?")}</p>
  </div>
</div>

<script>
// Card expand/collapse
document.querySelectorAll('.job-card').forEach(card => {{
  card.addEventListener('click', () => {{
    card.classList.toggle('expanded');
  }});
}});

// Filter tabs
document.querySelectorAll('.filter-tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    const filter = tab.dataset.filter;

    // Update tab states
    document.querySelectorAll('.filter-tab').forEach(t => {{
      t.classList.remove('active', 'active-b', 'active-c');
    }});
    if (filter === 'A' || filter === 'all') tab.classList.add('active');
    else if (filter === 'B') tab.classList.add('active-b');
    else if (filter === 'C') tab.classList.add('active-c');

    // Show/hide sections
    document.querySelectorAll('.tier-section').forEach(section => {{
      const tier = section.dataset.tierSection;
      if (filter === 'all' || filter === tier) {{
        section.style.display = '';
      }} else {{
        section.style.display = 'none';
      }}
    }});
  }});
}});

// Auto-expand A-tier cards on load
document.querySelectorAll('.job-card[data-tier="A"]').forEach(card => {{
  card.classList.add('expanded');
}});
</script>

</body>
</html>'''

    return html


def main():
    parser = argparse.ArgumentParser(description="从 scored_results.json 生成 HTML 报告")
    parser.add_argument("--input", required=True, help="scored_results.json 路径")
    parser.add_argument("--profile", required=True, help="boundary_profile.json 路径")
    parser.add_argument("--output", required=True, help="输出 HTML 文件路径")
    parser.add_argument("--decision-context", default=None,
                       help="decision_context.json 路径（可选，assess_competitiveness 输出）")
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

    # 生成报告
    html = generate_html(data, profile, decision_context)

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
