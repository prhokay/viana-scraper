"""
Centralized logging setup.
Import: from utils.logger import get_logger
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def get_logger(name: str, level: Optional[str] = None, log_file: Optional[str] = None) -> logging.Logger:
    """
    Returns a named logger with console + optional file handler.
    On second call with the same name returns the existing logger (idempotent).
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    # resolve level
    try:
        from config import settings
        _level = level or settings.log_level
        _file = log_file or settings.log_file
    except Exception:
        _level = level or "INFO"
        _file = log_file

    numeric_level = getattr(logging, _level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # console — force UTF-8 on Windows to avoid cp1251 errors
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(numeric_level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # file (optional)
    if _file:
        try:
            fh = logging.FileHandler(_file, encoding="utf-8")
            fh.setLevel(numeric_level)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError:
            logger.warning("Could not open log file: %s", _file)

    logger.propagate = False
    return logger
