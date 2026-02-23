"""Initialize project with standard settings and templates."""

from __future__ import annotations

import argparse
import base64
import urllib.parse
from importlib import resources

import requests

from gl_settings.models import ACCESS_LEVELS, ActionResult
from gl_settings.operations.base import Operation, register_operation


@register_operation("init-project")
class InitProjectOperation(Operation):
    """Initialize a project with standard organizational settings and templates."""

    # Default project settings to apply
    DEFAULT_PROJECT_SETTINGS = {
        "only_allow_merge_if_pipeline_succeeds": True,
        "only_allow_merge_if_all_discussions_are_resolved": True,
        "remove_source_branch_after_merge": True,
        "merge_pipelines_enabled": True,
        "issue_branch_template": "feature/%{id}-%{title}",
        "forking_access_level": "disabled",
        "pages_access_level": "private",
        "package_registry_access_level": "private",
        "security_and_compliance_access_level": "private",
        "auto_devops_enabled": False,
    }

    # Default MR approval settings
    DEFAULT_MR_SETTINGS = {
        "reset_approvals_on_push": True,
    }

    # Protected branches: name -> (push_level, merge_level, allow_force_push)
    DEFAULT_PROTECTED_BRANCHES = {
        "main": ("maintainer", "maintainer", False),
        "release/*": ("maintainer", "maintainer", True),
    }

    # Protected tags: pattern -> create_level
    DEFAULT_PROTECTED_TAGS = {
        "rc*": "maintainer",
        "v*": "maintainer",
    }

    # Default release branch to create and set as default
    DEFAULT_RELEASE_BRANCH = "release/0.0.1"
    DEFAULT_RELEASE_SOURCE = "main"

    # Issue templates to install (relative to templates directory)
    DEFAULT_TEMPLATES = ["bug.md", "chore.md", "docs.md", "feature.md"]

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--skip-settings",
            action="store_true",
            help="Skip applying project settings",
        )
        parser.add_argument(
            "--skip-branches",
            action="store_true",
            help="Skip protected branch configuration",
        )
        parser.add_argument(
            "--skip-tags",
            action="store_true",
            help="Skip protected tag configuration",
        )
        parser.add_argument(
            "--skip-templates",
            action="store_true",
            help="Skip issue template installation",
        )
        parser.add_argument(
            "--skip-mr-settings",
            action="store_true",
            help="Skip merge request approval settings",
        )
        parser.add_argument(
            "--skip-release-branch",
            action="store_true",
            help="Skip creating release branch and setting it as default",
        )

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        """Apply all initialization steps to a project."""
        results = []

        # 1. Project settings
        if not self.args.skip_settings:
            result = self._apply_project_settings(project_id, project_path)
            results.append(result)

        # 2. MR approval settings
        if not self.args.skip_mr_settings:
            result = self._apply_mr_settings(project_id, project_path)
            results.append(result)

        # 3. Create release branch and set as default
        if not self.args.skip_release_branch:
            result = self._create_release_branch(project_id, project_path)
            results.append(result)

        # 4. Protected branches
        if not self.args.skip_branches:
            for branch, (push, merge, force_push) in self.DEFAULT_PROTECTED_BRANCHES.items():
                result = self._protect_branch(project_id, project_path, branch, push, merge, force_push)
                results.append(result)

        # 5. Protected tags
        if not self.args.skip_tags:
            for tag, create_level in self.DEFAULT_PROTECTED_TAGS.items():
                result = self._protect_tag(project_id, project_path, tag, create_level)
                results.append(result)

        # 6. Issue templates
        if not self.args.skip_templates:
            for template in self.DEFAULT_TEMPLATES:
                result = self._install_template(project_id, project_path, template)
                results.append(result)

        # Summarize
        applied = sum(1 for r in results if r.action in ("applied", "would_apply"))
        already_set = sum(1 for r in results if r.action == "already_set")
        errors = sum(1 for r in results if r.action == "error")

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation="init-project",
                action="applied" if errors == 0 else "error",
                detail=f"applied={applied}, already_set={already_set}, errors={errors}",
                dry_run=self.client.dry_run,
            )
        )

    def _apply_project_settings(self, project_id: int, project_path: str) -> ActionResult:
        """Apply project settings."""
        try:
            current = self.client.get(f"/projects/{project_id}")
        except requests.HTTPError as e:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="init-project:settings",
                    action="error",
                    detail=f"Failed to get settings: {e}",
                )
            )

        changes = {k: v for k, v in self.DEFAULT_PROJECT_SETTINGS.items() if current.get(k) != v}

        if not changes:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="init-project:settings",
                    action="already_set",
                    detail=f"{len(self.DEFAULT_PROJECT_SETTINGS)} settings",
                )
            )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(f"/projects/{project_id}", data=changes)
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="init-project:settings",
                        action="error",
                        detail=f"Failed to apply: {e}",
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation="init-project:settings",
                action=action,
                detail=f"changed {len(changes)} of {len(self.DEFAULT_PROJECT_SETTINGS)} settings",
                dry_run=self.client.dry_run,
            )
        )

    def _apply_mr_settings(self, project_id: int, project_path: str) -> ActionResult:
        """Apply merge request approval settings."""
        endpoint = f"/projects/{project_id}/merge_request_approval_settings"

        try:
            current = self.client.get(endpoint)
            # Modern API uses retain_approvals_on_push (inverted logic)
            current_reset = not current.get("retain_approvals_on_push", True)
            desired_reset = self.DEFAULT_MR_SETTINGS.get("reset_approvals_on_push", True)

            if current_reset == desired_reset:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="init-project:mr-settings",
                        action="already_set",
                        detail="reset_approvals_on_push",
                    )
                )

            action = "would_apply" if self.client.dry_run else "applied"
            if not self.client.dry_run:
                self.client.put(endpoint, data={"retain_approvals_on_push": not desired_reset})

            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="init-project:mr-settings",
                    action=action,
                    detail="reset_approvals_on_push",
                    dry_run=self.client.dry_run,
                )
            )
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                # Modern API not available, try legacy
                return self._apply_mr_settings_legacy(project_id, project_path)
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="init-project:mr-settings",
                    action="error",
                    detail=str(e),
                )
            )

    def _apply_mr_settings_legacy(self, project_id: int, project_path: str) -> ActionResult:
        """Apply MR settings using legacy API."""
        endpoint = f"/projects/{project_id}/approvals"
        try:
            current = self.client.get(endpoint)
            if current.get("reset_approvals_on_push") == self.DEFAULT_MR_SETTINGS.get("reset_approvals_on_push"):
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="init-project:mr-settings",
                        action="already_set",
                        detail="reset_approvals_on_push (legacy)",
                    )
                )

            action = "would_apply" if self.client.dry_run else "applied"
            if not self.client.dry_run:
                self.client.post(endpoint, data=self.DEFAULT_MR_SETTINGS)

            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="init-project:mr-settings",
                    action=action,
                    detail="reset_approvals_on_push (legacy)",
                    dry_run=self.client.dry_run,
                )
            )
        except requests.HTTPError as e:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation="init-project:mr-settings",
                    action="error",
                    detail=str(e),
                )
            )

    def _create_release_branch(self, project_id: int, project_path: str) -> ActionResult:
        """Create a release branch from main and set it as the default branch."""
        branch_name = self.DEFAULT_RELEASE_BRANCH
        source_ref = self.DEFAULT_RELEASE_SOURCE

        # Check if branch already exists
        encoded_branch = urllib.parse.quote(branch_name, safe="")
        try:
            self.client.get(f"/projects/{project_id}/repository/branches/{encoded_branch}")
            branch_exists = True
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                branch_exists = False
            else:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:release-branch:{branch_name}",
                        action="error",
                        detail=str(e),
                    )
                )

        # Check current default branch
        try:
            project = self.client.get(f"/projects/{project_id}")
            current_default = project.get("default_branch", "main")
        except requests.HTTPError as e:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"init-project:release-branch:{branch_name}",
                    action="error",
                    detail=f"Failed to get project: {e}",
                )
            )

        # Already done?
        if branch_exists and current_default == branch_name:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"init-project:release-branch:{branch_name}",
                    action="already_set",
                    detail="branch exists and is default",
                )
            )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            # Create the branch if it doesn't exist
            if not branch_exists:
                try:
                    self.client.post(
                        f"/projects/{project_id}/repository/branches",
                        data={"branch": branch_name, "ref": source_ref},
                    )
                except requests.HTTPError as e:
                    return self._record(
                        ActionResult(
                            target_type="project",
                            target_path=project_path,
                            target_id=project_id,
                            operation=f"init-project:release-branch:{branch_name}",
                            action="error",
                            detail=f"Failed to create branch: {e}",
                        )
                    )

            # Set as default branch
            if current_default != branch_name:
                try:
                    self.client.put(f"/projects/{project_id}", data={"default_branch": branch_name})
                except requests.HTTPError as e:
                    return self._record(
                        ActionResult(
                            target_type="project",
                            target_path=project_path,
                            target_id=project_id,
                            operation=f"init-project:release-branch:{branch_name}",
                            action="error",
                            detail=f"Failed to set default branch: {e}",
                        )
                    )

        detail_parts = []
        if not branch_exists:
            detail_parts.append(f"created from {source_ref}")
        if current_default != branch_name:
            detail_parts.append(f"set as default (was {current_default})")
        detail = ", ".join(detail_parts)

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"init-project:release-branch:{branch_name}",
                action=action,
                detail=detail,
                dry_run=self.client.dry_run,
            )
        )

    def _protect_branch(
        self, project_id: int, project_path: str, branch: str, push: str, merge: str, force_push: bool
    ) -> ActionResult:
        """Protect a branch with specified settings."""
        desired_push = ACCESS_LEVELS[push]
        desired_merge = ACCESS_LEVELS[merge]
        encoded_branch = urllib.parse.quote(branch, safe="")

        try:
            existing = self.client.get(f"/projects/{project_id}/protected_branches/{encoded_branch}")
            current_push = self._max_access_level(existing.get("push_access_levels", []))
            current_merge = self._max_access_level(existing.get("merge_access_levels", []))
            current_force = existing.get("allow_force_push", False)

            if current_push == desired_push and current_merge == desired_merge and current_force == force_push:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:branch:{branch}",
                        action="already_set",
                        detail=f"push={push}, merge={merge}",
                    )
                )

            # Need update - delete and recreate
            if not self.client.dry_run:
                self.client.delete(f"/projects/{project_id}/protected_branches/{encoded_branch}")
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:branch:{branch}",
                        action="error",
                        detail=str(e),
                    )
                )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(
                    f"/projects/{project_id}/protected_branches",
                    data={
                        "name": branch,
                        "push_access_level": desired_push,
                        "merge_access_level": desired_merge,
                        "allow_force_push": force_push,
                    },
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:branch:{branch}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"init-project:branch:{branch}",
                action=action,
                detail=f"push={push}, merge={merge}, force_push={force_push}",
                dry_run=self.client.dry_run,
            )
        )

    def _protect_tag(self, project_id: int, project_path: str, tag: str, create_level: str) -> ActionResult:
        """Protect a tag pattern."""
        desired_create = ACCESS_LEVELS[create_level]
        encoded_tag = urllib.parse.quote(tag, safe="")

        try:
            existing = self.client.get(f"/projects/{project_id}/protected_tags/{encoded_tag}")
            current_create = self._max_access_level(existing.get("create_access_levels", []))

            if current_create == desired_create:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:tag:{tag}",
                        action="already_set",
                        detail=f"create={create_level}",
                    )
                )

            if not self.client.dry_run:
                self.client.delete(f"/projects/{project_id}/protected_tags/{encoded_tag}")
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:tag:{tag}",
                        action="error",
                        detail=str(e),
                    )
                )

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(
                    f"/projects/{project_id}/protected_tags",
                    data={"name": tag, "create_access_level": desired_create},
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:tag:{tag}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"init-project:tag:{tag}",
                action=action,
                detail=f"create={create_level}",
                dry_run=self.client.dry_run,
            )
        )

    def _install_template(self, project_id: int, project_path: str, template_name: str) -> ActionResult:
        """Install an issue template from bundled resources."""
        # Load template from package resources
        try:
            template_content = resources.files("gl_settings.templates").joinpath(template_name).read_text()
        except FileNotFoundError:
            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"init-project:template:{template_name}",
                    action="error",
                    detail="Template not found in package",
                )
            )

        # Get project's default branch
        try:
            project = self.client.get(f"/projects/{project_id}")
            default_branch = project.get("default_branch", "main")
        except requests.HTTPError:
            default_branch = "main"

        gitlab_path = f".gitlab/issue_templates/{template_name}"
        encoded_path = urllib.parse.quote(gitlab_path, safe="")

        # Check if template already exists
        try:
            existing = self.client.get(
                f"/projects/{project_id}/repository/files/{encoded_path}", params={"ref": default_branch}
            )
            existing_content = base64.b64decode(existing.get("content", "")).decode("utf-8")

            if existing_content.strip() == template_content.strip():
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:template:{template_name}",
                        action="already_set",
                        detail=gitlab_path,
                    )
                )

            # Update existing
            action = "would_apply" if self.client.dry_run else "applied"
            if not self.client.dry_run:
                self.client.put(
                    f"/projects/{project_id}/repository/files/{encoded_path}",
                    data={
                        "branch": default_branch,
                        "content": template_content,
                        "commit_message": f"Update issue template: {template_name}",
                        "encoding": "text",
                    },
                )

            return self._record(
                ActionResult(
                    target_type="project",
                    target_path=project_path,
                    target_id=project_id,
                    operation=f"init-project:template:{template_name}",
                    action=action,
                    detail=f"updated {gitlab_path}",
                    dry_run=self.client.dry_run,
                )
            )
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:template:{template_name}",
                        action="error",
                        detail=str(e),
                    )
                )

        # Create new template
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(
                    f"/projects/{project_id}/repository/files/{encoded_path}",
                    data={
                        "branch": default_branch,
                        "content": template_content,
                        "commit_message": f"Add issue template: {template_name}",
                        "encoding": "text",
                    },
                )
            except requests.HTTPError as e:
                return self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation=f"init-project:template:{template_name}",
                        action="error",
                        detail=str(e),
                    )
                )

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation=f"init-project:template:{template_name}",
                action=action,
                detail=f"created {gitlab_path}",
                dry_run=self.client.dry_run,
            )
        )

    @staticmethod
    def _max_access_level(access_levels: list[dict]) -> int:
        """Extract the effective access level from GitLab's access_levels array."""
        if not access_levels:
            return 0
        return max(al.get("access_level", 0) for al in access_levels)
