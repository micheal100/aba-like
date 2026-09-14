"""Logging setup with configurable verbosity.

CLI -v/-vv flags override config file level; both are optional.
"""
from __future__ import annotations

import logging
import sys

from .config import LoggingConfig

_LEVELS = ["WARNING", "INFO", "DEBUG"]


def setup_logging(cfg: LoggingConfig, verbosity: int = 0) -> None:
    level_name = cfg.level.upper()
    if verbosity > 0:
        base_idx = _LEVELS.index(level_name) if level_name in _LEVELS else 1
        level_name = _LEVELS[min(base_idx + verbosity, len(_LEVELS) - 1)]

    level = getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if cfg.file:
        handlers.append(logging.FileHandler(cfg.file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
