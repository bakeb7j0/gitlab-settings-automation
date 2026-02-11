"""Tests for retry logic with exponential backoff."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
import responses

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Constants
MOCK_GITLAB_URL = "https://gitlab.example.com"
MOCK_API_URL = f"{MOCK_GITLAB_URL}/api/v4"

from gl_settings import (
    DEFAULT_MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    RETRYABLE_STATUS_CODES,
    GitLabClient,
)


class TestRetryOn429:
    """Tests for retry on rate limit (429) responses."""

    @responses.activate
    def test_429_triggers_retry(self):
        """429 response triggers retry and eventually succeeds."""
        # First call returns 429, second succeeds
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            status=429,
            headers={"Retry-After": "0.1"},
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={"id": 123, "name": "test"},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)
        result = client.get("/projects/123")

        assert result["id"] == 123
        assert len(responses.calls) == 2

    @responses.activate
    def test_429_respects_retry_after_header(self):
        """429 response uses Retry-After header for wait time."""
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            status=429,
            headers={"Retry-After": "0.05"},  # 50ms
        )
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={"id": 123},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)

        with patch("time.sleep") as mock_sleep:
            client.get("/projects/123")
            # Should have used Retry-After value
            mock_sleep.assert_called_once()
            assert mock_sleep.call_args[0][0] == 0.05


class TestRetryOn5xx:
    """Tests for retry on server error (5xx) responses."""

    @responses.activate
    def test_503_triggers_retry_with_backoff(self):
        """503 response triggers retry with exponential backoff."""
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=503)
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=503)
        responses.add(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            json={"id": 123},
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)

        with patch("time.sleep") as mock_sleep:
            result = client.get("/projects/123")
            assert result["id"] == 123
            assert len(responses.calls) == 3
            # Should have slept twice (before 2nd and 3rd attempts)
            assert mock_sleep.call_count == 2

    @responses.activate
    def test_all_retryable_status_codes(self):
        """All status codes in RETRYABLE_STATUS_CODES trigger retries."""
        for status_code in RETRYABLE_STATUS_CODES:
            responses.reset()
            responses.add(
                responses.GET,
                f"{MOCK_API_URL}/projects/123",
                status=status_code,
            )
            responses.add(
                responses.GET,
                f"{MOCK_API_URL}/projects/123",
                json={"id": 123},
            )

            client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=1)

            with patch("time.sleep"):
                result = client.get("/projects/123")
                assert result["id"] == 123, f"Failed for status code {status_code}"


class TestRetryOnConnectionError:
    """Tests for retry on connection errors."""

    @responses.activate
    def test_connection_error_triggers_retry(self):
        """Connection error triggers retry."""
        # Use callback to raise ConnectionError first, then succeed
        call_count = [0]

        def request_callback(request):
            call_count[0] += 1
            if call_count[0] == 1:
                raise requests.exceptions.ConnectionError("Connection refused")
            return (200, {}, '{"id": 123}')

        responses.add_callback(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            callback=request_callback,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)

        with patch("time.sleep"):
            result = client.get("/projects/123")
            assert result["id"] == 123
            assert call_count[0] == 2


class TestMaxRetriesExceeded:
    """Tests for behavior when max retries are exceeded."""

    @responses.activate
    def test_raises_after_max_retries_5xx(self):
        """Raises HTTPError after max retries exceeded for 5xx."""
        for _ in range(DEFAULT_MAX_RETRIES + 1):
            responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=503)

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=DEFAULT_MAX_RETRIES)

        with patch("time.sleep"):
            with pytest.raises(requests.HTTPError) as exc_info:
                client.get("/projects/123")
            assert exc_info.value.response.status_code == 503

    @responses.activate
    def test_raises_after_max_retries_connection_error(self):
        """Raises ConnectionError after max retries exceeded."""

        def always_fail(request):
            raise requests.exceptions.ConnectionError("Connection refused")

        responses.add_callback(
            responses.GET,
            f"{MOCK_API_URL}/projects/123",
            callback=always_fail,
        )

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=2)

        with patch("time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError):
                client.get("/projects/123")


class TestNoRetryOn4xx:
    """Tests that 4xx errors (except 429) are not retried."""

    @responses.activate
    def test_400_not_retried(self):
        """400 Bad Request is not retried."""
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=400)

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)

        with pytest.raises(requests.HTTPError):
            client.get("/projects/123")

        assert len(responses.calls) == 1  # No retry

    @responses.activate
    def test_403_not_retried(self):
        """403 Forbidden is not retried."""
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=403)

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)

        with pytest.raises(requests.HTTPError):
            client.get("/projects/123")

        assert len(responses.calls) == 1  # No retry

    @responses.activate
    def test_404_not_retried(self):
        """404 Not Found is not retried."""
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=404)

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=3)

        with pytest.raises(requests.HTTPError):
            client.get("/projects/123")

        assert len(responses.calls) == 1  # No retry


class TestBackoffCalculation:
    """Tests for exponential backoff calculation."""

    def test_backoff_increases_exponentially(self):
        """Backoff time increases exponentially with attempts."""
        client = GitLabClient(MOCK_GITLAB_URL, "test-token")

        # Create a mock response without Retry-After
        mock_response = requests.Response()
        mock_response.status_code = 503
        mock_response.headers = {}

        # Attempt 0: 0.5 * (2^0) = 0.5
        assert client._calculate_backoff(mock_response, 0) == RETRY_BACKOFF_FACTOR * 1
        # Attempt 1: 0.5 * (2^1) = 1.0
        assert client._calculate_backoff(mock_response, 1) == RETRY_BACKOFF_FACTOR * 2
        # Attempt 2: 0.5 * (2^2) = 2.0
        assert client._calculate_backoff(mock_response, 2) == RETRY_BACKOFF_FACTOR * 4

    def test_429_uses_retry_after_not_exponential(self):
        """429 with Retry-After header uses header value, not exponential."""
        client = GitLabClient(MOCK_GITLAB_URL, "test-token")

        mock_response = requests.Response()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "5.5"}

        # Should use Retry-After value regardless of attempt number
        assert client._calculate_backoff(mock_response, 0) == 5.5
        assert client._calculate_backoff(mock_response, 5) == 5.5

    def test_429_without_retry_after_uses_exponential(self):
        """429 without Retry-After header falls back to exponential backoff."""
        client = GitLabClient(MOCK_GITLAB_URL, "test-token")

        mock_response = requests.Response()
        mock_response.status_code = 429
        mock_response.headers = {}  # No Retry-After

        assert client._calculate_backoff(mock_response, 0) == RETRY_BACKOFF_FACTOR * 1
        assert client._calculate_backoff(mock_response, 1) == RETRY_BACKOFF_FACTOR * 2


class TestCustomMaxRetries:
    """Tests for custom max_retries configuration."""

    @responses.activate
    def test_custom_max_retries_respected(self):
        """Custom max_retries value is respected."""
        # Add 2 failures + 1 success = 3 total calls needed
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=503)
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=503)
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", json={"id": 123})

        # With max_retries=1, should fail (only 2 attempts: initial + 1 retry)
        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=1)

        with patch("time.sleep"):
            with pytest.raises(requests.HTTPError):
                client.get("/projects/123")

        assert len(responses.calls) == 2  # initial + 1 retry

    @responses.activate
    def test_zero_retries_no_retry(self):
        """max_retries=0 means no retries."""
        responses.add(responses.GET, f"{MOCK_API_URL}/projects/123", status=503)

        client = GitLabClient(MOCK_GITLAB_URL, "test-token", max_retries=0)

        with pytest.raises(requests.HTTPError):
            client.get("/projects/123")

        assert len(responses.calls) == 1  # Only initial attempt
