# gl-settings CLI Extension Plan

## Context

The gl-settings CLI tool applies settings to GitLab groups/projects with recursive traversal. It has two working operations (`protect-branch`, `protect-tag`) and needs to be extended into a production-ready tool with additional operations, error resilience, filtering, and proper packaging.

## Implementation Order

| Phase | Feature | Rationale |
|-------|---------|-----------|
| 1 | Retry Logic | Foundation - all features benefit from resilient API calls |
| 2 | `--filter` Flag | Enables safer testing against large groups |
| 3 | `project-setting` Operation | Most generally useful, establishes group-level pattern |
| 4 | `approval-rule` Operation | Builds on phase 3 patterns |
| 5 | `merge-request-setting` Operation | Most complex (dual-API support) |
| 6 | Test Suite | Validates all features |
| 7 | Packaging | Finalization |

---

## Phase 1: Retry Logic

**File:** `gl_settings.py`

**Changes:**
1. Add `import time` and constants:
   ```python
   DEFAULT_MAX_RETRIES = 3
   RETRY_BACKOFF_FACTOR = 0.5
   RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
   ```

2. Update `GitLabClient.__init__` to accept `max_retries` parameter

3. Replace `_request()` method (lines 159-166) with retry loop:
   - Retry on 429 and 5xx responses
   - Use `Retry-After` header for 429s
   - Exponential backoff: `RETRY_BACKOFF_FACTOR * (2 ** attempt)`
   - Also retry on `ConnectionError`

4. Add `--max-retries` global flag in `build_parser()` (line ~614)

---

## Phase 2: `--filter` Flag

**File:** `gl_settings.py`

**Changes:**
1. Add `import fnmatch`

2. Add global flag in `build_parser()`:
   ```python
   parser.add_argument("--filter", dest="filter_pattern", default=None,
                       help="Glob pattern to filter projects by path_with_namespace")
   ```

3. Update `recurse()` signature to accept `filter_pattern: str | None = None`

4. Add filter checks before `apply_to_project()` calls:
   ```python
   if filter_pattern and not fnmatch.fnmatch(project_path, filter_pattern):
       logger.debug(f"Skipping project (filter): {project_path}")
       continue
   ```

5. Update `main()` to pass `filter_pattern=args.filter_pattern` to `recurse()`

---

## Phase 3: `project-setting` Operation

**File:** `gl_settings.py` (after `ProtectTagOperation`, line ~593)

**Design:**
- `--setting key=value` (repeatable via `action="append"`)
- Split on first `=` to allow values containing `=`
- Type coercion: `true/false` → bool, numeric strings → int/float
- Works on both projects (`PUT /projects/:id`) and groups (`PUT /groups/:id`)
- Idempotency: GET current settings, compare each key, only PUT if changed

**Implementation:**
```python
@register_operation("project-setting")
class ProjectSettingOperation(Operation):
    def applies_to_group(self) -> bool:
        return True

    def _apply_settings(self, entity_type, entity_id, entity_path, get_endpoint, put_endpoint):
        # Parse settings, GET current, compare, PUT if changed
```

---

## Phase 4: `approval-rule` Operation

**File:** `gl_settings.py`

**Design:**
- `--rule-name` (required) - identifies rule
- `--approvals` (int) - required approvals count
- `--add-user` / `--remove-user` (repeatable) - accepts usernames or IDs
- `--unprotect` - delete the rule
- API: `GET/POST/PUT/DELETE /projects/:id/approval_rules`

**Additional client method:**
```python
def resolve_user(self, identifier: str) -> int:
    """Resolve username or ID to numeric user ID via GET /users?username="""
```

**Idempotency:** Find rule by name, compare approvals count and user list

---

## Phase 5: `merge-request-setting` Operation

**File:** `gl_settings.py`

**Design:**
- `--approvals-before-merge`, `--reset-approvals-on-push`, `--disable-overriding-approvers`
- Dual-API support for GitLab version compatibility:
  1. Try modern API: `PUT /projects/:id/merge_request_approval_settings`
  2. Fall back to legacy: `POST /projects/:id/approvals`
- Log which API was used at debug level

---

## Phase 6: Test Suite

**New files:**
```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures: mock_client, sample_project, sample_group
├── test_url_parsing.py  # Unit tests for _extract_path_from_url()
├── test_idempotency.py  # Unit tests for already_set detection
├── test_operations.py   # Integration tests with responses library
└── test_dry_run.py      # Verify no POST/PUT/DELETE in dry-run
```

**Key test cases:**
- URL parsing: full URLs, bare paths, `.git` suffix, `/-/` paths
- Idempotency: same settings → `already_set`, different → `applied`
- Recursion: nested groups, filter pattern matching
- Dry-run: only GET calls, no mutations

---

## Phase 7: Packaging

**New files:**

**`pyproject.toml`:**
- `requests>=2.28.0` dependency
- `pytest`, `responses`, `ruff`, `mypy` dev dependencies
- Entry point: `gl-settings = gl_settings:main`
- Python >= 3.10

**`Makefile`:**
```makefile
install:      pip install .
install-dev:  pip install -e ".[dev]"
lint:         ruff check
test:         pytest tests/ -v
```

---

## Files to Modify/Create

| File | Action |
|------|--------|
| `gl_settings.py` | Modify - add retry, filter, 3 new operations |
| `pyproject.toml` | Create - packaging config |
| `Makefile` | Create - build targets |
| `tests/conftest.py` | Create - shared fixtures |
| `tests/test_url_parsing.py` | Create |
| `tests/test_idempotency.py` | Create |
| `tests/test_operations.py` | Create |
| `tests/test_dry_run.py` | Create |

---

## Verification

After implementation:
1. `make install-dev` - install with dev deps
2. `make test` - run test suite
3. `make lint` - check code style
4. Manual tests:
   ```bash
   # Dry-run project-setting
   python gl_settings.py --dry-run project-setting https://gitlab.com/myorg \
       --setting visibility=private --setting merge_method=ff

   # Filter test
   python gl_settings.py --dry-run --filter "myorg/team-*" protect-branch \
       https://gitlab.com/myorg --branch main --push maintainer --merge developer
   ```
