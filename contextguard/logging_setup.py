"""Structured logging for long-running deployments.

The dev scripts print to stdout, which is fine at a terminal but
useless once ContextGuard is running unattended under systemd. This
gives every module a real logger (rotating file + stderr), so a
service running for weeks doesn't silently fill the disk or lose its
history on restart.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from .config import REPO_ROOT

LOG_DIR = REPO_ROOT / "data" / "logs"
LOG_FILE = LOG_DIR / "contextguard.log"

_configured = False


def setup_logging(level: str | None = None) -> logging.Logger:
    """Idempotent -- safe to call from every entry point (dashboard,
    headless script, CLI tools) without producing duplicate handlers.
    """
    global _configured
    logger = logging.getLogger("contextguard")

    if _configured:
        return logger

    level_name = (level or os.environ.get("CONTEXTGUARD_LOG_LEVEL", "INFO")).upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        # Read-only filesystem, permission issue, etc. -- console logging
        # alone is a fine degradation, not a reason to crash the service.
        logger.warning("Could not open %s for writing; file logging disabled.", LOG_FILE)

    logger.propagate = False
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"contextguard.{name}")
