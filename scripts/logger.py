import logging
import logging.handlers
from pathlib import Path

from config import Config


def get_logger(name: str) -> logging.Logger:
    """Return a named logger with both console and file handlers.

    Features:
    - Logs to console for real-time feedback
    - Logs to file in logs/sika.log with rotation (10 files, 5MB each)
    - Consistent format across both handlers

    Call once per module:
        logger = get_logger(__name__)
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
