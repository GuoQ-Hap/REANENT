from __future__ import annotations

import logging
import os
import sys
from typing import Any


DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(event)s | %(request_id)s | %(task_type)s | %(message)s"


class ContextDefaultsFilter(logging.Filter):
    """确保每条日志都有统一的审计字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        for field in ("event", "request_id", "task_type"):
            if not hasattr(record, field):
                setattr(record, field, "-")
        return True


def configure_logging(level: str | None = None) -> None:
    """配置包级日志器，并保证重复调用不会重复添加 handler。"""

    log_level = (level or os.getenv("PMC_AGENT_LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger("pmc_agent")
    root.setLevel(log_level)
    root.propagate = False

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        handler.addFilter(ContextDefaultsFilter())
        root.addHandler(handler)

    for handler in root.handlers:
        handler.setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def log_extra(event: str, request_id: str = "-", task_type: str = "-", **extra: Any) -> dict[str, Any]:
    """构造所有模块通用的结构化日志字段。"""

    payload: dict[str, Any] = {"event": event, "request_id": request_id, "task_type": task_type}
    payload.update(extra)
    return payload
