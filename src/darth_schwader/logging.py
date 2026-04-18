from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from darth_schwader.config import Settings

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "authorization",
    "client_secret",
    "token_encryption_key",
    "code_verifier",
}
_SCHWAB_PATH_RE = re.compile(r"/schwab/|api\.schwabapi\.com", re.IGNORECASE)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        if _SCHWAB_PATH_RE.search(value):
            return "[redacted schwab payload]"
        if len(value) > 12 and ("token" in value.lower() or value.startswith("Bearer ")):
            return "[redacted]"
        return value
    if isinstance(value, dict):
        return {key: _redact_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_event_dict(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        lowered = key.lower()
        if lowered in _SENSITIVE_KEYS or "token" in lowered or "secret" in lowered:
            event_dict[key] = "[redacted]"
            continue
        if lowered in {"request_body", "response_body", "body"}:
            path = str(event_dict.get("path", ""))
            url = str(event_dict.get("url", ""))
            if _SCHWAB_PATH_RE.search(path) or _SCHWAB_PATH_RE.search(url):
                event_dict[key] = "[redacted schwab payload]"
                continue
        event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def _rename_event_key(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event = event_dict.pop("event", None)
    if event is not None:
        event_dict["message"] = event
    return event_dict


def configure_logging(settings: Settings) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_event_dict,
        _rename_event_key,
    ]

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )

    if settings.is_prod:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx"):
        logging.getLogger(logger_name).handlers.clear()
        logging.getLogger(logger_name).propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


__all__ = ["configure_logging", "get_logger"]
