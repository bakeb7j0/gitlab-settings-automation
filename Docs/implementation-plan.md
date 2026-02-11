# gl-settings CLI Extension Plan

## Current Status

**Last Updated:** During session - PR #13 open for issue #6

### Completed Issues
| Issue | Title | PR | Status |
|-------|-------|-----|--------|
| #1 | Retry logic with exponential backoff | #8 | ✅ Merged |
| #2 | --filter flag for project filtering | #9 | ✅ Merged |
| #3 | project-setting operation | #10 | ✅ Merged |
| #4 | approval-rule operation | #11 | ✅ Merged |
| #5 | merge-request-setting operation | #12 | ✅ Merged |

### In Progress
| Issue | Title | PR | Status |
|-------|-------|-----|--------|
| #6 | pytest test suite | #13 | 🔄 PR Open - ready to merge |

### Remaining Issues
| Issue | Title | Blocked By | Status |
|-------|-------|------------|--------|
| #7 | Packaging + CI (pyproject.toml, Makefile, GitHub Actions) | #6 | ⏳ Blocked |

---

## Implementation Order

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Retry Logic | ✅ Done |
| 2 | `--filter` Flag | ✅ Done |
| 3 | `project-setting` Operation | ✅ Done |
| 4 | `approval-rule` Operation | ✅ Done |
| 5 | `merge-request-setting` Operation | ✅ Done |
| 6 | Test Suite | 🔄 PR Open |
| 7 | Packaging + CI | ⏳ Next |

---

## Key Files

- `gl_settings.py` - Main CLI (~1100 lines now with all operations)
- `CLAUDE.md` - Project rules and conventions
- `Docs/implementation-plan.md` - This file

## Operations Implemented

1. **protect-branch** - Branch protection (original)
2. **protect-tag** - Tag protection (original)
3. **project-setting** - Generic key=value settings for projects/groups
4. **approval-rule** - MR approval rules CRUD
5. **merge-request-setting** - MR approval settings (dual-API)

## Next Steps

1. Merge PR #13 (test suite)
2. Start #7 (packaging + CI) - pyproject.toml, Makefile, GitHub Actions

## Session Notes

- All operations follow the same pattern: `@register_operation`, `add_arguments()`, `apply_to_project()`
- Idempotency is key: GET current state, compare, only mutate if different
- `--dry-run` and `--filter` work with all operations via the recursion engine
