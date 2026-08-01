"""T6 验收测试：执行 Trace"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from trace import ExecutionTracer


class TestExecutionTracer:
    def test_creates_jsonl_file(self, tmp_path):
        t = ExecutionTracer("test", output_dir=str(tmp_path))
        t.record_call("stage1", "friday", "gpt-4o-mini", 100, 50, 1000)
        assert (tmp_path / "test.jsonl").exists()
        lines = (tmp_path / "test.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["stage"] == "stage1"
        assert data["input_tokens"] == 100

    def test_summary_aggregation(self, tmp_path):
        t = ExecutionTracer("test2", output_dir=str(tmp_path))
        t.record_call("stage1", "friday", "m1", 100, 50, 1000)
        t.record_call("stage2", "friday", "m2", 200, 80, 2000)
        t.record_failure("stage1", "friday", "m1", "timeout")
        s = t.summary()
        assert s["total_calls"] == 2
        assert s["total_failures"] == 1
        assert s["total_input_tokens"] == 300
        assert s["total_output_tokens"] == 130

    def test_empty_tracer_summary(self, tmp_path):
        t = ExecutionTracer("empty", output_dir=str(tmp_path))
        s = t.summary()
        assert s["total_calls"] == 0
        assert s["total_tokens"] == 0

    def test_cost_estimation(self, tmp_path):
        t = ExecutionTracer("cost", output_dir=str(tmp_path))
        # gpt-4o-mini: $0.15/1M in, $0.60/1M out
        # 1M in * 0.15 + 0.5M out * 0.60 = 0.15 + 0.30 = 0.45
        t.record_call("stage1", "friday", "gpt-4o-mini", 1_000_000, 500_000, 1000)
        s = t.summary()
        assert abs(s["estimated_cost_usd"] - 0.45) < 1e-6
        # 未知模型按 0 计价，不计入成本
        t.record_call("stage2", "friday", "unknown-model", 1_000_000, 0, 1000)
        s2 = t.summary()
        assert abs(s2["estimated_cost_usd"] - 0.45) < 1e-6
        # call_fail 不计入成本
        t.record_failure("stage1", "friday", "gpt-4o-mini", "timeout")
        s3 = t.summary()
        assert abs(s3["estimated_cost_usd"] - 0.45) < 1e-6
