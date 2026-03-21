"""
logger_setup.py — Shared logging factory.

Creates a logger with:
  - Coloured console output (via colorlog when available, plain otherwise)
  - Timestamped file handler written to the path in config["logging"]["file"]

Calling setup_logger() more than once with the same name returns the same
instance so handlers are never duplicated.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    import colorlog  # type: ignore[import]

    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

_registry: dict[str, logging.Logger] = {}


def setup_logger(name: str, log_config: dict | None = None) -> logging.Logger:
    """
    Return a configured logger for *name*.

    Parameters
    ----------
    name:
        Logger name, e.g. ``"auto_clicker"`` or ``"monitor"``.
    log_config:
        The ``logging`` section from config.yaml, e.g.::

            {"file": "auto_clicker.log", "level": "INFO"}

        Defaults to INFO + ``auto_clicker.log`` when not supplied.
    """
    if name in _registry:
        return _registry[name]

    cfg = log_config or {}
    log_file: str = cfg.get("file", "auto_clicker.log")
    level_name: str = cfg.get("level", "INFO").upper()
    level: int = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)   # handlers decide what to show
    logger.propagate = False

    # ------------------------------------------------------------------ #
    # Console handler
    # ------------------------------------------------------------------ #
    if _HAS_COLOR:
        fmt = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s [%(levelname)-8s]%(reset)s %(cyan)s%(name)s%(reset)s: %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG":    "white",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            },
        )
    else:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # ------------------------------------------------------------------ #
    # File handler
    # ------------------------------------------------------------------ #
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)   # always verbose in the file
        fh.setFormatter(file_fmt)
        logger.addHandler(fh)

    _registry[name] = logger
    return logger
