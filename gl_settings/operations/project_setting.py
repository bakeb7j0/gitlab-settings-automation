"""Project/group settings operation."""

from __future__ import annotations

import argparse
from typing import Any

import requests

from gl_settings.models import ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("project-setting")
class ProjectSettingOperation(Operation):
    """Set project or group settings via key=value pairs."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--setting",
            action="append",
            dest="settings",
            required=True,
            metavar="KEY=VALUE",
            help="Setting to apply (repeatable). Example: --setting visibility=private",
        )

    def applies_to_group(self) -> bool:
        return True

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        return self._apply_settings(
            entity_type="project",
            entity_id=project_id,
            entity_path=project_path,
            get_endpoint=f"/projects/{project_id}",
            put_endpoint=f"/projects/{project_id}",
        )

    def apply_to_group(self, group_id: int, group_path: str) -> ActionResult | None:
        return self._apply_settings(
            entity_type="group",
            entity_id=group_id,
            entity_path=group_path,
            get_endpoint=f"/groups/{group_id}",
            put_endpoint=f"/groups/{group_id}",
        )

    def _apply_settings(
        self,
        entity_type: str,
        entity_id: int,
        entity_path: str,
        get_endpoint: str,
        put_endpoint: str,
    ) -> ActionResult:
        """Apply settings to a project or group, with idempotency checking."""
        # Parse settings from --setting args
        desired: dict[str, Any] = {}
        for setting in self.args.settings:
            if "=" not in setting:
                return self._record(
                    ActionResult(
                        target_type=entity_type,
                        target_path=entity_path,
                        target_id=entity_id,
                        operation="project-setting",
                        action="error",
                        detail=f"Invalid format: {setting} (expected key=value)",
                    )
                )
            key, value = setting.split("=", 1)
            desired[key.strip()] = self._coerce_value(value.strip())

        # GET current settings
        try:
            current = self.client.get(get_endpoint)
        except requests.HTTPError as e:
            return self._record(
                ActionResult(
                    target_type=entity_type,
                    target_path=entity_path,
                    target_id=entity_id,
                    operation="project-setting",
                    action="error",
                    detail=f"Failed to get settings: {e}",
                )
            )

        # Compare and find changes
        changes = {k: v for k, v in desired.items() if current.get(k) != v}

        if not changes:
            return self._record(
                ActionResult(
                    target_type=entity_type,
                    target_path=entity_path,
                    target_id=entity_id,
                    operation="project-setting",
                    action="already_set",
                    detail=f"keys: {list(desired.keys())}",
                )
            )

        # Apply changes
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(put_endpoint, data=changes)
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type=entity_type,
                        target_path=entity_path,
                        target_id=entity_id,
                        operation="project-setting",
                        action="error",
                        detail=f"Failed to apply: {e}",
                    )
                )

        return self._record(
            ActionResult(
                target_type=entity_type,
                target_path=entity_path,
                target_id=entity_id,
                operation="project-setting",
                action=action,
                detail=f"changed: {list(changes.keys())}",
                dry_run=self.client.dry_run,
            )
        )

    @staticmethod
    def _coerce_value(value: str) -> Any:
        """Coerce string value to appropriate Python type."""
        # Boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        # Integer
        try:
            return int(value)
        except ValueError:
            pass
        # Float
        try:
            return float(value)
        except ValueError:
            pass
        # String (default)
        return value
