"""Shared helpers for the fake trading stack services."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

RUNTIME = Path(os.environ.get("RUNTIME_DIR", "/runtime"))
CONFIG_DIR = Path(os.environ.get("STACK_CONFIG_DIR", "/etc/stack"))
CONTROL = RUNTIME / "control"


def setup_logging(service: str) -> logging.Logger:
    """Log to stdout and to a rotating file under /runtime/logs, using WARN not WARNING."""
    logging.addLevelName(logging.WARNING, "WARN")
    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    CONTROL.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(sys.stdout),
                    RotatingFileHandler(RUNTIME / "logs" / f"{service}.log",
                                        maxBytes=5 * 2**20, backupCount=2)):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    return logging.getLogger(service)


def flag(name: str) -> bool:
    """Chaos switches are plain files in /runtime/control (see chaos.sh)."""
    return (CONTROL / name).exists()


def load_config(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f) or {}
