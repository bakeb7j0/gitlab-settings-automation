#!/bin/bash
# run-all.sh - Execute the complete gl-settings integration test suite
#
# Usage:
#   ./run-all.sh              # Run all tests
#   ./run-all.sh --quick      # Run only core operation tests (skip slow tests)
#   ./run-all.sh --prime      # Prime environment first, then run all tests
#   ./run-all.sh --cleanup    # Clean up test environment after tests
#   ./run-all.sh --prime --cleanup  # Prime, run tests, then clean up
#
# Environment:
#   GITLAB_TOKEN   - Required: GitLab Personal Access Token
#   GL_TEST_GROUP  - Optional: Target group (default: testtarget)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST SUITES
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Core operation tests
CORE_TESTS=(
    "test-protect-branch.sh"
    "test-protect-tag.sh"
    "test-project-setting.sh"
    "test-approval-rule.sh"
    "test-merge-request-setting.sh"
)

# Scenario tests
SCENARIO_TESTS=(
    "test-recursion.sh"
    "test-error-handling.sh"
    "test-init-project.sh"
)

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLOBAL COUNTERS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOTAL_TESTS=0
TOTAL_PASSED=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0
FAILED_SUITES=()

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

run_test_suite() {
    local script="$1"
    local script_path="${SCRIPT_DIR}/${script}"

    if [[ ! -x "$script_path" ]]; then
        echo -e "${YELLOW}SKIP${NC} $script (not executable or missing)"
        return
    fi

    echo ""
    echo -e "${CYAN}Running: $script${NC}"
    echo "─────────────────────────────────────────────────────────"

    # Run the test script and capture results
    local output exit_code
    output=$("$script_path" 2>&1) || exit_code=$?
    exit_code=${exit_code:-0}

    echo "$output"

    # Parse results from output
    local passed failed skipped
    passed=$(echo "$output" | grep -oP 'Passed:\s*\K\d+' | tail -1 || echo "0")
    failed=$(echo "$output" | grep -oP 'Failed:\s*\K\d+' | tail -1 || echo "0")
    skipped=$(echo "$output" | grep -oP 'Skipped:\s*\K\d+' | tail -1 || echo "0")

    # Handle "All tests skipped" case
    if [[ "$output" == *"All tests skipped"* ]]; then
        echo -e "${YELLOW}Suite skipped (feature not available)${NC}"
        return
    fi

    # Update totals
    TOTAL_PASSED=$((TOTAL_PASSED + passed))
    TOTAL_FAILED=$((TOTAL_FAILED + failed))
    TOTAL_SKIPPED=$((TOTAL_SKIPPED + skipped))
    TOTAL_TESTS=$((TOTAL_TESTS + passed + failed + skipped))

    if [[ $failed -gt 0 ]]; then
        FAILED_SUITES+=("$script")
    fi
}

print_final_summary() {
    echo ""
    echo ""
    print_header "Integration Test Suite Results"
    echo ""
    echo -e "  ${BOLD}Total Tests:${NC}  $TOTAL_TESTS"
    echo -e "  ${GREEN}Passed:${NC}       $TOTAL_PASSED"

    if [[ $TOTAL_FAILED -gt 0 ]]; then
        echo -e "  ${RED}Failed:${NC}       $TOTAL_FAILED"
    else
        echo -e "  Failed:       $TOTAL_FAILED"
    fi

    if [[ $TOTAL_SKIPPED -gt 0 ]]; then
        echo -e "  ${YELLOW}Skipped:${NC}      $TOTAL_SKIPPED"
    fi

    echo ""

    if [[ ${#FAILED_SUITES[@]} -gt 0 ]]; then
        echo -e "${RED}Failed test suites:${NC}"
        for suite in "${FAILED_SUITES[@]}"; do
            echo "  - $suite"
        done
        echo ""
    fi

    if [[ $TOTAL_FAILED -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}✓ All tests passed!${NC}"
    else
        echo -e "${RED}${BOLD}✗ Some tests failed${NC}"
    fi

    echo ""
}

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --quick       Run only core operation tests (faster)"
    echo "  --prime       Prime the test environment before running"
    echo "  --cleanup     Clean up (delete) test environment after tests"
    echo "  --help        Show this help message"
    echo ""
    echo "Environment:"
    echo "  GITLAB_TOKEN   Required: GitLab Personal Access Token"
    echo "  GL_TEST_GROUP  Optional: Target group (default: testtarget)"
}

cleanup_environment() {
    print_header "Cleaning Up Test Environment"
    echo ""
    echo -e "${YELLOW}Deleting all projects and subgroups in ${GL_TEST_GROUP}...${NC}"
    echo ""

    # Delete all projects first
    local projects
    projects=$(list_group_projects "${GL_TEST_GROUP}" 2>/dev/null || echo "")

    if [[ -n "$projects" ]]; then
        while IFS= read -r project; do
            echo -e "  ${DIM}Deleting project:${NC} $project"
            delete_project "$project"
            sleep 0.5
        done <<< "$projects"
    fi

    # Delete subgroups (deepest first)
    local subgroups
    subgroups=$(list_subgroups "${GL_TEST_GROUP}" 2>/dev/null | sort -r || echo "")

    if [[ -n "$subgroups" ]]; then
        while IFS= read -r subgroup; do
            echo -e "  ${DIM}Deleting subgroup:${NC} $subgroup"
            delete_subgroup "$subgroup"
            sleep 0.5
        done <<< "$subgroups"
    fi

    echo ""
    echo -e "${GREEN}✓${NC} Cleanup complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    local quick_mode=false
    local prime_first=false
    local cleanup_after=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --quick)
                quick_mode=true
                shift
                ;;
            --prime)
                prime_first=true
                shift
                ;;
            --cleanup)
                cleanup_after=true
                shift
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    print_header "gl-settings Integration Test Suite"
    echo ""
    echo "Target: ${GITLAB_URL}/${GL_TEST_GROUP}"
    echo "Mode:   $(if $quick_mode; then echo 'Quick (core only)'; else echo 'Full'; fi)"
    echo ""

    # Validate environment
    check_environment

    # Prime if requested
    if $prime_first; then
        echo ""
        echo -e "${CYAN}Priming test environment...${NC}"
        echo "─────────────────────────────────────────────────────────"
        "${SCRIPT_DIR}/prime.sh" <<< "y"
    fi

    # Record start time
    local start_time
    start_time=$(date +%s)

    # Run core operation tests
    echo ""
    echo -e "${BOLD}=== Core Operation Tests ===${NC}"

    for test in "${CORE_TESTS[@]}"; do
        run_test_suite "$test"
    done

    # Run scenario tests (unless quick mode)
    if ! $quick_mode; then
        echo ""
        echo -e "${BOLD}=== Scenario Tests ===${NC}"

        for test in "${SCENARIO_TESTS[@]}"; do
            run_test_suite "$test"
        done
    fi

    # Calculate duration
    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    # Print summary
    print_final_summary
    echo "Duration: ${duration}s"
    echo ""

    # Cleanup if requested
    if $cleanup_after; then
        cleanup_environment
    fi

    # Exit with appropriate code
    if [[ $TOTAL_FAILED -gt 0 ]]; then
        exit 1
    fi
}

main "$@"
