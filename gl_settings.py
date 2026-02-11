#!/usr/bin/env python3
"""
gl-settings: A composable CLI tool for applying settings to GitLab groups and projects.

Designed to be called by automation scripts. Resolves a GitLab URL to a group or project,
then applies the specified operation — recursing into child groups/projects as needed.

Environment:
    GITLAB_TOKEN - GitLab Personal Access Token (required)
    GITLAB_URL   - GitLab instance URL (default: https://gitlab.com)

Examples:
    # Protect a branch on a single project
    gl-settings protect-branch https://gitlab.com/myorg/myproject \\
        --branch release/1.2 --push no_access --merge no_access

    # Protect a tag pattern across all projects in a group
    gl-settings protect-tag https://gitlab.com/myorg \\
        --tag "v1.2.*" --create maintainer

    # Dry-run to see what would happen
    gl-settings protect-branch https://gitlab.com/myorg \\
        --branch main --push maintainer --merge developer --dry-run

    # JSON output for machine parsing
    gl-settings protect-branch https://gitlab.com/myorg/myproject \\
        --branch main --push no_access --merge no_access --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import sys
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# Constants & Enums
# ---------------------------------------------------------------------------

DEFAULT_GITLAB_URL = "https://gitlab.com"
API_V4 = "/api/v4"
PER_PAGE = 100

# Retry configuration
DEFAULT_MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 0.5  # seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# GitLab access level constants
ACCESS_LEVELS = {
    "no_access": 0,
    "minimal": 5,
    "guest": 10,
    "reporter": 20,
    "developer": 30,
    "maintainer": 40,
    "owner": 50,
    "admin": 60,
}


class TargetType(Enum):
    PROJECT = "project"
    GROUP = "group"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class Target:
    """Resolved GitLab target (group or project)."""
    type: TargetType
    id: int
    path: str
    name: str
    web_url: str


@dataclass
class ActionResult:
    """Result of a single operation application."""
    target_type: str
    target_path: str
    target_id: int
    operation: str
    action: str  # "applied", "already_set", "skipped", "error"
    detail: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict:
        d = {
            "target_type": self.target_type,
            "target_path": self.target_path,
            "target_id": self.target_id,
            "operation": self.operation,
            "action": self.action,
            "detail": self.detail,
        }
        if self.dry_run:
            d["dry_run"] = True
        return d


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GitLab API Client
# ---------------------------------------------------------------------------


class GitLabClient:
    """Thin wrapper around GitLab REST API v4 with pagination support and retry logic."""

    def __init__(self, base_url: str, token: str, dry_run: bool = False,
                 max_retries: int = DEFAULT_MAX_RETRIES):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}{API_V4}"
        self.session = requests.Session()
        self.session.headers.update({
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        })
        self.dry_run = dry_run
        self.max_retries = max_retries
        self.logger = logging.getLogger("gl-settings")

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make an HTTP request with retry logic for transient failures."""
        url = f"{self.api_url}{endpoint}"
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                self.logger.debug(
                    f"{method.upper()} {url} {kwargs.get('params', '')} {kwargs.get('json', '')} "
                    f"(attempt {attempt + 1}/{self.max_retries + 1})"
                )
                resp = self.session.request(method, url, **kwargs)

                # Retry on rate limit or server errors
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    wait_time = self._calculate_backoff(resp, attempt)
                    self.logger.warning(
                        f"Retryable error {resp.status_code}, waiting {wait_time:.1f}s before retry"
                    )
                    time.sleep(wait_time)
                    continue

                if resp.status_code >= 400:
                    self.logger.error(f"API error {resp.status_code}: {resp.text[:500]}")
                resp.raise_for_status()
                return resp

            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
                    self.logger.warning(
                        f"Connection error, retrying in {wait_time:.1f}s: {e}"
                    )
                    time.sleep(wait_time)
                    continue
                raise

        # Should not reach here, but safety net
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry loop exit")

    def _calculate_backoff(self, resp: requests.Response, attempt: int) -> float:
        """Calculate backoff time, respecting Retry-After header for 429s."""
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass  # Fall through to exponential backoff
        return RETRY_BACKOFF_FACTOR * (2 ** attempt)

    def get(self, endpoint: str, params: dict | None = None) -> Any:
        return self._request("GET", endpoint, params=params).json()

    def post(self, endpoint: str, data: dict | None = None) -> Any:
        return self._request("POST", endpoint, json=data).json()

    def put(self, endpoint: str, data: dict | None = None) -> Any:
        return self._request("PUT", endpoint, json=data).json()

    def delete(self, endpoint: str, params: dict | None = None) -> requests.Response:
        return self._request("DELETE", endpoint, params=params)

    def paginate(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Fetch all pages of a paginated endpoint."""
        params = dict(params or {})
        params.setdefault("per_page", PER_PAGE)
        page = 1
        results = []
        while True:
            params["page"] = page
            resp = self._request("GET", endpoint, params=params)
            data = resp.json()
            if not data:
                break
            results.extend(data)
            # Check if there are more pages
            total_pages = int(resp.headers.get("x-total-pages", page))
            if page >= total_pages:
                break
            page += 1
        return results

    # -- Resolution helpers --

    def resolve_target(self, url: str) -> Target:
        """
        Resolve a GitLab web URL to a Target (project or group).

        Tries project first (more specific), falls back to group.
        """
        path = self._extract_path_from_url(url)
        encoded_path = urllib.parse.quote(path, safe="")

        # Try project first
        try:
            proj = self.get(f"/projects/{encoded_path}")
            return Target(
                type=TargetType.PROJECT,
                id=proj["id"],
                path=proj["path_with_namespace"],
                name=proj["name"],
                web_url=proj["web_url"],
            )
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                raise

        # Fall back to group
        try:
            grp = self.get(f"/groups/{encoded_path}")
            return Target(
                type=TargetType.GROUP,
                id=grp["id"],
                path=grp["full_path"],
                name=grp["name"],
                web_url=grp["web_url"],
            )
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise SystemExit(f"ERROR: Could not resolve '{url}' as a project or group.")
            raise

    def _extract_path_from_url(self, url: str) -> str:
        """Extract the namespace/project path from a GitLab URL."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme and parsed.netloc:
            # Full URL: https://gitlab.com/myorg/myteam/myproject
            path = parsed.path.strip("/")
            # Strip common suffixes
            for suffix in ("/-/", "/-", ".git"):
                if suffix in path:
                    path = path[: path.index(suffix)]
            return path
        else:
            # Bare path: myorg/myteam/myproject
            return url.strip("/")

    def get_subgroups(self, group_id: int) -> list[dict]:
        return self.paginate(f"/groups/{group_id}/subgroups")

    def get_group_projects(self, group_id: int) -> list[dict]:
        return self.paginate(f"/groups/{group_id}/projects", params={"include_subgroups": False})

    def resolve_user(self, identifier: str) -> int:
        """Resolve a username or user ID to a numeric user ID."""
        # If already numeric, return as-is
        try:
            return int(identifier)
        except ValueError:
            pass

        # Look up by username
        users = self.get("/users", params={"username": identifier})
        if not users:
            raise ValueError(f"User not found: {identifier}")
        return users[0]["id"]


# ---------------------------------------------------------------------------
# Operation Base Class & Registry
# ---------------------------------------------------------------------------

_operation_registry: dict[str, type["Operation"]] = {}


def register_operation(name: str):
    """Decorator to register an operation class under a CLI subcommand name."""
    def decorator(cls):
        _operation_registry[name] = cls
        cls.operation_name = name
        return cls
    return decorator


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
            "applied": "✓",
            "already_set": "·",
            "skipped": "→",
            "error": "✗",
            "would_apply": "○",
        }.get(result.action, "?")

        # Log to structured logger
        record = self.logger.makeRecord(
            "gl-settings", logging.INFO, "", 0, "", (), None
        )
        record.action_result = result
        self.logger.handle(record)

        # Also log human-readable to stderr if not in json mode
        handler = self.logger.handlers[0] if self.logger.handlers else None
        if handler and not getattr(handler.formatter, "json_mode", False):
            prefix = "[DRY-RUN] " if result.dry_run else ""
            self.logger.info(
                f"{prefix}{icon} [{result.target_type}] {result.target_path}: "
                f"{result.operation} → {result.action}"
                f"{' (' + result.detail + ')' if result.detail else ''}"
            )
        return result


# ---------------------------------------------------------------------------
# Recursion Engine
# ---------------------------------------------------------------------------


def recurse(client: GitLabClient, target: Target, operation: Operation,
            filter_pattern: str | None = None) -> None:
    """Walk the target tree and apply the operation, optionally filtering projects."""
    logger = logging.getLogger("gl-settings")

    if target.type == TargetType.PROJECT:
        # Apply filter to direct project targets
        if filter_pattern and not fnmatch.fnmatch(target.path, filter_pattern):
            logger.debug(f"Skipping project (filter): {target.path}")
            return
        operation.apply_to_project(target.id, target.path)
        return

    # It's a group
    if operation.applies_to_group():
        operation.apply_to_group(target.id, target.path)

    # Recurse into subgroups (groups are always traversed, filter applies only to projects)
    for subgroup in client.get_subgroups(target.id):
        sub_target = Target(
            type=TargetType.GROUP,
            id=subgroup["id"],
            path=subgroup["full_path"],
            name=subgroup["name"],
            web_url=subgroup["web_url"],
        )
        recurse(client, sub_target, operation, filter_pattern)

    # Apply to direct child projects (with filtering)
    for project in client.get_group_projects(target.id):
        project_path = project["path_with_namespace"]
        if filter_pattern and not fnmatch.fnmatch(project_path, filter_pattern):
            logger.debug(f"Skipping project (filter): {project_path}")
            continue
        operation.apply_to_project(project["id"], project_path)


# ---------------------------------------------------------------------------
# Operations: protect-branch
# ---------------------------------------------------------------------------


@register_operation("protect-branch")
class ProtectBranchOperation(Operation):
    """Protect or update protection on a branch."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--branch", required=True, help="Branch name or wildcard pattern (e.g., 'release/1.2', 'release/*')")
        parser.add_argument("--push", default="maintainer", choices=list(ACCESS_LEVELS.keys()),
                            help="Allowed to push (default: maintainer)")
        parser.add_argument("--merge", default="maintainer", choices=list(ACCESS_LEVELS.keys()),
                            help="Allowed to merge (default: maintainer)")
        parser.add_argument("--unprotect", action="store_true",
                            help="Remove protection instead of applying it")
        parser.add_argument("--allow-force-push", action="store_true", default=False,
                            help="Allow force push to the branch")

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
            existing = self.client.get(
                f"/projects/{project_id}/protected_branches/{encoded_branch}"
            )
            # Branch is already protected — check if settings match
            current_push = self._max_access_level(existing.get("push_access_levels", []))
            current_merge = self._max_access_level(existing.get("merge_access_levels", []))
            current_force_push = existing.get("allow_force_push", False)

            if (current_push == desired_push
                    and current_merge == desired_merge
                    and current_force_push == allow_force_push):
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"protect-branch:{branch}", action="already_set",
                    detail=f"push={self.args.push}, merge={self.args.merge}",
                ))

            # Need to update — GitLab requires delete + recreate for protected branches
            if not self.client.dry_run:
                self.client.delete(
                    f"/projects/{project_id}/protected_branches/{encoded_branch}"
                )
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"protect-branch:{branch}", action="error",
                    detail=str(e),
                ))
            # 404 = not yet protected, proceed to create

        # Apply protection
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(f"/projects/{project_id}/protected_branches", data={
                    "name": branch,
                    "push_access_level": desired_push,
                    "merge_access_level": desired_merge,
                    "allow_force_push": allow_force_push,
                })
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"protect-branch:{branch}", action="error",
                    detail=str(e),
                ))

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"protect-branch:{branch}", action=action,
            detail=f"push={self.args.push}, merge={self.args.merge}, force_push={allow_force_push}",
            dry_run=self.client.dry_run,
        ))

    def _unprotect(self, project_id: int, project_path: str, branch: str) -> ActionResult:
        encoded_branch = urllib.parse.quote(branch, safe="")
        try:
            self.client.get(f"/projects/{project_id}/protected_branches/{encoded_branch}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"unprotect-branch:{branch}", action="already_set",
                    detail="branch is not protected",
                ))
            raise

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            self.client.delete(f"/projects/{project_id}/protected_branches/{encoded_branch}")

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"unprotect-branch:{branch}", action=action,
            detail="removed branch protection",
            dry_run=self.client.dry_run,
        ))

    @staticmethod
    def _max_access_level(access_levels: list[dict]) -> int:
        """Extract the effective access level from GitLab's access_levels array."""
        if not access_levels:
            return 0
        return max(al.get("access_level", 0) for al in access_levels)


# ---------------------------------------------------------------------------
# Operations: protect-tag
# ---------------------------------------------------------------------------


@register_operation("protect-tag")
class ProtectTagOperation(Operation):
    """Protect or update protection on a tag pattern."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--tag", required=True,
                            help="Tag name or wildcard pattern (e.g., 'v1.2.*', 'release-*')")
        parser.add_argument("--create", default="maintainer", choices=list(ACCESS_LEVELS.keys()),
                            help="Allowed to create (default: maintainer)")
        parser.add_argument("--unprotect", action="store_true",
                            help="Remove tag protection instead of applying it")

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        tag = self.args.tag

        if self.args.unprotect:
            return self._unprotect(project_id, project_path, tag)

        desired_create = ACCESS_LEVELS[self.args.create]

        # Check current protection
        try:
            encoded_tag = urllib.parse.quote(tag, safe="")
            existing = self.client.get(
                f"/projects/{project_id}/protected_tags/{encoded_tag}"
            )
            current_create = self._max_access_level(existing.get("create_access_levels", []))

            if current_create == desired_create:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"protect-tag:{tag}", action="already_set",
                    detail=f"create={self.args.create}",
                ))

            # Update requires delete + recreate
            if not self.client.dry_run:
                self.client.delete(f"/projects/{project_id}/protected_tags/{encoded_tag}")

        except requests.HTTPError as e:
            if e.response.status_code != 404:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"protect-tag:{tag}", action="error",
                    detail=str(e),
                ))

        # Apply protection
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(f"/projects/{project_id}/protected_tags", data={
                    "name": tag,
                    "create_access_level": desired_create,
                })
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"protect-tag:{tag}", action="error",
                    detail=str(e),
                ))

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"protect-tag:{tag}", action=action,
            detail=f"create={self.args.create}",
            dry_run=self.client.dry_run,
        ))

    def _unprotect(self, project_id: int, project_path: str, tag: str) -> ActionResult:
        encoded_tag = urllib.parse.quote(tag, safe="")
        try:
            self.client.get(f"/projects/{project_id}/protected_tags/{encoded_tag}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"unprotect-tag:{tag}", action="already_set",
                    detail="tag is not protected",
                ))
            raise

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            self.client.delete(f"/projects/{project_id}/protected_tags/{encoded_tag}")

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"unprotect-tag:{tag}", action=action,
            detail="removed tag protection",
            dry_run=self.client.dry_run,
        ))

    @staticmethod
    def _max_access_level(access_levels: list[dict]) -> int:
        if not access_levels:
            return 0
        return max(al.get("access_level", 0) for al in access_levels)


# ---------------------------------------------------------------------------
# Operations: project-setting
# ---------------------------------------------------------------------------


@register_operation("project-setting")
class ProjectSettingOperation(Operation):
    """Set project or group settings via key=value pairs."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--setting", action="append", dest="settings", required=True,
            metavar="KEY=VALUE",
            help="Setting to apply (repeatable). Example: --setting visibility=private"
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
                return self._record(ActionResult(
                    target_type=entity_type, target_path=entity_path, target_id=entity_id,
                    operation="project-setting", action="error",
                    detail=f"Invalid format: {setting} (expected key=value)",
                ))
            key, value = setting.split("=", 1)
            desired[key.strip()] = self._coerce_value(value.strip())

        # GET current settings
        try:
            current = self.client.get(get_endpoint)
        except requests.HTTPError as e:
            return self._record(ActionResult(
                target_type=entity_type, target_path=entity_path, target_id=entity_id,
                operation="project-setting", action="error",
                detail=f"Failed to get settings: {e}",
            ))

        # Compare and find changes
        changes = {k: v for k, v in desired.items() if current.get(k) != v}

        if not changes:
            return self._record(ActionResult(
                target_type=entity_type, target_path=entity_path, target_id=entity_id,
                operation="project-setting", action="already_set",
                detail=f"keys: {list(desired.keys())}",
            ))

        # Apply changes
        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(put_endpoint, data=changes)
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type=entity_type, target_path=entity_path, target_id=entity_id,
                    operation="project-setting", action="error",
                    detail=f"Failed to apply: {e}",
                ))

        return self._record(ActionResult(
            target_type=entity_type, target_path=entity_path, target_id=entity_id,
            operation="project-setting", action=action,
            detail=f"changed: {list(changes.keys())}",
            dry_run=self.client.dry_run,
        ))

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


# ---------------------------------------------------------------------------
# Operations: approval-rule
# ---------------------------------------------------------------------------


@register_operation("approval-rule")
class ApprovalRuleOperation(Operation):
    """Manage project-level merge request approval rules."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--rule-name", required=True,
                            help="Name of the approval rule (used to find/create)")
        parser.add_argument("--approvals", type=int, default=None,
                            help="Required number of approvals")
        parser.add_argument("--add-user", action="append", dest="add_users", default=[],
                            metavar="USER", help="Add user (username or ID, repeatable)")
        parser.add_argument("--remove-user", action="append", dest="remove_users", default=[],
                            metavar="USER", help="Remove user (username or ID, repeatable)")
        parser.add_argument("--unprotect", action="store_true",
                            help="Delete the approval rule")

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
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation=f"approval-rule:{rule_name}", action="error",
                detail="--approvals is required when creating a new rule",
            ))

        user_ids = self._resolve_users(self.args.add_users)

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.post(f"/projects/{project_id}/approval_rules", data={
                    "name": rule_name,
                    "approvals_required": self.args.approvals,
                    "user_ids": user_ids,
                })
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"approval-rule:{rule_name}", action="error",
                    detail=str(e),
                ))

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"approval-rule:{rule_name}", action=action,
            detail=f"created with {self.args.approvals} approvals, {len(user_ids)} users",
            dry_run=self.client.dry_run,
        ))

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
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation=f"approval-rule:{rule_name}", action="already_set",
                detail=f"approvals={current_approvals}, users={len(current_user_ids)}",
            ))

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(f"/projects/{project_id}/approval_rules/{rule_id}", data={
                    "approvals_required": desired_approvals,
                    "user_ids": list(desired_user_ids),
                })
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"approval-rule:{rule_name}", action="error",
                    detail=str(e),
                ))

        # Build change description
        changes = []
        if current_approvals != desired_approvals:
            changes.append(f"approvals: {current_approvals} -> {desired_approvals}")
        if current_user_ids != desired_user_ids:
            changes.append(f"users: {len(current_user_ids)} -> {len(desired_user_ids)}")

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"approval-rule:{rule_name}", action=action,
            detail="; ".join(changes),
            dry_run=self.client.dry_run,
        ))

    def _delete_rule(self, project_id: int, project_path: str, rule_name: str) -> ActionResult:
        """Delete an approval rule."""
        existing = self._find_rule(project_id, rule_name)

        if not existing:
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation=f"approval-rule:{rule_name}", action="already_set",
                detail="rule does not exist",
            ))

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.delete(f"/projects/{project_id}/approval_rules/{existing['id']}")
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation=f"approval-rule:{rule_name}", action="error",
                    detail=str(e),
                ))

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation=f"approval-rule:{rule_name}", action=action,
            detail="deleted approval rule",
            dry_run=self.client.dry_run,
        ))


# ---------------------------------------------------------------------------
# Operations: merge-request-setting
# ---------------------------------------------------------------------------


@register_operation("merge-request-setting")
class MergeRequestSettingOperation(Operation):
    """Configure project merge request approval settings."""

    # Field mappings from legacy API to modern API (some have inverted logic)
    # Format: legacy_field -> (modern_field, is_inverted)
    FIELD_MAPPING = {
        "reset_approvals_on_push": ("retain_approvals_on_push", True),
        "disable_overriding_approvers_per_merge_request": (
            "allow_overrides_to_approver_list_per_merge_request", True
        ),
        "merge_requests_author_approval": ("allow_author_approval", False),
        "merge_requests_disable_committers_approval": ("allow_committer_approval", True),
    }

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--approvals-before-merge", type=int, default=None,
                            help="Required approvals before merge (deprecated in newer GitLab)")
        parser.add_argument("--reset-approvals-on-push", choices=["true", "false"], default=None,
                            help="Reset approvals when new commits are pushed")
        parser.add_argument("--disable-overriding-approvers", choices=["true", "false"], default=None,
                            help="Prevent users from modifying approvers per MR")
        parser.add_argument("--merge-requests-author-approval", choices=["true", "false"], default=None,
                            help="Allow MR author to approve their own MR")
        parser.add_argument("--merge-requests-disable-committers-approval", choices=["true", "false"],
                            default=None,
                            help="Prevent committers from approving MRs they committed to")

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        # Build desired settings from args
        desired: dict[str, Any] = {}

        if self.args.approvals_before_merge is not None:
            desired["approvals_before_merge"] = self.args.approvals_before_merge
        if self.args.reset_approvals_on_push is not None:
            desired["reset_approvals_on_push"] = self.args.reset_approvals_on_push == "true"
        if self.args.disable_overriding_approvers is not None:
            desired["disable_overriding_approvers_per_merge_request"] = (
                self.args.disable_overriding_approvers == "true"
            )
        if self.args.merge_requests_author_approval is not None:
            desired["merge_requests_author_approval"] = (
                self.args.merge_requests_author_approval == "true"
            )
        if self.args.merge_requests_disable_committers_approval is not None:
            desired["merge_requests_disable_committers_approval"] = (
                self.args.merge_requests_disable_committers_approval == "true"
            )

        if not desired:
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation="merge-request-setting", action="skipped",
                detail="No settings specified",
            ))

        # Try modern API first, fall back to legacy
        result = self._try_modern_api(project_id, project_path, desired)
        if result is not None:
            return result
        return self._use_legacy_api(project_id, project_path, desired)

    def _try_modern_api(
        self, project_id: int, project_path: str, desired: dict[str, Any]
    ) -> ActionResult | None:
        """Try the modern merge_request_approval_settings API (GitLab 13.x+)."""
        endpoint = f"/projects/{project_id}/merge_request_approval_settings"

        try:
            current = self.client.get(endpoint)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.debug("Modern approval settings API not available, falling back to legacy")
                return None  # Signal to use legacy API
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation="merge-request-setting", action="error",
                detail=f"Failed to get settings: {e}",
            ))

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
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation="merge-request-setting", action="already_set",
                detail=f"keys: {list(desired.keys())}",
            ))

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                self.client.put(endpoint, data=changes)
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation="merge-request-setting", action="error",
                    detail=f"Failed to apply: {e}",
                ))

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation="merge-request-setting", action=action,
            detail=f"changed (modern API): {list(changes.keys())}",
            dry_run=self.client.dry_run,
        ))

    def _use_legacy_api(
        self, project_id: int, project_path: str, desired: dict[str, Any]
    ) -> ActionResult:
        """Use the legacy /approvals API (GitLab 12.x and earlier)."""
        endpoint = f"/projects/{project_id}/approvals"

        try:
            current = self.client.get(endpoint)
        except requests.HTTPError as e:
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation="merge-request-setting", action="error",
                detail=f"Failed to get settings: {e}",
            ))

        # Compare and find changes (legacy API uses same field names as our args)
        changes = {k: v for k, v in desired.items() if current.get(k) != v}

        if not changes:
            return self._record(ActionResult(
                target_type="project", target_path=project_path, target_id=project_id,
                operation="merge-request-setting", action="already_set",
                detail=f"keys: {list(desired.keys())}",
            ))

        action = "would_apply" if self.client.dry_run else "applied"
        if not self.client.dry_run:
            try:
                # Legacy API uses POST, not PUT!
                self.client.post(endpoint, data=changes)
            except requests.HTTPError as e:
                return self._record(ActionResult(
                    target_type="project", target_path=project_path, target_id=project_id,
                    operation="merge-request-setting", action="error",
                    detail=f"Failed to apply: {e}",
                ))

        return self._record(ActionResult(
            target_type="project", target_path=project_path, target_id=project_id,
            operation="merge-request-setting", action=action,
            detail=f"changed (legacy API): {list(changes.keys())}",
            dry_run=self.client.dry_run,
        ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gl-settings",
        description="Apply settings to GitLab groups and projects, with recursive group traversal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output results as JSON lines (to stderr)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--gitlab-url", default=None,
                        help="GitLab instance URL (default: from GITLAB_URL env or https://gitlab.com)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help=f"Maximum retry attempts for transient errors (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--filter", dest="filter_pattern", default=None,
                        help="Glob pattern to filter projects by path (e.g., 'myorg/team-*/*')")

    subparsers = parser.add_subparsers(dest="operation", required=True,
                                        help="Operation to perform")

    for name, op_cls in sorted(_operation_registry.items()):
        sub = subparsers.add_parser(name, help=op_cls.__doc__)
        sub.add_argument("target_url", help="GitLab URL of the target project or group")
        op_cls.add_arguments(sub)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve GitLab URL
    gitlab_url = args.gitlab_url or os.environ.get("GITLAB_URL", DEFAULT_GITLAB_URL)

    # Get token
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        print("ERROR: GITLAB_TOKEN environment variable is not set.", file=sys.stderr)
        return 1

    # Setup logging
    logger = setup_logging(json_mode=args.json_output, verbose=args.verbose)

    # Build client
    client = GitLabClient(base_url=gitlab_url, token=token, dry_run=args.dry_run,
                          max_retries=args.max_retries)

    # Resolve target
    logger.info(f"Resolving target: {args.target_url}")
    try:
        target = client.resolve_target(args.target_url)
    except SystemExit as e:
        logger.error(str(e))
        return 1

    logger.info(f"Resolved: {target.type.value} '{target.path}' (id={target.id})")

    if args.dry_run:
        logger.info("DRY-RUN MODE — no changes will be made")

    # Instantiate and run the operation
    op_cls = _operation_registry[args.operation]
    operation = op_cls(client=client, args=args)

    try:
        recurse(client, target, operation, filter_pattern=args.filter_pattern)
    except requests.HTTPError as e:
        logger.error(f"Fatal API error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130

    # Summary
    total = len(operation.results)
    applied = sum(1 for r in operation.results if r.action in ("applied", "would_apply"))
    already = sum(1 for r in operation.results if r.action == "already_set")
    errors = sum(1 for r in operation.results if r.action == "error")

    logger.info(f"Done: {total} targets, {applied} {'would change' if args.dry_run else 'changed'}, "
                f"{already} already set, {errors} errors")

    # Exit code: non-zero if any errors
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
