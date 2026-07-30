#!/usr/bin/env python3
"""Phase 8.1 岗位趋势感知 — 测试（纯本地、零 LLM，可离线回归）。"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from trend_analyzer import (
    analyze_trend,
    append_snapshot,
    build_snapshot,
    capture_snapshot,
    classify_direction,
    keyword_hit_rate,
    load_store,
    render_full_html,
    render_trend_html,
)


def _job(title: str, text: str) -> dict:
    return {"title": title, "full_text": text}


def _jobs_raw(jobs) -> str:
    """jobs: list of (title, body) -> jobs_raw.txt 文本。"""
    blocks = []
    for i, (t, b) in enumerate(jobs, start=1):
        blocks.append(f"--- JOB {i} ---\n{t}\n{b}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# 方向与关键词匹配
# ---------------------------------------------------------------------------
def test_classify_direction():
    assert classify_direction("高级后端工程师 - 推荐系统") == "后端开发"
    assert classify_direction("前端开发工程师 - React") == "前端/客户端"
    assert classify_direction("算法工程师 NLP 大模型") == "算法/机器学习"
    assert classify_direction("产品经理 - 增长") == "产品"
    assert classify_direction("莫名其妙的岗位 xyz") == "其他"


def test_keyword_hit_rate():
    jobs = [_job("A", "需要 Python 与 Go"), _job("B", "需要 Java")]
    assert keyword_hit_rate(jobs, "python") == 0.5
    assert keyword_hit_rate(jobs, "java") == 0.5
    assert keyword_hit_rate(jobs, "rust") == 0.0
    assert keyword_hit_rate([], "python") == 0.0


# ---------------------------------------------------------------------------
# 快照构建与存储
# ---------------------------------------------------------------------------
def test_build_snapshot_basic():
    jobs = [
        _job("高级后端工程师", "要求 Python Go 分布式 微服务"),
        _job("前端开发工程师", "要求 React TypeScript 前端"),
    ]
    snap = build_snapshot(jobs, date_str="2026-07-01")
    assert snap["date"] == "2026-07-01"
    assert snap["total"] == 2
    assert snap["direction_counts"]["后端开发"] == 1
    assert snap["direction_counts"]["前端/客户端"] == 1
    assert 0.0 <= snap["keyword_rates"]["python"] <= 1.0
    assert snap["job_titles"] == ["高级后端工程师", "前端开发工程师"]


def test_append_snapshot_overwrite_and_sort(tmp_path):
    store_p = tmp_path / "trend_store.json"
    s1 = build_snapshot([_job("A", "python")], date_str="2026-07-01")
    s2 = build_snapshot([_job("B", "python")], date_str="2026-07-03")
    append_snapshot(str(store_p), s1)
    append_snapshot(str(store_p), s2)
    store = load_store(str(store_p))
    assert [s["date"] for s in store["snapshots"]] == ["2026-07-01", "2026-07-03"]
    # 同日重跑应覆盖而非新增
    append_snapshot(str(store_p), build_snapshot([_job("C", "python")], date_str="2026-07-01"))
    store = load_store(str(store_p))
    assert len(store["snapshots"]) == 2
    assert store["snapshots"][0]["total"] == 1
    assert store["snapshots"][0]["job_titles"] == ["C"]


def test_capture_snapshot_from_file(tmp_path):
    raw = _jobs_raw([
        ("后端工程师", "要求 Python 分布式"),
        ("前端工程师", "要求 React 前端"),
    ])
    p = tmp_path / "jobs_raw.txt"
    p.write_text(raw, encoding="utf-8")
    snap = capture_snapshot(str(p), date_str="2026-07-01")
    assert snap["total"] == 2
    assert snap["direction_counts"]["后端开发"] == 1
    assert snap["direction_counts"]["前端/客户端"] == 1


# ---------------------------------------------------------------------------
# 趋势分析
# ---------------------------------------------------------------------------
def _make_store_two_rounds() -> dict:
    snap_a = build_snapshot([
        _job("后端工程师甲", "Python Go 分布式 微服务"),
        _job("前端工程师甲", "React 前端 TypeScript"),
    ], date_str="2026-07-01")
    snap_b = build_snapshot([
        _job("后端工程师乙", "Python Go 分布式 微服务 Kafka"),
        _job("后端工程师丙", "Python Kafka 机器学习"),
        _job("算法工程师", "大模型 LLM Python 机器学习"),
    ], date_str="2026-07-15")
    return {"snapshots": [snap_a, snap_b]}


def test_analyze_not_enough():
    store = {"snapshots": [build_snapshot([_job("A", "python")], date_str="2026-07-01")]}
    res = analyze_trend(store)
    assert res["enough"] is False
    assert res["snapshots"] == 1


def test_analyze_deltas():
    store = _make_store_two_rounds()
    res = analyze_trend(store)
    assert res["enough"] is True
    assert res["total_latest"] == 3 and res["total_ref"] == 2
    assert res["total_delta"] == 1
    assert res["total_pct"] == 0.5
    # 方向漂移
    assert res["direction_drift"]["后端开发"]["delta"] == 1
    assert res["direction_drift"]["前端/客户端"]["delta"] == -1
    assert res["direction_drift"]["算法/机器学习"]["delta"] == 1
    # 关键词漂移按绝对变化降序，top 必为最大绝对变化项（构造保证）
    top = res["top_keywords"][0]
    max_abs = max(abs(d["delta"]) for d in res["keyword_drift"])
    assert abs(top["delta"]) == max_abs
    # 关键漂移方向正确：python 上升、前端 下降
    by_kw = {d["keyword"]: d["delta"] for d in res["keyword_drift"]}
    assert by_kw["python"] == 0.5
    assert by_kw["前端"] == -0.5
    # 时间序列
    assert [s["date"] for s in res["series"]] == ["2026-07-01", "2026-07-15"]
    # first_seen：B 中标题不在 A 中
    assert set(res["first_seen"]) == {"后端工程师乙", "后端工程师丙", "算法工程师"}


def test_analyze_weeks_selection():
    # 三轮快照：07-01 / 07-08 / 07-15
    s1 = build_snapshot([_job("A", "python")], date_str="2026-07-01")
    s2 = build_snapshot([_job("B", "python")], date_str="2026-07-08")
    s3 = build_snapshot([_job("C", "python")], date_str="2026-07-15")
    store = {"snapshots": [s1, s2, s3]}
    # 默认环比上一轮 → 参考 07-08
    assert analyze_trend(store)["ref_date"] == "2026-07-08"
    # weeks=2（14 天）→ 参考 <= 07-01 → 07-01
    assert analyze_trend(store, weeks=2)["ref_date"] == "2026-07-01"


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------
def test_render_trend_html_not_enough():
    store = {"snapshots": [build_snapshot([_job("A", "python")])]}
    assert render_trend_html(analyze_trend(store)) == ""


def test_render_trend_html_enough():
    res = analyze_trend(_make_store_two_rounds())
    html = render_trend_html(res)
    assert "市场趋势洞察" in html
    assert "总量环比变化" in html
    assert "Python" in html or "python" in html
    assert "后端工程师乙" in html  # first_seen 渲染
    assert "trend-section" in html


def test_render_full_html():
    store = _make_store_two_rounds()
    html = render_full_html(store)
    assert html.startswith("<!DOCTYPE html>")
    assert "岗位市场趋势" in html
    assert "trend-section" in html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_capture_analyze_render(tmp_path):
    raw = _jobs_raw([
        ("后端工程师", "Python 分布式 微服务"),
        ("前端工程师", "React 前端"),
    ])
    jobs_p = tmp_path / "jobs_raw.txt"
    jobs_p.write_text(raw, encoding="utf-8")
    store_p = tmp_path / "trend_store.json"
    out_p = tmp_path / "trend_report.html"
    ana_p = tmp_path / "analysis.json"

    # 1) capture（1 轮，不足以分析）
    rc = __import__("trend_analyzer").main([
        "--capture", str(jobs_p), "--store", str(store_p), "--date", "2026-07-01",
    ])
    assert rc == 0
    assert load_store(str(store_p))["snapshots"][0]["total"] == 2

    # analyze → 单轮不足
    rc = __import__("trend_analyzer").main([
        "--analyze", "--store", str(store_p), "--output", str(ana_p),
    ])
    assert rc == 0
    assert json.loads(ana_p.read_text(encoding="utf-8"))["enough"] is False

    # 追加第 2 轮并 analyze → 充足
    jobs_p2 = tmp_path / "jobs_raw2.txt"
    jobs_p2.write_text(_jobs_raw([
        ("后端工程师", "Python 分布式 微服务 Kafka"),
        ("算法工程师", "大模型 LLM Python"),
        ("数据工程师", "Python SQL Spark"),
    ]), encoding="utf-8")
    __import__("trend_analyzer").main([
        "--capture", str(jobs_p2), "--store", str(store_p), "--date", "2026-07-08",
    ])
    rc = __import__("trend_analyzer").main([
        "--analyze", "--store", str(store_p), "--output", str(ana_p),
    ])
    assert rc == 0
    assert json.loads(ana_p.read_text(encoding="utf-8"))["enough"] is True

    # render 独立页
    rc = __import__("trend_analyzer").main([
        "--render", "--store", str(store_p), "--output", str(out_p),
    ])
    assert rc == 0
    html = out_p.read_text(encoding="utf-8")
    assert "trend-section" in html


# ---------------------------------------------------------------------------
# 与 generate_report 集成（验证 HTML 注入点不破坏报告）
# ---------------------------------------------------------------------------
def test_generate_report_injects_trend(tmp_path):
    import generate_report

    data = {
        "recommendations": {"tier_A": [], "tier_B": [], "tier_C": []},
        "summary": {"tier_A": 0, "tier_B": 0, "tier_C": 0},
    }
    profile = {}
    res = analyze_trend(_make_store_two_rounds())
    trend_html = render_trend_html(res)
    html = generate_report.generate_html(data, profile, None, None, trend_html)
    assert "市场趋势洞察" in html
    assert "trend-section" in html
    # 基本结构未被破坏
    assert html.startswith("<!DOCTYPE html>")
    assert "report-footer" in html
