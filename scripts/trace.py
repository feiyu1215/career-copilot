"""执行 Trace：记录管线每次运行的所有 LLM 调用。"""
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# 模型定价（单位：$ / 1M tokens）。(input_price, output_price)
PRICING_PER_MILLION = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "deepseek-v4-flash": (0.07, 0.28),
    "deepseek-v4-pro": (0.27, 1.10),
    "agnes-2.0-flash": (0.00, 0.00),  # 内部免费
}


@dataclass
class TraceEvent:
    timestamp: str
    stage: str           # "stage1" | "stage1_5" | "stage2" | "stage2_5" | "post_judge"
    event: str           # "call_start" | "call_end" | "call_fail" | "stage_summary"
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    job_ids: list = field(default_factory=list)
    error: Optional[str] = None
    is_fallback: bool = False


class ExecutionTracer:
    """JSONL append-only trace。每次运行一个文件。"""

    def __init__(self, run_id: str = None, output_dir: str = ".traces"):
        if run_id is None:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id
        self.dir = Path(output_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{run_id}.jsonl"
        self._events: list[TraceEvent] = []
        self._start_time = time.time()

    def record(self, event: TraceEvent):
        self._events.append(event)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def record_call(self, stage: str, provider: str, model: str,
                    input_tokens: int, output_tokens: int, latency_ms: int,
                    job_ids: list = None, is_fallback: bool = False):
        self.record(TraceEvent(
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            stage=stage, event="call_end",
            provider=provider, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=latency_ms, job_ids=job_ids or [],
            is_fallback=is_fallback,
        ))

    def record_failure(self, stage: str, provider: str, model: str, error: str):
        self.record(TraceEvent(
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            stage=stage, event="call_fail",
            provider=provider, model=model, error=error,
        ))

    def summary(self) -> dict:
        """生成运行摘要"""
        total_input = sum(e.input_tokens for e in self._events)
        total_output = sum(e.output_tokens for e in self._events)
        total_calls = sum(1 for e in self._events if e.event == "call_end")
        total_failures = sum(1 for e in self._events if e.event == "call_fail")
        wall_seconds = time.time() - self._start_time

        # 成本估算：仅对成功调用（call_end）按模型定价累加
        cost_usd = 0.0
        for e in self._events:
            if e.event == "call_end":
                pricing = PRICING_PER_MILLION.get(e.model, (0, 0))
                cost_usd += (e.input_tokens * pricing[0]
                             + e.output_tokens * pricing[1]) / 1_000_000

        return {
            "run_id": self.run_id,
            "wall_seconds": round(wall_seconds, 1),
            "total_calls": total_calls,
            "total_failures": total_failures,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "estimated_cost_usd": round(cost_usd, 6),
            "trace_file": str(self.path),
        }
