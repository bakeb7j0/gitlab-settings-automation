"""Unit tests for the kahuna-sandbox composite operation.

The composite delegates to push-rule, protect-branch, approval-rule, and
project-setting — each already has dedicated unit tests. These tests cover:

- Happy path (all 4 sub-ops invoked in order against a greenfield project)
- Idempotency (all 4 already-set -> composite returns already_set)
- Dry-run end-to-end (no writes at any sub-op)
- Early halt on sub-op error (later sub-ops NOT invoked)
- Composite registration
"""

import argparse
import sys
from pathlib import Path

import responses

sys.path.insert(0, str(Path(__file__).parent.parent))

from gl_settings.client import GitLabClient
from gl_settings.operations import KahunaSandboxOperation, get_operation_registry
from gl_settings.operations.kahuna_sandbox import (
    DEFAULT_KAHUNA_REGEX,
    KAHUNA_APPROVAL_RULE_NAME,
    KAHUNA_BRANCH_PATTERN,
)

MOCK_GITLAB_URL = "https://gitlab.example.com"
MOCK_API_URL = f"{MOCK_GITLAB_URL}/api/v4"
PROJECT_ID = 123
PROJECT_PATH = "myorg/myproject"


def make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "dry_run": False,
        "json_output": False,
        "verbose": False,
        "gitlab_url": None,
        "max_retries": 3,
        "filter_pattern": None,
        "branch_name_regex": DEFAULT_KAHUNA_REGEX,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


PROTECTED_BRANCH_ID = 42  # mock id returned by the resolve-after-protect GET


def _mock_greenfield_project():
    """Stub GitLab responses for a project that has none of the sandbox knobs set.

    Order of HTTP calls:
      1. push-rule GET(404) -> POST
      2. protect-branch GET(404) -> POST
      3. resolve-protected-branch-id GET (kahuna-sandbox's internal lookup)
      4. approval-rule paginate GET -> POST
      5. project-setting GET -> PUT
    """
    # 1. push-rule: GET 404 (no existing rule) -> POST
    responses.add(responses.GET, f"{MOCK_API_URL}/projects/{PROJECT_ID}/push_rule", status=404)
    responses.add(
        responses.POST,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}/push_rule",
        json={"branch_name_regex": DEFAULT_KAHUNA_REGEX},
        status=201,
    )

    # 2. protect-branch: GET 404 (branch not protected) -> POST
    # protect_branch URL-encodes the pattern; "kahuna/*" becomes "kahuna%2F%2A"
    responses.add(
        responses.GET,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches/kahuna%2F%2A",
        status=404,
    )
    responses.add(
        responses.POST,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches",
        json={"id": PROTECTED_BRANCH_ID, "name": KAHUNA_BRANCH_PATTERN},
    )

    # 2b. kahuna-sandbox's internal _resolve_protected_branch_id lookup
    responses.add(
        responses.GET,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches/kahuna%2F%2A",
        json={"id": PROTECTED_BRANCH_ID, "name": KAHUNA_BRANCH_PATTERN},
    )

    # 3. approval-rule: paginate empty list -> POST create
    responses.add(
        responses.GET,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}/approval_rules",
        json=[],
    )
    responses.add(
        responses.POST,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}/approval_rules",
        json={
            "id": 1,
            "name": KAHUNA_APPROVAL_RULE_NAME,
            "approvals_required": 0,
            "protected_branches": [{"id": PROTECTED_BRANCH_ID, "name": KAHUNA_BRANCH_PATTERN}],
        },
    )

    # 4. project-setting: GET current -> PUT changes
    responses.add(
        responses.GET,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}",
        json={
            "only_allow_merge_if_pipeline_succeeds": False,
            "squash_option": "default_off",
            "merge_pipelines_enabled": False,
            "merge_trains_enabled": False,
        },
    )
    responses.add(
        responses.PUT,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}",
        json={"id": PROJECT_ID},
    )


class TestKahunaSandboxHappyPath:
    @responses.activate
    def test_all_four_sub_ops_invoked_in_order(self):
        _mock_greenfield_project()

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = KahunaSandboxOperation(client, make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "applied"
        assert result.operation == "kahuna-sandbox"
        # Total HTTP calls: 5 GETs (push-rule, protect-branch, resolve-id,
        # approval-rules, project) + 4 writes = 9
        assert len(responses.calls) == 9, [c.request.url for c in responses.calls]

        # Confirm order of writes by URL
        write_urls = [c.request.url for c in responses.calls if c.request.method != "GET"]
        assert write_urls[0].endswith(f"/projects/{PROJECT_ID}/push_rule")
        assert write_urls[1].endswith(f"/projects/{PROJECT_ID}/protected_branches")
        assert write_urls[2].endswith(f"/projects/{PROJECT_ID}/approval_rules")
        assert write_urls[3].endswith(f"/projects/{PROJECT_ID}")

    @responses.activate
    def test_approval_rule_post_is_scoped_to_kahuna_protected_branch(self):
        """CRITICAL: the approval-rule POST must include protected_branch_ids so
        the zero-approval rule is scoped to kahuna/* only and does NOT apply to
        main. If this assertion fails, main becomes unprotected.
        """
        import json

        _mock_greenfield_project()

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = KahunaSandboxOperation(client, make_args())
        op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        # Find the approval-rule POST call
        approval_post_calls = [
            c
            for c in responses.calls
            if c.request.method == "POST" and c.request.url.endswith(f"/projects/{PROJECT_ID}/approval_rules")
        ]
        assert len(approval_post_calls) == 1
        body = json.loads(approval_post_calls[0].request.body or "{}")
        assert body.get("approvals_required") == 0
        assert body.get("protected_branch_ids") == [PROTECTED_BRANCH_ID], (
            f"approval rule is not scoped to kahuna/* — would apply to all branches. body={body}"
        )


class TestKahunaSandboxIdempotency:
    @responses.activate
    def test_all_knobs_already_set_returns_already_set(self):
        # push-rule: GET returns matching regex
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/push_rule",
            json={"id": 1, "branch_name_regex": DEFAULT_KAHUNA_REGEX},
        )
        # protect-branch: GET returns matching settings (developer=30 for both).
        # Must include `id` so resolve-protected-branch-id picks it up from the
        # same endpoint (this is the protect-branch-op's existence check AND the
        # composite's id-resolution call — both hit the same URL).
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches/kahuna%2F%2A",
            json={
                "id": PROTECTED_BRANCH_ID,
                "name": KAHUNA_BRANCH_PATTERN,
                "push_access_levels": [{"access_level": 30}],
                "merge_access_levels": [{"access_level": 30}],
                "allow_force_push": False,
            },
        )
        # The composite's _resolve_protected_branch_id hits the same URL a second
        # time after protect-branch's own GET. Add a duplicate response so the
        # `responses` library can replay it.
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches/kahuna%2F%2A",
            json={
                "id": PROTECTED_BRANCH_ID,
                "name": KAHUNA_BRANCH_PATTERN,
                "push_access_levels": [{"access_level": 30}],
                "merge_access_levels": [{"access_level": 30}],
                "allow_force_push": False,
            },
        )
        # approval-rule: paginate returns the rule with 0 approvals, scoped to
        # the kahuna/* protected branch.
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/approval_rules",
            json=[
                {
                    "id": 1,
                    "name": KAHUNA_APPROVAL_RULE_NAME,
                    "approvals_required": 0,
                    "users": [],
                    "protected_branches": [{"id": PROTECTED_BRANCH_ID, "name": KAHUNA_BRANCH_PATTERN}],
                }
            ],
        )
        # project-setting: GET returns matching settings
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}",
            json={
                "only_allow_merge_if_pipeline_succeeds": True,
                "squash_option": "default_on",
                "merge_pipelines_enabled": True,
                "merge_trains_enabled": True,
            },
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = KahunaSandboxOperation(client, make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "already_set"
        # Only GETs happened, zero writes
        methods = [c.request.method for c in responses.calls]
        assert all(m == "GET" for m in methods), methods


class TestKahunaSandboxDryRun:
    @responses.activate
    def test_dry_run_no_writes_reports_would_apply(self):
        # Only GET 4 times — no writes should happen under dry-run
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/{PROJECT_ID}/push_rule", status=404)
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches/kahuna%2F%2A",
            status=404,
        )
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/{PROJECT_ID}/approval_rules", json=[])
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}",
            json={
                "only_allow_merge_if_pipeline_succeeds": False,
                "squash_option": "default_off",
                "merge_pipelines_enabled": False,
                "merge_trains_enabled": False,
            },
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", dry_run=True)
        op = KahunaSandboxOperation(client, make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "would_apply"
        assert result.dry_run is True
        methods = [c.request.method for c in responses.calls]
        assert all(m == "GET" for m in methods), f"dry-run wrote to API: {methods}"


class TestKahunaSandboxEarlyHalt:
    @responses.activate
    def test_push_rule_error_halts_composite(self):
        # push-rule GET returns 500 (not retried: max_retries=0)
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/{PROJECT_ID}/push_rule", status=500)

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=0)
        op = KahunaSandboxOperation(client, make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "error"
        assert "push-rule" in (result.detail or "")
        # Only 1 HTTP call happened: the failing push-rule GET. Downstream sub-ops
        # never got invoked.
        assert len(responses.calls) == 1

    @responses.activate
    def test_protect_branch_error_halts_before_approval_rule(self):
        # push-rule succeeds (idempotent path, already set)
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/push_rule",
            json={"id": 1, "branch_name_regex": DEFAULT_KAHUNA_REGEX},
        )
        # protect-branch GET then POST-fails with 500
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches/kahuna%2F%2A",
            status=404,
        )
        responses.add(
            responses.POST,
            f"{MOCK_API_URL}/projects/{PROJECT_ID}/protected_branches",
            status=500,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=0)
        op = KahunaSandboxOperation(client, make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "error"
        # push-rule GET, protect-branch GET, protect-branch POST = 3 calls total,
        # no approval-rule or project-setting calls.
        assert len(responses.calls) == 3


class TestKahunaSandboxRegistration:
    def test_kahuna_sandbox_registered_in_registry(self):
        registry = get_operation_registry()
        assert "kahuna-sandbox" in registry
        assert registry["kahuna-sandbox"] is KahunaSandboxOperation
