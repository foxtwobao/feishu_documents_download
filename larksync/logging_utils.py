"""Logging helpers."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict

from .config import LoggingSettings


class JsonLogFormatter(logging.Formatter):
    """Simple JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - base signature
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            payload.update(getattr(record, "extra_data"))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: LoggingSettings) -> None:
    """Configure root logging according to provided settings."""

    level = getattr(logging, settings.level.upper(), logging.INFO)
    logging.basicConfig(level=level, handlers=[])

    handler = logging.StreamHandler(stream=sys.stderr)
    if settings.structured:
        handler.setFormatter(JsonLogFormatter())
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
