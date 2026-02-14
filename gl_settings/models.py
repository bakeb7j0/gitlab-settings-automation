"""Data models and constants for gl-settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Constants
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


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


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
