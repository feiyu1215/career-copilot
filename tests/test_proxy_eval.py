#!/usr/bin/env python3
"""P2-3 路径1 盲评脚手架确定性逻辑测试（SYNTHETIC-MECHANISM，全离线无 API）。

Seam：evals/proxy_eval_lib.py 的纯函数 redact_text / build_record / mask_label / aggregate_score。
对应 PRD：notes/path1-scaffold-prd.md；Tickets：notes/path1-scaffold-tickets.md（S1/S4）。

运行：python -m pytest tests/test_proxy_eval.py -q
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "scripts"))  # career_log 被 proxy_eval_lib 复用

import proxy_eval_lib as pel  # noqa: E402


# ── redact_text ───────────────────────────────────────────────
def test_redact_text_masks_phone():
    out = pel.redact_text("联系我 13800138000 谢谢")
    assert "13800138000" not in out
    assert "***" in out


def test_redact_text_masks_id_card():
    out = pel.redact_text("身份证 11010119900307123X 已验证")
    assert "11010119900307123X" not in out
    assert "***" in out


def test_redact_text_masks_email():
    out = pel.redact_text("邮箱 foo@bar.com 联系")
    assert "foo@bar.com" not in out
    assert "***" in out


def test_redact_text_masks_api_key_phrase():
    out = pel.redact_text("用 sk-abc123DEF456 调用")
    assert "sk-abc123DEF456" not in out
    # 强化断言（捕获 P1：sk- 类 key 原正则只遮首字符，后缀仍泄露）
    assert "sk-" not in out, "sk- 类 key 不应残留前缀"
    assert "bc123DEF456" not in out, "sk- key 后缀不应残留（脱敏须整串）"


def test_redact_text_preserves_clean_text():
    txt = "这是一段干净的求职对话，没有敏感信息。"
    assert pel.redact_text(txt) == txt


# ── build_record ──────────────────────────────────────────────
def test_build_record_adds_labels_and_redacts():
    lines = [
        {"role": "user", "text": "我的手机号13800138000"},
        {"role": "agent", "text": "好的收到"},
    ]
    rec = pel.build_record(
        lines, session_id="s1", phase="resume",
        before_or_after="after", model="agnes-2.0-flash",
    )
    assert rec["session_id"] == "s1"
    assert rec["phase"] == "resume"
    assert rec["before_or_after"] == "after"
    assert rec["model"] == "agnes-2.0-flash"
    assert "13800138000" not in rec["turns"][0]["text"]
    assert "***" in rec["turns"][0]["text"]


def test_build_record_no_redact_keeps_original():
    lines = [{"role": "user", "text": "手机13800138000"}]
    rec = pel.build_record(
        lines, session_id="s2", phase="match",
        before_or_after="before", model="nvidia-x", redact=False,
    )
    assert rec["turns"][0]["text"] == "手机13800138000"


# ── mask_label ────────────────────────────────────────────────
def test_mask_label_removes_before_or_after():
    rec = pel.build_record(
        [{"role": "user", "text": "hi"}], session_id="s3",
        phase="match", before_or_after="before", model="m",
    )
    masked = pel.mask_label(rec)
    assert "before_or_after" not in masked
    assert masked["phase"] == "match"
    assert "turns" in masked


# ── aggregate_score ───────────────────────────────────────────
def test_aggregate_score_resume_sums_six():
    scores = {"D1": 2, "D2": 2, "D3": 2, "D4": 2, "D5": 2, "D6": 2}
    assert pel.aggregate_score(scores, "resume") == 12


def test_aggregate_score_nonresume_normalizes():
    # 五维全 2 → raw 10 → round(10/10*12)=12
    scores = {"D1": 2, "D2": 2, "D3": 2, "D4": 2, "D6": 2}
    assert pel.aggregate_score(scores, "match") == 12
    # 五维全 1 → raw 5 → round(5/10*12)=6
    scores1 = {"D1": 1, "D2": 1, "D3": 1, "D4": 1, "D6": 1}
    assert pel.aggregate_score(scores1, "match") == 6


def test_aggregate_score_zero():
    scores = {"D1": 0, "D2": 0, "D3": 0, "D4": 0, "D6": 0}
    assert pel.aggregate_score(scores, "interview") == 0
