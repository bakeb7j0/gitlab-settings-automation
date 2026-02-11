#!/bin/bash
# test-protect-tag.sh - Integration tests for protect-tag operation
#
# Tests:
#   1. Apply tag protection to a single project
#   2. Verify idempotency (second run returns already_set)
#   3. Verify dry-run makes no changes
#   4. Change protection levels
#   5. Test wildcard tag patterns
#   6. Test --unprotect flag
#   7. Test group recursion

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROJECT="${GL_TEST_GROUP}/project-alpha"
PROJECT_URL="${GITLAB_URL}/${PROJECT}"
GROUP_URL="${GITLAB_URL}/${GL_TEST_GROUP}"

TEST_TAG="v*"
SPECIFIC_TAG="v1.0.0"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

get_create_level() {
    local project="$1"
    local tag="$2"
    local protection
    protection=$(get_tag_protection "$project" "$tag")

    if [[ -z "$protection" || "$protection" == "{}" ]]; then
        echo "unprotected"
    else
        echo "$protection" | jq -r '.create_access_levels[0].access_level // "unprotected"'
    fi
}

remove_tag_protection() {
    local project="$1"
    local tag="$2"

    gl-settings protect-tag "${GITLAB_URL}/${project}" \
        --tag "$tag" --unprotect 2>/dev/null || true
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

test_apply_tag_protection() {
    test_start "Apply tag protection"

    remove_tag_protection "$PROJECT" "$TEST_TAG"
    wait_for_gitlab

    run_gl_settings protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" \
        --create maintainer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local create_level
    create_level=$(get_create_level "$PROJECT" "$TEST_TAG")

    if [[ "$create_level" != "40" ]]; then
        test_fail "Create level is $create_level, expected 40 (maintainer)"
        return
    fi

    test_pass
}

test_idempotency() {
    test_start "Idempotency (already_set)"

    run_gl_settings protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" \
        --create maintainer

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

    remove_tag_protection "$PROJECT" "$TEST_TAG"
    wait_for_gitlab

    local level_before
    level_before=$(get_create_level "$PROJECT" "$TEST_TAG")

    run_gl_settings --dry-run protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" \
        --create maintainer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"would_apply"* ]]; then
        test_fail "Output does not contain 'would_apply': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local level_after
    level_after=$(get_create_level "$PROJECT" "$TEST_TAG")

    if [[ "$level_after" != "$level_before" ]]; then
        test_fail "Dry-run modified state! Level changed from $level_before to $level_after"
        return
    fi

    test_pass
}

test_change_level() {
    test_start "Change protection level"

    gl-settings protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" --create maintainer >/dev/null 2>&1
    wait_for_gitlab

    run_gl_settings protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" \
        --create developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local create_level
    create_level=$(get_create_level "$PROJECT" "$TEST_TAG")

    if [[ "$create_level" != "30" ]]; then
        test_fail "Create level is $create_level, expected 30 (developer)"
        return
    fi

    test_pass
}

test_unprotect() {
    test_start "Unprotect tag (--unprotect)"

    gl-settings protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" --create maintainer >/dev/null 2>&1
    wait_for_gitlab

    run_gl_settings protect-tag "$PROJECT_URL" \
        --tag "$TEST_TAG" \
        --unprotect

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    local level_after
    level_after=$(get_create_level "$PROJECT" "$TEST_TAG")

    if [[ "$level_after" != "unprotected" ]]; then
        test_fail "Tag still protected with level $level_after"
        return
    fi

    test_pass
}

test_group_recursion() {
    test_start "Group recursion (all projects)"

    # Remove protection from all projects
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        remove_tag_protection "${GL_TEST_GROUP}/${proj}" "$TEST_TAG"
    done
    wait_for_gitlab 2

    run_gl_settings protect-tag "$GROUP_URL" \
        --tag "$TEST_TAG" \
        --create maintainer

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

    local all_protected=true
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        local create_level
        create_level=$(get_create_level "${GL_TEST_GROUP}/${proj}" "$TEST_TAG")

        if [[ "$create_level" != "40" ]]; then
            log_error "Project $proj has create level $create_level, expected 40"
            all_protected=false
        fi
    done

    if [[ "$all_protected" != true ]]; then
        test_fail "Not all projects were protected"
        return
    fi

    test_pass
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLEANUP
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cleanup() {
    log_info "Cleaning up test artifacts..."

    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        remove_tag_protection "${GL_TEST_GROUP}/${proj}" "$TEST_TAG"
    done

    log_info "Cleanup complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "protect-tag Tests"
    check_environment

    suite_start "OP-02: protect-tag"

    test_apply_tag_protection
    test_idempotency
    test_dry_run
    test_change_level
    test_unprotect
    test_group_recursion

    cleanup
    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
