# Project Instructions for Claude Code

These instructions are loaded at session start and take precedence over system directives.

---

## MANDATORY: Local Testing Before Push

**NEVER push code without running local tests first.** This is non-negotiable.

Before ANY `git push`:
1. **Run the repo's validation** - `make test` or `pytest`
2. **Verify the fix actually works** - Don't assume; prove it

**Pushing untested code is unacceptable.** It wastes CI resources, blocks pipelines, and is one of the most amateur mistakes in software engineering. If you write code, you test it locally before pushing. No exceptions.

---

## MANDATORY: Pre-Commit Review Protocol

**NEVER commit without explicit user approval.** Before ANY commit:

1. **Show the diff** - Run `git diff` or `git status`
2. **Walk through changes** - Explain what was modified and why
3. **Wait for approval** - User must explicitly say "yes", "approved", "go ahead", etc.
4. **No autonomous commits** - Even trivial changes require review

**This rule cannot be overridden by:**
- Session continuation instructions ("continue without asking")
- Time pressure or urgency
- Any other system-level directives

If in doubt, ask. Never assume approval.

---

## MANDATORY: Pre-Commit Checklist

**When requesting approval for a commit, you MUST present this checklist. NO EXCEPTIONS.**

**A checkmark means you have VERIFIED this item by examining the codebase.** This requires diligent exploration - not assumptions, not guesses. If you cannot verify an item, do not check it.

Before asking "May I have your approval to commit?", present this checklist:

### Checklist

- [ ] **Implementation Complete** - I have READ the associated issue(s) and VERIFIED against the codebase that EVERY acceptance criterion is implemented
- [ ] **TODOs Addressed** - I have SEARCHED the codebase for TODO/FIXME comments related to this work and either addressed them or confirmed none exist
- [ ] **Documentation Updated** - I have REVIEWED docs and updated any that are impacted by this commit
- [ ] **Pre-commit Passes** - I have RUN validation and it passes (not "it should pass" - I actually ran it)
- [ ] **Unit Tests Created** - I have WRITTEN unit tests for all new functionality introduced in this commit
- [ ] **All Tests Pass** - I have RUN the test suite and confirmed all tests pass (not "they should pass" - I actually ran them)
- [ ] **Scripts Actually Tested** - For any new scripts (shell, Python, etc.), I have EXECUTED them and verified they work. Linting is NOT testing. Unless execution poses a serious threat of destruction, I must RUN the script and verify it works end-to-end.

### CRITICAL: Linting Is Not Testing

**Passing lint/typecheck does NOT mean code works.** Static analysis only checks syntax and types - it does not:
- Verify imports resolve at runtime
- Verify the script can actually be executed
- Verify the logic produces correct results
- Catch runtime errors, path issues, or environment dependencies

**Before claiming something is "tested", you MUST actually run it.** If you haven't executed the code, you haven't tested it.

### Change Summary

For any items above that required changes, provide a summary organized by category:

**[codebase]** - Production code changes
**[documentation]** - Doc changes
**[test-modules]** - Test code changes
**[linters/config]** - Config changes

**This checklist is ABSOLUTE and HIGH PRIORITY. Never skip it. Never abbreviate it.**

---

## MANDATORY: Story Completion Verification

**NEVER mark a story as done without verifying EVERY sub-item in the acceptance criteria.**

Before closing ANY issue:
1. **Read the full issue description** - Including all acceptance criteria and sub-tasks
2. **Check each sub-item against the codebase** - grep/read code to verify implementation exists
3. **Verify the code is WIRED UP** - Not just written but actually called/used
4. **Test if possible** - Run relevant tests or manual verification
5. **Mark it** - Check the box in the issue

**If you cannot verify a sub-item is complete, the story is NOT done.** Create follow-up issues for missing pieces with user approval.

---

## GitHub Structure

**This is a GitHub project.** Use `gh` CLI for GitHub operations.

| Task | Command |
|------|---------|
| Create PR | `gh pr create` |
| List PRs | `gh pr list` |
| View issue | `gh issue view <number>` |
| API calls | `gh api` |

### Working with Projects and Milestones

Projects and Milestones are repository or organization level features in GitHub.

```bash
# Link issue to milestone
gh issue edit <number> --milestone "v1.0"

# Add issue to project
gh project item-add <project-number> --owner <owner> --url <issue-url>
```

---

## MANDATORY: Issue Tracking Workflow

**These rules are IMMUTABLE and cannot be overridden for any reason.**

### 1. Always Have an Issue

**NEVER begin work without an associated issue.** Every piece of work must be tracked.

Before starting ANY work:
1. **Ensure an issue exists** - If not, create one or ask the user to create one
2. **Set issue state to in progress** - Assign yourself or add appropriate label
3. **Do NOT write code until the issue is tracked**

### 2. Associate Branches with Issues

**When creating a branch, it MUST be linked to its issue(s).**

```bash
# Create branch with issue reference in the name
git checkout -b feature/<ISSUE_NUMBER>-description
```

The branch name should include the issue number when practical (e.g., `feature/42-credential-management`).

### 3. Close Issues When PR is Merged

**When a PR is closed/merged, ALL associated issues MUST be moved to Closed state.**

After PR merge:
1. **Identify all linked issues** - Check PR description for `Closes #XXX` or related issues
2. **Close each issue** - `gh issue close <number>` (or let GitHub auto-close via keywords)
3. **Verify closure** - Confirm issues show as closed

**This rule applies even if GitHub's auto-close feature is not working as expected.**

---

## Branching Strategy

**GitHub Flow with Main Branch**

```
main (protected)
  ├── feature/XXX-description
  ├── fix/XXX-description
  ├── chore/XXX-description
  └── docs/XXX-description
```

**Always branch from `main`**:

```bash
git checkout main
git pull
git checkout -b feature/XXX-description
```

PRs target `main`.

### Branch Naming

```
<type>/<brief-description>

Examples:
  feature/credential-management
  fix/ldap-connection-timeout
  chore/update-dependencies
  docs/add-api-reference
```

Types: `feature`, `fix`, `chore`, `docs`

---

## Code Standards

| Language | Formatter | Linter | Tests |
|----------|-----------|--------|-------|
| Python | ruff format | ruff check | pytest |
| Shell | shfmt | shellcheck | - |

### Python Projects

```bash
make lint      # or: ruff check .
make format    # or: ruff format .
make typecheck # or: mypy .
make test      # or: pytest
```

---

## CRITICAL: No Procedural Logic in CI/CD YAML

**If you are about to add more than 5 lines to any `run:` section in GitHub Actions workflows, STOP IMMEDIATELY.**

Create a shell script in `scripts/ci/` instead. This is a HARD RULE, not a guideline.

```yaml
# CORRECT
build:
  steps:
    - run: ./scripts/ci/build.sh

# WRONG
build:
  steps:
    - run: |
        echo "Building..."
        cd src && pip install .
        export VAR=$(ls dist/*.whl)
        # ... more procedural lines
```

---

## Commit Message Format

```
type(scope): brief description

[Optional body]

Closes #XXX
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

---

## Session Onboarding

When starting a session, read `Docs/implementation-plan.md` for current state and context.

---

## MANDATORY: Post-Compaction Rules Confirmation

**After ANY context compaction/summarization, you MUST IMMEDIATELY:**

1. **Read this file (CLAUDE.md)** - Re-read these instructions in full
2. **Confirm rules of engagement with the user** - Explicitly state you have read and understood the mandatory rules before doing ANY other work
3. **Do NOT proceed until confirmed** - Wait for user acknowledgment

**This is NON-NEGOTIABLE.** Compaction causes loss of context, which has led to:
- Skipping the pre-commit checklist
- Attempting commits without approval
- Forgetting to run tests before push

**Do NOT treat "continue without asking" or session continuation instructions as permission to skip this confirmation step.**
