# gl-settings

A composable CLI tool for applying settings to GitLab groups and projects with recursive group traversal. Designed to be called by automation scripts.

## Quick Start

```bash
# Set your GitLab PAT
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"

# Optional: non-gitlab.com instances
export GITLAB_URL="https://gitlab.mycompany.com"

# Dry-run a branch protection across a whole group
python3 gl_settings.py --dry-run protect-branch https://gitlab.com/myorg \
    --branch release/1.2 --push no_access --merge no_access

# Apply it for real
python3 gl_settings.py protect-branch https://gitlab.com/myorg/myproject \
    --branch release/1.2 --push no_access --merge no_access
```

## Requirements

- Python 3.10+
- `requests` library (`pip install requests`)

## How It Works

```
target URL → resolve (project or group?)
  ├─ project → apply operation directly
  └─ group   → apply to group (if applicable)
               ├─ recurse into subgroups
               └─ apply to each child project
```

The tool resolves any GitLab web URL (or bare path) to determine whether it's a project or group, then applies the specified operation. For groups, it recursively walks all subgroups and projects.

## Operations

### `protect-branch`

Protect a branch or update its protection settings.

```bash
gl_settings.py protect-branch <target-url> \
    --branch <name-or-pattern> \
    --push <access-level> \
    --merge <access-level> \
    [--allow-force-push] \
    [--unprotect]
```

### `protect-tag`

Protect a tag pattern or update its protection settings.

```bash
gl_settings.py protect-tag <target-url> \
    --tag <name-or-pattern> \
    --create <access-level>
    [--unprotect]
```

### Access Levels

| Name | Value | Description |
|------|-------|-------------|
| `no_access` | 0 | No access |
| `minimal` | 5 | Minimal access |
| `guest` | 10 | Guest |
| `reporter` | 20 | Reporter |
| `developer` | 30 | Developer |
| `maintainer` | 40 | Maintainer |
| `owner` | 50 | Owner |
| `admin` | 60 | Admin |

## Global Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Show what would happen without making changes |
| `--json` | Emit results as JSON lines to stderr |
| `--verbose` / `-v` | Enable debug logging |
| `--gitlab-url` | Override the GitLab instance URL |

## Idempotency

All operations are idempotent. Running the same command twice will report `already_set` on the second run. This makes it safe to use in automation that may be retried.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All operations succeeded (or already set) |
| `1` | One or more errors occurred |
| `130` | Interrupted (Ctrl+C) |

## Composing Automation

The tool is designed as a building block. See `examples/release-lockdown.sh` for a meta-script that combines multiple `gl-settings` calls to lock down an LTS release.

## Adding New Operations

1. Create a new class inheriting from `Operation`
2. Decorate with `@register_operation("your-operation-name")`
3. Implement `add_arguments()` and `apply_to_project()`
4. Optionally implement `applies_to_group()` and `apply_to_group()`

The operation is automatically available as a CLI subcommand.
