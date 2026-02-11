# Integration Test Plan — gl-settings CLI

## Overview

This test plan defines systematic integration tests for the `gl-settings` CLI tool against a real GitLab instance. These tests validate actual API interactions, not mocked responses.

**Objectives:**
1. Verify all 5 operations work correctly against GitLab
2. Confirm idempotency (running twice produces `already_set`)
3. Test group recursion and `--filter` flag
4. Validate `--dry-run` makes no changes
5. Verify error handling for invalid inputs
6. Ensure `--json` output is parseable

---

## Test Environment

### Requirements

| Requirement | Description |
|-------------|-------------|
| GitLab Access | Personal Access Token with `api` scope |
| Test Target | GitLab group with at least 2 projects (one nested) |
| Permissions | Maintainer or Owner on test target |
| Tools | `gl-settings`, `glab` CLI (for verification), `jq` |

### Environment Variables

```bash
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"
export GL_TEST_GROUP="testtarget"                    # Top-level group
export GL_TEST_PROJECT="testtarget/targetproject1"  # Single project for isolated tests
export GL_TEST_NESTED="testtarget/internalgroup/targetproject2"  # Nested project
```

### Test Target Structure

```
testtarget/                          (GL_TEST_GROUP)
├── targetproject1                   (GL_TEST_PROJECT)
└── internalgroup/
    └── targetproject2               (GL_TEST_NESTED)
```

---

## Test Categories

### Category 1: Operation Correctness

Each operation must be tested for:
- **Apply**: Setting is correctly applied to GitLab
- **Idempotency**: Running again returns `already_set`
- **Dry-run**: No changes made, output shows `would_apply`
- **Revert**: Can undo the change

| Test ID | Operation | Script |
|---------|-----------|--------|
| OP-01 | protect-branch | `test-protect-branch.sh` |
| OP-02 | protect-tag | `test-protect-tag.sh` |
| OP-03 | project-setting | `test-project-setting.sh` |
| OP-04 | approval-rule | `test-approval-rule.sh` |
| OP-05 | merge-request-setting | `test-merge-request-setting.sh` |

### Category 2: Scope & Recursion

| Test ID | Scenario | Script |
|---------|----------|--------|
| REC-01 | Apply to single project | (included in OP-* tests) |
| REC-02 | Apply to group (recurse to all projects) | `test-recursion.sh` |
| REC-03 | Apply with `--filter` (subset of projects) | `test-recursion.sh` |
| REC-04 | Filter excludes non-matching projects | `test-recursion.sh` |

### Category 3: Idempotency

| Test ID | Scenario | Script |
|---------|----------|--------|
| IDEM-01 | First run applies change | `test-idempotency.sh` |
| IDEM-02 | Second run returns `already_set` | `test-idempotency.sh` |
| IDEM-03 | Change value, re-run applies new value | `test-idempotency.sh` |

### Category 4: Output Modes

| Test ID | Scenario | Script |
|---------|----------|--------|
| OUT-01 | Normal output includes status indicators | (all tests) |
| OUT-02 | `--json` output is valid JSON | `test-json-output.sh` |
| OUT-03 | `--json` includes all expected fields | `test-json-output.sh` |
| OUT-04 | `--verbose` shows debug info | (manual verification) |

### Category 5: Error Handling

| Test ID | Scenario | Expected | Script |
|---------|----------|----------|--------|
| ERR-01 | Invalid project URL | Error message, exit 1 | `test-error-handling.sh` |
| ERR-02 | Invalid group URL | Error message, exit 1 | `test-error-handling.sh` |
| ERR-03 | Missing GITLAB_TOKEN | Error message, exit 1 | `test-error-handling.sh` |
| ERR-04 | Invalid access level | Error message, exit 1 | `test-error-handling.sh` |
| ERR-05 | Nonexistent branch (protect) | Succeeds (creates protection) | `test-error-handling.sh` |
| ERR-06 | Permission denied (403) | Error message, exit 1 | `test-error-handling.sh` |

### Category 6: Edge Cases

| Test ID | Scenario | Script |
|---------|----------|--------|
| EDGE-01 | Branch name with slash: `release/1.0` | `test-edge-cases.sh` |
| EDGE-02 | Tag pattern with wildcard: `v1.2.*` | `test-edge-cases.sh` |
| EDGE-03 | Setting value with `=`: `description=a=b=c` | `test-edge-cases.sh` |
| EDGE-04 | Unicode in rule name | `test-edge-cases.sh` |
| EDGE-05 | Very long branch name | `test-edge-cases.sh` |

---

## Test Procedures

### General Test Pattern

Each test follows this structure:

```bash
# 1. SETUP - Ensure known starting state
# 2. ACT - Run gl-settings command
# 3. VERIFY - Check GitLab state using glab/API
# 4. CLEANUP - Revert to original state
# 5. REPORT - Output PASS/FAIL
```

### Verification Methods

| What to Verify | How |
|----------------|-----|
| Branch protection | `glab api projects/:id/protected_branches/:branch` |
| Tag protection | `glab api projects/:id/protected_tags/:tag` |
| Project settings | `glab api projects/:id` |
| Approval rules | `glab api projects/:id/approval_rules` |
| MR settings | `glab api projects/:id/approval_settings` |

### Pass/Fail Criteria

| Condition | Result |
|-----------|--------|
| Command exits 0 AND GitLab state matches expected | **PASS** |
| Command exits non-zero when it should succeed | **FAIL** |
| Command exits 0 but GitLab state is wrong | **FAIL** |
| Command exits non-zero for expected error case | **PASS** |
| Dry-run modifies GitLab state | **FAIL** |

---

## Script Inventory

| Script | Purpose |
|--------|---------|
| `setup.sh` | Create test branches/tags, set baseline state |
| `teardown.sh` | Remove test artifacts, reset to clean state |
| `run-all.sh` | Execute all tests, report summary |
| `lib.sh` | Shared functions (assertions, API helpers) |
| `test-protect-branch.sh` | OP-01: Branch protection tests |
| `test-protect-tag.sh` | OP-02: Tag protection tests |
| `test-project-setting.sh` | OP-03: Project settings tests |
| `test-approval-rule.sh` | OP-04: Approval rule tests |
| `test-merge-request-setting.sh` | OP-05: MR settings tests |
| `test-recursion.sh` | REC-*: Group recursion and filter tests |
| `test-idempotency.sh` | IDEM-*: Idempotency verification |
| `test-json-output.sh` | OUT-*: JSON output validation |
| `test-error-handling.sh` | ERR-*: Error condition tests |
| `test-edge-cases.sh` | EDGE-*: Edge case tests |

---

## Execution

### Quick Smoke Test

```bash
cd tests/integration
./setup.sh
./test-protect-branch.sh  # Just one operation
./teardown.sh
```

### Full Test Suite

```bash
cd tests/integration
./run-all.sh
```

### Expected Output

```
=== gl-settings Integration Tests ===
Environment: https://gitlab.com/testtarget

[SETUP] Creating test branches and tags...
[SETUP] Done.

[OP-01] protect-branch
  - Apply protection .................... PASS
  - Idempotency check ................... PASS
  - Dry-run safety ...................... PASS
  - Revert .............................. PASS

[OP-02] protect-tag
  ...

=== Summary ===
Total: 42 | Passed: 42 | Failed: 0
```

---

## Test Data

### Branch Protection Levels

| Test | Branch | Push | Merge |
|------|--------|------|-------|
| Default | `main` | maintainer | maintainer |
| Locked | `main` | no_access | no_access |
| Open | `main` | developer | developer |

### Tag Protection Levels

| Test | Pattern | Create |
|------|---------|--------|
| Default | `v*` | maintainer |
| Locked | `v*` | no_access |
| Open | `v*` | developer |

### Project Settings

| Test | Setting | Value |
|------|---------|-------|
| Visibility | `visibility` | `private` / `internal` |
| Merge method | `merge_method` | `ff` / `merge` |
| Pipeline required | `only_allow_merge_if_pipeline_succeeds` | `true` / `false` |

### Approval Rules

| Test | Rule Name | Approvals |
|------|-----------|-----------|
| Create | `Test Rule` | 2 |
| Update | `Test Rule` | 3 |
| Delete | `Test Rule` | (removed) |

---

## Known Limitations

1. **Rate limiting** - Tests may trigger GitLab rate limits if run repeatedly
2. **Permission tests** - ERR-06 requires a token with limited permissions (manual test)
3. **Approval rules** - Require GitLab Premium/Ultimate for some features
4. **User resolution** - `--add-user` tests need valid usernames in the target instance

---

## Maintenance

- **After adding new operation**: Add corresponding `test-<operation>.sh`
- **After adding new flag**: Add tests to relevant scripts
- **After changing API behavior**: Update verification methods

