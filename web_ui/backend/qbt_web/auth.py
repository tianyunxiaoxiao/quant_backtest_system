"""Shared authentication backed by the factor research platform."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from qbt_web.config import settings

SESSION_COOKIE_NAME = "qbt_session"
UPSTREAM_COOKIE_NAME = "qpf_session"


class SharedAuthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    csrf_token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def from_payload(cls, payload: dict) -> "Principal":
        user = payload.get("user")
        if not isinstance(user, dict):
            raise SharedAuthError("因子平台返回了无效用户信息")
        return cls(
            user_id=int(user["user_id"]),
            username=str(user["username"]),
            role=str(user["role"]),
            csrf_token=str(user["csrf_token"]),
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "is_admin": self.is_admin,
            "csrf_token": self.csrf_token,
        }


class SharedAuthClient:
    def __init__(self) -> None:
        if not settings.factor_platform_url:
            raise SharedAuthError("未配置 FACTOR_PLATFORM_URL")
        self.base_url = settings.factor_platform_url.rstrip("/") + "/"

    def login(self, username: str, password: str) -> tuple[str, Principal]:
        request = Request(
            urljoin(self.base_url, "api/auth/login"),
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        payload, headers = self._json(request)
        cookie = SimpleCookie()
        for value in headers.get_all("Set-Cookie", []):
            cookie.load(value)
        session = cookie.get(UPSTREAM_COOKIE_NAME)
        if session is None or not session.value:
            raise SharedAuthError("因子平台未签发登录会话")
        return session.value, Principal.from_payload(payload)

    def principal(self, token: str) -> Principal | None:
        if not token:
            return None
        request = Request(
            urljoin(self.base_url, "api/auth/me"),
            headers={
                "Cookie": f"{UPSTREAM_COOKIE_NAME}={token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            payload, _ = self._json(request)
        except SharedAuthError as exc:
            if exc.status_code in {401, 403}:
                return None
            raise
        return Principal.from_payload(payload)

    def logout(self, token: str, csrf_token: str) -> None:
        if not token:
            return
        request = Request(
            urljoin(self.base_url, "api/auth/logout"),
            data=b"{}",
            headers={
                "Cookie": f"{UPSTREAM_COOKIE_NAME}={token}",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf_token,
            },
            method="POST",
        )
        try:
            self._json(request)
        except SharedAuthError as exc:
            if exc.status_code not in {401, 403}:
                raise

    @staticmethod
    def _json(request: Request) -> tuple[dict, object]:
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                headers = response.headers
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
                message = str(payload.get("error") or payload.get("detail") or exc.reason)
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = str(exc.reason)
            raise SharedAuthError(message, status_code=exc.code) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SharedAuthError(f"无法连接因子平台认证服务: {exc}") from exc
        if not isinstance(payload, dict):
            raise SharedAuthError("因子平台返回了无效认证响应")
        return payload, headers


def session_token_from_cookie(cookie_header: str) -> str:
    parsed = SimpleCookie(cookie_header)
    for name in (SESSION_COOKIE_NAME, UPSTREAM_COOKIE_NAME):
        morsel = parsed.get(name)
        if morsel is not None and morsel.value:
            return morsel.value
    return ""


def upstream_cookie(cookie_header: str) -> str:
    token = session_token_from_cookie(cookie_header)
    return f"{UPSTREAM_COOKIE_NAME}={token}" if token else ""


def principal_from_request(request) -> Principal:
    return request.state.principal


def owns(principal: Principal, owner_user_id: int | None) -> bool:
    return principal.is_admin or owner_user_id == principal.user_id
