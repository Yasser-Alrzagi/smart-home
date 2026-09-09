"""Unit tests for the desktop client transport layer (stdlib urllib)."""

import io
import json
import urllib.error
import urllib.request
from unittest import mock

from desktop_client.api import ApiClient, ApiError


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def patch_urlopen(payload, status=200):
    return mock.patch(
        "urllib.request.urlopen",
        return_value=FakeResponse(json.dumps(payload).encode(), status=status),
    )


def test_login_stores_token_and_force_flag():
    with patch_urlopen(
        {
            "access_token": "tok123",
            "token_type": "bearer",
            "expires_in": 1800,
            "password_change_required": True,
        }
    ):
        client = ApiClient("http://127.0.0.1:8000")
        result = client.login("admin", "secret")
    assert client.token == "tok123"
    assert client.password_change_required is True
    assert result["expires_in"] == 1800


def test_login_failure_raises_api_error_with_detail():
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "http://x", 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"Incorrect username or password"}')
        ),
    ):
        client = ApiClient()
        try:
            client.login("admin", "wrong")
        except ApiError as exc:
            assert exc.status == 401
            assert "Incorrect" in exc.detail
        else:  # pragma: no cover
            raise AssertionError("ApiError was not raised")


def test_authenticated_requests_carry_bearer_header():
    with patch_urlopen({"access_token": "tok", "password_change_required": False}):
        client = ApiClient()
        client.login("admin", "x")
    captured = {}

    def fake_urlopen(request, timeout=15):
        captured["header"] = request.get_header("Authorization")
        return FakeResponse(b'{"unread": 3}')

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        count = client.unread_count()
    assert count == 3
    assert captured["header"] == "Bearer tok"


def test_change_password_posts_json_body():
    with patch_urlopen({"access_token": "tok", "password_change_required": True}):
        client = ApiClient()
        client.login("admin", "x")

    captured = {}

    def fake_urlopen(request, timeout=15):
        captured["body"] = request.data
        return FakeResponse(b"", status=204)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.change_password("old", "New Pass 2026!")
    payload = json.loads(captured["body"])
    assert payload == {"current_password": "old", "new_password": "New Pass 2026!"}


def test_logout_clears_token_even_on_network_error():
    with patch_urlopen({"access_token": "tok", "password_change_required": False}):
        client = ApiClient()
        client.login("admin", "x")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        client.logout()  # must swallow the error
    assert client.token is None


def test_connection_error_surfaces_as_api_error():
    with patch_urlopen({"access_token": "tok", "password_change_required": False}):
        client = ApiClient()
        client.login("admin", "x")
    with mock.patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("refused")
    ):
        try:
            client.get_json("/api/v1/auth/users/me")
        except ApiError as exc:
            assert exc.status == 0
            assert "تعذر الاتصال" in exc.detail
        else:  # pragma: no cover
            raise AssertionError("ApiError was not raised")
