#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-3 路径1 盲评脚手架：确定性共享逻辑（SYNTHETIC-MECHANISM，离线可验）。

复用 scripts/career_log.py 的 SENSITIVE_PATTERNS 做脱敏（DRY，不重造正则）。
本模块只含纯函数，无 API、无文件 I/O（I/O 在 collect_transcript.py / blind_eval_runner.py），
便于 tests/test_proxy_eval.py 离线断言。

对应 PRD：notes/path1-scaffold-prd.md
方法学：notes/proxy-quality-eval-protocol.md（D1–D6 rubric / 脱敏 / 盲评 B2）
"""
from __future__ import annotations

import os
import sys
from typing import Any

# 复用 career_log 的 SENSITIVE_PATTERNS（脱敏正则集中维护，避免重造）
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from career_log import SENSITIVE_PATTERNS  # noqa: E402


def redact_text(text: str) -> str:
    """按 SENSITIVE_PATTERNS 把手机号/身份证/email/key/敏感词替换为 ``***``。无命中返回原文。"""
    if not text:
        return text
    out = text
    for pat in SENSITIVE_PATTERNS:
        out = pat.sub("***", out)
    return out


def build_record(
    lines: list[dict],
    *,
    session_id: str,
    phase: str,
    before_or_after: str,
    model: str,
    redact: bool = True,
) -> dict:
    """把原始 JSONL turns 加元数据标签，可选脱敏，返回统一 record 结构。

    record = {session_id, phase, before_or_after, model, turns:[{role,text}]}
    ``redact=True`` 时每条 text 过 redact_text（协议第二节隐私红线）。
    """
    turns = []
    for ln in lines:
        role = ln.get("role", "")
        txt = ln.get("text", "")
        if redact:
            txt = redact_text(txt)
        turns.append({"role": role, "text": txt})
    return {
        "session_id": session_id,
        "phase": phase,
        "before_or_after": before_or_after,
        "model": model,
        "turns": turns,
    }


def mask_label(record: dict) -> dict:
    """剥离 ``before_or_after``（防盲评 B2 确认偏差）。judge 仅应见 turns + phase。"""
    return {k: v for k, v in record.items() if k != "before_or_after"}


# 非 resume phase 计入的 5 个核心维度（D5 仅 resume phase 计）
_CORE_DIMS = ("D1", "D2", "D3", "D4", "D6")
_RESUME_DIMS = _CORE_DIMS + ("D5",)


def aggregate_score(scores: dict, phase: str) -> int:
    """D1–D6 各 0–2 → 0–12。

    - resume phase：六维求和（0–12）。
    - 其他 phase：核心五维求和（0–10）归一到 0–12（``round(raw/10*12)``）。
    - 缺 key 或值为 ``None``（judge 返回 null，如非 resume 的 D5）视作 0。
    """
    if phase == "resume":
        dims = _RESUME_DIMS
        return sum(int(scores.get(d) or 0) for d in dims)  # 0–12
    raw = sum(int(scores.get(d) or 0) for d in _CORE_DIMS)  # 0–10
    return round(raw / 10 * 12)  # 归一 0–12


if __name__ == "__main__":
    # 最小自测：证明四个纯函数接线（非 pytest 路径，供快速 smoke）
    assert "13800138000" not in redact_text("手机13800138000")
    assert build_record(
        [{"role": "user", "text": "x"}], session_id="s", phase="match",
        before_or_after="before", model="m",
    )["before_or_after"] == "before"
    assert "before_or_after" not in mask_label(
        build_record([{"role": "u", "text": "x"}], session_id="s", phase="match",
                     before_or_after="before", model="m"))
    assert aggregate_score({"D1": 2, "D2": 2, "D3": 2, "D4": 2, "D5": 2, "D6": 2}, "resume") == 12
    print("proxy_eval_lib smoke OK")
