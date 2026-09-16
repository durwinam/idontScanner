"""Application logging with a bounded single-file rotation policy."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import DATA_DIR, LOG_MAX_BYTES


class SingleFileRotatingHandler(RotatingFileHandler):
    """Drop the old file at the size boundary and start a clean one."""

    def doRollover(self):  # noqa: N802 - stdlib hook name
        if self.stream:
            self.stream.close()
            self.stream = None
        try:
            Path(self.baseFilename).unlink(missing_ok=True)
        finally:
            if not self.delay:
                self.stream = self._open()


def configure_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "idontscanner.log"

    logger = logging.getLogger("idontscanner")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = SingleFileRotatingHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=0,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ))
        logger.addHandler(handler)

    return logger
