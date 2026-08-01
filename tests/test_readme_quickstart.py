"""README Quick Start 契约守卫（Phase 5.2）。

确保 README 保持在「上手指南」定位：
- 行数 ≤ 320（单文件双语 zh+en，仍避免退化成项目说明书）；
- 含 5 分钟 Quick Start 关键锚点：建档 / 匹配岗位 / 环境检测。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

MAX_LINES = 320
REQUIRED_ANCHORS = (
    "5 分钟 Quick Start",
    "帮我建档",
    "帮我匹配岗位",
    "check_env.py",
)


def test_readme_exists():
    assert README.exists(), "README.md 缺失"


def test_readme_within_line_budget():
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) <= MAX_LINES, f"README {len(lines)} 行 > 上限 {MAX_LINES} 行（单文件双语 zh+en，计划 5.2 放宽至 ≤320）"


def test_readme_has_quickstart_anchors():
    text = README.read_text(encoding="utf-8")
    missing = [a for a in REQUIRED_ANCHORS if a not in text]
    assert not missing, f"README 缺少 Quick Start 关键锚点：{missing}"
