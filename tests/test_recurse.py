"""Integration tests for recursion and --filter flag."""

import argparse
import sys
from pathlib import Path

import pytest
import responses

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Constants
MOCK_GITLAB_URL = "https://gitlab.example.com"
MOCK_API_URL = f"{MOCK_GITLAB_URL}/api/v4"


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

from gl_settings import (
    GitLabClient,
    Target,
    TargetType,
    ProtectBranchOperation,
    recurse,
)


class TestRecursion:
    """Tests for group recursion."""

    @responses.activate
    def test_recurse_visits_all_projects(self, nested_group_structure):
        """Recursion visits all projects in nested groups."""
        struct = nested_group_structure

        # Setup mock responses for group traversal
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/1/subgroups",
            json=struct["subgroups"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/1/projects",
            json=struct["root_projects"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/2/subgroups",
            json=[],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/2/projects",
            json=struct["team_a_projects"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/3/subgroups",
            json=[],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/3/projects",
            json=struct["team_b_projects"],
            headers={"x-total-pages": "1"},
        )

        # Setup mock responses for branch protection checks
        for project_id in [10, 11, 12]:
            responses.add(
                responses.GET,
                f"{MOCK_API_URL}/projects/{project_id}/protected_branches/main",
                status=404,
            )
            responses.add(
                responses.POST,
                f"{MOCK_API_URL}/projects/{project_id}/protected_branches",
                json={"name": "main"},
            )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        root_target = Target(
            type=TargetType.GROUP,
            id=1,
            path="org",
            name="org",
            web_url=f"{MOCK_GITLAB_URL}/org",
        )

        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)

        recurse(client, root_target, op)

        # Should have 3 projects processed
        assert len(op.results) == 3


class TestFilterFlag:
    """Tests for --filter flag functionality."""

    @responses.activate
    def test_filter_excludes_non_matching_projects(self, nested_group_structure):
        """Filter pattern excludes projects that don't match."""
        struct = nested_group_structure

        # Setup mock responses for group traversal
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/1/subgroups",
            json=struct["subgroups"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/1/projects",
            json=struct["root_projects"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/2/subgroups",
            json=[],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/2/projects",
            json=struct["team_a_projects"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/3/subgroups",
            json=[],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/3/projects",
            json=struct["team_b_projects"],
            headers={"x-total-pages": "1"},
        )

        # Only team-a projects should be processed (matching "org/team-a/*")
        for project_id in [11, 12]:
            responses.add(
                responses.GET,
                f"{MOCK_API_URL}/projects/{project_id}/protected_branches/main",
                status=404,
            )
            responses.add(
                responses.POST,
                f"{MOCK_API_URL}/projects/{project_id}/protected_branches",
                json={"name": "main"},
            )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        root_target = Target(
            type=TargetType.GROUP,
            id=1,
            path="org",
            name="org",
            web_url=f"{MOCK_GITLAB_URL}/org",
        )

        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)

        # Filter to only team-a projects
        recurse(client, root_target, op, filter_pattern="org/team-a/*")

        # Should have only 2 projects processed (team-a/service, team-a/frontend)
        assert len(op.results) == 2
        for result in op.results:
            assert "team-a" in result.target_path

    @responses.activate
    def test_filter_applies_to_direct_project_target(self):
        """Filter applies even when target is a project directly."""
        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        project_target = Target(
            type=TargetType.PROJECT,
            id=123,
            path="myorg/other-project",  # Doesn't match filter
            name="other-project",
            web_url=f"{MOCK_GITLAB_URL}/myorg/other-project",
        )

        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)

        # Filter for "myorg/myproject*" should skip "myorg/other-project"
        recurse(client, project_target, op, filter_pattern="myorg/myproject*")

        # Project should be skipped - no results
        assert len(op.results) == 0

    @responses.activate
    def test_filter_matches_direct_project_target(self):
        """Filter includes matching project when target is a project directly."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_branches/main",
            status=404,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_URL}/projects/123/protected_branches",
            json={"name": "main"},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        project_target = Target(
            type=TargetType.PROJECT,
            id=123,
            path="myorg/myproject",  # Matches filter
            name="myproject",
            web_url=f"{MOCK_GITLAB_URL}/myorg/myproject",
        )

        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)

        recurse(client, project_target, op, filter_pattern="myorg/myproject*")

        # Project should be processed
        assert len(op.results) == 1

    @responses.activate
    def test_groups_always_traversed_regardless_of_filter(self, nested_group_structure):
        """Groups are always traversed even with a filter that wouldn't match the group path."""
        struct = nested_group_structure

        # Setup mock responses - all groups should be traversed
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/1/subgroups",
            json=struct["subgroups"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/1/projects",
            json=struct["root_projects"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/2/subgroups",
            json=[],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/2/projects",
            json=struct["team_a_projects"],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/3/subgroups",
            json=[],
            headers={"x-total-pages": "1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/groups/3/projects",
            json=struct["team_b_projects"],
            headers={"x-total-pages": "1"},
        )

        # Only one project should match the filter
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/11/protected_branches/main",
            status=404,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_URL}/projects/11/protected_branches",
            json={"name": "main"},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        root_target = Target(
            type=TargetType.GROUP,
            id=1,
            path="org",
            name="org",
            web_url=f"{MOCK_GITLAB_URL}/org",
        )

        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)

        # Filter for a very specific project
        recurse(client, root_target, op, filter_pattern="org/team-a/service")

        # Only 1 project should match
        assert len(op.results) == 1
        assert op.results[0].target_path == "org/team-a/service"

        # But all subgroups should have been traversed (verify by checking call count)
        # We should have: 3 subgroup GETs + 3 project GETs + 1 branch GET + 1 branch POST
        subgroup_calls = [c for c in responses.calls if "/subgroups" in c.request.url]
        # Note: project list calls have /groups/N/projects (may have query params)
        project_list_calls = [c for c in responses.calls if "/groups/" in c.request.url and "/projects" in c.request.url]
        assert len(subgroup_calls) == 3  # All groups traversed
        assert len(project_list_calls) == 3  # All groups' projects queried
