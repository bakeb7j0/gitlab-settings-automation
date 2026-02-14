"""Shared test fixtures for gl-settings tests."""

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from gl_settings.client import GitLabClient
from gl_settings.models import Target, TargetType

# Constants for use in tests - pytest makes conftest.py fixtures available,
# but these constants need to be imported directly from tests
MOCK_GITLAB_URL = "https://gitlab.example.com"
MOCK_API_URL = f"{MOCK_GITLAB_URL}/api/v4"


@pytest.fixture
def mock_client():
    """GitLabClient pointing at mock server."""
    return GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=False)


@pytest.fixture
def dry_run_client():
    """GitLabClient in dry-run mode."""
    return GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)


@pytest.fixture
def sample_project() -> dict[str, Any]:
    """Sample project API response."""
    return {
        "id": 123,
        "name": "my-project",
        "path_with_namespace": "myorg/my-project",
        "web_url": f"{MOCK_GITLAB_URL}/myorg/my-project",
    }


@pytest.fixture
def sample_group() -> dict[str, Any]:
    """Sample group API response."""
    return {
        "id": 456,
        "name": "myorg",
        "full_path": "myorg",
        "web_url": f"{MOCK_GITLAB_URL}/myorg",
    }


@pytest.fixture
def nested_group_structure() -> dict[str, Any]:
    """Nested groups with projects for recursion tests."""
    return {
        "root": {"id": 1, "name": "org", "full_path": "org", "web_url": f"{MOCK_GITLAB_URL}/org"},
        "subgroups": [
            {
                "id": 2,
                "name": "team-a",
                "full_path": "org/team-a",
                "web_url": f"{MOCK_GITLAB_URL}/org/team-a",
            },
            {
                "id": 3,
                "name": "team-b",
                "full_path": "org/team-b",
                "web_url": f"{MOCK_GITLAB_URL}/org/team-b",
            },
        ],
        "root_projects": [
            {"id": 10, "path_with_namespace": "org/shared"},
        ],
        "team_a_projects": [
            {"id": 11, "path_with_namespace": "org/team-a/service"},
            {"id": 12, "path_with_namespace": "org/team-a/frontend"},
        ],
        "team_b_projects": [],
    }


@pytest.fixture
def sample_target_project(sample_project) -> Target:
    """Sample Target object for a project."""
    return Target(
        type=TargetType.PROJECT,
        id=sample_project["id"],
        path=sample_project["path_with_namespace"],
        name=sample_project["name"],
        web_url=sample_project["web_url"],
    )


@pytest.fixture
def sample_target_group(sample_group) -> Target:
    """Sample Target object for a group."""
    return Target(
        type=TargetType.GROUP,
        id=sample_group["id"],
        path=sample_group["full_path"],
        name=sample_group["name"],
        web_url=sample_group["web_url"],
    )


def make_args(**kwargs) -> argparse.Namespace:
    """Helper to create argparse.Namespace with default values."""
    defaults = {
        "dry_run": False,
        "json_output": False,
        "verbose": False,
        "gitlab_url": None,
        "max_retries": 3,
        "filter_pattern": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)
