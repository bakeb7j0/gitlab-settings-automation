#!/bin/bash
# release-lockdown.sh
#
# Example meta-script that uses gl-settings to lock down an old LTS release branch.
#
# Usage:
#   ./release-lockdown.sh <project-url> <release-branch> <tag-prefix> [--dry-run]
#
# Example:
#   ./release-lockdown.sh https://gitlab.com/myorg/ct-scanner release/1.2 "v1.2.*" --dry-run
#   ./release-lockdown.sh https://gitlab.com/myorg/ct-scanner release/1.2 "v1.2.*"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GL_SETTINGS="${SCRIPT_DIR}/gl_settings.py"

PROJECT_URL="${1:?Usage: $0 <project-url> <release-branch> <tag-prefix> [--dry-run]}"
BRANCH="${2:?Missing release branch (e.g., release/1.2)}"
TAG_PREFIX="${3:?Missing tag prefix (e.g., v1.2.*)}"
DRY_RUN="${4:-}"

echo "=== Release Lockdown ==="
echo "Project:    ${PROJECT_URL}"
echo "Branch:     ${BRANCH}"
echo "Tag prefix: ${TAG_PREFIX}"
echo "Mode:       ${DRY_RUN:=LIVE}"
echo ""

# Step 1: Lock down the old release branch — no push, no merge
echo "--- Step 1: Protecting branch '${BRANCH}' (no push, no merge) ---"
python3 "${GL_SETTINGS}" ${DRY_RUN} protect-branch "${PROJECT_URL}" \
    --branch "${BRANCH}" \
    --push no_access \
    --merge no_access
echo ""

# Step 2: Lock down tags — only maintainers can create matching tags
echo "--- Step 2: Protecting tags '${TAG_PREFIX}' (create=maintainer) ---"
python3 "${GL_SETTINGS}" ${DRY_RUN} protect-tag "${PROJECT_URL}" \
    --tag "${TAG_PREFIX}" \
    --create maintainer
echo ""

# Step 3: You could add more steps here, e.g.:
# - Update project merge settings
# - Add/remove approval rules
# - Notify a Slack channel via curl
# - Update a CI variable

echo "=== Done ==="
