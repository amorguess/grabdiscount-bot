"""Logging structuré pour GrabDiscount.

Deux formats disponibles :
- `text`  : lisible pour le dev local (défaut en TTY).
- `json`  : une ligne = un objet JSON (prod, Sentry, Grafana Loki friendly).

Usage :

    from app.core.logging import configure_logging, get_logger

    configure_logging(level="INFO", format="json")
    log = get_logger(__name__)
    log.info("compte_assigné", extra={"account_id": "abc", "user_id": 42})

Le format JSON sérialise systématiquement `logger`, `level`, `msg`, `ts`,
les champs `extra`, et l'exception stack si présente.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any, Literal

# Clés déjà présentes dans LogRecord qu'on ne veut pas sérialiser une 2e fois
_STDLIB_FIELDS = frozenset(
    {
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
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Formatter JSON — une ligne = un objet."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info

        # Champs extras utilisateur (ex: log.info("x", extra={"user_id": 42}))
        for key, value in record.__dict__.items():
            if key in _STDLIB_FIELDS or key.startswith("_"):
                continue
            payload[key] = _jsonable(value)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Formatter texte coloré pour dev local."""

    _COLORS = {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[1;31m",  # bold red
    }
    _RESET = "\033[0m"

    def __init__(self, *, colorize: bool) -> None:
        super().__init__()
        self.colorize = colorize

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S")
        level = record.levelname
        if self.colorize:
            color = self._COLORS.get(level, "")
            level = f"{color}{level:<8}{self._RESET}"
        else:
            level = f"{level:<8}"
        base = f"{ts} {level} {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _jsonable(value: Any) -> Any:
    """Convertit une valeur en quelque chose que json.dumps peut sérialiser."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


FormatKind = Literal["text", "json", "auto"]


def configure_logging(
    *,
    level: str | int = "INFO",
    format: FormatKind = "auto",
    stream: Any = None,
) -> None:
    """Configure le logging racine.

    Idempotent : remplace les handlers existants.

    Args:
        level: niveau (str ou int logging).
        format: "text" (dev), "json" (prod), ou "auto" (JSON si non-TTY).
        stream: destination (défaut: stderr).
    """
    stream = stream if stream is not None else sys.stderr

    resolved_format: Literal["text", "json"]
    if format == "auto":
        resolved_format = "text" if _is_tty(stream) else "json"
    else:
        resolved_format = format

    formatter: logging.Formatter
    if resolved_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter(colorize=_is_tty(stream))

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)

    # Bibliothèques tierces bruyantes → WARNING par défaut
    for noisy in ("httpx", "httpcore", "urllib3", "telegram", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger nommé (wrapper sur logging.getLogger)."""
    return logging.getLogger(name)


def _is_tty(stream: Any) -> bool:
    # Respecte NO_COLOR (https://no-color.org/)
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())
