"""Application settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EMBEDDED_QBT_ROOT = _PROJECT_ROOT.parent


def _default_qbt_root() -> Path:
    if (_EMBEDDED_QBT_ROOT / "src" / "qbt").is_dir():
        return _EMBEDDED_QBT_ROOT
    return _PROJECT_ROOT.parent / "quant_backtest_system_clean"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qbt_project_root: Path = _default_qbt_root()
    qbt_warehouse: Path | None = None
    qbt_index_dir: Path | None = None
    output_root: Path = _PROJECT_ROOT / "data" / "runs"
    database_path: Path = _PROJECT_ROOT / "qbt_web.db"
    cors_origins: list[str] = ["*"]
    app_name: str = "量化回测可视化"
    factor_platform_url: str | None = None
    factor_task_api_url: str | None = None
    factor_task_api_key_id: str | None = None
    factor_task_api_secret: str | None = None
    qbt_auth_required: bool = True
    qbt_secure_cookies: bool = False
    qbt_max_concurrent_runs: int = Field(default=1, ge=1, le=8)

    @property
    def qbt_src(self) -> Path:
        return self.qbt_project_root / "src"

    @property
    def warehouse_dir(self) -> Path:
        return self.qbt_warehouse or self.qbt_project_root / "warehouse_rqdata"

    @property
    def index_source_dir(self) -> Path:
        return self.qbt_index_dir or self.qbt_project_root / "data" / "index_membership_source"


settings = Settings()
