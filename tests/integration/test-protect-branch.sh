#!/bin/bash
# test-protect-branch.sh - Integration tests for protect-branch operation
#
# Tests:
#   1. Apply branch protection to a single project
#   2. Verify idempotency (second run returns already_set)
#   3. Verify dry-run makes no changes
#   4. Change protection levels and verify
#   5. Test wildcard branch patterns
#   6. Test --unprotect flag
#   7. Test group recursion (applies to all projects)
#
# Usage:
#   ./test-protect-branch.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Test targets
PROJECT="${GL_TEST_GROUP}/project-alpha"
PROJECT_URL="${GITLAB_URL}/${PROJECT}"
GROUP_URL="${GITLAB_URL}/${GL_TEST_GROUP}"

# Branch to test
TEST_BRANCH="main"
WILDCARD_BRANCH="release/*"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Get push access level for a protected branch
# Returns: access level number (0=no_access, 30=developer, 40=maintainer)
get_push_level() {
    local project="$1"
    local branch="$2"
    local protection
    protection=$(get_branch_protection "$project" "$branch")

    if [[ -z "$protection" || "$protection" == "{}" ]]; then
        echo "unprotected"
    else
        echo "$protection" | jq -r '.push_access_levels[0].access_level // "unprotected"'
    fi
}

# Get merge access level for a protected branch
get_merge_level() {
    local project="$1"
    local branch="$2"
    local protection
    protection=$(get_branch_protection "$project" "$branch")

    if [[ -z "$protection" || "$protection" == "{}" ]]; then
        echo "unprotected"
    else
        echo "$protection" | jq -r '.merge_access_levels[0].access_level // "unprotected"'
    fi
}

# Remove branch protection (cleanup helper)
remove_protection() {
    local project="$1"
    local branch="$2"

    gl-settings protect-branch "${GITLAB_URL}/${project}" \
        --branch "$branch" --unprotect 2>/dev/null || true
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

test_apply_protection() {
    test_start "Apply branch protection"

    # Setup: ensure branch is unprotected
    remove_protection "$PROJECT" "$TEST_BRANCH"
    wait_for_gitlab

    # Act: apply protection
    run_gl_settings protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Verify: output indicates applied
    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    # Verify: GitLab state is correct
    local push_level merge_level
    push_level=$(get_push_level "$PROJECT" "$TEST_BRANCH")
    merge_level=$(get_merge_level "$PROJECT" "$TEST_BRANCH")

    if [[ "$push_level" != "40" ]]; then
        test_fail "Push level is $push_level, expected 40 (maintainer)"
        return
    fi

    if [[ "$merge_level" != "30" ]]; then
        test_fail "Merge level is $merge_level, expected 30 (developer)"
        return
    fi

    test_pass
}

test_idempotency() {
    test_start "Idempotency (already_set)"

    # Precondition: protection should already be set from previous test
    # Act: run the same command again
    run_gl_settings protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Verify: output indicates already_set
    if [[ "$GL_OUTPUT" != *"already_set"* ]]; then
        test_fail "Output does not contain 'already_set': $GL_OUTPUT"
        return
    fi

    test_pass
}

test_dry_run_no_changes() {
    test_start "Dry-run makes no changes"

    # Setup: remove protection first
    remove_protection "$PROJECT" "$TEST_BRANCH"
    wait_for_gitlab

    # Verify precondition: branch is unprotected
    local push_before
    push_before=$(get_push_level "$PROJECT" "$TEST_BRANCH")

    if [[ "$push_before" != "unprotected" ]]; then
        test_fail "Precondition failed: branch should be unprotected, got $push_before"
        return
    fi

    # Act: run with --dry-run
    run_gl_settings --dry-run protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Verify: output indicates would_apply
    if [[ "$GL_OUTPUT" != *"would_apply"* ]]; then
        test_fail "Output does not contain 'would_apply': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    # Verify: GitLab state unchanged (still unprotected)
    local push_after
    push_after=$(get_push_level "$PROJECT" "$TEST_BRANCH")

    if [[ "$push_after" != "unprotected" ]]; then
        test_fail "Dry-run modified state! Push level is now $push_after"
        return
    fi

    test_pass
}

test_change_protection_levels() {
    test_start "Change protection levels"

    # Setup: apply initial protection
    gl-settings protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge maintainer >/dev/null 2>&1
    wait_for_gitlab

    # Act: change to different levels
    run_gl_settings protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push developer \
        --merge developer

    # Verify: command succeeded and indicates applied
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    # Verify: GitLab state reflects new levels
    local push_level merge_level
    push_level=$(get_push_level "$PROJECT" "$TEST_BRANCH")
    merge_level=$(get_merge_level "$PROJECT" "$TEST_BRANCH")

    if [[ "$push_level" != "30" ]]; then
        test_fail "Push level is $push_level, expected 30 (developer)"
        return
    fi

    if [[ "$merge_level" != "30" ]]; then
        test_fail "Merge level is $merge_level, expected 30 (developer)"
        return
    fi

    test_pass
}

test_wildcard_branch() {
    test_start "Wildcard branch pattern (release/*)"

    # Setup: ensure pattern is unprotected
    remove_protection "$PROJECT" "$WILDCARD_BRANCH"
    wait_for_gitlab

    # Act: protect wildcard pattern
    run_gl_settings protect-branch "$PROJECT_URL" \
        --branch "$WILDCARD_BRANCH" \
        --push no_access \
        --merge maintainer

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    # Verify: protection exists for the pattern
    local push_level
    push_level=$(get_push_level "$PROJECT" "$WILDCARD_BRANCH")

    if [[ "$push_level" != "0" ]]; then
        test_fail "Push level is $push_level, expected 0 (no_access)"
        return
    fi

    # Cleanup
    remove_protection "$PROJECT" "$WILDCARD_BRANCH"

    test_pass
}

test_unprotect() {
    test_start "Unprotect branch (--unprotect)"

    # Setup: ensure branch is protected
    gl-settings protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge maintainer >/dev/null 2>&1
    wait_for_gitlab

    # Verify precondition
    local push_before
    push_before=$(get_push_level "$PROJECT" "$TEST_BRANCH")

    if [[ "$push_before" == "unprotected" ]]; then
        test_fail "Precondition failed: branch should be protected"
        return
    fi

    # Act: unprotect
    run_gl_settings protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --unprotect

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    # Verify: branch is now unprotected
    local push_after
    push_after=$(get_push_level "$PROJECT" "$TEST_BRANCH")

    if [[ "$push_after" != "unprotected" ]]; then
        test_fail "Branch still protected with push level $push_after"
        return
    fi

    test_pass
}

test_group_recursion() {
    test_start "Group recursion (all projects)"

    # Setup: ensure all projects have no protection on develop branch
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        remove_protection "${GL_TEST_GROUP}/${proj}" "develop"
    done
    wait_for_gitlab 2

    # Act: apply to entire group
    run_gl_settings protect-branch "$GROUP_URL" \
        --branch "develop" \
        --push maintainer \
        --merge developer

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Verify: output mentions multiple projects (should have 4 "applied" or mix of applied/already_set)
    local apply_count
    apply_count=$(echo "$GL_OUTPUT" | grep -c "applied\|already_set" || true)

    if [[ $apply_count -lt 4 ]]; then
        test_fail "Expected 4 projects affected, got $apply_count"
        return
    fi

    wait_for_gitlab 2

    # Verify: all projects have protection
    local all_protected=true
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        local push_level
        push_level=$(get_push_level "${GL_TEST_GROUP}/${proj}" "develop")

        if [[ "$push_level" != "40" ]]; then
            log_error "Project $proj has push level $push_level, expected 40"
            all_protected=false
        fi
    done

    if [[ "$all_protected" != true ]]; then
        test_fail "Not all projects were protected"
        return
    fi

    # Cleanup: remove protection from all
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        remove_protection "${GL_TEST_GROUP}/${proj}" "develop"
    done

    test_pass
}

test_json_output() {
    test_start "JSON output (--json)"

    # Setup: ensure known state
    remove_protection "$PROJECT" "$TEST_BRANCH"
    wait_for_gitlab

    # Act: run with --json
    run_gl_settings_json protect-branch "$PROJECT_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge maintainer

    # Verify: command succeeded
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # JSON mode outputs multiple lines: log messages + result objects
    # Filter for result lines (those with "action" field)
    local result_line
    result_line=$(echo "$GL_JSON" | grep '"action"' | head -1)

    # Verify: we got a result line
    if [[ -z "$result_line" ]]; then
        test_fail "No result line with 'action' field in output: $GL_JSON"
        return
    fi

    # Verify: result line is valid JSON
    if ! echo "$result_line" | jq -e . >/dev/null 2>&1; then
        test_fail "Result line is not valid JSON: $result_line"
        return
    fi

    # Verify: JSON has expected fields
    local action target_path
    action=$(echo "$result_line" | jq -r '.action')
    target_path=$(echo "$result_line" | jq -r '.target_path')

    if [[ "$action" != "applied" ]]; then
        test_fail "JSON action is '$action', expected 'applied'"
        return
    fi

    if [[ "$target_path" != "$PROJECT" ]]; then
        test_fail "JSON target_path is '$target_path', expected '$PROJECT'"
        return
    fi

    test_pass
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLEANUP
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cleanup() {
    log_info "Cleaning up test artifacts..."

    # Remove any protections we created
    remove_protection "$PROJECT" "$TEST_BRANCH"
    remove_protection "$PROJECT" "$WILDCARD_BRANCH"

    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        remove_protection "${GL_TEST_GROUP}/${proj}" "develop"
    done

    log_info "Cleanup complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "protect-branch Tests"

    # Validate environment
    check_environment

    # Run tests
    suite_start "OP-01: protect-branch"

    test_apply_protection
    test_idempotency
    test_dry_run_no_changes
    test_change_protection_levels
    test_wildcard_branch
    test_unprotect
    test_group_recursion
    test_json_output

    # Cleanup
    cleanup

    # Summary
    print_summary
}

# Run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
