"""T14 验收测试：Career Log v2（envelope 字段 + schema + 内存索引 + trace/expire）"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import career_log


def _use_tmp(career_log, tmp_path):
    career_log.LOG_FILE = tmp_path / "career-log.jsonl"
    career_log.BASE_DIR = tmp_path


def test_write_event_enriches_envelope(tmp_path):
    _use_tmp(career_log, tmp_path)
    ev = {"type": "interview_done", "timestamp": career_log.now_iso(),
          "company": "字节", "result": "pass"}
    career_log.write_event(ev)
    # 读取回写内容
    raw = tmp_path / "career-log.jsonl"
    stored = [line for line in raw.read_text(encoding="utf-8").splitlines() if line]
    rec = __import__("json").loads(stored[0])
    assert len(rec["event_id"]) == 32  # UUID4 hex
    assert rec["session_id"]
    assert rec["status"] == "active"
    assert rec["expires_at"] > rec["timestamp"]
    # 原 dict 也被补齐（setdefault 副作用）
    assert ev["event_id"] == rec["event_id"]


def test_validate_event_rejects_missing_required():
    # interview_done 必填 company + result
    import pytest
    with pytest.raises(ValueError):
        career_log.validate_event("interview_done", {"company": "x"})  # 缺 result
    # 合法通过
    career_log.validate_event("interview_done", {"company": "x", "result": "pass"})


def test_match_round_requires_direction_anchors():
    import pytest
    with pytest.raises(ValueError):
        career_log.validate_event("match_round", {"top_matches": []})  # 缺 direction_anchors


def test_event_index_query_by_company_under_50ms_1000_events(tmp_path):
    _use_tmp(career_log, tmp_path)
    # 写入 1000 条：500 家 A、500 家 B
    for i in range(1000):
        c = "A" if i % 2 == 0 else "B"
        career_log.write_event({
            "type": "interview_done",
            "timestamp": career_log.now_iso(),
            "company": c,
            "result": "pass" if i % 3 else "fail",
        })
    idx = career_log.EventIndex(career_log.read_all_events())
    t0 = time.perf_counter()
    res = idx.query(company="A")
    dt = time.perf_counter() - t0
    assert len(res) == 500, f"应查到 500 条 A 公司事件，实际 {len(res)}"
    # 验收：1000 事件按 company 查询 < 50ms
    assert dt < 0.05, f"按 company 查询耗时 {dt*1000:.2f}ms 应 < 50ms"


def test_query_combines_type_and_company(tmp_path):
    _use_tmp(career_log, tmp_path)
    career_log.write_event({"type": "interview_done", "timestamp": career_log.now_iso(),
                            "company": "X", "result": "pass"})
    career_log.write_event({"type": "interview_prep", "timestamp": career_log.now_iso(),
                            "company": "X", "role": "PM"})
    idx = career_log.EventIndex(career_log.read_all_events())
    res = idx.query(type="interview_done", company="X")
    assert len(res) == 1
    assert res[0]["type"] == "interview_done"


def test_trace_command_lists_events(tmp_path, capsys):
    _use_tmp(career_log, tmp_path)
    career_log.write_event({"type": "interview_done", "timestamp": career_log.now_iso(),
                            "company": "字节", "result": "pass"})
    career_log.cmd_trace(company="字节", event_type=None, limit=10)
    out = capsys.readouterr().out
    assert "字节" in out
    assert "id=" in out  # event_id 简写


def test_expire_command_marks_expired(tmp_path, capsys):
    _use_tmp(career_log, tmp_path)
    career_log.write_event({"type": "interview_done", "timestamp": career_log.now_iso(),
                            "company": "A", "result": "pass"})
    career_log.write_event({"type": "interview_done", "timestamp": career_log.now_iso(),
                            "company": "B", "result": "pass"})
    career_log.cmd_expire(older_than_days=None, company="A")
    events = career_log.read_all_events()
    a = [e for e in events if e["company"] == "A"][0]
    b = [e for e in events if e["company"] == "B"][0]
    assert a["status"] == "expired"
    assert b["status"] == "active"
    out = capsys.readouterr().out
    assert "expired 1 event" in out
