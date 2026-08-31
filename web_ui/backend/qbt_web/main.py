"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse

from qbt_web.auth import (
    SESSION_COOKIE_NAME,
    Principal,
    SharedAuthClient,
    SharedAuthError,
    session_token_from_cookie,
)
from qbt_web.config import settings

# Routers import qbt analytics during application startup. Register the configured
# core source tree before importing them so a local uvicorn start is self-contained.
qbt_src = str(settings.qbt_src)
if qbt_src not in sys.path:
    sys.path.insert(0, qbt_src)

from qbt_web import db  # noqa: E402
from qbt_web.routers import artifacts, factor_values, meta, runs  # noqa: E402

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def shared_authentication(request: Request, call_next):
    path = request.url.path
    public_api = request.method == "OPTIONS" or path in {"/api/health", "/api/auth/login"}
    if not path.startswith("/api/") or public_api:
        return await call_next(request)

    if not settings.qbt_auth_required:
        request.state.principal = Principal(0, "local", "admin", "local-csrf-token")
        return await call_next(request)

    token = session_token_from_cookie(request.headers.get("cookie", ""))
    try:
        principal = await asyncio.to_thread(SharedAuthClient().principal, token)
    except SharedAuthError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
    if principal is None:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("X-CSRF-Token", "") != principal.csrf_token:
            return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    request.state.principal = principal
    return await call_next(request)


app.include_router(meta.router)
app.include_router(runs.router)
app.include_router(artifacts.router)
app.include_router(factor_values.router)

# Static frontend files
dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")


@app.on_event("startup")
async def startup():
    if settings.qbt_auth_required and not settings.factor_platform_url:
        raise RuntimeError("QBT_AUTH_REQUIRED=true requires FACTOR_PLATFORM_URL")
    db.init_db()
    db.fail_interrupted_runs()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/auth/login")
async def login(request: Request):
    try:
        payload = await request.json()
        token, principal = await asyncio.to_thread(
            SharedAuthClient().login,
            str(payload.get("username", "")),
            str(payload.get("password", "")),
        )
    except SharedAuthError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
    except (AttributeError, ValueError):
        return JSONResponse({"detail": "Invalid login request"}, status_code=400)
    response = JSONResponse({"user": principal.public_dict(), "auth_source": "factor-platform"})
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=43_200,
        httponly=True,
        secure=settings.qbt_secure_cookies,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/api/auth/me")
async def current_user(request: Request):
    principal = request.state.principal
    return {"user": principal.public_dict(), "auth_source": "factor-platform"}


@app.post("/api/auth/logout")
async def logout(request: Request):
    principal = request.state.principal
    token = session_token_from_cookie(request.headers.get("cookie", ""))
    try:
        await asyncio.to_thread(SharedAuthClient().logout, token, principal.csrf_token)
    except SharedAuthError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/api/runs/{run_id}/artifacts/{path:path}")
async def artifact_route(run_id: str, path: str, request: Request):
    """Keep the explicit route registration before the catch-all."""
    return await artifacts.get_artifact(run_id, path, request)


# Serve the SPA for all other routes.
@app.get("/{full_path:path}")
async def spa_catch_all(full_path: str):
    if dist_dir.exists():
        index = dist_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
    return {"message": f"{settings.app_name} API is running"}
