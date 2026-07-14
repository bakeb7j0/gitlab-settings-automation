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


def _mock_ci_config(ci_config: str) -> None:
    """Register the step-5 advisory's raw `.gitlab-ci.yml` GET (#34).

    ci_config: 'mr' → admits merge-request pipelines; 'branch_only' → no MR rule;
    'missing' → 404 (no file).
    """
    url = f"{MOCK_API_URL}/projects/{PROJECT_ID}/repository/files/.gitlab-ci.yml/raw"
    if ci_config == "missing":
        responses.add(responses.GET, url, status=404)
        return
    if ci_config == "branch_only":
        body = "test:\n  script: echo hi\n  rules:\n    - if: '$CI_COMMIT_BRANCH'\n"
    else:  # 'mr'
        body = (
            "workflow:\n"
            "  rules:\n"
            "    - if: '$CI_PIPELINE_SOURCE == \"merge_request_event\"'\n"
            "    - if: '$CI_COMMIT_BRANCH'\n"
        )
    responses.add(responses.GET, url, body=body, content_type="text/plain")


def _mock_greenfield_project(ci_config: str = "mr"):
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

    # 4. project-setting: GET current -> PUT changes.
    # Current state models the REAL migration case, and it is deliberately WRONG in
    # BOTH directions so the PUT body must carry both keys:
    #   trains ON            -> must be turned OFF
    #   merged-results OFF   -> must be turned ON   (the #33 regression: #31 wrongly
    #                           disabled these, silently blinding the wave gate)
    # If a fixture value already matched the desired value, that key would never
    # appear in the PUT body and the guard below would assert nothing.
    responses.add(
        responses.GET,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}",
        json={
            "only_allow_merge_if_pipeline_succeeds": False,
            "squash_option": "default_off",
            "merge_pipelines_enabled": False,
            "merge_trains_enabled": True,
            # Read again by the step-5 advisory to resolve the ref for .gitlab-ci.yml.
            "default_branch": "main",
        },
    )
    responses.add(
        responses.PUT,
        f"{MOCK_API_URL}/projects/{PROJECT_ID}",
        json={"id": PROJECT_ID},
    )

    # 5. advisory (read-only): the .gitlab-ci.yml raw content. Default 'mr' ADMITS
    # merge-request pipelines, so the greenfield happy path emits no warning.
    _mock_ci_config(ci_config)


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
        # approval-rules, project) + 4 writes + 2 read-only advisory GETs
        # (project again for default_branch, .gitlab-ci.yml raw) = 11.
        assert len(responses.calls) == 11, [c.request.url for c in responses.calls]
        # The greenfield fixture's CI config admits MR pipelines → no warning.
        assert result.warnings == [], result.warnings

    @responses.activate
    def test_warns_when_ci_config_has_no_mr_pipelines(self):
        """#34 AC: merge_pipelines_enabled is applied, but the project's
        .gitlab-ci.yml admits no merge-request pipelines → WARN, and the operation
        still SUCCEEDS (the CI config is not this tool's to own)."""
        _mock_greenfield_project(ci_config="branch_only")

        op = KahunaSandboxOperation(GitLabClient(MOCK_GITLAB_URL, "test-token"), make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "applied"  # NOT failed — advisory never blocks
        assert len(result.warnings) == 1, result.warnings
        w = result.warnings[0]
        assert "merge-request-pipeline rule" in w
        assert "branch HEAD" in w  # names the actual failure mode
        assert "gl-settings#33" in w
        # And it surfaces in the serialized envelope.
        assert result.to_dict()["warnings"] == result.warnings

    @responses.activate
    def test_no_warning_when_mr_pipelines_configured(self):
        """#34 AC: a config WITH a merge_request_event rule → no warning."""
        _mock_greenfield_project(ci_config="mr")

        op = KahunaSandboxOperation(GitLabClient(MOCK_GITLAB_URL, "test-token"), make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "applied"
        assert result.warnings == []
        # Absent warnings must NOT appear in the serialized envelope (back-compat).
        assert "warnings" not in result.to_dict()

    @responses.activate
    def test_unverifiable_ci_config_emits_distinct_note(self):
        """#34 AC: a 404 on .gitlab-ci.yml → a DISTINCT 'could not verify' note,
        never a false all-clear (which would let a blind gate look fine)."""
        _mock_greenfield_project(ci_config="missing")

        op = KahunaSandboxOperation(GitLabClient(MOCK_GITLAB_URL, "test-token"), make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "applied"
        assert len(result.warnings) == 1, result.warnings
        note = result.warnings[0]
        assert "could not verify" in note.lower()
        assert "no .gitlab-ci.yml" in note
        # It is a NOTE, not the definite "no MR rule found" warning — the two are
        # distinct so an operator does not misread "absent CI" as "misconfigured CI".
        assert "shows no merge-request-pipeline rule" not in note

        # Confirm order of writes by URL
        write_urls = [c.request.url for c in responses.calls if c.request.method != "GET"]
        assert write_urls[0].endswith(f"/projects/{PROJECT_ID}/push_rule")
        assert write_urls[1].endswith(f"/projects/{PROJECT_ID}/protected_branches")
        assert write_urls[2].endswith(f"/projects/{PROJECT_ID}/approval_rules")
        assert write_urls[3].endswith(f"/projects/{PROJECT_ID}")

    @responses.activate
    def test_project_setting_put_disables_trains_but_keeps_merged_results(self):
        """CRITICAL: merge TRAINS and MERGED-RESULTS pipelines are different
        features and must move in OPPOSITE directions. This test exists because
        #31 conflated them, turned both off, and silently blinded the wave gate
        (#33).

          merge_trains_enabled    -> False   (a train serializes MRs; we don't need one)
          merge_pipelines_enabled -> True    (produces the MERGE-RESULT pipeline the
                                              KAHUNA trust gate validates instead of the
                                              branch HEAD -- mcp-server-sdlc#452. Turn it
                                              off and the gate keeps passing while grading
                                              the wrong commit. No error. Just blind.)

        The CI gate and squash-on-merge must survive untouched.
        """
        import json

        _mock_greenfield_project()

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = KahunaSandboxOperation(client, make_args())
        op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        put_calls = [
            c
            for c in responses.calls
            if c.request.method == "PUT" and c.request.url.rstrip("/").endswith(f"/projects/{PROJECT_ID}")
        ]
        assert len(put_calls) == 1, [c.request.url for c in responses.calls]

        body = json.loads(put_calls[0].request.body or "{}")
        assert body["merge_trains_enabled"] is False, body
        # NOT False. These are different features -- see the docstring.
        assert body["merge_pipelines_enabled"] is True, body
        # The CI gate is NOT what we removed — it must survive.
        assert body["only_allow_merge_if_pipeline_succeeds"] is True, body
        assert body["squash_option"] == "default_on", body

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
                "merge_trains_enabled": False,
                "default_branch": "main",
            },
        )
        # step-5 advisory (read-only): admits MR pipelines → no warning.
        _mock_ci_config("mr")

        client = GitLabClient(MOCK_GITLAB_URL, "test-token")
        op = KahunaSandboxOperation(client, make_args())
        result = op.apply_to_project(PROJECT_ID, PROJECT_PATH)

        assert result.action == "already_set"
        assert result.warnings == []  # the advisory found a valid config
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
                "default_branch": "main",
            },
        )
        # step-5 advisory is read-only, so it runs even under dry-run (GETs only).
        _mock_ci_config("mr")

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


class TestMergeRequestPipelineScan:
    """Direct tests for the raw .gitlab-ci.yml scan (#34). It is a TEXT scan, not a
    YAML parse, and must ignore comments — a full parse would be no more
    authoritative anyway, since `include:` can pull rules from files we don't fetch."""

    def _admits(self, content: str) -> bool:
        return KahunaSandboxOperation._admits_merge_request_pipelines(content)

    def test_workflow_rule_admits(self):
        assert self._admits("workflow:\n  rules:\n    - if: '$CI_PIPELINE_SOURCE == \"merge_request_event\"'\n")

    def test_legacy_only_merge_requests_admits(self):
        assert self._admits("test:\n  only:\n    - merge_requests\n")

    def test_branch_only_config_does_not_admit(self):
        assert not self._admits("test:\n  rules:\n    - if: '$CI_COMMIT_BRANCH'\n")

    def test_a_commented_marker_does_not_count(self):
        # The marker appears only in a comment — it admits nothing.
        assert not self._admits("# TODO: add a merge_request_event rule later\ntest:\n  script: echo hi\n")

    def test_trailing_comment_still_counts_the_real_rule(self):
        assert self._admits(
            "workflow:\n  rules:\n    - if: '$CI_PIPELINE_SOURCE == \"merge_request_event\"'  # MR pipelines\n"
        )

    def test_empty_config_does_not_admit(self):
        assert not self._admits("")

    def test_accepted_blind_spot_negated_marker_reads_as_admitting(self):
        # DOCUMENTED LIMITATION, not a bug: the whole-file substring scan cannot see
        # that this marker is negated by `when: never`, so it reads as admitting. A
        # YAML parse would not help (include: defeats it), and over-warning is the
        # only alternative. This test pins the behavior so a future reader treats it
        # as a known trade-off (documented in the README) rather than "fixing" it
        # into flakiness. If this ever becomes fixable, this assertion should flip.
        negated = "workflow:\n  rules:\n    - if: '$CI_PIPELINE_SOURCE == \"merge_request_event\"'\n      when: never\n"
        assert self._admits(negated)  # scanned as admit — the accepted false-positive
