"""Phase 8.2 竞争力动态评估：确定性内核 + 雷达图 + career_log 钩子集成 + agnes 降级。

全部离线、确定性。agnes 相关仅验证「调用失败优雅降级为确定性叙述」这一安全网（不依赖网络）。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import competitiveness_tracker as ct  # noqa: E402
from competitiveness_tracker import (  # noqa: E402
    build_snapshot,
    compute_delta,
    load_store,
    map_to_dimensions,
    recompute_after_event,
    render_radar_overlay,
    save_store,
)


def _write_log(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")


def test_map_to_dimensions():
    assert "系统设计" in map_to_dimensions("系统设计能力不错")
    assert "算法与数据结构" in map_to_dimensions("LeetCode 刷题较多")
    assert "项目经验" in map_to_dimensions("实习项目落地成果好")
    # 不命中
    assert map_to_dimensions("今天天气真好") == []
    # 一条文本可命中多维度
    assert set(map_to_dimensions("系统设计与项目经验都强")).issuperset({"系统设计", "项目经验"})


def test_build_snapshot_baseline():
    snap = build_snapshot([], as_of=datetime(2026, 7, 1), period="2026-07")
    assert snap["overall"] == 50.0
    assert all(v == 50.0 for v in snap["dimensions"].values())
    assert snap["n_interviews"] == 0
    assert snap["pass_rate"] is None


def test_build_snapshot_accumulates_and_clamps():
    events = [{"type": "interview_done", "timestamp": "2026-07-01T10:00:00+08:00",
               "company": "A", "result": "pass",
               "strong_points": ["系统设计", "架构", "分布式", "高并发",
                                  "微服务", "扩容", "架構", "高并發"],  # 全部命中系统设计
               "weak_points": []}] * 8
    snap = build_snapshot(events, as_of=datetime(2026, 7, 31), period="2026-07")
    # 单维度每事件封顶 +8，8 事件应被 clamp 到 100
    assert snap["dimensions"]["系统设计"] == 100.0
    assert snap["dimensions"]["算法与数据结构"] == 50.0  # 未命中保持基线


def test_build_snapshot_two_months_cumulative():
    events = [
        {"type": "interview_done", "timestamp": "2026-06-15T10:00:00+08:00",
         "company": "A", "result": "pass",
         "strong_points": ["系统设计"], "weak_points": ["算法"]},
        {"type": "interview_done", "timestamp": "2026-07-20T10:00:00+08:00",
         "company": "B", "result": "pass",
         "strong_points": ["系统设计", "项目经验"], "weak_points": []},
    ]
    # 累计到 7 月底
    snap = build_snapshot(events, as_of=datetime(2026, 7, 31, 23, 59, 59), period="2026-07")
    assert snap["dimensions"]["系统设计"] == 66.0   # 50 + 8 + 8
    assert snap["dimensions"]["项目经验"] == 58.0   # 50 + 8
    assert snap["dimensions"]["算法与数据结构"] == 44.0  # 50 - 6
    assert snap["n_interviews"] == 2


def test_compute_delta_basic():
    events = [
        {"type": "interview_done", "timestamp": "2026-06-15T10:00:00+08:00",
         "company": "A", "result": "pass",
         "strong_points": ["系统设计"], "weak_points": ["算法"]},
        {"type": "interview_done", "timestamp": "2026-07-20T10:00:00+08:00",
         "company": "B", "result": "pass",
         "strong_points": ["系统设计", "项目经验"], "weak_points": []},
    ]
    cur = build_snapshot(events, as_of=datetime(2026, 7, 31, 23, 59, 59), period="2026-07")
    prev = build_snapshot(events[:1], as_of=datetime(2026, 6, 30, 23, 59, 59), period="2026-06")
    delta = compute_delta(cur, prev, gap_events=[events[1]])
    assert delta is not None
    assert delta["from_period"] == "2026-06"
    assert delta["to_period"] == "2026-07"
    assert delta["dimensions"]["系统设计"]["delta"] == 8.0
    assert delta["dimensions"]["系统设计"]["from"] == 58.0
    assert delta["dimensions"]["系统设计"]["to"] == 66.0
    assert delta["dimensions"]["系统设计"]["signal"] == "up"
    # 算法本月无负向信号 → 持平
    assert delta["dimensions"]["算法与数据结构"]["signal"] == "flat"
    # top_up 应包含 系统设计
    assert any(x["dim"] == "系统设计" for x in delta["top_up"])


def test_compute_delta_none_when_no_previous():
    cur = build_snapshot([], as_of=datetime(2026, 7, 1), period="2026-07")
    assert compute_delta(cur, None) is None


def test_render_radar_overlay_two_polygons():
    events = [
        {"type": "interview_done", "timestamp": "2026-06-15T10:00:00+08:00",
         "company": "A", "result": "pass", "strong_points": ["系统设计"], "weak_points": ["算法"]},
        {"type": "interview_done", "timestamp": "2026-07-20T10:00:00+08:00",
         "company": "B", "result": "pass", "strong_points": ["系统设计", "项目经验"], "weak_points": []},
    ]
    cur = build_snapshot(events, as_of=datetime(2026, 7, 31, 23, 59, 59), period="2026-07")
    prev = build_snapshot(events[:1], as_of=datetime(2026, 6, 30, 23, 59, 59), period="2026-06")
    svg = render_radar_overlay(cur, prev)
    assert svg.startswith("<svg")
    # 数据多边形填充唯一：本月 rgba(37,99,235,0.18)；上月 rgba(148,163,184,0.18)
    # （图例方块用 0.5 透明度，不混淆；网格环用 #e5e7eb 描边，不计）
    assert svg.count('fill="rgba(37,99,235,0.18)"') == 1
    assert svg.count('fill="rgba(148,163,184,0.18)"') == 1
    assert all(dim in svg for dim in ct.DIMENSIONS)
    assert "本月" in svg and "上月" in svg


def test_render_radar_overlay_single_polygon_no_previous():
    cur = build_snapshot([], as_of=datetime(2026, 7, 1), period="2026-07")
    svg = render_radar_overlay(cur, None)
    assert svg.count('fill="rgba(37,99,235,0.18)"') == 1
    assert svg.count('fill="rgba(148,163,184,0.18)"') == 0
    assert "本月" in svg


def test_store_roundtrip_and_idempotent(tmp_path):
    log = tmp_path / "career-log.jsonl"
    store = tmp_path / "comp_store.json"
    events = [
        {"type": "interview_done", "timestamp": "2026-07-20T10:00:00+08:00",
         "company": "B", "result": "pass", "strong_points": ["系统设计", "项目经验"], "weak_points": []},
    ]
    _write_log(log, events)

    ev = events[0]
    cur1, _ = recompute_after_event(ev, career_log_path=str(log), store_path=str(store))
    cur2, _ = recompute_after_event(ev, career_log_path=str(log), store_path=str(store))
    # 幂等：同一月重算结果一致
    assert cur1 == cur2
    loaded = load_store(str(store))
    assert "2026-07" in loaded
    assert loaded["2026-07"]["n_interviews"] == 1


def test_recompute_after_event_delta_across_months(tmp_path):
    log = tmp_path / "career-log.jsonl"
    store = tmp_path / "comp_store.json"
    events = [
        {"type": "interview_done", "timestamp": "2026-06-15T10:00:00+08:00",
         "company": "A", "result": "pass", "strong_points": ["系统设计"], "weak_points": ["算法"]},
        {"type": "interview_done", "timestamp": "2026-07-20T10:00:00+08:00",
         "company": "B", "result": "pass", "strong_points": ["系统设计", "项目经验"], "weak_points": []},
    ]
    _write_log(log, events)
    # 真实世界：6 月面试先触发 6 月快照写入，7 月面试再触发 7 月并重算 delta
    recompute_after_event(events[0], career_log_path=str(log), store_path=str(store))
    cur, delta = recompute_after_event(events[1], career_log_path=str(log), store_path=str(store))
    assert cur["period"] == "2026-07"
    assert delta is not None
    assert delta["dimensions"]["系统设计"]["delta"] == 8.0
    loaded = load_store(str(store))
    assert set(loaded.keys()) == {"2026-06", "2026-07"}


def test_career_log_append_hook_triggers_recompute(tmp_path, monkeypatch):
    import career_log
    log = tmp_path / "career-log.jsonl"
    profile = tmp_path / "career-profile.md"
    store = tmp_path / "comp_store.json"
    monkeypatch.setattr(career_log, "LOG_FILE", log)
    monkeypatch.setattr(career_log, "PROFILE_FILE", profile)
    log.parent.mkdir(parents=True, exist_ok=True)

    career_log.cmd_append(
        "interview_done",
        '{"company":"测试厂","role":"后端","result":"pass","strong_points":["系统设计"],"weak_points":["算法"]}',
        competitiveness_store=str(store),
    )
    loaded = load_store(str(store))
    now_period = f"{datetime.now():%Y-%m}"
    assert now_period in loaded
    assert loaded[now_period]["n_interviews"] == 1
    # 真实日志确实写了事件
    assert log.exists() and "interview_done" in log.read_text(encoding="utf-8")


def test_generate_report_section_renders(tmp_path):
    from generate_report import generate_html, render_competitiveness_section
    events = [
        {"type": "interview_done", "timestamp": "2026-06-15T10:00:00+08:00",
         "company": "A", "result": "pass", "strong_points": ["系统设计"], "weak_points": ["算法"]},
        {"type": "interview_done", "timestamp": "2026-07-20T10:00:00+08:00",
         "company": "B", "result": "pass", "strong_points": ["系统设计", "项目经验"], "weak_points": []},
    ]
    store = tmp_path / "comp_store.json"
    # 直接用 build_snapshot 构造两段快照写入 store
    cur = build_snapshot(events, as_of=datetime(2026, 7, 31, 23, 59, 59), period="2026-07")
    prev = build_snapshot(events[:1], as_of=datetime(2026, 6, 30, 23, 59, 59), period="2026-06")
    save_store(str(store), {"2026-06": prev, "2026-07": cur})

    comp_html = render_competitiveness_section(str(store))
    assert "竞争力动态" in comp_html
    assert "<svg" in comp_html
    html = generate_html({}, {}, comp_html=comp_html)
    assert "competitiveness-section" in html
    assert "竞争力动态" in html


def test_agnes_enrich_fallback_when_call_fails(monkeypatch):
    import sys
    import types

    import competitiveness_tracker as ct

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def chat(self, *a, **k):
            raise RuntimeError("network unreachable")

    fake = types.ModuleType("llm_client")
    fake.LLMClient = FakeClient
    monkeypatch.setitem(sys.modules, "llm_client", fake)

    # provider 给定但调用失败 → 优雅降级为 None（不抛异常、不阻塞）
    assert ct.enrich_narrative("任意报告", provider="agnes") is None
    # 未给 provider → 直接 None（不发网络请求）
    assert ct.enrich_narrative("任意报告") is None


def _inject_agnes_env():
    """复用 test_agnes_e2e 的注入方式：加载 scholar .env 的 agnes 凭据并覆盖 llm_client 快照。

    必须在 import 顺序无关的前提下，保证 agnes provider 真正使用 AGNES_* 变量。
    """
    evals_dir = str(ROOT / "evals")
    if evals_dir not in sys.path:
        sys.path.insert(0, evals_dir)
    import eval_env  # noqa: F401
    import llm_client  # noqa: F401
    from llm_client import PROVIDERS  # noqa: F401
    eval_env.load_provider_env()
    base = os.environ.get("AGNES_BASE_URL", "")
    key = os.environ.get("AGNES_API_KEY", "")
    llm_client.AGNES_BASE_URL = base
    llm_client.AGNES_API_KEY = key
    PROVIDERS["agnes"]["base_url"] = base
    PROVIDERS["agnes"]["api_key"] = key
    return base, key


def test_agnes_enrich_real_call():
    """真实环境端到端：enrich_narrative(provider='agnes') 真正打到 agnes 并返回非空叙述。

    这一测试弥补上一轮「只验证降级」的缺口，并锁定 enrich_narrative 的 async/双参调用签名。
    无凭据则 pytest.skip，不阻断无网络/无凭据环境。
    """
    base, key = _inject_agnes_env()
    if not (base and key):
        pytest.skip("无 AGNES_BASE_URL/AGNES_API_KEY，跳过 agnes 增强真实调用")

    report = (
        "竞争力变化报告（2026-07 vs 2026-06）\n"
        "总评：较上月 +5.0\n"
        "系统设计：+8（本月面试多涉及高并发设计，表现较好）\n"
        "算法与数据结构：-3（两道动态规划题答得一般）\n"
        "工程实现：+2（代码规范，但边界处理略糙）\n"
    )
    narrative = ct.enrich_narrative(report, provider="agnes")
    assert isinstance(narrative, str) and narrative.strip(), "agnes 增强真实调用未返回有效叙述"
