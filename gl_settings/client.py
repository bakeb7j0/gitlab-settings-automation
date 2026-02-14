"""GitLab API client with pagination and retry support."""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any

import requests

from gl_settings.models import (
    API_V4,
    DEFAULT_MAX_RETRIES,
    PER_PAGE,
    RETRY_BACKOFF_FACTOR,
    RETRYABLE_STATUS_CODES,
    Target,
    TargetType,
)


class GitLabClient:
    """Thin wrapper around GitLab REST API v4 with pagination support and retry logic."""

    def __init__(self, base_url: str, token: str, dry_run: bool = False, max_retries: int = DEFAULT_MAX_RETRIES):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}{API_V4}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "PRIVATE-TOKEN": token,
                "Content-Type": "application/json",
            }
        )
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
                    self.logger.warning(f"Retryable error {resp.status_code}, waiting {wait_time:.1f}s before retry")
                    time.sleep(wait_time)
                    continue

                if resp.status_code >= 400:
                    self.logger.error(f"API error {resp.status_code}: {resp.text[:500]}")
                resp.raise_for_status()
                return resp

            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = RETRY_BACKOFF_FACTOR * (2**attempt)
                    self.logger.warning(f"Connection error, retrying in {wait_time:.1f}s: {e}")
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
        return RETRY_BACKOFF_FACTOR * (2**attempt)

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
                raise SystemExit(f"ERROR: Could not resolve '{url}' as a project or group.") from None
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

    def get_project(self, project_id: int) -> dict:
        """Get project details by ID."""
        return self.get(f"/projects/{project_id}")

    def get_project_by_path(self, path: str) -> dict:
        """Get project details by path."""
        encoded_path = urllib.parse.quote(path, safe="")
        return self.get(f"/projects/{encoded_path}")
