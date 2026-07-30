"""M2 回归测试：smart_score._parse_json Layer-4 兜底 + _classify_parse 的 is_fallback 透传。

核心：_parse_json 的 Layer-4 正则兜底会返回含 "score" 键的 dict 且 is_fallback=True；
此前 stage1 用 ``"score" not in result`` 判断回退，会把兜底分误判为真分。
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smart_score.py"
spec = importlib.util.spec_from_file_location("smart_score_parse", SCRIPT)
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


def test_parse_json_layer4_fallback_marks_is_fallback():
    # 含 "score": N 但非合法 JSON → Layer 4 兜底返回 is_fallback=True
    text = '模型说那是 "score": 73 左右'
    result = ss._parse_json(text)
    assert result is not None
    assert result.get("is_fallback") is True
    assert result.get("score") == 73


def test_parse_json_valid_json_no_fallback():
    result = ss._parse_json('{"score": 88, "reasoning": "匹配度高"}')
    assert result.get("is_fallback") is not True
    assert result.get("score") == 88


def test_classify_parse_none_is_fallback():
    is_fb, score, reasoning = ss._classify_parse(None)
    assert is_fb is True
    assert score == 30
    assert reasoning == ""


def test_classify_parse_layer4_propagates_fallback():
    # M2 核心：Layer4 兜底含 score 键，但 is_fallback 必须被识别为回退
    layer4 = {"score": 73, "reasoning": "", "is_fallback": True}
    is_fb, score, reasoning = ss._classify_parse(layer4)
    assert is_fb is True
    assert score == 73


def test_classify_parse_normal_not_fallback():
    normal = {"score": 88, "reasoning": "r"}
    is_fb, score, reasoning = ss._classify_parse(normal)
    assert is_fb is False
    assert score == 88
    assert reasoning == "r"
