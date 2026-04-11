import logging


def get_logger(name: str) -> logging.Logger:
    """Return a named logger with a consistent format.

    Call once per module:
        logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s — %(message)s", "%H:%M:%S"
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
