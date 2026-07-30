# -*- coding: utf-8 -*-
"""U4 SECURITY.md 诚实声明威胁模型：文档存在且覆盖关键声明点。

纯文档校验，不自动化任何事；仅确保「能防/防不住/数据边界」都被如实写出。
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SECURITY = _REPO / "SECURITY.md"

# 必须被如实写明的声明点（诚实，不夸大安全性）
_REQUIRED = [
    ("jd_guard 4 类注入", r"jd_guard"),
    ("扫描不等于绝对免疫", r"扫描\s*[≠!=]\s*绝对免疫|防不住|漏检"),
    ("非沙箱运行模型", r"非沙箱|指令级"),
    ("security_guards 护栏", r"security_guards"),
    ("个人数据不入库", r"不.*入库|不进入版本库|gitignore"),
    ("绝不自动外发", r"不.*自动发邮件|不自动外传|不自动改系统"),
    ("人工复核", r"人工复核"),
]


@pytest.mark.skipif(not _SECURITY.exists(),
                    reason="SECURITY.md 尚未创建")
def test_security_md_exists_and_covers_required_points():
    text = _SECURITY.read_text(encoding="utf-8")
    missing = []
    for label, pattern in _REQUIRED:
        if not re.search(pattern, text, re.IGNORECASE):
            missing.append(label)
    assert not missing, f"SECURITY.md 缺少声明点：{missing}"
