"""Centralised logger factory.

Setup with setup_file_logging(); logs to console and rotating file.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

_CONSOLE_FMT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
_FILE_FMT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_root = logging.getLogger("sika")
_root.setLevel(logging.DEBUG)

_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter(_CONSOLE_FMT, _DATE_FMT))
_root.addHandler(_console)


def setup_file_logging(log_dir: str = "logs") -> None:
    """Attach rotating file handler (1 MB, 5 backups) to root logger."""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "sika.log")

    if any(isinstance(h, RotatingFileHandler) for h in _root.handlers):
        return

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FMT, _DATE_FMT))
    _root.addHandler(file_handler)
    _root.info(f"File logging active → {log_path}")
    file_handler.flush()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger inheriting root's handlers."""
    return _root.getChild(name)
