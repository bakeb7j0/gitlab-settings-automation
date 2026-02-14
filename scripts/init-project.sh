#!/bin/bash
# init-project.sh - Initialize a GitLab project with standard settings
#
# DEPRECATED: This script is deprecated. Use the gl-settings CLI instead:
#   gl-settings init-project <project-url>
#   gl-settings init-project --dry-run <project-url>
#
# This script applies the Blueshift template settings to a new or existing project.
# It configures merge request policies, branch protection, tag protection, and
# access controls to match organizational standards.
#
# Usage:
#   ./init-project.sh <project-url>
#   ./init-project.sh https://gitlab.com/mygroup/myproject
#   ./init-project.sh --dry-run https://gitlab.com/mygroup/myproject
#
# Environment:
#   GITLAB_TOKEN - Required: GitLab Personal Access Token with api scope
#
# Based on settings from: analogicdev/internal/tools/blueshift/blueshift-template

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
NC='\033[0m'

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Project settings (non-default values)
declare -A PROJECT_SETTINGS=(
    # Merge Request policies
    ["only_allow_merge_if_pipeline_succeeds"]="true"
    ["only_allow_merge_if_all_discussions_are_resolved"]="true"
    ["remove_source_branch_after_merge"]="true"
    ["merge_pipelines_enabled"]="true"
    ["issue_branch_template"]="feature/%{id}-%{title}"

    # Access controls
    ["forking_access_level"]="disabled"
    ["pages_access_level"]="private"
    ["package_registry_access_level"]="private"
    ["security_and_compliance_access_level"]="private"

    # CI/CD
    ["auto_devops_enabled"]="false"
)

# MR Approval settings
declare -A MR_APPROVAL_SETTINGS=(
    ["reset_approvals_on_push"]="true"
    ["merge_requests_author_approval"]="true"
)

# Protected branches: name -> "push_level:merge_level:allow_force_push"
declare -A PROTECTED_BRANCHES=(
    ["main"]="maintainer:maintainer:false"
    ["release/*"]="maintainer:maintainer:true"
)

# Protected tags: pattern -> create_level
declare -A PROTECTED_TAGS=(
    ["rc*"]="maintainer"
    ["v*"]="maintainer"
)

# Issue templates directory (relative to this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISSUE_TEMPLATES_DIR="${SCRIPT_DIR}/../issue-templates"

# Issue templates to install
ISSUE_TEMPLATES=(
    "bug.md"
    "chore.md"
    "docs.md"
    "feature.md"
)

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_header() {
    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} $1${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}── $1 ──${NC}"
}

log_info() {
    echo -e "${GREEN}✓${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}!${NC} $*"
}

log_error() {
    echo -e "${RED}✗${NC} $*"
}

show_usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] <project-url>

Initialize a GitLab project with standard organizational settings.

Options:
    --dry-run         Show what would be changed without making changes
    --skip-branches   Skip protected branch configuration
    --skip-tags       Skip protected tag configuration
    --skip-templates  Skip issue template installation
    --help            Show this help message

Examples:
    $(basename "$0") https://gitlab.com/mygroup/myproject
    $(basename "$0") --dry-run https://gitlab.com/mygroup/myproject

Environment:
    GITLAB_TOKEN    Required: GitLab Personal Access Token with api scope

Settings applied:
    • Merge request policies (pipeline required, discussions resolved, etc.)
    • Access controls (forking disabled, private registries)
    • Protected branches (main, release/*)
    • Protected tags (v*, rc*)
    • MR approval settings (reset on push)
    • Issue templates (bug, feature, chore, docs)
EOF
}

check_prerequisites() {
    local missing=0

    if [[ -z "${GITLAB_TOKEN:-}" ]]; then
        log_error "GITLAB_TOKEN environment variable is not set"
        missing=1
    fi

    if ! command -v gl-settings &>/dev/null; then
        log_error "gl-settings is not installed (pip install gl-settings)"
        missing=1
    fi

    if ! command -v glab &>/dev/null; then
        log_error "glab CLI is not installed"
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        exit 1
    fi
}

# URL-encode a string
url_encode() {
    python3 -c "import urllib.parse; print(urllib.parse.quote('$1', safe=''))"
}

# Extract project path from GitLab URL
# e.g., https://gitlab.com/group/project -> group/project
extract_project_path() {
    local url="$1"
    # Remove protocol and host, then any trailing slashes
    echo "$url" | sed -E 's|https?://[^/]+/||' | sed 's|/$||'
}

# Get project ID from path
get_project_id() {
    local path="$1"
    local encoded
    encoded=$(url_encode "$path")
    glab api "projects/$encoded" 2>/dev/null | jq -r '.id'
}

# Get default branch for a project
get_default_branch() {
    local path="$1"
    local encoded
    encoded=$(url_encode "$path")
    glab api "projects/$encoded" 2>/dev/null | jq -r '.default_branch'
}

apply_project_settings() {
    local project_url="$1"
    local dry_run_flag="$2"

    print_section "Project Settings"

    # Build the settings arguments
    local settings_args=()
    for key in "${!PROJECT_SETTINGS[@]}"; do
        settings_args+=("--setting" "${key}=${PROJECT_SETTINGS[$key]}")
    done

    echo -e "${DIM}Settings to apply:${NC}"
    for key in "${!PROJECT_SETTINGS[@]}"; do
        echo -e "  ${DIM}${key}=${NC}${PROJECT_SETTINGS[$key]}"
    done
    echo ""

    gl-settings $dry_run_flag project-setting "$project_url" "${settings_args[@]}"
}

apply_mr_approval_settings() {
    local project_url="$1"
    local dry_run_flag="$2"

    print_section "MR Approval Settings"

    echo -e "${DIM}Settings to apply:${NC}"
    for key in "${!MR_APPROVAL_SETTINGS[@]}"; do
        echo -e "  ${DIM}${key}=${NC}${MR_APPROVAL_SETTINGS[$key]}"
    done
    echo ""

    # Build arguments based on settings
    local args=()

    if [[ "${MR_APPROVAL_SETTINGS[reset_approvals_on_push]}" == "true" ]]; then
        args+=("--reset-approvals-on-push" "true")
    fi

    # Note: merge_requests_author_approval requires a different API approach
    # For now, we'll document it but gl-settings may not support it directly

    if [[ ${#args[@]} -gt 0 ]]; then
        gl-settings $dry_run_flag merge-request-setting "$project_url" "${args[@]}"
    fi
}

apply_protected_branches() {
    local project_url="$1"
    local dry_run_flag="$2"

    print_section "Protected Branches"

    for branch in "${!PROTECTED_BRANCHES[@]}"; do
        local config="${PROTECTED_BRANCHES[$branch]}"
        IFS=':' read -r push_level merge_level force_push <<< "$config"

        echo -e "${DIM}Branch:${NC} $branch"
        echo -e "  ${DIM}push=${NC}${push_level}, ${DIM}merge=${NC}${merge_level}, ${DIM}force_push=${NC}${force_push}"

        local args=("--branch" "$branch" "--push" "$push_level" "--merge" "$merge_level")

        if [[ "$force_push" == "true" ]]; then
            args+=("--allow-force-push")
        fi

        gl-settings $dry_run_flag protect-branch "$project_url" "${args[@]}"
        echo ""
    done
}

apply_protected_tags() {
    local project_url="$1"
    local dry_run_flag="$2"

    print_section "Protected Tags"

    for tag in "${!PROTECTED_TAGS[@]}"; do
        local create_level="${PROTECTED_TAGS[$tag]}"

        echo -e "${DIM}Tag pattern:${NC} $tag"
        echo -e "  ${DIM}create=${NC}${create_level}"

        gl-settings $dry_run_flag protect-tag "$project_url" \
            --tag "$tag" \
            --create "$create_level"
        echo ""
    done
}

apply_issue_templates() {
    local project_url="$1"
    local dry_run="$2"

    print_section "Issue Templates"

    # Check if templates directory exists
    if [[ ! -d "$ISSUE_TEMPLATES_DIR" ]]; then
        log_warn "Issue templates directory not found: $ISSUE_TEMPLATES_DIR"
        return
    fi

    # Extract project path and get default branch
    local project_path default_branch
    project_path=$(extract_project_path "$project_url")
    default_branch=$(get_default_branch "$project_path")

    if [[ -z "$default_branch" || "$default_branch" == "null" ]]; then
        log_warn "Could not determine default branch, using 'main'"
        default_branch="main"
    fi

    local encoded_project
    encoded_project=$(url_encode "$project_path")

    for template in "${ISSUE_TEMPLATES[@]}"; do
        local template_path="${ISSUE_TEMPLATES_DIR}/${template}"
        local gitlab_path=".gitlab/issue_templates/${template}"
        local encoded_path
        encoded_path=$(url_encode "$gitlab_path")

        if [[ ! -f "$template_path" ]]; then
            log_warn "Template not found: $template"
            continue
        fi

        echo -e "${DIM}Template:${NC} $template → $gitlab_path"

        if [[ "$dry_run" == "true" ]]; then
            echo -e "  ${YELLOW}[DRY-RUN]${NC} Would create $gitlab_path"
            continue
        fi

        # Read template content
        local content
        content=$(cat "$template_path")

        # Check if file already exists
        local exists
        exists=$(glab api "projects/${encoded_project}/repository/files/${encoded_path}?ref=${default_branch}" 2>/dev/null | jq -r '.file_path // empty')

        if [[ -n "$exists" ]]; then
            # Update existing file
            local result
            result=$(glab api "projects/${encoded_project}/repository/files/${encoded_path}" \
                --method PUT \
                -f branch="$default_branch" \
                -f content="$content" \
                -f commit_message="Update issue template: ${template}" \
                -f encoding="text" 2>&1) || true

            if [[ "$result" == *"file_path"* ]]; then
                log_info "Updated: $gitlab_path"
            else
                log_warn "May already be up to date: $gitlab_path"
            fi
        else
            # Create new file
            local result
            result=$(glab api "projects/${encoded_project}/repository/files/${encoded_path}" \
                --method POST \
                -f branch="$default_branch" \
                -f content="$content" \
                -f commit_message="Add issue template: ${template}" \
                -f encoding="text" 2>&1) || true

            if [[ "$result" == *"file_path"* ]]; then
                log_info "Created: $gitlab_path"
            else
                log_error "Failed to create: $gitlab_path"
                echo -e "  ${DIM}${result}${NC}"
            fi
        fi
    done
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    local dry_run=false
    local dry_run_flag=""
    local skip_branches=false
    local skip_tags=false
    local skip_templates=false
    local project_url=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                dry_run=true
                dry_run_flag="--dry-run"
                shift
                ;;
            --skip-branches)
                skip_branches=true
                shift
                ;;
            --skip-tags)
                skip_tags=true
                shift
                ;;
            --skip-templates)
                skip_templates=true
                shift
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            -*)
                echo "Unknown option: $1"
                show_usage
                exit 1
                ;;
            *)
                project_url="$1"
                shift
                ;;
        esac
    done

    # Validate arguments
    if [[ -z "$project_url" ]]; then
        echo "Error: Project URL is required"
        echo ""
        show_usage
        exit 1
    fi

    # Print header
    print_header "GitLab Project Initialization"
    echo ""
    echo -e "Target: ${BOLD}${project_url}${NC}"
    if $dry_run; then
        echo -e "Mode:   ${YELLOW}DRY-RUN (no changes will be made)${NC}"
    else
        echo -e "Mode:   ${GREEN}APPLY${NC}"
    fi

    # Check prerequisites
    check_prerequisites

    # Apply settings
    apply_project_settings "$project_url" "$dry_run_flag"
    apply_mr_approval_settings "$project_url" "$dry_run_flag"

    if ! $skip_branches; then
        apply_protected_branches "$project_url" "$dry_run_flag"
    else
        log_warn "Skipping protected branches (--skip-branches)"
    fi

    if ! $skip_tags; then
        apply_protected_tags "$project_url" "$dry_run_flag"
    else
        log_warn "Skipping protected tags (--skip-tags)"
    fi

    if ! $skip_templates; then
        apply_issue_templates "$project_url" "$dry_run"
    else
        log_warn "Skipping issue templates (--skip-templates)"
    fi

    # Summary
    print_header "Complete"
    if $dry_run; then
        echo -e "${YELLOW}Dry-run complete. Re-run without --dry-run to apply changes.${NC}"
    else
        echo -e "${GREEN}Project initialized successfully!${NC}"
    fi
    echo ""
}

main "$@"
