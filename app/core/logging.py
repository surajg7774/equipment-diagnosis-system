"""Structured (JSON) logging.

Each log line is one JSON object, so logs can be shipped to any log platform
and queried by field (e.g. "show me all diagnoses with confidence < 0.4").

Usage::

    logger.info("diagnosis_completed", extra={"confidence": 0.82, "latency_ms": 41})
"""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

# Holds the id of the request currently being handled so every log line
# written during that request can be correlated.  ContextVars are safe across
# threads/async tasks (each request gets its own value).
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has by default; anything else came from ``extra=``.
_STANDARD_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON document."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        # Merge the structured fields passed through ``extra=``.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS:
                payload[key] = value
        # Stack traces go to the logs only; they are never sent to API clients.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once (safe to call repeatedly)."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Replace our own handler if we've been here before (avoids duplicate lines
    # when the app factory is called several times, e.g. in tests).
    for handler in list(root.handlers):
        if getattr(handler, "_servicediagnose", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._servicediagnose = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # Third-party libraries are chatty at INFO; keep them to warnings.
    for noisy in ("chromadb", "httpx", "sentence_transformers", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
