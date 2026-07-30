#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drafter_reviewer.py 求职信相关纯函数测试（不调用 LLM）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from drafter_reviewer import check_cover_letter_length  # noqa: E402


def test_short_cover_ok():
    text = "尊敬的招聘负责人：\n第一段。\n第二段。\n第三段。\n此致 / 敬礼"
    assert check_cover_letter_length(text) == []


def test_cjk_over_limit_warns():
    # 构造 > 400 中文字
    text = "中" * 401
    warns = check_cover_letter_length(text)
    assert warns and "400" in warns[0]


def test_en_over_limit_warns():
    text = ("word " * 301).strip()
    warns = check_cover_letter_length(text)
    assert warns and "300" in warns[0]


def test_empty_cover_no_warning():
    assert check_cover_letter_length("") == []
    assert check_cover_letter_length(None) == []
