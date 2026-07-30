"""verify_lens.py 软契约确定性检查测试。

覆盖：
- 合法对白（含标签）→ 通过，无 WARNING
- 强断言缺标签 → [LENS-W1] WARNING
- 绝对化保证缺标签 → [LENS-W3] WARNING（Over-Claim 镜面）
- 对外简历硬数字缺 [事实] → [LENS-W2] WARNING（单源红线）
- 带标签的同类表述 → 不 WARNING
- 非 agent 回合（user）不检查
- 非法 JSONL / 缺字段 → [L0] 硬失败退出 1
- --strict 下 WARNING 升级为失败（退出 1）
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_lens.py"
spec = importlib.util.spec_from_file_location("verify_lens", SCRIPT)
vl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vl)


def _turn(role, text):
    return {"role": role, "text": text}


def test_clean_with_tags_no_warning():
    turns = [
        _turn("user", "这个岗位适合我吗"),
        _turn("agent", "这个岗位[推测]高度匹配你，但还需看项目经验"),
    ]
    failures, warnings = vl.run_checks(turns)
    assert failures == []
    assert warnings == [], warnings


def test_strong_assertion_no_tag_warns():
    turns = [_turn("agent", "这个岗位高度匹配你，直接投吧")]
    failures, warnings = vl.run_checks(turns)
    assert any("[LENS-W1]" in w for w in warnings), warnings


def test_overclaim_absolute_no_tag_warns():
    turns = [_turn("agent", "绝对能过，放心")]
    failures, warnings = vl.run_checks(turns)
    assert any("[LENS-W3]" in w for w in warnings), warnings


def test_resume_number_no_fact_warns():
    turns = [_turn("agent", "对外简历：提升 50%，三年经验")]
    failures, warnings = vl.run_checks(turns)
    assert any("[LENS-W2]" in w for w in warnings), warnings


def test_tagged_resume_number_ok():
    turns = [_turn("agent", "对外简历：提升 [事实]50%，[事实]三年经验")]
    failures, warnings = vl.run_checks(turns)
    assert warnings == [], warnings


def test_user_turn_not_checked():
    turns = [_turn("user", "肯定能过，稳了")]
    failures, warnings = vl.run_checks(turns)
    assert warnings == [], warnings


def test_bad_jsonl_exits(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"role":"agent","text":"x"}\nnot json\n', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        vl.load_transcript(str(bad))
    assert e.value.code == 1


def test_missing_field_exits(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"role":"agent"}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        vl.load_transcript(str(bad))
    assert e.value.code == 1


def test_strict_mode_fails_on_warning(tmp_path):
    good = tmp_path / "t.jsonl"
    good.write_text(json.dumps(_turn("agent", "稳了，必中")) + "\n", encoding="utf-8")
    sys.argv = ["verify_lens.py", "--input", str(good), "--strict"]
    with pytest.raises(SystemExit) as e:
        vl.main()
    assert e.value.code == 1


def test_non_strict_passes_with_warning(tmp_path):
    good = tmp_path / "t.jsonl"
    good.write_text(json.dumps(_turn("agent", "稳了，必中")) + "\n", encoding="utf-8")
    sys.argv = ["verify_lens.py", "--input", str(good)]
    with pytest.raises(SystemExit) as e:
        vl.main()
    assert e.value.code == 0
