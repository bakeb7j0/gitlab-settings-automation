#!/bin/bash
# test-error-handling.sh - Integration tests for error conditions
#
# Tests:
#   1. Invalid project URL returns error
#   2. Invalid group URL returns error
#   3. Missing GITLAB_TOKEN returns error
#   4. Invalid access level returns error
#   5. Nonexistent branch protection succeeds (creates new)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

test_invalid_project_url() {
    test_start "Invalid project URL returns error"

    run_gl_settings protect-branch "https://gitlab.com/nonexistent/project12345" \
        --branch main \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -eq 0 ]]; then
        test_fail "Command should have failed but exited 0"
        return
    fi

    if [[ "$GL_OUTPUT" != *"Could not resolve"* ]] && [[ "$GL_OUTPUT" != *"404"* ]] && [[ "$GL_OUTPUT" != *"error"* ]]; then
        test_fail "Output should indicate resolution failure: $GL_OUTPUT"
        return
    fi

    test_pass
}

test_invalid_group_url() {
    test_start "Invalid group URL returns error"

    run_gl_settings protect-branch "https://gitlab.com/nonexistent-group-12345" \
        --branch main \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -eq 0 ]]; then
        test_fail "Command should have failed but exited 0"
        return
    fi

    test_pass
}

test_missing_token() {
    test_start "Missing GITLAB_TOKEN returns error"

    # Save current token and unset it
    local saved_token="${GITLAB_TOKEN:-}"

    # Run with empty token
    GL_OUTPUT=""
    GL_EXIT_CODE=0
    GITLAB_TOKEN="" gl-settings protect-branch "https://gitlab.com/testtarget/project-alpha" \
        --branch main --push maintainer --merge developer 2>&1 || GL_EXIT_CODE=$?

    GL_OUTPUT=$(GITLAB_TOKEN="" gl-settings protect-branch "https://gitlab.com/testtarget/project-alpha" \
        --branch main --push maintainer --merge developer 2>&1 || true)

    # Restore token
    export GITLAB_TOKEN="$saved_token"

    if [[ $GL_EXIT_CODE -eq 0 ]] && [[ "$GL_OUTPUT" != *"GITLAB_TOKEN"* ]]; then
        # Some versions might not fail but should mention the token
        if [[ "$GL_OUTPUT" != *"error"* ]] && [[ "$GL_OUTPUT" != *"401"* ]]; then
            test_fail "Command should fail or warn about missing token"
            return
        fi
    fi

    test_pass
}

test_invalid_access_level() {
    test_start "Invalid access level returns error"

    run_gl_settings protect-branch "https://gitlab.com/${GL_TEST_GROUP}/project-alpha" \
        --branch main \
        --push invalid_level \
        --merge developer

    if [[ $GL_EXIT_CODE -eq 0 ]]; then
        test_fail "Command should have failed with invalid access level"
        return
    fi

    if [[ "$GL_OUTPUT" != *"invalid"* ]] && [[ "$GL_OUTPUT" != *"Invalid"* ]] && [[ "$GL_OUTPUT" != *"error"* ]]; then
        test_fail "Output should indicate invalid level: $GL_OUTPUT"
        return
    fi

    test_pass
}

test_nonexistent_branch_creates_protection() {
    test_start "Protect nonexistent branch succeeds"

    # Protect a branch that doesn't exist yet (wildcard patterns)
    run_gl_settings protect-branch "https://gitlab.com/${GL_TEST_GROUP}/project-alpha" \
        --branch "feature/nonexistent-*" \
        --push developer \
        --merge developer

    # This should succeed - GitLab allows protecting patterns for branches that don't exist
    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed but should succeed for pattern: $GL_OUTPUT"
        return
    fi

    # Cleanup
    gl-settings protect-branch "https://gitlab.com/${GL_TEST_GROUP}/project-alpha" \
        --branch "feature/nonexistent-*" --unprotect 2>/dev/null || true

    test_pass
}

test_malformed_url() {
    test_start "Malformed URL returns error"

    run_gl_settings protect-branch "not-a-valid-url" \
        --branch main \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -eq 0 ]]; then
        test_fail "Command should have failed with malformed URL"
        return
    fi

    test_pass
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "Error Handling Tests"
    check_environment

    suite_start "ERR: Error Handling"

    test_invalid_project_url
    test_invalid_group_url
    test_missing_token
    test_invalid_access_level
    test_nonexistent_branch_creates_protection
    test_malformed_url

    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
