"""Safety tests for dry-run mode - ensures no mutations occur."""

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


from gl_settings.client import GitLabClient
from gl_settings.operations import (
    ApprovalRuleOperation,
    MergeRequestSettingOperation,
    ProjectSettingOperation,
    ProtectBranchOperation,
    ProtectTagOperation,
)


class TestDryRunProtectBranch:
    """Dry-run tests for protect-branch operation."""

    @responses.activate
    def test_dry_run_no_post_when_creating(self):
        """Dry-run should not POST when branch is unprotected."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_branches/main",
            status=404,
        )
        # NO POST registered - test fails if POST is attempted

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"

    @responses.activate
    def test_dry_run_no_delete_when_updating(self):
        """Dry-run should not DELETE/POST when updating branch protection."""
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
        # NO DELETE or POST registered - test fails if they're attempted

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op = ProtectBranchOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"


class TestDryRunProtectTag:
    """Dry-run tests for protect-tag operation."""

    @responses.activate
    def test_dry_run_no_post_when_creating(self):
        """Dry-run should not POST when tag is unprotected."""
        # Note: * is URL-encoded to %2A
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_tags/v1.0.%2A",
            status=404,
        )
        # NO POST registered

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(tag="v1.0.*", create="maintainer", unprotect=False)
        op = ProtectTagOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"


class TestDryRunProjectSetting:
    """Dry-run tests for project-setting operation."""

    @responses.activate
    def test_dry_run_no_put_when_changing(self):
        """Dry-run should not PUT when settings differ."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={"id": 123, "visibility": "public"},
        )
        # NO PUT registered

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(settings=["visibility=private"])
        op = ProjectSettingOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"


class TestDryRunApprovalRule:
    """Dry-run tests for approval-rule operation."""

    @responses.activate
    def test_dry_run_no_post_when_creating_rule(self):
        """Dry-run should not POST when creating new rule."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/approval_rules",
            json=[],  # No existing rules
        )
        # NO POST registered

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(
            rule_name="Security Review",
            approvals=2,
            add_users=[],
            remove_users=[],
            unprotect=False,
        )
        op = ApprovalRuleOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"

    @responses.activate
    def test_dry_run_no_delete_when_removing_rule(self):
        """Dry-run should not DELETE when unprotecting."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/approval_rules",
            json=[{"id": 1, "name": "Security Review", "approvals_required": 2, "users": []}],
        )
        # NO DELETE registered

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(
            rule_name="Security Review",
            approvals=None,
            add_users=[],
            remove_users=[],
            unprotect=True,
        )
        op = ApprovalRuleOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"


class TestDryRunMergeRequestSetting:
    """Dry-run tests for merge-request-setting operation."""

    @responses.activate
    def test_dry_run_no_put_modern_api(self):
        """Dry-run should not PUT on modern API."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/merge_request_approval_settings",
            json={
                "retain_approvals_on_push": True,  # reset_approvals_on_push=false equivalent
            },
        )
        # NO PUT registered

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(
            approvals_before_merge=None,
            reset_approvals_on_push="true",  # Wants to change to reset (retain=false)
            disable_overriding_approvers=None,
            merge_requests_author_approval=None,
            merge_requests_disable_committers_approval=None,
        )
        op = MergeRequestSettingOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"

    @responses.activate
    def test_dry_run_no_post_legacy_api(self):
        """Dry-run should not POST on legacy API fallback."""
        # Modern API returns 404
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/merge_request_approval_settings",
            status=404,
        )
        # Legacy API works
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/approvals",
            json={"approvals_before_merge": 1},
        )
        # NO POST registered

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        args = make_args(
            approvals_before_merge=2,  # Different
            reset_approvals_on_push=None,
            disable_overriding_approvers=None,
            merge_requests_author_approval=None,
            merge_requests_disable_committers_approval=None,
        )
        op = MergeRequestSettingOperation(client, args)
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        # Should have 2 GETs (modern 404, then legacy)
        assert len(responses.calls) == 2
        for call in responses.calls:
            assert call.request.method == "GET"


class TestDryRunOnlyGets:
    """Verify dry-run mode never uses mutating methods."""

    @responses.activate
    def test_dry_run_only_uses_get_method(self):
        """Comprehensive check that dry-run only uses GET."""
        # Setup responses for various endpoints that might be called
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/protected_branches/main",
            status=404,
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={"id": 123, "visibility": "public"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/approval_rules",
            json=[],
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)

        # Test protect-branch
        args1 = make_args(branch="main", push="maintainer", merge="developer", unprotect=False, allow_force_push=False)
        op1 = ProtectBranchOperation(client, args1)
        op1.apply_to_project(123, "myorg/myproject")

        # Test project-setting
        args2 = make_args(settings=["visibility=private"])
        op2 = ProjectSettingOperation(client, args2)
        op2.apply_to_project(123, "myorg/myproject")

        # Test approval-rule
        args3 = make_args(rule_name="Test", approvals=1, add_users=[], remove_users=[], unprotect=False)
        op3 = ApprovalRuleOperation(client, args3)
        op3.apply_to_project(123, "myorg/myproject")

        # Verify ALL calls were GET
        for call in responses.calls:
            assert call.request.method == "GET", f"Non-GET method used in dry-run: {call.request.method}"
