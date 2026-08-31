from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from qbt_web.auth import (
    SharedAuthClient,
    SharedAuthError,
    session_token_from_cookie,
    upstream_cookie,
)
from qbt_web.config import settings


class _Response:
    def __init__(self, payload: dict, *, cookie: str | None = None) -> None:
        self.content = json.dumps(payload).encode()
        self.headers = Message()
        if cookie:
            self.headers.add_header("Set-Cookie", cookie)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.content


def _user():
    return {
        "user_id": 7,
        "username": "alice",
        "role": "researcher",
        "is_admin": False,
        "csrf_token": "central-csrf",
    }


def _upstream(request, timeout=15):
    path = request.full_url.rsplit("/api/", 1)[-1]
    if path == "auth/login":
        payload = json.loads(request.data)
        if payload != {"username": "alice", "password": "correct-password"}:
            body = io.BytesIO(json.dumps({"error": "Authentication required."}).encode())
            raise HTTPError(request.full_url, 401, "Unauthorized", Message(), body)
        return _Response(
            {"user": _user()},
            cookie="qpf_session=central-token; Path=/; HttpOnly; SameSite=Strict",
        )
    if path == "auth/me":
        if request.get_header("Cookie") == "qpf_session=central-token":
            return _Response({"user": _user(), "auth_enabled": True})
        body = io.BytesIO(json.dumps({"error": "Authentication required."}).encode())
        raise HTTPError(request.full_url, 401, "Unauthorized", Message(), body)
    if path == "auth/logout":
        if (
            request.get_header("Cookie") == "qpf_session=central-token"
            and request.get_header("X-csrf-token") == "central-csrf"
        ):
            return _Response({"ok": True})
        body = io.BytesIO(json.dumps({"error": "Invalid CSRF token."}).encode())
        raise HTTPError(request.full_url, 403, "Forbidden", Message(), body)
    raise AssertionError(path)


class SharedAuthTest(unittest.TestCase):
    def setUp(self):
        self.old_url = settings.factor_platform_url
        settings.factor_platform_url = "https://factor.example.test"

    def tearDown(self):
        settings.factor_platform_url = self.old_url

    @patch("qbt_web.auth.urlopen", side_effect=_upstream)
    def test_login_me_logout_share_factor_platform_session(self, _mock_urlopen):
        client = SharedAuthClient()
        token, principal = client.login("alice", "correct-password")

        self.assertEqual(token, "central-token")
        self.assertEqual(principal.user_id, 7)
        self.assertEqual(principal.username, "alice")
        self.assertEqual(client.principal(token), principal)
        client.logout(token, principal.csrf_token)

    @patch("qbt_web.auth.urlopen", side_effect=_upstream)
    def test_invalid_login_and_cookie_translation(self, _mock_urlopen):
        with self.assertRaises(SharedAuthError) as context:
            SharedAuthClient().login("alice", "wrong")
        self.assertEqual(context.exception.status_code, 401)
        self.assertIsNone(SharedAuthClient().principal("expired"))
        self.assertEqual(session_token_from_cookie("qbt_session=central-token"), "central-token")
        self.assertEqual(upstream_cookie("qbt_session=central-token"), "qpf_session=central-token")


if __name__ == "__main__":
    unittest.main()
