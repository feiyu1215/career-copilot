#!/usr/bin/env python3
"""P1 文档层契约测试：SKILL.md 结构约定（SYNTHETIC-MECHANISM，离线解析，无需 live key）。

Seam：SKILL.md 作为契约文档，其结构是可机检的。本测试断言：
- TL;DR 段存在（P1-1）
- 决策路由正式命名「lite 模式」（P1-3）

对应 PRD：`notes/p1-packaging-prd.md`；Tickets：`notes/p1-packaging-tickets.md`。
"""
import os

SKILL_PATH = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
LITE_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "chatgpt-lite.md")
LITE_DIST_PATH = os.path.join(os.path.dirname(__file__), "..", "lite", "SKILL.md")


def _read_skill():
    with open(SKILL_PATH, encoding="utf-8") as f:
        return f.read()


def _read_lite():
    with open(LITE_PATH, encoding="utf-8") as f:
        return f.read()


def _read_lite_dist():
    with open(LITE_DIST_PATH, encoding="utf-8") as f:
        return f.read()


def test_skill_has_tldr():
    """P1-1：SKILL.md 顶部须有 30 秒速览段，含单岗匹配 3 步走。"""
    txt = _read_skill()
    assert "30 秒速览" in txt or "TL;DR" in txt, "缺少 TL;DR/30秒速览 段"
    assert "单岗匹配" in txt, "TL;DR 缺少『单岗匹配』指引"
    assert "3 步走" in txt, "TL;DR 缺少『3 步走』"


def test_lite_mode_named_in_routing():
    """P1-3：决策路由须正式命名『纯推理（lite 模式）』。"""
    txt = _read_skill()
    assert "纯推理（lite 模式）" in txt, "决策路由未正式命名 lite 模式"


def test_no_command_introduced():
    """哲学护栏：P1 文档层不得引入显式 /命令（Anti-pattern 红线）。"""
    txt = _read_skill()
    # 允许既有示例里的英文命令引用（如 fetch_jobs），但不得新增「/xxx」式用户命令
    # 仅断言本次新增内容不含独立成行的 /命令 触发
    import re

    new_section = txt  # 全量检查已足够保守；SKILL.md 现有内容本就无 /命令
    slash_cmds = re.findall(r"(?m)^/\w+", new_section)
    assert not slash_cmds, f"发现疑似显式 /命令：{slash_cmds}"


def test_lite_package_exists():
    """minor lite 包：references/chatgpt-lite.md 必须存在（Slice 1）。"""
    assert os.path.exists(LITE_PATH), "缺少 references/chatgpt-lite.md（lite 可粘贴段）"


def test_lite_package_has_no_mechanism_disclaimer():
    """minor lite 包诚实标签：必须声明『无机制保证』。"""
    txt = _read_lite()
    assert "无机制保证" in txt, "lite 包缺少强制『无机制保证』声明"


def test_lite_package_has_core_contracts():
    """minor lite 包：须覆盖 4 条核心契约关键词。"""
    txt = _read_lite()
    for kw in ("前提来源标注", "单源", "熔断", "Over-Claim"):
        assert kw in txt, f"lite 包缺少核心契约标记：{kw}"


# ── lite 分发包（lite/SKILL.md）──────────────────────────────
def test_lite_dist_skill_exists():
    """lite 分发：独立可加载 skill 必须存在。"""
    assert os.path.exists(LITE_DIST_PATH), "缺少 lite/SKILL.md（独立分发版）"


def test_lite_dist_has_frontmatter():
    """lite 分发：必须含合法 YAML frontmatter（name/description），可被 skill 运行时识别。"""
    txt = _read_lite_dist()
    assert txt.startswith("---"), "lite/SKILL.md 缺少 YAML frontmatter"
    assert 'name: career-copilot-lite' in txt, "frontmatter 缺 name"
    assert 'description:' in txt, "frontmatter 缺 description"


def test_lite_dist_has_no_mechanism_disclaimer():
    """lite 分发诚实标签：必须声明『无机制保证』，与主 lite 段同源口径。"""
    txt = _read_lite_dist()
    assert "无机制保证" in txt, "lite 分发版缺少强制『无机制保证』声明"


def test_lite_dist_has_core_contracts():
    """lite 分发：须覆盖 4 条核心契约关键词，与主 lite 段一致。"""
    txt = _read_lite_dist()
    for kw in ("前提来源标注", "单源", "熔断", "Over-Claim"):
        assert kw in txt, f"lite 分发版缺少核心契约标记：{kw}"
