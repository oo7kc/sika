"""Logging configuration with dual console and file output."""

import logging
import logging.handlers
from pathlib import Path

from config import Config


def get_logger(name: str) -> logging.Logger:
    """Create or retrieve a named logger with console and file handlers.

    Returns a logger configured with both console and file output. Console
    messages go to stdout in real-time for interactive feedback. File output
    uses rotating handlers to manage disk space (5MB per file, up to 10 backups).

    Multiple calls with the same name return the same logger instance, so it's
    safe to call this multiple times. Handlers are only attached on first call.

    Args:
        name: Logger name, typically __name__ for module-level loggers.

    Returns:
        Configured Logger instance with handlers ready to use.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Training started")
        >>> logger.warning("Low memory available")

    Note:
        Log files are stored in logs/sika.log with automatic rotation.
        Each file grows to 5MB before the next backup is created.
        Up to 10 backup files are retained.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        log_dir = Path(Config.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s — %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        log_file = log_dir / "sika.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        logger.setLevel(logging.INFO)

    return logger
