"""Centralized logging configuration with JSON option and request correlation.

Env vars:
- LOG_LEVEL: DEBUG|INFO|WARNING|ERROR (default: INFO)
- LOG_JSON: true/false (default: false)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict
import contextvars


# Per-request correlation id
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        except Exception:
            record.request_id = "-"  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        base: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    use_json = os.getenv("LOG_JSON", "false").lower() in {"1", "true", "yes", "on"}

    root = logging.getLogger()
    root.setLevel(level)

    # Clear default handlers
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(RequestIdFilter())
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    root.addHandler(handler)

    # Align uvicorn loggers with our formatter
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(level)


