"""m7 回归测试：verify_lens 来源标签闭合 + 绝对化标记不重复。

此前 SOURCE_TAGS 含未闭合的 "[来源"（缺 ]），且 "肯定能过" 同时出现在
STRONG_MARKERS 与 ABSOLUTE_MARKERS（重复）。
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_lens.py"
spec = importlib.util.spec_from_file_location("verify_lens_tags", SCRIPT)
vl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vl)


def test_source_tags_has_closing_bracket():
    assert "[来源]" in vl.SOURCE_TAGS, vl.SOURCE_TAGS
    assert "[来源" not in vl.SOURCE_TAGS, "不应再含未闭合的 '[来源'"


def test_肯定能过_not_duplicated():
    occ = sum(1 for m in vl.STRONG_MARKERS + vl.ABSOLUTE_MARKERS if m == "肯定能过")
    assert occ == 1, f"'肯定能过' 出现在 {occ} 个列表，应仅 1 个"


def test_source_tag_still_detects_来源():
    assert vl.has_source_tag("依据[来源]某内部数据") is True
