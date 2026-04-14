"""Structured logging for the pdf-to-wiki pipeline."""

from __future__ import annotations

import logging
import sys


def get_logger(name: str = "pdf_to_wiki") -> logging.Logger:
    """Return a configured logger for the pipeline."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger