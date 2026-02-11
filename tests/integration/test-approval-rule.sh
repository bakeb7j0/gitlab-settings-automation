#!/bin/bash
# test-approval-rule.sh - Integration tests for approval-rule operation
#
# NOTE: Approval rules may require GitLab Premium/Ultimate.
# Tests will skip gracefully if the feature is not available.
#
# Tests:
#   1. Create a new approval rule
#   2. Verify idempotency
#   3. Update approval count
#   4. Delete approval rule (--unprotect)
#   5. Test group recursion

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROJECT="${GL_TEST_GROUP}/project-alpha"
PROJECT_URL="${GITLAB_URL}/${PROJECT}"
GROUP_URL="${GITLAB_URL}/${GL_TEST_GROUP}"

RULE_NAME="Integration Test Rule"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

get_rule_approvals() {
    local project="$1"
    local rule_name="$2"
    local rule
    rule=$(get_approval_rule_by_name "$project" "$rule_name")

    if [[ -z "$rule" ]]; then
        echo "not_found"
    else
        echo "$rule" | jq -r '.approvals_required // "not_found"'
    fi
}

remove_rule() {
    local project="$1"
    local rule_name="$2"

    gl-settings approval-rule "${GITLAB_URL}/${project}" \
        --rule-name "$rule_name" --unprotect 2>/dev/null || true
}

# Check if approval rules are available (Premium feature)
check_approval_rules_available() {
    local encoded
    encoded=$(url_encode "$PROJECT")

    # Try to list approval rules - will fail with 403 if not available
    local result
    result=$(glab api "projects/$encoded/approval_rules" 2>&1) || true

    if [[ "$result" == *"403"* ]] || [[ "$result" == *"Forbidden"* ]]; then
        return 1
    fi
    return 0
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

test_create_rule() {
    test_start "Create approval rule"

    remove_rule "$PROJECT" "$RULE_NAME"
    wait_for_gitlab

    run_gl_settings approval-rule "$PROJECT_URL" \
        --rule-name "$RULE_NAME" \
        --approvals 2

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE: $GL_OUTPUT"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local approvals
    approvals=$(get_rule_approvals "$PROJECT" "$RULE_NAME")

    if [[ "$approvals" != "2" ]]; then
        test_fail "Approvals required is '$approvals', expected '2'"
        return
    fi

    test_pass
}

test_idempotency() {
    test_start "Idempotency (already_set)"

    run_gl_settings approval-rule "$PROJECT_URL" \
        --rule-name "$RULE_NAME" \
        --approvals 2

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

test_update_approvals() {
    test_start "Update approval count"

    run_gl_settings approval-rule "$PROJECT_URL" \
        --rule-name "$RULE_NAME" \
        --approvals 3

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    if [[ "$GL_OUTPUT" != *"applied"* ]]; then
        test_fail "Output does not contain 'applied': $GL_OUTPUT"
        return
    fi

    wait_for_gitlab

    local approvals
    approvals=$(get_rule_approvals "$PROJECT" "$RULE_NAME")

    if [[ "$approvals" != "3" ]]; then
        test_fail "Approvals required is '$approvals', expected '3'"
        return
    fi

    test_pass
}

test_delete_rule() {
    test_start "Delete rule (--unprotect)"

    # Ensure rule exists
    gl-settings approval-rule "$PROJECT_URL" \
        --rule-name "$RULE_NAME" --approvals 2 >/dev/null 2>&1
    wait_for_gitlab

    run_gl_settings approval-rule "$PROJECT_URL" \
        --rule-name "$RULE_NAME" \
        --unprotect

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    wait_for_gitlab

    local approvals
    approvals=$(get_rule_approvals "$PROJECT" "$RULE_NAME")

    if [[ "$approvals" != "not_found" ]]; then
        test_fail "Rule still exists with approvals $approvals"
        return
    fi

    test_pass
}

test_group_recursion() {
    test_start "Group recursion (all projects)"

    # Remove rule from all projects
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        remove_rule "${GL_TEST_GROUP}/${proj}" "$RULE_NAME"
    done
    wait_for_gitlab 2

    run_gl_settings approval-rule "$GROUP_URL" \
        --rule-name "$RULE_NAME" \
        --approvals 1

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

    local all_set=true
    for proj in "project-alpha" "project-beta" "subgroup-one/project-gamma" "subgroup-one/nested-subgroup/project-delta"; do
        local approvals
        approvals=$(get_rule_approvals "${GL_TEST_GROUP}/${proj}" "$RULE_NAME")

        if [[ "$approvals" != "1" ]]; then
            log_error "Project $proj has approvals $approvals, expected 1"
            all_set=false
        fi
    done

    if [[ "$all_set" != true ]]; then
        test_fail "Not all projects have the rule"
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
        remove_rule "${GL_TEST_GROUP}/${proj}" "$RULE_NAME"
    done

    log_info "Cleanup complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "approval-rule Tests"
    check_environment

    # Check if approval rules are available
    if ! check_approval_rules_available; then
        log_warn "Approval rules not available (requires GitLab Premium/Ultimate)"
        log_warn "Skipping all approval-rule tests"
        echo ""
        echo -e "${YELLOW}All tests skipped - feature not available${NC}"
        exit 0
    fi

    suite_start "OP-04: approval-rule"

    test_create_rule
    test_idempotency
    test_update_approvals
    test_delete_rule
    test_group_recursion

    cleanup
    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
