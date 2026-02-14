"""CLI entry point for gl-settings."""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys

import requests

# Ensure all operations are registered by importing the operations package
import gl_settings.operations  # noqa: F401
from gl_settings.client import GitLabClient
from gl_settings.logging_utils import setup_logging
from gl_settings.models import DEFAULT_GITLAB_URL, DEFAULT_MAX_RETRIES, Target, TargetType
from gl_settings.operations import Operation, get_operation_registry


def recurse(client: GitLabClient, target: Target, operation: Operation, filter_pattern: str | None = None) -> None:
    """Walk the target tree and apply the operation, optionally filtering projects."""
    import logging

    logger = logging.getLogger("gl-settings")

    if target.type == TargetType.PROJECT:
        # Apply filter to direct project targets
        if filter_pattern and not fnmatch.fnmatch(target.path, filter_pattern):
            logger.debug(f"Skipping project (filter): {target.path}")
            return
        operation.apply_to_project(target.id, target.path)
        return

    # It's a group
    if operation.applies_to_group():
        operation.apply_to_group(target.id, target.path)

    # Recurse into subgroups (groups are always traversed, filter applies only to projects)
    for subgroup in client.get_subgroups(target.id):
        sub_target = Target(
            type=TargetType.GROUP,
            id=subgroup["id"],
            path=subgroup["full_path"],
            name=subgroup["name"],
            web_url=subgroup["web_url"],
        )
        recurse(client, sub_target, operation, filter_pattern)

    # Apply to direct child projects (with filtering)
    for project in client.get_group_projects(target.id):
        project_path = project["path_with_namespace"]
        if filter_pattern and not fnmatch.fnmatch(project_path, filter_pattern):
            logger.debug(f"Skipping project (filter): {project_path}")
            continue
        operation.apply_to_project(project["id"], project_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gl-settings",
        description="Apply settings to GitLab groups and projects, with recursive group traversal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
gl-settings: A composable CLI tool for applying settings to GitLab groups and projects.

Designed to be called by automation scripts. Resolves a GitLab URL to a group or project,
then applies the specified operation - recursing into child groups/projects as needed.

Environment:
    GITLAB_TOKEN - GitLab Personal Access Token (required)
    GITLAB_URL   - GitLab instance URL (default: https://gitlab.com)

Examples:
    # Protect a branch on a single project
    gl-settings protect-branch https://gitlab.com/myorg/myproject \\
        --branch release/1.2 --push no_access --merge no_access

    # Protect a tag pattern across all projects in a group
    gl-settings protect-tag https://gitlab.com/myorg \\
        --tag "v1.2.*" --create maintainer

    # Dry-run to see what would happen
    gl-settings protect-branch https://gitlab.com/myorg \\
        --branch main --push maintainer --merge developer --dry-run

    # JSON output for machine parsing
    gl-settings protect-branch https://gitlab.com/myorg/myproject \\
        --branch main --push no_access --merge no_access --json

    # Initialize a project with standard settings
    gl-settings init-project https://gitlab.com/myorg/myproject
""",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument(
        "--json", action="store_true", dest="json_output", help="Output results as JSON lines (to stderr)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--gitlab-url", default=None, help="GitLab instance URL (default: from GITLAB_URL env or https://gitlab.com)"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum retry attempts for transient errors (default: {DEFAULT_MAX_RETRIES})",
    )
    parser.add_argument(
        "--filter",
        dest="filter_pattern",
        default=None,
        help="Glob pattern to filter projects by path (e.g., 'myorg/team-*/*')",
    )

    subparsers = parser.add_subparsers(dest="operation", required=True, help="Operation to perform")

    registry = get_operation_registry()
    for name, op_cls in sorted(registry.items()):
        sub = subparsers.add_parser(name, help=op_cls.__doc__)
        sub.add_argument("target_url", help="GitLab URL of the target project or group")
        op_cls.add_arguments(sub)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve GitLab URL
    gitlab_url = args.gitlab_url or os.environ.get("GITLAB_URL", DEFAULT_GITLAB_URL)

    # Get token
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        print("ERROR: GITLAB_TOKEN environment variable is not set.", file=sys.stderr)
        return 1

    # Setup logging
    logger = setup_logging(json_mode=args.json_output, verbose=args.verbose)

    # Build client
    client = GitLabClient(base_url=gitlab_url, token=token, dry_run=args.dry_run, max_retries=args.max_retries)

    # Resolve target
    logger.info(f"Resolving target: {args.target_url}")
    try:
        target = client.resolve_target(args.target_url)
    except SystemExit as e:
        logger.error(str(e))
        return 1

    logger.info(f"Resolved: {target.type.value} '{target.path}' (id={target.id})")

    if args.dry_run:
        logger.info("DRY-RUN MODE - no changes will be made")

    # Instantiate and run the operation
    registry = get_operation_registry()
    op_cls = registry[args.operation]
    operation = op_cls(client=client, args=args)

    try:
        recurse(client, target, operation, filter_pattern=args.filter_pattern)
    except requests.HTTPError as e:
        logger.error(f"Fatal API error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130

    # Summary
    total = len(operation.results)
    applied = sum(1 for r in operation.results if r.action in ("applied", "would_apply"))
    already = sum(1 for r in operation.results if r.action == "already_set")
    errors = sum(1 for r in operation.results if r.action == "error")

    logger.info(
        f"Done: {total} targets, {applied} {'would change' if args.dry_run else 'changed'}, "
        f"{already} already set, {errors} errors"
    )

    # Exit code: non-zero if any errors
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
