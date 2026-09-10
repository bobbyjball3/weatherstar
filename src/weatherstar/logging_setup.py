"""Structured, severity color-coded logging via structlog.

Defaults to stdout/stderr (colorized).  When a log file path is supplied the
same events are also written as JSON lines; ``console=False`` disables the
console sink.  A redaction processor masks any sensitive keys/values so
authentication settings never reach the logs.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import SecretStr

#: Substrings that mark a dict key / log key as sensitive.
SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "api-key",
    "auth",
    "credential",
    "cookie",
)

LOGGER_NAME = "weatherstar"


def is_sensitive_key(key: str) -> bool:
    """Return True if a log/config key looks sensitive by name."""
    lowered = str(key).lower().replace("_", "-").replace(" ", "-")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact(value: Any) -> Any:
    """Return a safe-to-log version of ``value``."""
    if isinstance(value, SecretStr):
        return "***"
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {k: ("***" if is_sensitive_key(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v) for v in value)  # type: ignore[arg-type]
    return value


def redact_sensitive(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor masking sensitive keys and values."""
    return {k: ("***" if is_sensitive_key(k) else _redact(v)) for k, v in event_dict.items()}


def _timestamp_rfc3339(_logger: Any, _method: str, event_dict: dict) -> dict:
    """Stamp events with an RFC 3339 timestamp plus the local TZ abbreviation."""
    now = datetime.now().astimezone()
    event_dict["timestamp"] = now.isoformat(timespec="seconds") + " " + now.strftime("%Z")
    return event_dict


def setup_logging(
    level: int = logging.INFO,
    *,
    console: bool = True,
    log_file: str | Path | None = None,
    colors: bool | None = None,
    reset: bool = False,
) -> logging.Logger:
    """Configure structlog + stdlib logging for the engine.

    Sinks: console (ANSI colored) by default, plus an optional JSON-lines file.
    Returns the underlying stdlib logger; use :func:`get_logger` for a bound one.
    """
    if colors is None:
        colors = sys.stdout.isatty() or _force_colors()
    if reset:
        _reset_logger()

    base = logging.getLogger(LOGGER_NAME)
    base.setLevel(level)
    base.propagate = False
    base.handlers.clear()

    pre_chain = [
        structlog.stdlib.add_log_level,
        redact_sensitive,
        _timestamp_rfc3339,
    ]

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=colors),
                foreign_pre_chain=pre_chain,
            )
        )
        base.addHandler(console_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=pre_chain,
            )
        )
        base.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            _timestamp_rfc3339,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_sensitive,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    return base


def _force_colors() -> bool:
    import os

    return os.environ.get("WEATHERSTAR4000_FORCE_COLOR", "").lower() in {"1", "true", "yes"}


def _reset_logger() -> None:
    logging.getLogger(LOGGER_NAME).handlers.clear()


def get_logger(name: str = "weatherstar") -> Any:
    """Return a bound structlog logger writing through the stdlib setup."""
    return structlog.get_logger(name)
