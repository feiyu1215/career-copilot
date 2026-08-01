"""结构化日志工具。替代散落的 print() 调用。"""
import json
import logging
import sys
from datetime import datetime


class JsonFormatter(logging.Formatter):
    """输出 JSON 格式日志，便于过滤和聚合。"""
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        # 附加结构化数据（通过 extra={"data": {...}} 传入）
        if hasattr(record, "data"):
            entry["data"] = record.data
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """获取带 JSON 格式的 logger。输出到 stderr（不污染 stdout 的 JSON 输出）。"""
    logger = logging.getLogger(f"career_copilot.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
