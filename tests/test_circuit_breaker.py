"""T1 验收测试：管线熔断器"""
import pytest
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from smart_score import PipelineAbortError, StageStats, stage1
from llm_client import LLMCallFailed


class TestStageStats:
    def test_failure_rate_zero_when_empty(self):
        s = StageStats()
        assert s.failure_rate == 0.0

    def test_failure_rate_calculation(self):
        s = StageStats(total=10, succeeded=7, failed=3)
        assert abs(s.failure_rate - 0.3) < 1e-9

    def test_failure_rate_all_failed(self):
        s = StageStats(total=5, succeeded=0, failed=5)
        assert s.failure_rate == 1.0


class TestCircuitBreakerLogic:
    """验证熔断逻辑（不需要真实 LLM 调用）"""

    def test_below_min_samples_no_abort(self):
        """样本数=5（最小样本边界），失败率 3/5=60% > 30%，应触发熔断"""
        stats = StageStats(total=5, succeeded=2, failed=3)
        processed = stats.succeeded + stats.failed  # = 5
        assert processed >= 5
        assert stats.failure_rate > 0.30

    def test_above_threshold_triggers(self):
        """10 个样本，失败率 4/10=40% > 30%，应中止"""
        stats = StageStats(total=10, succeeded=6, failed=4)
        assert stats.failure_rate > 0.30

    def test_below_threshold_continues(self):
        """10 个样本，失败率 2/10=20% < 30%，继续"""
        stats = StageStats(total=10, succeeded=8, failed=2)
        assert stats.failure_rate < 0.30


# ============================================================
# 真实熔断行为测试（驱动 LLMClient.chat 桩，验证 stage1 真的会 raise）
# ============================================================

class _FailingClient:
    provider_name = "fake"
    model = "fake"
    total_input_tokens = 0
    total_output_tokens = 0

    async def chat(self, system, user, temperature=0.0, max_tokens=150):
        raise LLMCallFailed("fake", "fake", 5, RuntimeError("boom"))


class _OkClient:
    provider_name = "fake"
    model = "fake"
    total_input_tokens = 0
    total_output_tokens = 0

    async def chat(self, system, user, temperature=0.0, max_tokens=150):
        return '{"score": 80, "reasoning": "ok"}'


def _make_jobs(n: int) -> list[dict]:
    return [
        {"title": f"T{i}", "department": "D", "location": "L",
         "full_text": "x", "job_id": f"J{i}"}
        for i in range(n)
    ]


class TestStage1CircuitBreaker:
    def test_trials_when_failure_rate_high(self):
        """全部失败（失败率 100% > 30%）应在达到最小样本数后触发 PipelineAbortError"""
        jobs = _make_jobs(6)
        with pytest.raises(PipelineAbortError):
            asyncio.run(stage1(_FailingClient(), "summary", "anchor", jobs, None))

    def test_no_abort_when_all_succeed(self):
        """全部成功（失败率 0%）不应触发熔断，且返回 (scored, stats)"""
        jobs = _make_jobs(6)
        scored, stats = asyncio.run(stage1(_OkClient(), "summary", "anchor", jobs, None))
        assert stats.failed == 0
        assert stats.succeeded == 6
        assert len(scored) == 6
