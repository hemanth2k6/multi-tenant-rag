"""Structured JSON logger with tenant context propagation."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable to track current tenant_id across async request contexts
tenant_id_context_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(UTC).isoformat()
        current_tenant = tenant_id_context_var.get()

        log_data: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Priority to record extra, then context variable
        tenant_id = getattr(record, "tenant_id", current_tenant)
        if tenant_id:
            log_data["tenant_id"] = str(tenant_id)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Include custom extra fields if provided
        for key, value in record.__dict__.items():
            if key not in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "tenant_id",
            }:
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, OverflowError):
                    log_data[key] = str(value)

        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure the root logger with the JSON formatter."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance for the given module name."""
    return logging.getLogger(name)
