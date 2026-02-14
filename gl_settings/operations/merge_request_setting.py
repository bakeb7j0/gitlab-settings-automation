"""Merge request settings operation."""

from __future__ import annotations

import argparse
from typing import Any

import requests

from gl_settings.models import ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("merge-request-setting")
class MergeRequestSettingOperation(Operation):
    """Configure project merge request approval settings."""

    # Field mappings from legacy API to modern API (some have inverted logic)
    # Format: legacy_field -> (modern_field, is_inverted)
    FIELD_MAPPING = {
        "reset_approvals_on_push": ("retain_approvals_on_push", True),
        "disable_overriding_approvers_per_merge_request": ("allow_overrides_to_approver_list_per_merge_request", True),
        "merge_requests_author_approval": ("allow_author_approval", False),
        "merge_requests_disable_committers_approval": ("allow_committer_approval", True),
    }

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--approvals-before-merge",
            type=int,
            default=None,
            help="Required approvals before merge (deprecated in newer GitLab)",
        )
        parser.add_argument(
            "--reset-approvals-on-push",
            choices=["true", "false"],
            default=None,
            help="Reset approvals when new commits are pushed",
        )
        parser.add_argument(
            "--disable-overriding-approvers",
            choices=["true", "false"],
            default=None,
            help="Prevent users from modifying approvers per MR",
        )
        parser.add_argument(
            "--merge-requests-author-approval",
            choices=["true", "false"],
            default=None,
            help="Allow MR author to approve their own MR",
        )
        parser.add_argument(
            "--merge-requests-disable-committers-approval",
            choices=["true", "false"],
            default=None,
            help="Prevent committers from approving MRs they committed to",
        )

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        # Build desired settings from args
        desired: dict[str, Any] = {}

        if self.args.approvals_before_merge is not None:
            desired["approvals_before_merge"] = self.args.approvals_before_merge
        if self.args.reset_approvals_on_push is not None:
            desired["reset_approvals_on_push"] = self.args.reset_approvals_on_push == "true"
        if self.args.disable_overriding_approvers is not None:
            desired["disable_overriding_approvers_per_merge_request"] = self.args.disable_overriding_approvers == "true"
        if self.args.merge_requests_author_approval is not None:
            desired["merge_requests_author_approval"] = self.args.merge_requests_author_approval == "true"
        if self.args.merge_requests_disable_committers_approval is not None:
            desired["merge_requests_disable_committers_approval"] = (
                self.args.merge_requests_disable_committers_approval == "true"
            )

        if not desired:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="merge-request-setting",
                    action="skipped",
                    detail="No settings specified",
                )
            )

        # Try modern API first, fall back to legacy
        result = self._try_modern_api(project_id, project_path, desired)
        if result is not None:
            return result
        return self._use_legacy_api(project_id, project_path, desired)

    def _try_modern_api(self, project_id: int, project_path: str, desired: dict[str, Any]) -> ActionResult | None:
        """Try the modern merge_request_approval_settings API (GitLab 13.x+)."""
        endpoint = f"/projects/{project_id}/merge_request_approval_settings"

        try:
            current = self.client.get(endpoint)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.debug("Modern approval settings API not available, falling back to legacy")
                return None  # Signal to use legacy API
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="merge-request-setting",
                    action="error",
                    detail=f"Failed to get settings: {e}",
                )
            )

        # Map legacy field names to modern API and handle inverted logic
        changes: dict[str, Any] = {}
        for legacy_key, value in desired.items():
            if legacy_key == "approvals_before_merge":
                # This field doesn't exist in modern API, skip it
                self.logger.debug("approvals_before_merge not supported in modern API, skipping")
                continue

            if legacy_key in self.FIELD_MAPPING:
                modern_key, is_inverted = self.FIELD_MAPPING[legacy_key]
                if is_inverted:
                    value = not value
                if current.get(modern_key) != value:
                    changes[modern_key] = value
            elif current.get(legacy_key) != value:
                changes[legacy_key] = value

        if not changes:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="merge-request-setting",
                    action="already_set",
                    detail=f"keys: {list(desired.keys())}",
                )
            )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(endpoint, data=changes)
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="merge-request-setting",
                        action="error",
                        detail=f"Failed to apply: {e}",
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation="merge-request-setting",
                action=action,
                detail=f"changed (modern API): {list(changes.keys())}",
                dry_run=self.client.dry_run,
            )
        )

    def _use_legacy_api(self, project_id: int, project_path: str, desired: dict[str, Any]) -> ActionResult:
        """Use the legacy /approvals API (GitLab 12.x and earlier)."""
        endpoint = f"/projects/{project_id}/approvals"

        try:
            current = self.client.get(endpoint)
        except requests.HTTPError as e:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="merge-request-setting",
                    action="error",
                    detail=f"Failed to get settings: {e}",
                )
            )

        # Compare and find changes (legacy API uses same field names as our args)
        changes = {k: v for k, v in desired.items() if current.get(k) != v}

        if not changes:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="merge-request-setting",
                    action="already_set",
                    detail=f"keys: {list(desired.keys())}",
                )
            )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                # Legacy API uses POST, not PUT!
                self.client.post(endpoint, data=changes)
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="merge-request-setting",
                        action="error",
                        detail=f"Failed to apply: {e}",
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation="merge-request-setting",
                action=action,
                detail=f"changed (legacy API): {list(changes.keys())}",
                dry_run=self.client.dry_run,
            )
        )
