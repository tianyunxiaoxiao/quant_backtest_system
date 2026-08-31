"""Authenticated bridge from the research platform to immutable qbt inputs."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from qbt_web.auth import upstream_cookie
from qbt_web.config import settings

SIGNATURE_VERSION = "qpf-hmac-v1"


class FactorPlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlatformFactorPayload:
    metadata: dict
    content: bytes


class FactorPlatformClient:
    def __init__(self) -> None:
        required = {
            "factor_platform_url": settings.factor_platform_url,
            "factor_task_api_url": settings.factor_task_api_url,
            "factor_task_api_key_id": settings.factor_task_api_key_id,
            "factor_task_api_secret": settings.factor_task_api_secret,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise FactorPlatformError(f"因子平台连接未配置: {', '.join(missing)}")

    @staticmethod
    def configured() -> bool:
        return all(
            (
                settings.factor_platform_url,
                settings.factor_task_api_url,
                settings.factor_task_api_key_id,
                settings.factor_task_api_secret,
            )
        )

    def list_visible(self, cookie: str) -> list[dict]:
        payload = self._public_json("/api/factors", cookie)
        return list(payload.get("factors", []))

    def fetch_visible_version(
        self,
        factor_id: str,
        version_id: str,
        cookie: str,
    ) -> PlatformFactorPayload:
        encoded = quote(factor_id, safe="")
        # The public endpoint enforces the logged-in user's ownership boundary.
        self._public_json(f"/api/factors/{encoded}", cookie)
        factor = self._internal_json(f"/internal/v1/factors/{encoded}")["factor"]
        current_version = str(
            factor.get("summary", {}).get("factor_version_id") or factor.get("source_run_id") or ""
        )
        if not version_id or current_version != version_id:
            raise FactorPlatformError(
                f"因子版本已变化: 请求 {version_id}, 当前 {current_version}; 请刷新因子列表"
            )
        content = self._internal_bytes(f"/internal/v1/factors/{encoded}/values")
        expected = factor.get("summary", {}).get("factor_values_hash")
        if expected:
            filename = str(factor.get("values_path") or "")
            digest = hashlib.sha256(filename.encode("utf-8") + content).hexdigest()
            actual = f"sha256:{digest}"
            if not hmac.compare_digest(str(expected), actual):
                raise FactorPlatformError("因子值文件哈希校验失败")
        return PlatformFactorPayload(metadata=factor, content=content)

    def _public_json(self, path: str, cookie: str) -> dict:
        forwarded_cookie = upstream_cookie(cookie)
        if not forwarded_cookie:
            raise FactorPlatformError("未检测到因子平台登录会话")
        request = Request(
            urljoin(settings.factor_platform_url.rstrip("/") + "/", path.lstrip("/")),
            headers={"Cookie": forwarded_cookie, "Accept": "application/json"},
            method="GET",
        )
        return self._read_json(request)

    def _internal_json(self, path: str) -> dict:
        return json.loads(self._internal_bytes(path).decode("utf-8"))

    def _internal_bytes(self, path: str) -> bytes:
        timestamp = datetime.now(timezone.utc).isoformat()
        nonce = secrets.token_urlsafe(24)
        body_hash = hashlib.sha256(b"").hexdigest()
        canonical = "\n".join((SIGNATURE_VERSION, "GET", path, timestamp, nonce, body_hash)).encode(
            "utf-8"
        )
        signature = hmac.new(
            settings.factor_task_api_secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()
        request = Request(
            urljoin(settings.factor_task_api_url.rstrip("/") + "/", path.lstrip("/")),
            headers={
                "X-QPF-Key-Id": settings.factor_task_api_key_id,
                "X-QPF-Timestamp": timestamp,
                "X-QPF-Nonce": nonce,
                "X-QPF-Signature": signature,
                "X-QPF-Signature-Version": SIGNATURE_VERSION,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise FactorPlatformError(f"因子平台内部接口失败: {exc}") from exc

    @staticmethod
    def _read_json(request: Request) -> dict:
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise FactorPlatformError(f"因子平台用户接口失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise FactorPlatformError("因子平台返回了无效响应")
        return payload
