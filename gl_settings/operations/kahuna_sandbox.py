"""Kahuna-sandbox composite operation.

Applies the per-project settings that establish a KAHUNA integration-branch
sandbox: flight-MRs into ``kahuna/*`` merge fast on CI-green with zero
human-approval churn, while main retains full protection. The composite is
a thin delegator — it builds per-sub-op argument namespaces and dispatches
to the existing single-purpose operations so all idempotency, dry-run, and
logging logic is inherited rather than reimplemented.

Sub-ops applied, in order:

1. ``push-rule`` — widen ``branch_name_regex`` to accept ``kahuna/*``.
2. ``protect-branch`` — protect ``kahuna/*`` pattern (prerequisite for 3).
3. ``approval-rule`` — per-branch rule with ``approvals_required=0`` scoped
   to the protected ``kahuna/*`` pattern.
4. ``project-setting`` — enable CI-gate, squash-on-merge, and merge trains
   so flight-MRs batch into a single pipeline run per train.
"""

from __future__ import annotations

import argparse
import urllib.parse

import requests

from gl_settings.models import ActionResult
from gl_settings.operations.approval_rule import ApprovalRuleOperation
from gl_settings.operations.base import Operation, register_operation
from gl_settings.operations.project_setting import ProjectSettingOperation
from gl_settings.operations.protect_branch import ProtectBranchOperation
from gl_settings.operations.push_rule import PushRuleOperation

# Default regex wide enough to accept main, develop, feature/*, fix/*, and kahuna/*.
# Callers who already have a regex can override via --branch-name-regex.
DEFAULT_KAHUNA_REGEX = r"^(main|develop|kahuna/.*|feature/.*|fix/.*)$"
KAHUNA_BRANCH_PATTERN = "kahuna/*"
KAHUNA_APPROVAL_RULE_NAME = "kahuna-zero-approvals"

# Sandbox-enabling project settings.
SANDBOX_PROJECT_SETTINGS: dict[str, bool | str] = {
    "only_allow_merge_if_pipeline_succeeds": True,
    "squash_option": "default_on",
    "merge_pipelines_enabled": True,
    "merge_trains_enabled": True,
}


@register_operation("kahuna-sandbox")
class KahunaSandboxOperation(Operation):
    """Apply the KAHUNA sandbox configuration to a project (composite)."""

    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--branch-name-regex",
            default=DEFAULT_KAHUNA_REGEX,
            metavar="REGEX",
            help=(
                "Regex for push-rule. Must include 'kahuna/.*' or flights can't push. "
                f"Default: {DEFAULT_KAHUNA_REGEX!r}"
            ),
        )

    def apply_to_project(self, project_id: int, project_path: str) -> ActionResult:
        sub_results: list[ActionResult] = []

        # Each sub-op gets its own Namespace with only the fields it reads.
        # Global flags that the base class / logging rely on (dry_run, verbose,
        # json_output) are carried on self.client/self.args, not copied.

        # 1. push-rule — widen branch_name_regex
        sub_results.append(
            self._run_sub(
                PushRuleOperation,
                argparse.Namespace(branch_name_regex=self.args.branch_name_regex),
                project_id,
                project_path,
            )
        )
        if _is_error(sub_results[-1]):
            return self._summarize(project_id, project_path, sub_results)

        # 2. protect-branch — kahuna/* pattern (prerequisite for approval rule)
        sub_results.append(
            self._run_sub(
                ProtectBranchOperation,
                argparse.Namespace(
                    branch=KAHUNA_BRANCH_PATTERN,
                    push="developer",  # flights push here; must be at least developer
                    merge="developer",
                    unprotect=False,
                    allow_force_push=False,
                ),
                project_id,
                project_path,
            )
        )
        if _is_error(sub_results[-1]):
            return self._summarize(project_id, project_path, sub_results)

        # 3. approval-rule — 0 approvals on kahuna/*, scoped to the protected branch.
        # Requires the numeric ID of the protected-branch created in step 2 so the
        # rule doesn't accidentally apply project-wide (including to main).
        protected_branch_id = self._resolve_protected_branch_id(project_id, project_path, KAHUNA_BRANCH_PATTERN)
        if protected_branch_id is None:
            sub_results.append(
                self._record(
                    ActionResult(
                        target_type="project",
                        target_path=project_path,
                        target_id=project_id,
                        operation="approval-rule:kahuna-zero-approvals",
                        action="error",
                        detail=(
                            f"cannot scope approval rule: protected branch {KAHUNA_BRANCH_PATTERN!r} "
                            "not found after protect-branch (would unsafely apply rule project-wide)"
                        ),
                    )
                )
            )
            return self._summarize(project_id, project_path, sub_results)

        sub_results.append(
            self._run_sub(
                ApprovalRuleOperation,
                argparse.Namespace(
                    rule_name=KAHUNA_APPROVAL_RULE_NAME,
                    approvals=0,
                    add_users=[],
                    remove_users=[],
                    unprotect=False,
                    protected_branch_ids=[protected_branch_id],
                ),
                project_id,
                project_path,
            )
        )
        if _is_error(sub_results[-1]):
            return self._summarize(project_id, project_path, sub_results)

        # 4. project-setting — CI-gate + squash + merge trains
        sub_results.append(
            self._run_sub(
                ProjectSettingOperation,
                argparse.Namespace(
                    settings=[f"{k}={_serialize(v)}" for k, v in SANDBOX_PROJECT_SETTINGS.items()],
                ),
                project_id,
                project_path,
            )
        )

        return self._summarize(project_id, project_path, sub_results)

    def _resolve_protected_branch_id(self, project_id: int, project_path: str, branch_pattern: str) -> int | None:
        """Resolve the numeric ID of a protected-branch entry by its name/pattern.

        Returns None if the branch is not found. In dry-run mode the protected
        branch may not actually exist (step 2 emitted ``would_apply``), so we
        return a sentinel ``0`` that approval-rule's dry-run path will accept
        without writing.
        """
        if self.client.dry_run:
            return 0

        encoded = urllib.parse.quote(branch_pattern, safe="")
        try:
            pb = self.client.get(f"/projects/{project_id}/protected_branches/{encoded}")
            return int(pb["id"])
        except (requests.HTTPError, KeyError, TypeError, ValueError):
            return None

    def _run_sub(
        self,
        sub_cls: type[Operation],
        sub_args: argparse.Namespace,
        project_id: int,
        project_path: str,
    ) -> ActionResult:
        """Instantiate a sub-op with the shared client and delegated args, apply it.

        Each sub-op handles its own GET/diff/PUT, dry-run, and idempotency via
        ``Operation._record``, so its result is already logged by the time we
        receive it back. We return it so the composite can decide whether to
        continue or halt.
        """
        sub_op = sub_cls(self.client, sub_args)
        return sub_op.apply_to_project(project_id, project_path)

    def _summarize(
        self,
        project_id: int,
        project_path: str,
        sub_results: list[ActionResult],
    ) -> ActionResult:
        """Reduce per-sub-op results to a single composite ActionResult.

        Precedence: error > applied/would_apply > already_set.
        """
        actions = [r.action for r in sub_results]
        if "error" in actions:
            overall = "error"
            failing = next(r for r in sub_results if r.action == "error")
            detail = f"failed at '{failing.operation}': {failing.detail}"
        elif any(a in ("applied", "would_apply") for a in actions):
            overall = "would_apply" if self.client.dry_run else "applied"
            applied = [r.operation for r in sub_results if r.action in ("applied", "would_apply")]
            detail = f"applied: {applied}"
        else:
            overall = "already_set"
            detail = f"all {len(sub_results)} knobs already matched"

        return self._record(
            ActionResult(
                target_type="project",
                target_path=project_path,
                target_id=project_id,
                operation="kahuna-sandbox",
                action=overall,
                detail=detail,
                dry_run=self.client.dry_run,
            )
        )


def _is_error(result: ActionResult) -> bool:
    return result.action == "error"


def _serialize(value: bool | str) -> str:
    """Serialize a Python value to the string form ProjectSettingOperation coerces."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
