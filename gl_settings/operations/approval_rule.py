"""Approval rule operation."""

from __future__ import annotations

import argparse

import requests

from gl_settings.models import ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("approval-rule")
class ApprovalRuleOperation(Operation):
    """Manage project-level merge request approval rules."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--rule-name", required=True, help="Name of the approval rule (used to find/create)")
        parser.add_argument("--approvals", type=int, default=None, help="Required number of approvals")
        parser.add_argument(
            "--add-user",
            action="append",
            dest="add_users",
            default=[],
            metavar="USER",
            help="Add user (username or ID, repeatable)",
        )
        parser.add_argument(
            "--remove-user",
            action="append",
            dest="remove_users",
            default=[],
            metavar="USER",
            help="Remove user (username or ID, repeatable)",
        )
        parser.add_argument("--unprotect", action="store_true", help="Delete the approval rule")

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        rule_name = self.args.rule_name

        if self.args.unprotect:
            return self._delete_rule(project_id, project_path, rule_name)

        existing = self._find_rule(project_id, rule_name)
        if existing:
            return self._update_rule(project_id, project_path, existing)
        return self._create_rule(project_id, project_path)

    def _find_rule(self, project_id: int, rule_name: str) -> dict | None:
        """Find an approval rule by name."""
        try:
            rules = self.client.paginate(f"/projects/{project_id}/approval_rules")
            return next((r for r in rules if r.get("name") == rule_name), None)
        except requests.HTTPError:
            return None

    def _resolve_users(self, identifiers: list[str]) -> list[int]:
        """Resolve usernames/IDs to user IDs, logging warnings for failures."""
        user_ids = []
        for ident in identifiers:
            try:
                user_ids.append(self.client.resolve_user(ident))
            except ValueError as e:
                self.logger.warning(f"Could not resolve user: {e}")
        return user_ids

    def _create_rule(self, project_id: int, project_path: str) -> ActionResult:
        """Create a new approval rule."""
        rule_name = self.args.rule_name

        if self.args.approvals is None:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"approval-rule:{rule_name}",
                    action="error",
                    detail="--approvals is required when creating a new rule",
                )
            )

        user_ids = self._resolve_users(self.args.add_users)

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(
                    f"/projects/{project_id}/approval_rules",
                    data={
                        "name": rule_name,
                        "approvals_required": self.args.approvals,
                        "user_ids": user_ids,
                    },
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"approval-rule:{rule_name}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"approval-rule:{rule_name}",
                action=action,
                detail=f"created with {self.args.approvals} approvals, {len(user_ids)} users",
                dry_run=self.client.dry_run,
            )
        )

    def _update_rule(self, project_id: int, project_path: str, existing: dict) -> ActionResult:
        """Update an existing approval rule."""
        rule_id = existing["id"]
        rule_name = self.args.rule_name

        # Calculate desired state
        current_approvals = existing.get("approvals_required", 0)
        current_user_ids = set(u["id"] for u in existing.get("users", []))

        desired_approvals = self.args.approvals if self.args.approvals is not None else current_approvals

        add_user_ids = set(self._resolve_users(self.args.add_users))
        remove_user_ids = set(self._resolve_users(self.args.remove_users))
        desired_user_ids = (current_user_ids | add_user_ids) - remove_user_ids

        # Check if anything changed
        if current_approvals == desired_approvals and current_user_ids == desired_user_ids:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"approval-rule:{rule_name}",
                    action="already_set",
                    detail=f"approvals={current_approvals}, users={len(current_user_ids)}",
                )
            )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(
                    f"/projects/{project_id}/approval_rules/{rule_id}",
                    data={
                        "approvals_required": desired_approvals,
                        "user_ids": list(desired_user_ids),
                    },
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"approval-rule:{rule_name}",
                        action="error",
                        detail=str(e),
                    )
                )

        # Build change description
        changes = []
        if current_approvals != desired_approvals:
            changes.append(f"approvals: {current_approvals} -> {desired_approvals}")
        if current_user_ids != desired_user_ids:
            changes.append(f"users: {len(current_user_ids)} -> {len(desired_user_ids)}")

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"approval-rule:{rule_name}",
                action=action,
                detail="; ".join(changes),
                dry_run=self.client.dry_run,
            )
        )

    def _delete_rule(self, project_id: int, project_path: str, rule_name: str) -> ActionResult:
        """Delete an approval rule."""
        existing = self._find_rule(project_id, rule_name)

        if not existing:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"approval-rule:{rule_name}",
                    action="already_set",
                    detail="rule does not exist",
                )
            )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.delete(f"/projects/{project_id}/approval_rules/{existing['id']}")
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"approval-rule:{rule_name}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"approval-rule:{rule_name}",
                action=action,
                detail="deleted approval rule",
                dry_run=self.client.dry_run,
            )
        )
