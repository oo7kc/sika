"""Validated operational configuration for Sika commands."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
LOG_FORMATS = frozenset({"text", "json"})


class ConfigurationError(ValueError):
    """Raised when operational configuration is invalid."""


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Logging settings shared by every command-line entry point."""

    level: str = "INFO"
    output_format: str = "text"
    file_path: Path | None = None


def load_logging_config(
    environ: Mapping[str, str] | None = None,
) -> LoggingConfig:
    """Load and validate the small set of supported logging variables."""

    values = os.environ if environ is None else environ
    level = values.get("SIKA_LOG_LEVEL", "INFO").strip().upper()
    if level not in LOG_LEVELS:
        allowed = ", ".join(sorted(LOG_LEVELS))
        raise ConfigurationError(f"SIKA_LOG_LEVEL must be one of: {allowed}")

    output_format = values.get("SIKA_LOG_FORMAT", "text").strip().lower()
    if output_format not in LOG_FORMATS:
        allowed = ", ".join(sorted(LOG_FORMATS))
        raise ConfigurationError(f"SIKA_LOG_FORMAT must be one of: {allowed}")

    raw_file = values.get("SIKA_LOG_FILE", "").strip()
    log_file = Path(raw_file).expanduser() if raw_file else None
    return LoggingConfig(
        level=level,
        output_format=output_format,
        file_path=log_file,
    )
