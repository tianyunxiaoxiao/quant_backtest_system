"""FastAPI application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from qbt_web import db
from qbt_web.config import settings
from qbt_web.routers import artifacts, factor_values, meta, runs

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    db.init_db()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/runs/{run_id}/artifacts/{path:path}")
async def artifact_route(run_id: str, path: str):
    """Keep the explicit route registration before the catch-all."""
    return await artifacts.get_artifact(run_id, path)


# Serve the SPA for all other routes.
@app.get("/{full_path:path}")
async def spa_catch_all(full_path: str):
    if dist_dir.exists():
        index = dist_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
    return {"message": f"{settings.app_name} API is running"}
