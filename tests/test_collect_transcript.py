#!/usr/bin/env python3
"""collect_transcript.py 采集 API 测试（SYNTHETIC-MECHANISM，全离线无 API）。

Seam：evals/collect_transcript.py 的 collect_session() + CLI main()。
验证：落盘位置 / 元数据标签 / 脱敏 / 非法参数 / CLI 复用 collect_session。

运行：python -m pytest tests/test_collect_transcript.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import collect_transcript as ct  # noqa: E402


def _read_record(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.loads(f.readline())


# ── collect_session：落盘 + 标签 + 脱敏 ────────────────────────
def test_collect_session_writes_file_and_redacts(tmp_path):
    turns = [
        {"role": "user", "text": "我的手机号13800138000"},
        {"role": "agent", "text": "好的收到"},
    ]
    out_path, rec, n_redacted = ct.collect_session(
        turns, phase="resume", before_or_after="after",
        model="agnes-2.0-flash", session_id="sess1", out_root=str(tmp_path),
    )
    assert Path(out_path).exists()
    # 脱敏生效
    assert "13800138000" not in rec["turns"][0]["text"]
    assert "***" in rec["turns"][0]["text"]
    assert n_redacted == 1
    # 元数据标签齐全
    saved = _read_record(out_path)
    assert saved["session_id"] == "sess1"
    assert saved["phase"] == "resume"
    assert saved["before_or_after"] == "after"
    assert saved["model"] == "agnes-2.0-flash"
    assert len(saved["turns"]) == 2


def test_collect_session_no_redact_keeps_original(tmp_path):
    turns = [{"role": "user", "text": "手机13800138000"}]
    _, rec, n_redacted = ct.collect_session(
        turns, phase="match", before_or_after="before", model="m",
        session_id="s2", redact=False, out_root=str(tmp_path),
    )
    assert rec["turns"][0]["text"] == "手机13800138000"
    assert n_redacted == 0


def test_collect_session_default_out_root_under_transcripts(tmp_path, monkeypatch):
    # 用 monkeypatch 把 ROOT 指到 tmp，验证默认落盘到 <ROOT>/evals/transcripts/...
    turns = [{"role": "user", "text": "干净对话无 PII"}]
    monkeypatch.setattr(ct, "ROOT", str(tmp_path))
    out_path, _, _ = ct.collect_session(
        turns, phase="match", before_or_after="after",
        model="m", session_id="s3", out_root=None,
    )
    assert out_path == str(tmp_path / "evals" / "transcripts" / "match" / "after" / "s3.jsonl")
    assert Path(out_path).exists()


# ── 非法参数应 SystemExit ─────────────────────────────────────
def test_collect_session_invalid_phase_raises(tmp_path):
    with pytest.raises(SystemExit):
        ct.collect_session(
            [{"role": "u", "text": "x"}], phase="bogus",
            before_or_after="after", model="m", session_id="s4",
            out_root=str(tmp_path),
        )


def test_collect_session_invalid_boa_raises(tmp_path):
    with pytest.raises(SystemExit):
        ct.collect_session(
            [{"role": "u", "text": "x"}], phase="match",
            before_or_after="around", model="m", session_id="s5",
            out_root=str(tmp_path),
        )


def test_collect_session_empty_turns_raises(tmp_path):
    with pytest.raises(SystemExit):
        ct.collect_session(
            [], phase="match", before_or_after="after",
            model="m", session_id="s6", out_root=str(tmp_path),
        )


# ── CLI 复用 collect_session（subprocess 端到端）────────────────
def test_cli_reuses_collect_session(tmp_path):
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        json.dumps({"role": "user", "text": "手机13800138000"}) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "collect_transcript.py"),
         "--input", str(inp), "--phase", "match", "--before-or-after", "before",
         "--model", "nvidia-x", "--session-id", "cli1",
         "--out-root", str(out_dir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    saved = _read_record(str(out_dir / "match" / "before" / "cli1.jsonl"))
    assert saved["session_id"] == "cli1"
    assert saved["model"] == "nvidia-x"
    assert "13800138000" not in saved["turns"][0]["text"]
