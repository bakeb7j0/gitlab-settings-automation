#!/bin/bash
# lib.sh - Shared functions for gl-settings integration tests
#
# Source this file in test scripts:
#   source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

set -euo pipefail

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COLORS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENVIRONMENT
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# GitLab configuration
GITLAB_URL="${GITLAB_URL:-https://gitlab.com}"
GL_TEST_GROUP="${GL_TEST_GROUP:-testtarget}"

# Derived values
GITLAB_API="${GITLAB_URL}/api/v4"
GL_TEST_GROUP_URL="${GITLAB_URL}/${GL_TEST_GROUP}"

# Test counters (global)
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0
CURRENT_TEST=""

# Validate required environment
check_environment() {
    local missing=0

    if [[ -z "${GITLAB_TOKEN:-}" ]]; then
        echo -e "${RED}ERROR: GITLAB_TOKEN is not set${NC}"
        missing=1
    fi

    if ! command -v gl-settings &>/dev/null; then
        echo -e "${RED}ERROR: gl-settings is not installed${NC}"
        missing=1
    fi

    if ! command -v glab &>/dev/null; then
        echo -e "${RED}ERROR: glab CLI is not installed${NC}"
        missing=1
    fi

    if ! command -v jq &>/dev/null; then
        echo -e "${RED}ERROR: jq is not installed${NC}"
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        echo ""
        echo "Required environment:"
        echo "  GITLAB_TOKEN  - GitLab Personal Access Token with 'api' scope"
        echo "  gl-settings   - This tool (pip install -e .)"
        echo "  glab          - GitLab CLI (https://gitlab.com/gitlab-org/cli)"
        echo "  jq            - JSON processor"
        exit 1
    fi

    echo -e "${GREEN}✓${NC} Environment validated"
    echo -e "  ${DIM}GITLAB_URL:${NC} ${GITLAB_URL}"
    echo -e "  ${DIM}GL_TEST_GROUP:${NC} ${GL_TEST_GROUP}"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST LIFECYCLE
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Start a test suite (group of tests)
suite_start() {
    local name="$1"
    echo ""
    echo -e "${BOLD}${BLUE}[$name]${NC}"
}

# Start an individual test
test_start() {
    local name="$1"
    CURRENT_TEST="$name"
    ((TESTS_RUN++)) || true
    printf "  - %-40s " "$name"
}

# Mark test as passed
test_pass() {
    local msg="${1:-}"
    ((TESTS_PASSED++)) || true
    echo -e "${GREEN}PASS${NC}"
    if [[ -n "$msg" ]]; then
        echo -e "    ${DIM}$msg${NC}"
    fi
}

# Mark test as failed
test_fail() {
    local msg="${1:-}"
    ((TESTS_FAILED++)) || true
    echo -e "${RED}FAIL${NC}"
    if [[ -n "$msg" ]]; then
        echo -e "    ${RED}$msg${NC}"
    fi
}

# Mark test as skipped
test_skip() {
    local msg="${1:-}"
    ((TESTS_SKIPPED++)) || true
    echo -e "${YELLOW}SKIP${NC}"
    if [[ -n "$msg" ]]; then
        echo -e "    ${DIM}$msg${NC}"
    fi
}

# Print test summary
print_summary() {
    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}Summary${NC}"
    echo -e "  Total:   ${TESTS_RUN}"
    echo -e "  ${GREEN}Passed:  ${TESTS_PASSED}${NC}"
    if [[ $TESTS_FAILED -gt 0 ]]; then
        echo -e "  ${RED}Failed:  ${TESTS_FAILED}${NC}"
    else
        echo -e "  Failed:  ${TESTS_FAILED}"
    fi
    if [[ $TESTS_SKIPPED -gt 0 ]]; then
        echo -e "  ${YELLOW}Skipped: ${TESTS_SKIPPED}${NC}"
    fi
    echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"

    # Return non-zero if any tests failed
    [[ $TESTS_FAILED -eq 0 ]]
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ASSERTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Assert two values are equal
# Usage: assert_eq "expected" "actual" "message"
assert_eq() {
    local expected="$1"
    local actual="$2"
    local msg="${3:-}"

    if [[ "$expected" == "$actual" ]]; then
        return 0
    else
        echo -e "${RED}Assertion failed${NC}: expected '$expected', got '$actual'" >&2
        if [[ -n "$msg" ]]; then
            echo -e "  ${DIM}$msg${NC}" >&2
        fi
        return 1
    fi
}

# Assert string contains substring
# Usage: assert_contains "haystack" "needle" "message"
assert_contains() {
    local haystack="$1"
    local needle="$2"
    local msg="${3:-}"

    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    else
        echo -e "${RED}Assertion failed${NC}: '$haystack' does not contain '$needle'" >&2
        if [[ -n "$msg" ]]; then
            echo -e "  ${DIM}$msg${NC}" >&2
        fi
        return 1
    fi
}

# Assert command exits with expected code
# Usage: assert_exit_code <expected_code> command [args...]
assert_exit_code() {
    local expected="$1"
    shift
    local actual=0
    "$@" || actual=$?

    if [[ "$expected" -eq "$actual" ]]; then
        return 0
    else
        echo -e "${RED}Assertion failed${NC}: expected exit code $expected, got $actual" >&2
        return 1
    fi
}

# Assert JSON field equals value
# Usage: assert_json_eq "json" ".field" "expected"
assert_json_eq() {
    local json="$1"
    local field="$2"
    local expected="$3"

    local actual
    actual=$(echo "$json" | jq -r "$field")

    assert_eq "$expected" "$actual" "JSON field $field"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GITLAB API HELPERS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# URL-encode a string
url_encode() {
    local string="$1"
    python3 -c "import urllib.parse; print(urllib.parse.quote('$string', safe=''))"
}

# Get project ID from path
# Usage: get_project_id "group/project"
get_project_id() {
    local path="$1"
    local encoded
    encoded=$(url_encode "$path")
    glab api "projects/$encoded" 2>/dev/null | jq -r '.id'
}

# Get group ID from path
# Usage: get_group_id "group/subgroup"
get_group_id() {
    local path="$1"
    local encoded
    encoded=$(url_encode "$path")
    glab api "groups/$encoded" 2>/dev/null | jq -r '.id'
}

# Get branch protection settings
# Usage: get_branch_protection "group/project" "branch"
# Returns: JSON object or empty if not protected
get_branch_protection() {
    local project="$1"
    local branch="$2"
    local encoded_project encoded_branch
    encoded_project=$(url_encode "$project")
    encoded_branch=$(url_encode "$branch")

    glab api "projects/$encoded_project/protected_branches/$encoded_branch" 2>/dev/null || echo "{}"
}

# Get tag protection settings
# Usage: get_tag_protection "group/project" "tag_pattern"
get_tag_protection() {
    local project="$1"
    local tag="$2"
    local encoded_project encoded_tag
    encoded_project=$(url_encode "$project")
    encoded_tag=$(url_encode "$tag")

    glab api "projects/$encoded_project/protected_tags/$encoded_tag" 2>/dev/null || echo "{}"
}

# Get project settings
# Usage: get_project_setting "group/project" ".field"
get_project_setting() {
    local project="$1"
    local field="$2"
    local encoded
    encoded=$(url_encode "$project")

    glab api "projects/$encoded" 2>/dev/null | jq -r "$field"
}

# Get approval rules for a project
# Usage: get_approval_rules "group/project"
get_approval_rules() {
    local project="$1"
    local encoded
    encoded=$(url_encode "$project")

    glab api "projects/$encoded/approval_rules" 2>/dev/null || echo "[]"
}

# Get approval rule by name
# Usage: get_approval_rule_by_name "group/project" "rule_name"
get_approval_rule_by_name() {
    local project="$1"
    local rule_name="$2"

    get_approval_rules "$project" | jq -r ".[] | select(.name == \"$rule_name\")"
}

# Get MR approval settings
# Usage: get_mr_approval_settings "group/project"
get_mr_approval_settings() {
    local project="$1"
    local encoded
    encoded=$(url_encode "$project")

    # Try modern API first, fall back to legacy
    glab api "projects/$encoded/approval_settings" 2>/dev/null ||
        glab api "projects/$encoded/approvals" 2>/dev/null ||
        echo "{}"
}

# List all projects in a group (recursive)
# Usage: list_group_projects "group"
# Note: Filters out projects marked for deletion (soft-deleted)
list_group_projects() {
    local group="$1"
    local encoded
    encoded=$(url_encode "$group")

    # Filter out soft-deleted projects (marked_for_deletion_at set, or renamed with deletion_scheduled)
    glab api "groups/$encoded/projects?include_subgroups=true&per_page=100" 2>/dev/null |
        jq -r '.[] | select(.marked_for_deletion_at == null) | select(.path_with_namespace | contains("deletion_scheduled") | not) | .path_with_namespace'
}

# List all subgroups in a group (recursive, including nested)
# Usage: list_subgroups "group"
# Note: Filters out subgroups marked for deletion (soft-deleted)
list_subgroups() {
    local group="$1"
    local encoded
    encoded=$(url_encode "$group")

    # Use descendant_groups to get ALL nested subgroups, not just direct children
    # Filter out soft-deleted groups (marked_for_deletion_on set, or renamed with deletion_scheduled)
    glab api "groups/$encoded/descendant_groups?per_page=100" 2>/dev/null |
        jq -r '.[] | select(.marked_for_deletion_on == null) | select(.full_path | contains("deletion_scheduled") | not) | .full_path'
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GITLAB MUTATION HELPERS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Create a subgroup
# Usage: create_subgroup "parent_group" "subgroup_name"
create_subgroup() {
    local parent="$1"
    local name="$2"
    local parent_id

    parent_id=$(get_group_id "$parent")

    glab api groups --method POST \
        -f "name=$name" \
        -f "path=$name" \
        -f "parent_id=$parent_id" \
        -f "visibility=private" 2>/dev/null | jq -r '.id'
}

# Create a project in a group
# Usage: create_project "group" "project_name"
create_project() {
    local group="$1"
    local name="$2"
    local group_id

    group_id=$(get_group_id "$group")

    glab api projects --method POST \
        -f "name=$name" \
        -f "path=$name" \
        -f "namespace_id=$group_id" \
        -f "visibility=private" \
        -f "initialize_with_readme=true" 2>/dev/null | jq -r '.id'
}

# Create a branch in a project
# Usage: create_branch "group/project" "branch_name" "ref"
create_branch() {
    local project="$1"
    local branch="$2"
    local ref="${3:-main}"
    local encoded
    encoded=$(url_encode "$project")

    glab api "projects/$encoded/repository/branches" --method POST \
        -f "branch=$branch" \
        -f "ref=$ref" 2>/dev/null | jq -r '.name'
}

# Create a tag in a project
# Usage: create_tag "group/project" "tag_name" "ref"
create_tag() {
    local project="$1"
    local tag="$2"
    local ref="${3:-main}"
    local encoded
    encoded=$(url_encode "$project")

    glab api "projects/$encoded/repository/tags" --method POST \
        -f "tag_name=$tag" \
        -f "ref=$ref" 2>/dev/null | jq -r '.name'
}

# Delete a subgroup (and all contents)
# Usage: delete_subgroup "group/subgroup"
delete_subgroup() {
    local path="$1"
    local encoded
    encoded=$(url_encode "$path")

    glab api "groups/$encoded" --method DELETE 2>/dev/null || true
}

# Delete a project
# Usage: delete_project "group/project"
delete_project() {
    local path="$1"
    local encoded
    encoded=$(url_encode "$path")

    glab api "projects/$encoded" --method DELETE 2>/dev/null || true
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GL-SETTINGS WRAPPERS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Run gl-settings and capture output
# Usage: run_gl_settings [args...]
# Sets: GL_OUTPUT, GL_EXIT_CODE
run_gl_settings() {
    GL_OUTPUT=""
    GL_EXIT_CODE=0
    GL_OUTPUT=$(gl-settings "$@" 2>&1) || GL_EXIT_CODE=$?
}

# Run gl-settings with --json and parse output
# Usage: run_gl_settings_json [args...]
# Sets: GL_JSON, GL_EXIT_CODE
run_gl_settings_json() {
    GL_JSON=""
    GL_EXIT_CODE=0
    GL_JSON=$(gl-settings --json "$@" 2>&1) || GL_EXIT_CODE=$?
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITIES
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Log an info message
log_info() {
    echo -e "${CYAN}[INFO]${NC} $*"
}

# Log a warning
log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

# Log an error
log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Wait for GitLab to process (rate limit safety)
wait_for_gitlab() {
    local seconds="${1:-1}"
    sleep "$seconds"
}

# Print a section header
print_header() {
    local title="$1"
    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} $title${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
}
