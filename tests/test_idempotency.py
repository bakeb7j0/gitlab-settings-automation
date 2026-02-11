"""Unit tests for idempotency detection in operations."""

import argparse
import sys
from pathlib import Path

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
    ApprovalRuleOperation,
    GitLabClient,
    ProjectSettingOperation,
    ProtectBranchOperation,
    ProtectTagOperation,
)


class TestProtectBranchIdempotency:
    """Tests for protect-branch idempotency."""

    @responses.activate
    def test_already_protected_same_settings(self):
        """Branch already protected with same settings returns already_set."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_branches/main",
            json={
                "name": "main",
                "push_access_levels": [{"access_level": 40}],  # maintainer
                "merge_access_levels": [{"access_level": 30}],  # developer
                "allow_force_push": False,
            },
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "already_set"
        assert len(responses.calls) == 1  # Only GET, no DELETE/POST

    @responses.activate
    def test_different_settings_updates(self):
        """Branch with different settings triggers update."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_branches/main",
            json={
                "name": "main",
                "push_access_levels": [{"access_level": 30}],  # developer (different)
                "merge_access_levels": [{"access_level": 30}],
                "allow_force_push": False,
            },
        )
        responses.add(
            responses.DELETE,
            f"{MOCK_API_URL}/projects/123/protected_branches/main",
            status=204,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_URL}/projects/123/protected_branches",
            json={"name": "main"},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "applied"
        assert len(responses.calls) == 3  # GET, DELETE, POST

    @responses.activate
    def test_not_protected_creates_new(self):
        """Unprotected branch creates new protection."""
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
        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "applied"
        assert len(responses.calls) == 2  # GET (404), POST


class TestProtectTagIdempotency:
    """Tests for protect-tag idempotency."""

    @responses.activate
    def test_already_protected_same_settings(self):
        """Tag already protected with same settings returns already_set."""
        # Note: * is URL-encoded to %2A
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_tags/v1.2.%2A",
            json={
                "name": "v1.2.*",
                "create_access_levels": [{"access_level": 40}],  # maintainer
            },
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(tag="v1.2.*", create="maintainer", unprotect=False)
        op = ProtectTagOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "already_set"
        assert len(responses.calls) == 1  # Only GET


class TestProjectSettingIdempotency:
    """Tests for project-setting idempotency."""

    @responses.activate
    def test_settings_already_match(self):
        """Settings already matching returns already_set."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={
                "id": 123,
                "visibility": "private",
                "merge_method": "ff",
            },
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(settings=["visibility=private", "merge_method=ff"])
        op = ProjectSettingOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "already_set"
        assert len(responses.calls) == 1  # Only GET

    @responses.activate
    def test_settings_different_updates(self):
        """Different settings trigger update."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={
                "id": 123,
                "visibility": "public",  # Different
                "merge_method": "merge",  # Different
            },
        )
        responses.add(
            responses.PUT,
            f"{MOCK_API_URL}/projects/123",
            json={"visibility": "private", "merge_method": "ff"},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(settings=["visibility=private", "merge_method=ff"])
        op = ProjectSettingOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "applied"
        assert len(responses.calls) == 2  # GET, PUT


class TestApprovalRuleIdempotency:
    """Tests for approval-rule idempotency."""

    @responses.activate
    def test_rule_already_exists_same_settings(self):
        """Rule with same settings returns already_set."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/approval_rules",
            json=[
                {
                    "id": 1,
                    "name": "Security Review",
                    "approvals_required": 2,
                    "users": [{"id": 100}, {"id": 101}],
                }
            ],
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(
            rule_name="Security Review",
            approvals=None,  # Not changing
            add_users=[],
            remove_users=[],
            unprotect=False,
        )
        op = ApprovalRuleOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "already_set"
        assert len(responses.calls) == 1  # Only GET

    @responses.activate
    def test_rule_different_approvals_updates(self):
        """Rule with different approval count triggers update."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/approval_rules",
            json=[
                {
                    "id": 1,
                    "name": "Security Review",
                    "approvals_required": 1,  # Different
                    "users": [],
                }
            ],
        )
        responses.add(
            responses.PUT,
            f"{MOCK_API_URL}/projects/123/approval_rules/1",
            json={"approvals_required": 2},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        args = make_args(
            rule_name="Security Review",
            approvals=2,
            add_users=[],
            remove_users=[],
            unprotect=False,
        )
        op = ApprovalRuleOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "applied"
        assert len(responses.calls) == 2  # GET, PUT
