"""Logging utilities for gl-settings."""

from __future__ import annotations

import json
import logging
import sys


class StructuredFormatter(logging.Formatter):
    """Formatter that can emit JSON lines when configured."""

    def __init__(self, json_mode: bool = False):
        super().__init__()
        self.json_mode = json_mode

    def format(self, record: logging.LogRecord) -> str:
        if self.json_mode and hasattr(record, "action_result"):
            return json.dumps(record.action_result.to_dict())
        if self.json_mode:
            return json.dumps({"level": record.levelname, "message": record.getMessage()})
        return f"[{record.levelname:<7}] {record.getMessage()}"


def setup_logging(json_mode: bool = False, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("gl-settings")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(StructuredFormatter(json_mode=json_mode))
    logger.addHandler(handler)
    return logger
