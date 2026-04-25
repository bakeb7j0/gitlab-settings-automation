"""Unit tests for the push-rule operation."""

import argparse
import sys
from pathlib import Path

import responses

sys.path.insert(0, str(Path(__file__).parent.parent))

from gl_settings.client import GitLabClient
from gl_settings.operations import PushRuleOperation

MOCK_GITLAB_URL = "https://gitlab.example.com"
MOCK_API_URL = f"{MOCK_GITLAB_URL}/api/v4"
KAHUNA_REGEX = r"^(main|develop|kahuna/.*|feature/.*|fix/.*)$"


def make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "dry_run": False,
        "json_output": False,
        "verbose": False,
        "gitlab_url": None,
        "max_retries": 3,
        "filter_pattern": None,
        "branch_name_regex": KAHUNA_REGEX,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestPushRuleCreation:
    """First-time push rule creation: GET 404 -> POST."""

    @responses.activate
    def test_no_existing_rule_posts_new(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            status=404,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"branch_name_regex": KAHUNA_REGEX},
            status=201,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "applied"
        assert len(responses.calls) == 2  # GET(404), POST


class TestPushRuleIdempotency:
    """Existing rule with same regex -> skip."""

    @responses.activate
    def test_same_regex_is_already_set(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"id": 1, "branch_name_regex": KAHUNA_REGEX},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "already_set"
        assert len(responses.calls) == 1  # GET only, no write

    @responses.activate
    def test_different_regex_puts_update(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"id": 1, "branch_name_regex": "^(main|develop)$"},
        )
        responses.add(
            responses.PUT,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"id": 1, "branch_name_regex": KAHUNA_REGEX},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "applied"
        assert len(responses.calls) == 2  # GET, PUT


class TestPushRuleDryRun:
    """Dry-run should GET but never write."""

    @responses.activate
    def test_dry_run_no_existing_rule(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            status=404,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1  # GET only

    @responses.activate
    def test_dry_run_drift_detected(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"id": 1, "branch_name_regex": "^(main|develop)$"},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "would_apply"
        assert result.dry_run is True
        assert len(responses.calls) == 1  # GET only, no PUT

    @responses.activate
    def test_dry_run_idempotent_still_skips(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"id": 1, "branch_name_regex": KAHUNA_REGEX},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "already_set"
        assert len(responses.calls) == 1


class TestPushRuleErrors:
    """Non-404 errors from GET and POST/PUT should surface as action=error."""

    @responses.activate
    def test_get_500_returns_error(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            status=500,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=0)
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "error"
        assert "Failed to get push rule" in (result.detail or "")

    @responses.activate
    def test_post_failure_returns_error(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            status=404,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_URL}/projects/123/push_rule",
            status=403,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=0)
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "error"
        assert "Failed to apply push rule" in (result.detail or "")

    @responses.activate
    def test_put_failure_returns_error(self):
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123/push_rule",
            json={"id": 1, "branch_name_regex": "^(main|develop)$"},
        )
        responses.add(
            responses.PUT,
            f"{MOCK_API_URL}/projects/123/push_rule",
            status=403,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=0)
        op = PushRuleOperation(client, make_args())
        result = op.apply_to_project(123, "myorg/myproject")

        assert result.action == "error"
        assert "Failed to apply push rule" in (result.detail or "")


class TestPushRuleGroupBehavior:
    """push-rule is per-project only; applies_to_group must be False."""

    def test_applies_to_group_false(self):
        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = PushRuleOperation(client, make_args())
        assert op.applies_to_group() is False
