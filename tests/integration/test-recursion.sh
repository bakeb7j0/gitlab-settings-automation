#!/bin/bash
# test-recursion.sh - Integration tests for group recursion and --filter flag
#
# Tests:
#   1. Group recursion reaches all nested projects
#   2. --filter includes matching projects
#   3. --filter excludes non-matching projects
#   4. Nested subgroup projects are included

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GROUP_URL="${GITLAB_URL}/${GL_TEST_GROUP}"
TEST_BRANCH="main"

# All projects in the test group
ALL_PROJECTS=(
    "project-alpha"
    "project-beta"
    "subgroup-one/project-gamma"
    "subgroup-one/nested-subgroup/project-delta"
)

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

remove_all_protections() {
    for proj in "${ALL_PROJECTS[@]}"; do
        gl-settings protect-branch "${GITLAB_URL}/${GL_TEST_GROUP}/${proj}" \
            --branch "$TEST_BRANCH" --unprotect 2>/dev/null || true
    done
    wait_for_gitlab 2
}

count_projects_in_output() {
    local output="$1"
    # Count lines that indicate actual project processing (applied or already_set)
    # Exclude soft-deleted projects (deletion_scheduled in path)
    echo "$output" | grep -E "(applied|already_set)" | grep "${GL_TEST_GROUP}/" | grep -cv "deletion_scheduled" || echo "0"
}

check_project_in_output() {
    local output="$1"
    local project="$2"

    if [[ "$output" == *"$project"* ]]; then
        return 0
    fi
    return 1
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

test_all_projects_reached() {
    test_start "Group recursion reaches all 4 projects"

    remove_all_protections

    run_gl_settings protect-branch "$GROUP_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    local count
    count=$(count_projects_in_output "$GL_OUTPUT")

    if [[ $count -ne 4 ]]; then
        test_fail "Expected 4 projects, found $count"
        return
    fi

    # Verify each project is mentioned
    for proj in "${ALL_PROJECTS[@]}"; do
        if ! check_project_in_output "$GL_OUTPUT" "${GL_TEST_GROUP}/${proj}"; then
            test_fail "Project ${proj} not found in output"
            return
        fi
    done

    test_pass
}

test_filter_includes_matching() {
    test_start "Filter includes matching projects"

    remove_all_protections

    # Filter for only alpha project
    run_gl_settings --filter "*/project-alpha" protect-branch "$GROUP_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    local count
    count=$(count_projects_in_output "$GL_OUTPUT")

    if [[ $count -ne 1 ]]; then
        test_fail "Expected 1 project, found $count"
        return
    fi

    if ! check_project_in_output "$GL_OUTPUT" "project-alpha"; then
        test_fail "project-alpha not found in output"
        return
    fi

    test_pass
}

test_filter_excludes_non_matching() {
    test_start "Filter excludes non-matching projects"

    remove_all_protections

    # Filter for alpha, verify beta is NOT included
    run_gl_settings --filter "*alpha*" protect-branch "$GROUP_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Should NOT contain beta, gamma, or delta
    if check_project_in_output "$GL_OUTPUT" "project-beta"; then
        test_fail "project-beta should be excluded but was found"
        return
    fi

    if check_project_in_output "$GL_OUTPUT" "project-gamma"; then
        test_fail "project-gamma should be excluded but was found"
        return
    fi

    if check_project_in_output "$GL_OUTPUT" "project-delta"; then
        test_fail "project-delta should be excluded but was found"
        return
    fi

    test_pass
}

test_nested_subgroups_included() {
    test_start "Nested subgroup projects are reached"

    remove_all_protections

    run_gl_settings protect-branch "$GROUP_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    # Specifically check the deepest nested project
    if ! check_project_in_output "$GL_OUTPUT" "nested-subgroup/project-delta"; then
        test_fail "Deeply nested project-delta not found"
        return
    fi

    test_pass
}

test_filter_wildcard_patterns() {
    test_start "Filter with wildcard patterns"

    remove_all_protections

    # Filter for projects starting with 'project-' (should get alpha and beta, not gamma/delta which are in subgroups)
    run_gl_settings --filter "${GL_TEST_GROUP}/project-*" protect-branch "$GROUP_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    local count
    count=$(count_projects_in_output "$GL_OUTPUT")

    # Should match only project-alpha and project-beta (direct children)
    if [[ $count -ne 2 ]]; then
        test_fail "Expected 2 projects with pattern '${GL_TEST_GROUP}/project-*', found $count"
        return
    fi

    test_pass
}

test_filter_subgroup_projects() {
    test_start "Filter for subgroup projects only"

    remove_all_protections

    # Filter for only subgroup projects
    run_gl_settings --filter "*subgroup*" protect-branch "$GROUP_URL" \
        --branch "$TEST_BRANCH" \
        --push maintainer \
        --merge developer

    if [[ $GL_EXIT_CODE -ne 0 ]]; then
        test_fail "Command failed with exit code $GL_EXIT_CODE"
        return
    fi

    local count
    count=$(count_projects_in_output "$GL_OUTPUT")

    # Should match gamma and delta (both are in subgroups)
    if [[ $count -ne 2 ]]; then
        test_fail "Expected 2 subgroup projects, found $count"
        return
    fi

    # Alpha and beta should NOT be included
    if check_project_in_output "$GL_OUTPUT" "${GL_TEST_GROUP}/project-alpha"; then
        test_fail "project-alpha should be excluded"
        return
    fi

    test_pass
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLEANUP
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cleanup() {
    log_info "Cleaning up test artifacts..."
    remove_all_protections
    log_info "Cleanup complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    print_header "Recursion & Filter Tests"
    check_environment

    suite_start "REC: Recursion & Filter"

    test_all_projects_reached
    test_filter_includes_matching
    test_filter_excludes_non_matching
    test_nested_subgroups_included
    test_filter_wildcard_patterns
    test_filter_subgroup_projects

    cleanup
    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
