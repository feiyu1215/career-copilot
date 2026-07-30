"""T1–T15 审计回归测试：generate_report 的 HTML 转义（修复 MEDIUM bug）。

修复前 render_job_card / generate_html 对所有动态字段原样插值，
JD 文本含 `<` `&` `"` 会破坏报告结构，属性上下文（href/id）还能注入/XSS。
修复后任何动态值都经 html.escape（属性上下文 quote=True）。
"""

import sys

sys.path.insert(0, "scripts")

import generate_report  # noqa: E402


def _evil_job():
    return {
        "job_id": 'JOB"<x>',
        "title": 'C++ & <script>alert(1)</script>',
        "url": 'https://x.com/a"onmouseover="x()"',
        "department": "研发",
        "location": "北京",
        "match_reasons": ['needs "quotes" & <b>bold</b>'],
        "risks": ['risk & <i>italic</i>'],
        "advice": 'do <b>this</b> & that',
        "score": 85,
        "stage1_score": 80,
    }


def test_render_job_card_escapes_html_and_attributes():
    html = generate_report.render_job_card(_evil_job(), "A")

    # 元素体：原始标签被转义，不能出现裸 <script>
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>" not in html
    assert "&lt;b&gt;" in html

    # 属性上下文（href / id）：引号被转义，不能形成属性注入
    assert '"onmouseover' not in html
    assert "&quot;onmouseover" in html
    assert 'id="JOB"' not in html  # 裸 id 属性不被注入
    assert "id=&quot;JOB" in html or "id=&#x27;" in html or "JOB&quot;&lt;x&gt;" in html

    # 关键字段确实出现在转义后的文本中
    assert "C++ &amp;" in html
    assert "needs &quot;quotes&quot;" in html


def test_generate_html_escapes_dynamic_fields():
    data = {
        "recommendations": {"tier_A": [], "tier_B": [], "tier_C": []},
        "summary": {"tier_A": 0, "tier_B": 0, "tier_C": 0},
        "pipeline": {
            "stage1": {"model": "fake<s>", "total_jobs": 0, "top_k": 0},
            "stage2": {"model": "fake", "wall_time": 0},
            "stage1_5": {"wall_time": 0},
            "direction_anchor": "推荐 & <系统>",
        },
        "generated_at": "2026-07-22T00:00:00",
    }
    profile = {"role_type": "AI<产品>", "direction_anchors": ["推荐<b>系统</b>"]}
    html = generate_report.generate_html(data, profile)

    assert "AI&lt;产品&gt;" in html
    assert "推荐&lt;b&gt;系统&lt;/b&gt;" in html
    assert "fake&lt;s&gt;" in html
    assert "推荐 &amp; &lt;系统&gt;" in html
    # 无裸标签泄漏
    assert "<产品>" not in html
    assert "<系统>" not in html


# ---------------------------------------------------------------------------
# Phase 9.1：竞争力段接入 agnes 教练式叙述
# ---------------------------------------------------------------------------

def _fake_competitiveness_tracker(narrative=None):
    """构造假 competitiveness_tracker 模块，供 render_competitiveness_section 懒加载。"""
    import types
    mod = types.ModuleType("competitiveness_tracker")
    store = {
        "2026-06": {"period": "2026-06", "overall": 50,
                    "系统设计": 50, "算法与数据结构": 50, "工程实现": 50,
                    "业务理解": 50, "沟通表达": 50, "项目经验": 50},
        "2026-07": {"period": "2026-07", "overall": 55,
                    "系统设计": 60, "算法与数据结构": 47, "工程实现": 52,
                    "业务理解": 53, "沟通表达": 55, "项目经验": 54},
    }
    delta = {"from_period": "2026-06", "to_period": "2026-07", "overall_delta": 5.0,
             "dimensions": [], "top_up": [], "top_down": [], "attribution": "测试"}
    mod.load_store = lambda p: store
    mod.previous_period = lambda p: "2026-06"
    mod.compute_delta = lambda cur, prev, gap_events=None: delta
    mod.render_delta_report = lambda d, current=None: "竞争力变化报告（测试）"
    mod.render_radar_overlay = lambda cur, prev: "<svg>radar</svg>"
    mod.load_events = lambda p: []
    mod.enrich_narrative = lambda report_md, provider=None, model=None: narrative
    return mod


def test_render_competitiveness_section_injects_narrative_with_provider(monkeypatch):
    fake = _fake_competitiveness_tracker(narrative="建议加强算法刷题，保持系统设计优势。")
    monkeypatch.setitem(sys.modules, "competitiveness_tracker", fake)
    html = generate_report.render_competitiveness_section("fake_store.json", provider="agnes")
    assert "competitiveness-section" in html
    assert "comp-narrative" in html
    assert "建议加强算法刷题" in html
    assert "教练建议" in html


def test_render_competitiveness_section_no_narrative_without_provider(monkeypatch):
    fake = _fake_competitiveness_tracker(narrative="不应出现")
    monkeypatch.setitem(sys.modules, "competitiveness_tracker", fake)
    html = generate_report.render_competitiveness_section("fake_store.json")
    assert "competitiveness-section" in html
    assert "comp-narrative" not in html
    assert "不应出现" not in html


def test_build_optional_sections_threads_stores(monkeypatch):
    """build_optional_sections 应按 store 是否提供，分别渲染三段（或返回 None）。"""
    import types
    monkeypatch.setattr(generate_report, "render_competitiveness_section",
                        lambda store, cl=None, provider=None: "<div>comp</div>")

    fake_cal = types.ModuleType("calibration_feedback")
    fake_cal.compute_tier_funnel = lambda apps: {"rows": [], "total_reached": 0}
    fake_cal.load_applications = lambda p: []
    monkeypatch.setitem(sys.modules, "calibration_feedback", fake_cal)

    fake_trend = types.ModuleType("trend_analyzer")
    fake_trend.load_store = lambda p: {}
    fake_trend.analyze_trend = lambda s: {}
    fake_trend.render_trend_html = lambda t: "<div>trend</div>"
    monkeypatch.setitem(sys.modules, "trend_analyzer", fake_trend)

    # 给定三 store → 三段均非 None；provider 透传给竞争力段
    hf, th, ch = generate_report.build_optional_sections(
        history_store="h.json", trend_store="t.json",
        competitiveness_store="c.json", competitiveness_provider="agnes")
    assert hf is not None and th is not None and ch is not None

    # 不给任何 store → 三段均 None
    hf2, th2, ch2 = generate_report.build_optional_sections()
    assert hf2 is None and th2 is None and ch2 is None
