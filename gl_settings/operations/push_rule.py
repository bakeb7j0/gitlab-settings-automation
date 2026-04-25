"""Push rule operation — manage project-level push rules (e.g. branch_name_regex)."""

from __future__ import annotations

import argparse
from typing import Any

import requests

from gl_settings.models import ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("push-rule")
class PushRuleOperation(Operation):
    """Configure project push rules. Currently manages ``branch_name_regex``.

    GitLab's push-rule endpoint is asymmetric: ``GET /projects/:id/push_rule``
    returns 404 when no rule has ever been created, so the first write must
    be a ``POST``; subsequent writes use ``PUT``.
    """

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--branch-name-regex",
            required=True,
            metavar="REGEX",
            help=("Regex that branch names must match. Example: '^(main|develop|kahuna/.*|feature/.*|fix/.*)$'"),
        )

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        desired: dict[str, Any] = {"branch_name_regex": self.args.branch_name_regex}
        endpoint = f"/projects/{project_id}/push_rule"

        # GET current rule. 404 means no rule exists yet -> POST to create.
        current: dict | None
        try:
            current = self.client.get(endpoint)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                current = None
            else:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="push-rule",
                        action="error",
                        detail=f"Failed to get push rule: {e}",
                    )
                )

        if current is not None:
            existing = current.get("branch_name_regex")
            if existing == desired["branch_name_regex"]:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="push-rule",
                        action="already_set",
                        detail=f"branch_name_regex: {existing!r}",
                    )
                )

        action = "would_apply" if self.client.dry_run else "applied"
        detail = f"branch_name_regex: {(current or {}).get('branch_name_regex')!r} -> {desired['branch_name_regex']!r}"

        if not self.client.dry_run:
            try:
                if current is None:
                    self.client.post(endpoint, data=desired)
                else:
                    self.client.put(endpoint, data=desired)
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="push-rule",
                        action="error",
                        detail=f"Failed to apply push rule: {e}",
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation="push-rule",
                action=action,
                detail=detail,
                dry_run=self.client.dry_run,
            )
        )
