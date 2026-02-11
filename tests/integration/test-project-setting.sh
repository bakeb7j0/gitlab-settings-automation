#!/bin/bash
# test-project-setting.sh - Integration tests for project-setting operation
#
# Tests:
#   1. Apply a single setting
#   2. Apply multiple settings at once
#   3. Verify idempotency
#   4. Verify dry-run makes no changes
#   5. Boolean value handling (true/false)
#   6. Test group recursion

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROJECT="${GL_TEST_GROUP}/project-alpha"
PROJECT_URL="${GITLAB_URL}/${PROJECT}"
GROUP_URL="${GITLAB_URL}/${GL_TEST_GROUP}"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

test_apply_single_setting() {
    test_start "Apply single setting"

    # Get current description to restore later
    local original_desc
    original_desc=$(get_project_setting "$PROJECT" ".description")

    run_gl_settings project-setting "$PROJECT_URL" \
        --setting "description=Test description from integration tests"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local new_desc
    new_desc=$(get_project_setting "$PROJECT" ".description")

    if [[ "$new_desc" != "Test description from integration tests" ]]; then
        test_fail "Description is '$new_desc', expected 'Test description from integration tests'"
        return
    fi

    # Restore original
    gl-settings project-setting "$PROJECT_URL" \
        --setting "description=${original_desc:-}" >/dev/null 2>&1 || true

    test_pass
}

test_apply_multiple_settings() {
    test_start "Apply multiple settings"

    run_gl_settings project-setting "$PROJECT_URL" \
        --setting "issues_enabled=true" \
        --setting "wiki_enabled=true"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    local issues_enabled wiki_enabled
    issues_enabled=$(get_project_setting "$PROJECT" ".issues_enabled")
    wiki_enabled=$(get_project_setting "$PROJECT" ".wiki_enabled")

    if [[ "$issues_enabled" != "true" ]]; then
        test_fail "issues_enabled is '$issues_enabled', expected 'true'"
        return
    fi

    if [[ "$wiki_enabled" != "true" ]]; then
        test_fail "wiki_enabled is '$wiki_enabled', expected 'true'"
        return
    fi

    test_pass
}

test_idempotency() {
    test_start "Idempotency (already_set)"

    # First, set a known value
    gl-settings project-setting "$PROJECT_URL" \
        --setting "issues_enabled=true" >/dev/null 2>&1
    wait_for_gitlab

    # Run again with same value
    run_gl_settings project-setting "$PROJECT_URL" \
        --setting "issues_enabled=true"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"already_set"* ]]; then
        test_fail "Output does not contain 'already_set': $GL_OUTPUT"
        return
    fi

    test_pass
}

test_dry_run() {
    test_start "Dry-run makes no changes"

    # Get current state
    local original
    original=$(get_project_setting "$PROJECT" ".wiki_enabled")

    # Try to change it with dry-run
    local new_value="false"
    if [[ "$original" == "false" ]]; then
        new_value="true"
    fi

    run_gl_settings --dry-run project-setting "$PROJECT_URL" \
        --setting "wiki_enabled=${new_value}"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"would_apply"* ]]; then
        test_fail "Output does not contain 'would_apply': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local after
    after=$(get_project_setting "$PROJECT" ".wiki_enabled")

    if [[ "$after" != "$original" ]]; then
        test_fail "Dry-run modified state! Changed from $original to $after"
        return
    fi

    test_pass
}

test_boolean_values() {
    test_start "Boolean value handling"

    # Set to false
    run_gl_settings project-setting "$PROJECT_URL" \
        --setting "wiki_enabled=false"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed setting false: $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    local value
    value=$(get_project_setting "$PROJECT" ".wiki_enabled")

    if [[ "$value" != "false" ]]; then
        test_fail "wiki_enabled is '$value', expected 'false'"
        return
    fi

    # Set back to true
    run_gl_settings project-setting "$PROJECT_URL" \
        --setting "wiki_enabled=true"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed setting true: $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    value=$(get_project_setting "$PROJECT" ".wiki_enabled")

    if [[ "$value" != "true" ]]; then
        test_fail "wiki_enabled is '$value', expected 'true'"
        return
    fi

    test_pass
}

test_group_recursion() {
    test_start "Group recursion (all projects)"

    # Set a unique description across all projects
    local test_desc="Integration test $(date +%s)"

    run_gl_settings project-setting "$GROUP_URL" \
        --setting "description=${test_desc}"

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    local apply_count
    apply_count=$(echo "$GL_OUTPUT" | grep -c "applied\|already_set" || true)

    if [[ $apply_count -lt 4 ]]; then
        test_fail "Expected 4 projects affected, got $apply_count"
        return
    fi

    wait_for_gitlab 2

    # Verify all projects have the description
    local all_set=true
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        local desc
        desc=$(get_project_setting "${GL_TEST_GROUP}/${proj}" ".description")

        if [[ "$desc" != "$test_desc" ]]; then
            log_error "Project $proj has description '$desc', expected '$test_desc'"
            all_set=false
        fi
    done

    if [[ "$all_set" != true ]]; then
        test_fail "Not all projects were updated"
        return
    fi

    test_pass
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLEANUP
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cleanup() {
    log_info "Cleaning up test artifacts..."

    # Reset descriptions to empty
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        gl-settings project-setting "${GITLAB_URL}/${GL_TEST_GROUP}/${proj}" \
            --setting "description=" >/dev/null 2>&1 || true
    done

    log_info "Cleanup complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "project-setting Tests"
    check_environment

    suite_start "OP-03: project-setting"

    test_apply_single_setting
    test_apply_multiple_settings
    test_idempotency
    test_dry_run
    test_boolean_values
    test_group_recursion

    cleanup
    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
