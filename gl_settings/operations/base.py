"""Base class and registry for operations."""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from gl_settings.models import ActionResult

if TYPE_CHECKING:
    from gl_settings.client import GitLabClient

# ---------------------------------------------------------------------------
# Operation Registry
# ---------------------------------------------------------------------------

_operation_registry: dict[str, type[Operation]] = {}


def register_operation(name: str):
    """Decorator to register an operation class under a CLI subcommand name."""

    def decorator(cls):
        _operation_registry[name] = cls
        cls.operation_name = name
        return cls

    return decorator


def get_operation_registry() -> dict[str, type[Operation]]:
    """Get the operation registry."""
    return _operation_registry


# ---------------------------------------------------------------------------
# Operation Base Class
# ---------------------------------------------------------------------------


class Operation(ABC):
    """Base class for all operations."""

    operation_name: str = ""

    def __init__(self, client: GitLabClient, args: argparse.Namespace):
        self.client = client
        self.args = args
        self.logger = logging.getLogger("gl-settings")
        self.results: list[ActionResult] = []

    @staticmethod
    @abstractmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        """Add operation-specific CLI arguments."""
        ...

    @abstractmethod
    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        """Apply this operation to a single project."""
        ...

    def applies_to_group(self) -> bool:
        """Override to return True if this operation can be set at group level."""
        return False

    def apply_to_group(self, group_id: int, group_path: str) -> ActionResult | None:
        """Apply this operation at the group level. Override if applies_to_group() is True."""
        return None

    def _record(self, result: ActionResult) -> ActionResult:
        self.results.append(result)
        icon = {
            "applied": "\u2713",
            "already_set": "\u00b7",
            "skipped": "\u2192",
            "error": "\u2717",
            "would_apply": "\u25cb",
        }.get(result.action, "?")

        # Log to structured logger
        record = self.logger.makeRecord("gl-settings", logging.INFO, "", 0, "", (), None)
        record.action_result = result
        self.logger.handle(record)

        # Also log human-readable to stderr if not in json mode
        handler = self.logger.handlers[0] if self.logger.handlers else None
        if handler and not getattr(handler.formatter, "json_mode", False):
            prefix = "[DRY-RUN] " if result.dry_run else ""
            self.logger.info(
                f"{prefix}{icon} [{result.target_type}] {result.target_path}: "
                f"{result.operation} \u2192 {result.action}"
                f"{' (' + result.detail + ')' if result.detail else ''}"
            )
        return result
