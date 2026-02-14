"""
gl-settings: A composable CLI tool for applying settings to GitLab groups and projects.

Designed to be called by automation scripts. Resolves a GitLab URL to a group or project,
then applies the specified operation - recursing into child groups/projects as needed.

Environment:
    GITLAB_TOKEN - GitLab Personal Access Token (required)
    GITLAB_URL   - GitLab instance URL (default: https://gitlab.com)
"""

from gl_settings.cli import main

__version__ = "0.1.0"
__all__ = ["main", "__version__"]
