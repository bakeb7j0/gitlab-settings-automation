#!/bin/bash
# prime.sh - Create a clean, known-good test environment
#
# This script:
#   1. Deletes all subgroups and projects inside GL_TEST_GROUP
#   2. Creates a fresh project/group structure
#   3. Creates test branches and tags in each project
#
# Usage:
#   ./prime.sh              # Create test environment
#   ./prime.sh --clean-only # Just delete, don't recreate
#
# Environment:
#   GITLAB_TOKEN   - Required: GitLab Personal Access Token
#   GL_TEST_GROUP  - Optional: Target group (default: testtarget)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib.sh"

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Test environment structure
# testtarget/
# ├── project-alpha
# ├── project-beta
# └── subgroup-one/
#     ├── project-gamma
#     └── nested-subgroup/
#         └── project-delta

PROJECTS_ROOT=(
    "project-alpha"
    "project-beta"
)

SUBGROUPS=(
    "subgroup-one"
    "subgroup-one/nested-subgroup"
)

PROJECTS_SUBGROUP_ONE=(
    "project-gamma"
)

PROJECTS_NESTED=(
    "project-delta"
)

# Branches to create in each project (besides main)
BRANCHES=(
    "develop"
    "release/1.0"
)

# Tags to create in each project
TAGS=(
    "v1.0.0"
)

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLEAN FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

clean_all() {
    print_header "Cleaning Test Environment"

    log_info "Deleting all projects in ${GL_TEST_GROUP}..."

    # Get all projects in the group (including subgroups)
    local projects
    projects=$(list_group_projects "${GL_TEST_GROUP}" 2>/dev/null || echo "")

    if [[ -n "$projects" ]]; then
        while IFS= read -r project; do
            log_info "  Deleting project: $project"
            delete_project "$project"
            wait_for_gitlab 0.5
        done <<< "$projects"
    else
        log_info "  No projects found"
    fi

    log_info "Deleting all subgroups in ${GL_TEST_GROUP}..."

    # Get subgroups (we need to delete nested ones first, so reverse sort by depth)
    local subgroups
    subgroups=$(list_subgroups "${GL_TEST_GROUP}" 2>/dev/null | sort -r || echo "")

    if [[ -n "$subgroups" ]]; then
        while IFS= read -r subgroup; do
            log_info "  Deleting subgroup: $subgroup"
            delete_subgroup "$subgroup"
            wait_for_gitlab 0.5
        done <<< "$subgroups"
    else
        log_info "  No subgroups found"
    fi

    log_info "Clean complete"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CREATE FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

create_subgroups() {
    print_header "Creating Subgroups"

    for subgroup in "${SUBGROUPS[@]}"; do
        local name parent full_path

        # Handle nested subgroups
        if [[ "$subgroup" == *"/"* ]]; then
            parent="${GL_TEST_GROUP}/$(dirname "$subgroup")"
            name="$(basename "$subgroup")"
        else
            parent="${GL_TEST_GROUP}"
            name="$subgroup"
        fi

        full_path="${GL_TEST_GROUP}/${subgroup}"
        log_info "Creating subgroup: $full_path"

        local result
        result=$(create_subgroup "$parent" "$name")

        if [[ -n "$result" && "$result" != "null" ]]; then
            echo -e "  ${GREEN}✓${NC} Created (ID: $result)"
        else
            echo -e "  ${RED}✗${NC} Failed to create $full_path"
            exit 1
        fi

        wait_for_gitlab 1
    done
}

create_projects() {
    print_header "Creating Projects"

    # Root-level projects
    for project in "${PROJECTS_ROOT[@]}"; do
        create_single_project "${GL_TEST_GROUP}" "$project"
    done

    # Subgroup-one projects
    for project in "${PROJECTS_SUBGROUP_ONE[@]}"; do
        create_single_project "${GL_TEST_GROUP}/subgroup-one" "$project"
    done

    # Nested subgroup projects
    for project in "${PROJECTS_NESTED[@]}"; do
        create_single_project "${GL_TEST_GROUP}/subgroup-one/nested-subgroup" "$project"
    done
}

create_single_project() {
    local group="$1"
    local name="$2"
    local full_path="${group}/${name}"

    log_info "Creating project: $full_path"

    local result
    result=$(create_project "$group" "$name")

    if [[ -n "$result" && "$result" != "null" ]]; then
        echo -e "  ${GREEN}✓${NC} Created (ID: $result)"
    else
        echo -e "  ${RED}✗${NC} Failed to create $full_path"
        exit 1
    fi

    wait_for_gitlab 1
}

create_branches_and_tags() {
    print_header "Creating Branches and Tags"

    # Get all projects we just created
    local projects
    projects=$(list_group_projects "${GL_TEST_GROUP}")

    while IFS= read -r project; do
        log_info "Setting up: $project"

        # Create branches
        for branch in "${BRANCHES[@]}"; do
            local result
            result=$(create_branch "$project" "$branch" "main" 2>/dev/null || echo "")

            if [[ -n "$result" && "$result" != "null" ]]; then
                echo -e "  ${GREEN}✓${NC} Branch: $branch"
            else
                echo -e "  ${YELLOW}~${NC} Branch: $branch (may already exist)"
            fi
        done

        # Create tags
        for tag in "${TAGS[@]}"; do
            local result
            result=$(create_tag "$project" "$tag" "main" 2>/dev/null || echo "")

            if [[ -n "$result" && "$result" != "null" ]]; then
                echo -e "  ${GREEN}✓${NC} Tag: $tag"
            else
                echo -e "  ${YELLOW}~${NC} Tag: $tag (may already exist)"
            fi
        done

        wait_for_gitlab 0.5
    done <<< "$projects"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VERIFICATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

verify_environment() {
    print_header "Verifying Environment"

    local projects subgroups
    projects=$(list_group_projects "${GL_TEST_GROUP}")
    subgroups=$(list_subgroups "${GL_TEST_GROUP}")

    log_info "Projects created:"
    while IFS= read -r project; do
        echo -e "  ${GREEN}✓${NC} $project"
    done <<< "$projects"

    echo ""
    log_info "Subgroups created:"
    while IFS= read -r subgroup; do
        echo -e "  ${GREEN}✓${NC} $subgroup"
    done <<< "$subgroups"

    # Count totals
    local project_count subgroup_count
    project_count=$(echo "$projects" | wc -l)
    subgroup_count=$(echo "$subgroups" | wc -l)

    echo ""
    echo -e "${BOLD}Environment Summary:${NC}"
    echo -e "  Projects:  $project_count (expected: 4)"
    echo -e "  Subgroups: $subgroup_count (expected: 2)"

    if [[ "$project_count" -eq 4 && "$subgroup_count" -eq 2 ]]; then
        echo ""
        echo -e "${GREEN}${BOLD}✓ Test environment is ready!${NC}"
        return 0
    else
        echo ""
        echo -e "${RED}${BOLD}✗ Environment verification failed${NC}"
        return 1
    fi
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    local clean_only=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --clean-only)
                clean_only=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [--clean-only]"
                echo ""
                echo "Options:"
                echo "  --clean-only  Delete all contents but don't recreate"
                echo ""
                echo "Environment:"
                echo "  GITLAB_TOKEN   Required: GitLab Personal Access Token"
                echo "  GL_TEST_GROUP  Optional: Target group (default: testtarget)"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    print_header "gl-settings Integration Test Environment"
    echo ""
    echo "Target group: ${GITLAB_URL}/${GL_TEST_GROUP}"
    echo ""

    # Validate environment
    check_environment

    # Confirm with user
    echo ""
    echo -e "${YELLOW}WARNING: This will DELETE all contents of ${GL_TEST_GROUP}${NC}"
    read -p "Continue? [y/N] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi

    # Clean existing content
    clean_all

    if [[ "$clean_only" == true ]]; then
        echo ""
        echo -e "${GREEN}Clean complete. Exiting (--clean-only mode).${NC}"
        exit 0
    fi

    # Create fresh environment
    create_subgroups
    create_projects
    create_branches_and_tags

    # Verify
    verify_environment
}

main "$@"
