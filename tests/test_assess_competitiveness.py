"""m9 回归测试：assess_competitiveness.assess_single 解析失败时标记 needs_review，
而非静默默认 match。

此前模型输出无法解析时，会静默回退为 positioning="match"，可能误导投递策略。
"""
import asyncio
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "assess_competitiveness.py"
spec = importlib.util.spec_from_file_location("assess_test", SCRIPT)
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


class _FakeMsg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMsg(content)]


class _UnparseableClient:
    async def chat_raw(self, messages=None, **kwargs):
        return _FakeResp("这根本不是 JSON 啊啊啊")


class _ValidClient:
    async def chat_raw(self, messages=None, **kwargs):
        return _FakeResp(
            '{"positioning": "match", "confidence": 0.8, "gaps": [], '
            '"interview_risk": "x", "reasoning": "y"}'
        )


def _profile():
    return {"hard_negatives": [], "direction_anchors": ["AI产品"]}


def _job():
    return {"job_id": "J1", "title": "某岗位", "tier": "A", "score": 90,
            "match_reasons": ["理由"], "risks": []}


def test_assess_single_parse_failure_marks_needs_review():
    result = asyncio.run(ac.assess_single(_UnparseableClient(), "候选人摘要", _profile(), _job()))
    assert result["positioning"] == "needs_review"
    assert result.get("needs_review") is True
    assert result["confidence"] == 0.0


def test_assess_single_valid_json_no_needs_review():
    result = asyncio.run(ac.assess_single(_ValidClient(), "候选人摘要", _profile(), _job()))
    assert result["positioning"] == "match"
    assert result.get("needs_review") is not True
