"""REST client for the desktop platform — Python standard library only.

Every call goes through the same RESTful API the web portal uses, so both
platforms share one database exclusively over HTTP. Tokens live in memory
only: nothing is ever written to disk.

Design notes (SRP):
    * This module owns ONE responsibility: JSON/HTTP transport + error model.
    * The Tkinter UI (app.py) never talks to urllib directly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 15


class ApiError(Exception):
    """Raised for any non-success HTTP response, carrying the server detail."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class ApiClient:
    """Thin typed facade over the Smart Home system REST API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or DEFAULT_API).rstrip("/")
        self.token: str | None = None
        self.password_change_required = False

    # ------------------------------------------------------------------ core
    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict | list | None]:
        """Perform one HTTP request and parse a JSON body when present."""
        url = self.base_url + path
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                body = resp.read()
                payload = json.loads(body) if body else None
                return resp.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = self._extract_detail(raw)
            raise ApiError(exc.code, detail) from None
        except urllib.error.URLError as exc:
            raise ApiError(0, f"تعذر الاتصال بالخادم ({exc.reason})") from None

    @staticmethod
    def _extract_detail(raw: bytes) -> str:
        """FastAPI errors carry {"detail": ...}; fall back to raw text."""
        try:
            payload = json.loads(raw or b"{}")
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list):  # validation errors
                return "؛ ".join(
                    str(item.get("msg", item)) for item in detail if isinstance(item, dict)
                ) or str(detail)
            if detail is not None:
                return str(detail)
        except (ValueError, TypeError):
            pass
        return (raw or b"").decode("utf-8", "replace")[:300] or "خطأ غير معروف"

    def _authed_headers(self) -> dict[str, str]:
        if not self.token:
            raise ApiError(401, "لا توجد جلسة مسجلة")
        return {"Authorization": f"Bearer {self.token}"}

    # ------------------------------------------------------------- identity
    def login(self, username: str, password: str) -> dict:
        """POST /auth/login/access-token. Returns raw token payload."""
        form = urllib.parse.urlencode({"username": username, "password": password}).encode()
        status, payload = self._request(
            "POST",
            "/api/v1/auth/login/access-token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert status == 200 and isinstance(payload, dict)
        self.token = payload["access_token"]
        self.password_change_required = bool(payload.get("password_change_required"))
        return payload

    def me(self) -> dict:
        """GET /auth/users/me — current user profile."""
        return self.get_json("/api/v1/auth/users/me")

    def change_password(self, current: str, new: str) -> None:
        """POST /auth/change-password. Raises ApiError on bad input."""
        status, _ = self._request(
            "POST",
            "/api/v1/auth/change-password",
            data=json.dumps({"current_password": current, "new_password": new}).encode(),
            headers={**self._authed_headers(), "Content-Type": "application/json"},
        )
        assert status == 204

    def logout(self) -> None:
        """POST /auth/logout — revokes the current session server-side."""
        try:
            self._request("POST", "/api/v1/auth/logout", headers=self._authed_headers())
        except ApiError:
            pass  # session already gone; local state is cleared regardless
        finally:
            self.token = None
            self.password_change_required = False

    # -------------------------------------------------------------- read API
    def get_json(self, path: str) -> dict | list:
        """Authenticated GET returning parsed JSON."""
        status, payload = self._request("GET", path, headers=self._authed_headers())
        assert status == 200 and payload is not None
        return payload

    def post_json(self, path: str, body: dict) -> dict | list | None:
        """Authenticated POST with a JSON body."""
        status, payload = self._request(
            "POST",
            path,
            data=json.dumps(body).encode(),
            headers={**self._authed_headers(), "Content-Type": "application/json"},
        )
        return payload

    # --------------------------------------------------------- high level
    def dashboard(self) -> dict:
        """GET /dashboards/me — role-scoped summary for the main window."""
        return self.get_json("/api/v1/dashboards/me")

    def list_users(self, limit: int = 50) -> dict:
        """GET /users — System Administrator only."""
        return self.get_json(f"/api/v1/users?limit={limit}")

    def create_user(
        self, username: str, email: str, role: str, password: str
    ) -> dict:
        """POST /users — System Administrator only."""
        result = self.post_json(
            "/api/v1/users",
            {"username": username, "email": email, "role": role, "password": password},
        )
        return result if isinstance(result, dict) else {}

    def applications(self, limit: int = 20) -> dict:
        """GET /applications — staff workflow queue."""
        return self.get_json(f"/api/v1/applications?limit={limit}")

    def notifications(self, limit: int = 30) -> dict:
        """GET /notifications/my — personal mailbox."""
        return self.get_json(f"/api/v1/notifications/my?limit={limit}")

    def unread_count(self) -> int:
        """GET /notifications/unread-count."""
        payload = self.get_json("/api/v1/notifications/unread-count")
        return int(payload.get("unread", 0)) if isinstance(payload, dict) else 0
