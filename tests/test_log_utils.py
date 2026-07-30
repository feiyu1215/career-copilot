"""T3.5 结构化日志基础测试。"""
import io
import json
import logging
import sys

sys.path.insert(0, "scripts")

from log_utils import get_logger, JsonFormatter  # noqa: E402


def test_get_logger_emits_valid_json_with_extra_data():
    log = get_logger("t3_logutils_test")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    log.handlers = [handler]
    log.info("hello", extra={"data": {"key": "val"}})

    entry = json.loads(buf.getvalue().strip())
    assert entry["level"] == "INFO"
    assert entry["msg"] == "hello"
    assert entry["data"] == {"key": "val"}
    assert "ts" in entry
    assert entry["module"] == "career_copilot.t3_logutils_test"


def test_logger_name_prefix():
    log = get_logger("submodule")
    assert log.name == "career_copilot.submodule"
