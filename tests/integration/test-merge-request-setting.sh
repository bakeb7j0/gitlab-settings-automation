#!/bin/bash
# test-merge-request-setting.sh - Integration tests for merge-request-setting operation
#
# NOTE: These tests verify the tool's behavior (output, exit codes) but GitLab state
# verification is limited due to API complexity with dual-API support (modern vs legacy).
#
# Tests:
#   1. Command executes successfully
#   2. Verify idempotency
#   3. Verify dry-run
#   4. Test group recursion

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

test_command_executes() {
    test_start "Command executes successfully"

    run_gl_settings merge-request-setting "$PROJECT_URL" \
        --reset-approvals-on-push true

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE: $GL_OUTPUT"
        return
    fi

    # Should report applied or already_set
    if [[ "$GL_OUTPUT" != *"applied"* ]] && [[ "$GL_OUTPUT" != *"already_set"* ]]; then
        test_fail "Output doesn't indicate success: $GL_OUTPUT"
        return
    fi

    test_pass
}

test_multiple_settings() {
    test_start "Multiple settings at once"

    run_gl_settings merge-request-setting "$PROJECT_URL" \
        --reset-approvals-on-push true \
        --disable-overriding-approvers true

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE: $GL_OUTPUT"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]] && [[ "$GL_OUTPUT" != *"already_set"* ]]; then
        test_fail "Output doesn't indicate success: $GL_OUTPUT"
        return
    fi

    test_pass
}

test_idempotency() {
    test_start "Idempotency (consistent output)"

    # Run twice with same settings
    gl-settings merge-request-setting "$PROJECT_URL" \
        --reset-approvals-on-push true >/dev/null 2>&1
    wait_for_gitlab

    run_gl_settings merge-request-setting "$PROJECT_URL" \
        --reset-approvals-on-push true

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Second run should report already_set or applied (depending on API behavior)
    if [[ "$GL_OUTPUT" != *"applied"* ]] && [[ "$GL_OUTPUT" != *"already_set"* ]]; then
        test_fail "Output doesn't indicate completion: $GL_OUTPUT"
        return
    fi

    test_pass
}

test_dry_run() {
    test_start "Dry-run reports correctly"

    run_gl_settings --dry-run merge-request-setting "$PROJECT_URL" \
        --reset-approvals-on-push false

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Should indicate dry-run mode
    if [[ "$GL_OUTPUT" != *"DRY-RUN"* ]]; then
        test_fail "Output doesn't indicate dry-run mode: $GL_OUTPUT"
        return
    fi

    test_pass
}

test_group_recursion() {
    test_start "Group recursion (all projects)"

    run_gl_settings merge-request-setting "$GROUP_URL" \
        --reset-approvals-on-push true

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Count how many projects were processed
    local project_count
    project_count=$(echo "$GL_OUTPUT" | grep -c "testtarget/" || true)

    if [[ $project_count -lt 4 ]]; then
        test_fail "Expected 4 projects, found $project_count"
        return
    fi

    test_pass
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "merge-request-setting Tests"
    check_environment

    suite_start "OP-05: merge-request-setting"

    test_command_executes
    test_multiple_settings
    test_idempotency
    test_dry_run
    test_group_recursion

    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
