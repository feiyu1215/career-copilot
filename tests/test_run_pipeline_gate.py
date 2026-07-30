"""Phase 4.3 质量门禁在 run_pipeline 中的接入测试。

直接测 quality_gate_check（fetch 之后、score 之前的门禁），
通过 monkeypatch 隔离 smart_score.parse_jobs_raw，避免引入 LLM / 重依赖。
"""
from types import SimpleNamespace

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_pipeline as rp
from job_common import quality_gate


def _opts(**kw):
    base = dict(
        no_quality_gate=False,
        quality_gate_fail=False,
        source="pipeline",
        quality_gate_min_accept_rate=0.5,
        quality_report=None,
        quality_gate_max_warning_rate=None,
        quality_gate_warnings_fatal=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _good_records():
    return [
        {"title": "后端工程师", "company": "美团", "url": "https://zhipin.com/job/1"},
        {"title": "算法工程师", "company": "阿里", "url": "https://job.x.com/2"},
    ]


def test_gate_passes_when_all_valid(monkeypatch, tmp_path):
    p = tmp_path / "jobs_raw.txt"
    p.write_text("dummy\n", encoding="utf-8")  # 让门禁越过「文件缺失跳过」
    monkeypatch.setattr(rp, "_parse_jobs", lambda _: _good_records())
    # 不应抛异常
    rp.quality_gate_check(_opts(), p)


def test_gate_fails_below_min_accept_rate(monkeypatch, tmp_path):
    p = tmp_path / "jobs_raw.txt"
    p.write_text("dummy\n", encoding="utf-8")
    # 1 有效 + 2 拦截（缺标题、占位符+坏 URL）→ 接受率 33% < 0.8
    recs = [
        {"title": "后端工程师", "company": "美团", "url": "https://x.com/1"},
        {"title": "", "company": "腾讯", "url": "https://x.com/2"},
        {"title": "职位", "company": "字节", "url": "www.example.com"},
    ]
    monkeypatch.setattr(rp, "_parse_jobs", lambda _: recs)
    with pytest.raises(RuntimeError):
        rp.quality_gate_check(
            _opts(quality_gate_fail=True, quality_gate_min_accept_rate=0.8), p)


def test_gate_skipped_with_flag(monkeypatch, tmp_path):
    p = tmp_path / "jobs_raw.txt"
    p.write_text("dummy\n", encoding="utf-8")
    # 全坏记录，但 --no-quality-gate → 不抛
    recs = [{"title": "", "company": "", "url": ""}]
    monkeypatch.setattr(rp, "_parse_jobs", lambda _: recs)
    rp.quality_gate_check(_opts(no_quality_gate=True), p)


def test_gate_writes_report(monkeypatch, tmp_path):
    p = tmp_path / "jobs_raw.txt"
    p.write_text("dummy\n", encoding="utf-8")
    report = tmp_path / "qg.json"
    monkeypatch.setattr(rp, "_parse_jobs", lambda _: _good_records())
    rp.quality_gate_check(_opts(quality_report=str(report)), p)
    assert report.exists()
    import json
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["stats"]["accepted"] == 2


def test_gate_warning_threshold_non_fatal(monkeypatch, tmp_path):
    p = tmp_path / "jobs_raw.txt"
    p.write_text("dummy\n", encoding="utf-8")
    # 全部缺薪资/地点/JD → warning_rate=1.0；非致命仅告警
    recs = [{"title": "后端工程师", "company": "美团", "url": "https://x.com/1"}]
    monkeypatch.setattr(rp, "_parse_jobs", lambda _: recs)
    rp.quality_gate_check(
        _opts(quality_gate_max_warning_rate=0.5, quality_gate_warnings_fatal=False), p)


def test_gate_warning_threshold_fatal(monkeypatch, tmp_path):
    p = tmp_path / "jobs_raw.txt"
    p.write_text("dummy\n", encoding="utf-8")
    recs = [{"title": "后端工程师", "company": "美团", "url": "https://x.com/1"}]
    monkeypatch.setattr(rp, "_parse_jobs", lambda _: recs)
    with pytest.raises(RuntimeError):
        rp.quality_gate_check(
            _opts(quality_gate_fail=True, quality_gate_max_warning_rate=0.5,
                  quality_gate_warnings_fatal=True), p)


def test_quality_gate_stats_has_warning_rate():
    recs = [{"title": "后端工程师", "company": "美团", "url": "https://x.com/1"}]
    g = quality_gate(recs)
    assert g["stats"]["warned_records"] == 1
    assert g["stats"]["warning_rate"] == 1.0
    # 补齐字段后无警告
    full = [{"title": "后端工程师", "company": "美团", "url": "https://x.com/1",
             "salary": "30k", "location": "北京", "jd": "desc"}]
    g2 = quality_gate(full)
    assert g2["stats"]["warned_records"] == 0
    assert g2["stats"]["warning_rate"] == 0.0
