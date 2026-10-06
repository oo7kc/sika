"""Consistent, reviewable logging for command-line workflows."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from .configuration import LoggingConfig, load_logging_config

LOGGER_NAME = "sika"
_MANAGED_HANDLER = "_sika_managed_handler"


class JsonLineFormatter(logging.Formatter):
    """Emit a stable JSON object without copying arbitrary record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, str) and event:
            payload["event"] = event
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _formatter(output_format: str) -> logging.Formatter:
    if output_format == "json":
        return JsonLineFormatter()
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def configure_logging(config: LoggingConfig | None = None) -> logging.Logger:
    """Configure Sika's logger once and replace only handlers owned by Sika."""

    resolved = config or load_logging_config()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(resolved.level)
    logger.propagate = False

    for handler in tuple(logger.handlers):
        if getattr(handler, _MANAGED_HANDLER, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = _formatter(resolved.output_format)
    console = logging.StreamHandler()
    console.setLevel(resolved.level)
    console.setFormatter(formatter)
    setattr(console, _MANAGED_HANDLER, True)
    logger.addHandler(console)

    if resolved.file_path is not None:
        resolved.file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            resolved.file_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(resolved.level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _MANAGED_HANDLER, True)
        logger.addHandler(file_handler)

    return logger


def command_logger(command: str) -> logging.Logger:
    """Configure logging and return a namespaced logger for one command."""

    configure_logging()
    return logging.getLogger(f"{LOGGER_NAME}.{command}")
