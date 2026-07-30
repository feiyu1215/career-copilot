#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 8.3 智能投递时机建议 — 测试（纯本地、零 LLM，可离线回归）。"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import first_seen
from run_pipeline import _apply_first_seen, _record_first_seen
from generate_report import render_job_card, generate_html


# --------------------------------------------------------------------------- #
# 归一化身份键
# --------------------------------------------------------------------------- #
def test_normalize_key_canonicalizes():
    a = first_seen.normalize_key("后端工程师（推荐系统）")
    b = first_seen.normalize_key("后端工程师 (推荐系统)")
    c = first_seen.normalize_key(" 后端工程师（推荐系统） ")
    assert a == b == c
    # 不同标题应不同键
    assert a != first_seen.normalize_key("前端工程师")


# --------------------------------------------------------------------------- #
# 记录 + 持久化
# --------------------------------------------------------------------------- #
def test_record_first_seen_persists_and_keeps_original(tmp_path):
    store_path = str(tmp_path / "fs.json")
    jobs = [{"job_id": "JOB_1", "title": "后端工程师"},
            {"job_id": "JOB_2", "title": "前端工程师"}]
    now1 = datetime(2026, 7, 1, 9, 0, 0)

    store, fs_map = first_seen.record_first_seen({}, jobs, now=now1)
    first_seen.save_store(store_path, store)
    assert fs_map["JOB_1"] == now1.isoformat()
    assert fs_map["JOB_2"] == now1.isoformat()

    # 重新加载后，再次出现同一岗位应保留原始首见时间
    reloaded = first_seen.load_store(store_path)
    jobs2 = [{"job_id": "JOB_1", "title": "后端工程师"},
             {"job_id": "JOB_3", "title": "算法工程师"}]
    now2 = datetime(2026, 7, 20, 9, 0, 0)
    store2, fs_map2 = first_seen.record_first_seen(reloaded, jobs2, now=now2)
    assert fs_map2["JOB_1"] == now1.isoformat()      # 保留首次
    assert fs_map2["JOB_3"] == now2.isoformat()      # 新岗位取 now


# --------------------------------------------------------------------------- #
# 时机建议
# --------------------------------------------------------------------------- #
def test_timing_advice_fresh():
    now = datetime.now()
    seen = (now - timedelta(hours=1)).isoformat()
    adv = first_seen.timing_advice(seen, now=now)
    assert adv["urgency"] == "fresh"
    assert "h 内投递" in adv["label"]
    assert adv["hours_remaining"] == 47


def test_timing_advice_normal():
    seen = (datetime.now() - timedelta(days=3)).isoformat()
    adv = first_seen.timing_advice(seen, now=datetime.now())
    assert adv["urgency"] == "normal"


def test_timing_advice_stale():
    seen = (datetime.now() - timedelta(days=8)).isoformat()
    adv = first_seen.timing_advice(seen, now=datetime.now())
    assert adv["urgency"] == "stale"
    assert "可能已关闭" in adv["label"]


def test_timing_advice_boundary_48h_is_normal():
    seen = (datetime.now() - timedelta(hours=48)).isoformat()
    adv = first_seen.timing_advice(seen, now=datetime.now())
    assert adv["urgency"] == "normal"


def test_timing_advice_none_returns_none():
    assert first_seen.timing_advice(None) is None
    assert first_seen.timing_advice("") is None


# --------------------------------------------------------------------------- #
# 徽标渲染
# --------------------------------------------------------------------------- #
def test_render_timing_badge_classes():
    now = datetime.now()
    fresh = {"job_id": "J1", "first_seen_at": (now - timedelta(hours=1)).isoformat()}
    normal = {"job_id": "J2", "first_seen_at": (now - timedelta(days=3)).isoformat()}
    stale = {"job_id": "J3", "first_seen_at": (now - timedelta(days=8)).isoformat()}

    assert "badge-urgent" in first_seen.render_timing_badge(fresh, now=now)
    assert "badge-timing" in first_seen.render_timing_badge(normal, now=now)
    assert "badge-stale" in first_seen.render_timing_badge(stale, now=now)


def test_render_timing_badge_no_first_seen_is_empty():
    assert first_seen.render_timing_badge({"job_id": "J"}, now=datetime.now()) == ""


# --------------------------------------------------------------------------- #
# run_pipeline 集成（注入 helper）
# --------------------------------------------------------------------------- #
def test_apply_first_seen_via_run_pipeline():
    scored = {"recommendations": {"tier_A": [{"job_id": "JOB_0", "title": "X"}]}}
    out = _apply_first_seen(scored, {"JOB_0": "2026-07-01T00:00:00"})
    assert out["recommendations"]["tier_A"][0]["first_seen_at"] == "2026-07-01T00:00:00"


def test_apply_first_seen_keeps_existing():
    scored = {"recommendations": {"tier_A": [
        {"job_id": "JOB_0", "title": "X", "first_seen_at": "2026-01-01T00:00:00"}]}}
    out = _apply_first_seen(scored, {})  # 空 map 不覆盖已有
    assert out["recommendations"]["tier_A"][0]["first_seen_at"] == "2026-01-01T00:00:00"


def test_record_first_seen_via_run_pipeline(tmp_path):
    store_path = str(tmp_path / "fs.json")
    opts = SimpleNamespace(first_seen_store=store_path)
    state = {"jobs_lookup": {"JOB_1": {"job_id": "JOB_1", "title": "后端工程师"}}}

    _record_first_seen(opts, state)
    assert Path(store_path).exists()
    assert state["first_seen_map"]["JOB_1"]

    store = first_seen.load_store(store_path)
    assert any("后端工程师" in k for k in store)  # 归一化键含标题

    # 二次记录同一岗位，首见时间应保持不变
    prev = state["first_seen_map"]["JOB_1"]
    _record_first_seen(opts, {"jobs_lookup": {"JOB_1": {"job_id": "JOB_1", "title": "后端工程师"}}})
    assert state["first_seen_map"]["JOB_1"] == prev


# --------------------------------------------------------------------------- #
# generate_report 集成
# --------------------------------------------------------------------------- #
def test_render_job_card_shows_timing_badge():
    now = datetime.now()
    job = {"job_id": "JOB_1", "title": "X",
           "first_seen_at": (now - timedelta(hours=1)).isoformat()}
    html = render_job_card(job, "A", positioning_map=None, now=now)
    assert "badge-urgent" in html
    assert "建议" in html

    html_no = render_job_card({"job_id": "J", "title": "Y"}, "A", now=now)
    assert "badge-urgent" not in html_no
    assert "badge-timing" not in html_no
    assert "badge-stale" not in html_no


def test_generate_html_passes_now_to_cards():
    seen = (datetime.now() - timedelta(hours=1)).isoformat()
    data = {
        "recommendations": {
            "tier_A": [{"job_id": "JOB_1", "title": "X", "first_seen_at": seen}],
            "tier_B": [], "tier_C": [],
        },
        "summary": {"tier_A": 1, "tier_B": 0, "tier_C": 0},
    }
    html = generate_html(data, {}, now=datetime.now())
    assert "badge-urgent" in html
    # 未提供趋势数据时不应渲染趋势 section（与 8.1 互不干扰；CSS 中仅 .trend-section 带点）
    assert '<div class="trend-section">' not in html
