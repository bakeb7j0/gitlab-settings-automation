# gl-settings

A composable CLI tool for applying settings to GitLab groups and projects with recursive group traversal. Designed for automation scripts, CI/CD pipelines, and bulk configuration management.

## Quick Start

```bash
# Install
pip install git+https://github.com/bakeb7j0/gitlab-settings-automation.git

# Set your GitLab Personal Access Token (needs api scope)
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"

# Optional: for self-hosted GitLab instances
export GITLAB_URL="https://gitlab.mycompany.com"

# Always dry-run first to see what would change
gl-settings --dry-run protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer

# Apply for real
gl-settings protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer
```

## Installation

### From PyPI (coming soon)

```bash
pip install gl-settings
```

### From source

```bash
# User install
pip install git+https://github.com/bakeb7j0/gitlab-settings-automation.git

# Development install
git clone https://github.com/bakeb7j0/gitlab-settings-automation.git
cd gitlab-settings-automation
make install-dev
```

### Requirements

- Python 3.10+
- GitLab Personal Access Token with `api` scope

## How It Works

```
gl-settings <operation> <target-url> [options]
                           │
                           ▼
              ┌─────────────────────────┐
              │  Resolve target URL     │
              │  (project or group?)    │
              └───────────┬─────────────┘
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
    ┌──────────┐                   ┌──────────┐
    │ Project  │                   │  Group   │
    │          │                   │          │
    │ Apply    │                   │ Apply to │
    │ directly │                   │ group    │
    └──────────┘                   └────┬─────┘
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                   ┌────────────┐              ┌────────────┐
                   │ Recurse    │              │ Apply to   │
                   │ subgroups  │              │ projects   │
                   └────────────┘              └────────────┘
```

The tool accepts any GitLab URL format:
- Full URL: `https://gitlab.com/myorg/myproject`
- With path: `https://gitlab.com/myorg/myproject/-/settings`
- Bare path: `myorg/myproject`

## Operations

### `protect-branch`

Protect a branch or wildcard pattern with specific access levels.

```bash
gl-settings protect-branch <target> --branch <pattern> --push <level> --merge <level>
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--branch` | Yes | Branch name or wildcard (e.g., `main`, `release/*`) |
| `--push` | No | Who can push (default: `maintainer`) |
| `--merge` | No | Who can merge (default: `maintainer`) |
| `--allow-force-push` | No | Allow force push to this branch |
| `--unprotect` | No | Remove protection instead of adding it |

**Examples:**

```bash
# Lock down main branch - only maintainers can push/merge
gl-settings protect-branch https://gitlab.com/myorg/myproject \
    --branch main --push maintainer --merge maintainer

# Protect all release branches - no direct push, developers can merge
gl-settings protect-branch https://gitlab.com/myorg \
    --branch "release/*" --push no_access --merge developer

# Remove branch protection
gl-settings protect-branch https://gitlab.com/myorg/myproject \
    --branch main --unprotect
```

---

### `protect-tag`

Protect tag patterns to control who can create tags.

```bash
gl-settings protect-tag <target> --tag <pattern> --create <level>
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--tag` | Yes | Tag pattern (e.g., `v*`, `release-*`) |
| `--create` | No | Who can create matching tags (default: `maintainer`) |
| `--unprotect` | No | Remove protection instead of adding it |

**Examples:**

```bash
# Only maintainers can create version tags
gl-settings protect-tag https://gitlab.com/myorg \
    --tag "v*" --create maintainer

# Developers can create feature tags
gl-settings protect-tag https://gitlab.com/myorg/myproject \
    --tag "feature-*" --create developer
```

---

### `project-setting`

Set any project or group setting via key=value pairs. Works with any setting from the [GitLab Projects API](https://docs.gitlab.com/ee/api/projects.html#edit-project) or [Groups API](https://docs.gitlab.com/ee/api/groups.html#update-group).

```bash
gl-settings project-setting <target> --setting key=value [--setting key2=value2 ...]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--setting` | Yes | Setting in `key=value` format (repeatable) |

Values are automatically converted: `true`/`false` → boolean, numbers → int/float.

**Examples:**

```bash
# Make all projects in a group private
gl-settings project-setting https://gitlab.com/myorg \
    --setting visibility=private

# Configure merge settings
gl-settings project-setting https://gitlab.com/myorg/myproject \
    --setting merge_method=ff \
    --setting only_allow_merge_if_pipeline_succeeds=true \
    --setting only_allow_merge_if_all_discussions_are_resolved=true

# Disable features across a group
gl-settings project-setting https://gitlab.com/myorg \
    --setting issues_enabled=false \
    --setting wiki_enabled=false

# Set default branch
gl-settings project-setting https://gitlab.com/myorg \
    --setting default_branch=main
```

---

### `approval-rule`

Manage merge request approval rules - create, update, or delete rules with specific approvers.

```bash
gl-settings approval-rule <target> --rule-name <name> [options]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--rule-name` | Yes | Name of the approval rule |
| `--approvals` | For new | Required number of approvals |
| `--add-user` | No | Add user as approver (username or ID, repeatable) |
| `--remove-user` | No | Remove user from approvers (repeatable) |
| `--unprotect` | No | Delete the approval rule |

**Examples:**

```bash
# Require 2 security team approvals
gl-settings approval-rule https://gitlab.com/myorg \
    --rule-name "Security Review" \
    --approvals 2 \
    --add-user security-lead \
    --add-user security-engineer

# Update required approvals
gl-settings approval-rule https://gitlab.com/myorg/myproject \
    --rule-name "Security Review" \
    --approvals 3

# Add a new approver to existing rule
gl-settings approval-rule https://gitlab.com/myorg/myproject \
    --rule-name "Security Review" \
    --add-user new-security-member

# Delete an approval rule
gl-settings approval-rule https://gitlab.com/myorg \
    --rule-name "Old Rule" --unprotect
```

---

### `merge-request-setting`

Configure merge request approval settings. Supports both modern GitLab (13.x+) and legacy APIs.

```bash
gl-settings merge-request-setting <target> [options]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--approvals-before-merge` | No | Required approvals before merge |
| `--reset-approvals-on-push` | No | Reset approvals when new commits pushed (`true`/`false`) |
| `--disable-overriding-approvers` | No | Prevent changing approvers per MR (`true`/`false`) |
| `--merge-requests-author-approval` | No | Allow authors to approve own MRs (`true`/`false`) |
| `--merge-requests-disable-committers-approval` | No | Prevent committers from approving (`true`/`false`) |

**Examples:**

```bash
# Strict approval settings for compliance
gl-settings merge-request-setting https://gitlab.com/myorg \
    --reset-approvals-on-push true \
    --disable-overriding-approvers true \
    --merge-requests-author-approval false \
    --merge-requests-disable-committers-approval true

# Relaxed settings for internal projects
gl-settings merge-request-setting https://gitlab.com/myorg/internal \
    --reset-approvals-on-push false \
    --merge-requests-author-approval true
```

---

## Global Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview changes without applying them |
| `--filter PATTERN` | Only apply to projects matching glob pattern |
| `--max-retries N` | Retry failed API calls (default: 3) |
| `--json` | Output results as JSON lines (for scripting) |
| `--verbose` / `-v` | Enable debug logging |
| `--gitlab-url URL` | Override GitLab instance URL |

### Using `--filter`

The `--filter` flag accepts glob patterns to target specific projects within a group:

```bash
# Only affect team-a's projects
gl-settings --filter "myorg/team-a/*" protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer

# Only affect frontend projects
gl-settings --filter "*/frontend" project-setting https://gitlab.com/myorg \
    --setting ci_config_path=.gitlab/ci/frontend.yml

# Exclude test repositories
gl-settings --filter "myorg/[!test]*" protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer
```

### Using `--json`

Get machine-readable output for scripting:

```bash
gl-settings --json protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer 2>&1 | jq .
```

Output:
```json
{"target_type": "project", "target_path": "myorg/service-a", "target_id": 123, "operation": "protect-branch:main", "action": "applied"}
{"target_type": "project", "target_path": "myorg/service-b", "target_id": 124, "operation": "protect-branch:main", "action": "already_set"}
```

---

## Access Levels

Used with `--push`, `--merge`, and `--create` flags:

| Level | Value | Description |
|-------|-------|-------------|
| `no_access` | 0 | No one (lock the branch/tag) |
| `developer` | 30 | Developers and above |
| `maintainer` | 40 | Maintainers and above |
| `admin` | 60 | Only administrators |

---

## Real-World Examples

### Lock Down a Release Branch

When an LTS release goes into maintenance mode, lock it down completely:

```bash
#!/bin/bash
# release-lockdown.sh

RELEASE_BRANCH="release/1.2"
TAG_PREFIX="v1.2.*"
GROUP_URL="https://gitlab.com/myorg"

# Step 1: No one can push or merge to the release branch
gl-settings protect-branch "$GROUP_URL" \
    --branch "$RELEASE_BRANCH" \
    --push no_access \
    --merge no_access

# Step 2: Only maintainers can create release tags
gl-settings protect-tag "$GROUP_URL" \
    --tag "$TAG_PREFIX" \
    --create maintainer

# Step 3: Require security review for any changes
gl-settings approval-rule "$GROUP_URL" \
    --rule-name "Security Review" \
    --approvals 2
```

### Enforce Compliance Settings Org-Wide

```bash
#!/bin/bash
# compliance-settings.sh

GROUP_URL="https://gitlab.com/myorg"

# Require pipeline success before merge
gl-settings project-setting "$GROUP_URL" \
    --setting only_allow_merge_if_pipeline_succeeds=true \
    --setting only_allow_merge_if_all_discussions_are_resolved=true

# Strict approval settings
gl-settings merge-request-setting "$GROUP_URL" \
    --reset-approvals-on-push true \
    --disable-overriding-approvers true \
    --merge-requests-author-approval false

# Protect main branch everywhere
gl-settings protect-branch "$GROUP_URL" \
    --branch main \
    --push maintainer \
    --merge developer
```

### Configure Team-Specific Settings

```bash
#!/bin/bash
# team-setup.sh

# Backend team: strict settings
gl-settings --filter "myorg/backend-*" project-setting https://gitlab.com/myorg \
    --setting merge_method=ff \
    --setting squash_option=always

# Frontend team: allow squash
gl-settings --filter "myorg/frontend-*" project-setting https://gitlab.com/myorg \
    --setting merge_method=merge \
    --setting squash_option=default_on

# Infrastructure: require 2 approvals
gl-settings --filter "myorg/infra-*" approval-rule https://gitlab.com/myorg \
    --rule-name "Infrastructure Review" \
    --approvals 2
```

### CI/CD Pipeline Integration

```yaml
# .gitlab-ci.yml
enforce-settings:
  stage: deploy
  image: python:3.12-slim
  script:
    - pip install git+https://github.com/bakeb7j0/gitlab-settings-automation.git
    - gl-settings protect-branch $CI_PROJECT_URL
        --branch main --push maintainer --merge developer
    - gl-settings protect-tag $CI_PROJECT_URL
        --tag "v*" --create maintainer
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  variables:
    GITLAB_TOKEN: $GL_SETTINGS_TOKEN
```

```yaml
# GitHub Actions (.github/workflows/gitlab-settings.yml)
name: Enforce GitLab Settings
on:
  schedule:
    - cron: '0 0 * * *'  # Daily
  workflow_dispatch:

jobs:
  enforce:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install gl-settings
        run: pip install git+https://github.com/bakeb7j0/gitlab-settings-automation.git

      - name: Enforce branch protection
        env:
          GITLAB_TOKEN: ${{ secrets.GITLAB_TOKEN }}
        run: |
          gl-settings protect-branch https://gitlab.com/myorg \
            --branch main --push maintainer --merge developer
```

---

## Idempotency

All operations are idempotent - running the same command twice is safe:

```bash
$ gl-settings protect-branch https://gitlab.com/myorg/proj --branch main --push maintainer --merge developer
[INFO   ] ✓ [project] myorg/proj: protect-branch:main → applied

$ gl-settings protect-branch https://gitlab.com/myorg/proj --branch main --push maintainer --merge developer
[INFO   ] · [project] myorg/proj: protect-branch:main → already_set
```

This makes it safe to run in automation that may be retried.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All operations succeeded (or already set) |
| `1` | One or more errors occurred |
| `130` | Interrupted (Ctrl+C) |

---

## Troubleshooting

### "GITLAB_TOKEN environment variable is not set"

```bash
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"
```

The token needs `api` scope. Create one at GitLab → Settings → Access Tokens.

### "Could not resolve 'xxx' as a project or group"

- Check the URL/path is correct
- Verify your token has access to the project/group
- For private groups, ensure the token owner is a member

### "403 Forbidden" errors

Your token may lack permissions. Required access levels:
- Branch/tag protection: Maintainer
- Project settings: Maintainer (some settings require Owner)
- Approval rules: Maintainer

### Rate limiting (429 errors)

The tool automatically retries with exponential backoff. For large groups, you may need to increase retries:

```bash
gl-settings --max-retries 5 protect-branch https://gitlab.com/large-org ...
```

### Testing changes safely

Always use `--dry-run` first:

```bash
gl-settings --dry-run protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer
```

Use `--filter` to test on a subset:

```bash
gl-settings --filter "myorg/test-*" protect-branch https://gitlab.com/myorg \
    --branch main --push maintainer --merge developer
```

---

## Development

```bash
make install-dev  # Install with dev dependencies
make test         # Run tests (55 tests)
make lint         # Check code style (ruff)
make format       # Auto-format code
make typecheck    # Run type checker (mypy)
make clean        # Remove build artifacts
```

## License

MIT
