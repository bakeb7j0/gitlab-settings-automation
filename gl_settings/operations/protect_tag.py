"""Tag protection operation."""

from __future__ import annotations

import argparse
import urllib.parse

import requests

from gl_settings.models import ACCESS_LEVELS, ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("protect-tag")
class ProtectTagOperation(Operation):
    """Protect or update protection on a tag pattern."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--tag", required=True, help="Tag name or wildcard pattern (e.g., 'v1.2.*', 'release-*')")
        parser.add_argument(
            "--create",
            default="maintainer",
            choices=list(ACCESS_LEVELS.keys()),
            help="Allowed to create (default: maintainer)",
        )
        parser.add_argument("--unprotect", action="store_true", help="Remove tag protection instead of applying it")

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        tag = self.args.tag

        if self.args.unprotect:
            return self._unprotect(project_id, project_path, tag)

        desired_create = ACCESS_LEVELS[self.args.create]

        # Check current protection
        try:
            encoded_tag = urllib.parse.quote(tag, safe="")
            existing = self.client.get(f"/projects/{project_id}/protected_tags/{encoded_tag}")
            current_create = self._max_access_level(existing.get("create_access_levels", []))

            if current_create == desired_create:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"protect-tag:{tag}",
                        action="already_set",
                        detail=f"create={self.args.create}",
                    )
                )

            # Update requires delete + recreate
            if not self.client.dry_run:
                self.client.delete(f"/projects/{project_id}/protected_tags/{encoded_tag}")

        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"protect-tag:{tag}",
                        action="error",
                        detail=str(e),
                    )
                )

        # Apply protection
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(
                    f"/projects/{project_id}/protected_tags",
                    data={
                        "name": tag,
                        "create_access_level": desired_create,
                    },
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"protect-tag:{tag}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"protect-tag:{tag}",
                action=action,
                detail=f"create={self.args.create}",
                dry_run=self.client.dry_run,
            )
        )

    def _unprotect(self, project_id: int, project_path: str, tag: str) -> ActionResult:
        encoded_tag = urllib.parse.quote(tag, safe="")
        try:
            self.client.get(f"/projects/{project_id}/protected_tags/{encoded_tag}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"unprotect-tag:{tag}",
                        action="already_set",
                        detail="tag is not protected",
                    )
                )
            raise

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            self.client.delete(f"/projects/{project_id}/protected_tags/{encoded_tag}")

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"unprotect-tag:{tag}",
                action=action,
                detail="removed tag protection",
                dry_run=self.client.dry_run,
            )
        )

    @staticmethod
    def _max_access_level(access_levels: list[dict]) -> int:
        if not access_levels:
            return 0
        return max(al.get("access_level", 0) for al in access_levels)
