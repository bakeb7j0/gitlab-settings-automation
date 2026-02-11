"""Unit tests for URL parsing in GitLabClient._extract_path_from_url()."""


# Constants (also defined in conftest.py for fixtures)
MOCK_GITLAB_URL = "https://gitlab.example.com"


class TestExtractPathFromUrl:
    """Tests for _extract_path_from_url method."""

    def test_full_https_url(self, mock_client):
        """Full HTTPS URL extracts path correctly."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project")
        assert result == "org/project"

    def test_full_http_url(self, mock_client):
        """Full HTTP URL extracts path correctly."""
        result = mock_client._extract_path_from_url("http://gitlab.com/org/project")
        assert result == "org/project"

    def test_url_with_trailing_slash(self, mock_client):
        """URL with trailing slash handles correctly."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project/")
        assert result == "org/project"

    def test_url_with_git_suffix(self, mock_client):
        """URL with .git suffix strips it."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project.git")
        assert result == "org/project"

    def test_url_with_settings_path(self, mock_client):
        """URL with /-/ settings path strips it."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project/-/settings/repository")
        assert result == "org/project"

    def test_url_with_hyphen_only(self, mock_client):
        """URL with /- path strips it."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project/-")
        assert result == "org/project"

    def test_bare_path_simple(self, mock_client):
        """Bare path without URL scheme."""
        result = mock_client._extract_path_from_url("org/project")
        assert result == "org/project"

    def test_bare_path_with_slashes(self, mock_client):
        """Bare path with leading/trailing slashes."""
        result = mock_client._extract_path_from_url("/org/project/")
        assert result == "org/project"

    def test_single_segment(self, mock_client):
        """Single segment (group only)."""
        result = mock_client._extract_path_from_url("myorg")
        assert result == "myorg"

    def test_single_segment_url(self, mock_client):
        """Single segment in URL form."""
        result = mock_client._extract_path_from_url("https://gitlab.com/myorg")
        assert result == "myorg"

    def test_deeply_nested_path(self, mock_client):
        """Deeply nested group/project path."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/team/subteam/project")
        assert result == "org/team/subteam/project"

    def test_deeply_nested_bare_path(self, mock_client):
        """Deeply nested bare path."""
        result = mock_client._extract_path_from_url("org/team/sub/project")
        assert result == "org/team/sub/project"

    def test_url_with_tree_path(self, mock_client):
        """URL pointing to a branch/tree strips the extra path."""
        # Note: Current implementation would include /-/ so this tests the /-/ stripping
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project/-/tree/main")
        assert result == "org/project"

    def test_url_with_merge_requests_path(self, mock_client):
        """URL pointing to merge requests strips the extra path."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/project/-/merge_requests")
        assert result == "org/project"

    def test_custom_gitlab_instance(self, mock_client):
        """URL from custom GitLab instance."""
        result = mock_client._extract_path_from_url("https://gitlab.mycompany.com/team/service")
        assert result == "team/service"

    def test_path_with_dots(self, mock_client):
        """Path containing dots (not .git suffix)."""
        result = mock_client._extract_path_from_url("https://gitlab.com/org/my.project.name")
        assert result == "org/my.project.name"

    def test_path_with_hyphens(self, mock_client):
        """Path containing hyphens."""
        result = mock_client._extract_path_from_url("https://gitlab.com/my-org/my-project")
        assert result == "my-org/my-project"

    def test_path_with_underscores(self, mock_client):
        """Path containing underscores."""
        result = mock_client._extract_path_from_url("https://gitlab.com/my_org/my_project")
        assert result == "my_org/my_project"
