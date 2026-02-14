"""Branch protection operation."""

from __future__ import annotations

import argparse
import urllib.parse

import requests

from gl_settings.models import ACCESS_LEVELS, ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("protect-branch")
class ProtectBranchOperation(Operation):
    """Protect or update protection on a branch."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--branch", required=True, help="Branch name or wildcard pattern (e.g., 'release/1.2', 'release/*')"
        )
        parser.add_argument(
            "--push",
            default="maintainer",
            choices=list(ACCESS_LEVELS.keys()),
            help="Allowed to push (default: maintainer)",
        )
        parser.add_argument(
            "--merge",
            default="maintainer",
            choices=list(ACCESS_LEVELS.keys()),
            help="Allowed to merge (default: maintainer)",
        )
        parser.add_argument("--unprotect", action="store_true", help="Remove protection instead of applying it")
        parser.add_argument(
            "--allow-force-push", action="store_true", default=False, help="Allow force push to the branch"
        )

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        branch = self.args.branch

        if self.args.unprotect:
            return self._unprotect(project_id, project_path, branch)

        desired_push = ACCESS_LEVELS[self.args.push]
        desired_merge = ACCESS_LEVELS[self.args.merge]
        allow_force_push = self.args.allow_force_push

        # Check current protection state
        try:
            encoded_branch = urllib.parse.quote(branch, safe="")
            existing = self.client.get(f"/projects/{project_id}/protected_branches/{encoded_branch}")
            # Branch is already protected - check if settings match
            current_push = self._max_access_level(existing.get("push_access_levels", []))
            current_merge = self._max_access_level(existing.get("merge_access_levels", []))
            current_force_push = existing.get("allow_force_push", False)

            if (
                current_push == desired_push
                and current_merge == desired_merge
                and current_force_push == allow_force_push
            ):
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"protect-branch:{branch}",
                        action="already_set",
                        detail=f"push={self.args.push}, merge={self.args.merge}",
                    )
                )

            # Need to update - GitLab requires delete + recreate for protected branches
            if not self.client.dry_run:
                self.client.delete(f"/projects/{project_id}/protected_branches/{encoded_branch}")
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"protect-branch:{branch}",
                        action="error",
                        detail=str(e),
                    )
                )
            # 404 = not yet protected, proceed to create

        # Apply protection
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(
                    f"/projects/{project_id}/protected_branches",
                    data={
                        "name": branch,
                        "push_access_level": desired_push,
                        "merge_access_level": desired_merge,
                        "allow_force_push": allow_force_push,
                    },
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"protect-branch:{branch}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"protect-branch:{branch}",
                action=action,
                detail=f"push={self.args.push}, merge={self.args.merge}, force_push={allow_force_push}",
                dry_run=self.client.dry_run,
            )
        )

    def _unprotect(self, project_id: int, project_path: str, branch: str) -> ActionResult:
        encoded_branch = urllib.parse.quote(branch, safe="")
        try:
            self.client.get(f"/projects/{project_id}/protected_branches/{encoded_branch}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"unprotect-branch:{branch}",
                        action="already_set",
                        detail="branch is not protected",
                    )
                )
            raise

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            self.client.delete(f"/projects/{project_id}/protected_branches/{encoded_branch}")

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"unprotect-branch:{branch}",
                action=action,
                detail="removed branch protection",
                dry_run=self.client.dry_run,
            )
        )

    @staticmethod
    def _max_access_level(access_levels: list[dict]) -> int:
        """Extract the effective access level from GitLab's access_levels array."""
        if not access_levels:
            return 0
        return max(al.get("access_level", 0) for al in access_levels)
