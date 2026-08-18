"""Structured JSON logging.

Why JSON: the application is intended to be deployed behind a log
aggregator. A single line of JSON per record is easier to ship to
Loki / Datadog / CloudWatch than free-form text, and it lets the
ingestion layer (Phase 2+) emit per-request timing fields without
ad-hoc string formatting.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Render log records as one-line JSON.

    Extra fields passed via `logger.info("msg", extra={...})` are
    merged into the record. The reserved keys (timestamp, level,
    logger, message) are always present and cannot be overridden.
    """

    RESERVED = {"timestamp", "level", "logger", "message", "exc_info"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Anything passed via `extra=` ends up on the record's __dict__.
        for key, value in record.__dict__.items():
            if key in self.RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging to emit JSON to stdout.

    Safe to call multiple times — handlers are reset to avoid
    duplicate output when uvicorn reloads workers.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root.addHandler(handler)
    root.setLevel(level.upper())

    # Tame noisy third-party loggers unless the operator opts in.
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel("WARNING")
