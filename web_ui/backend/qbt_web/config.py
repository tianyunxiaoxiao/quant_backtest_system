"""Application settings."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qbt_project_root: Path = _PROJECT_ROOT.parent / "quant_backtest_system_clean"
    qbt_warehouse: Path | None = None
    qbt_index_dir: Path | None = None
    output_root: Path = _PROJECT_ROOT / "data" / "runs"
    database_path: Path = _PROJECT_ROOT / "qbt_web.db"
    cors_origins: list[str] = ["*"]
    app_name: str = "量化回测可视化"

    @property
    def qbt_src(self) -> Path:
        return self.qbt_project_root / "src"

    @property
    def warehouse_dir(self) -> Path:
        return self.qbt_warehouse or self.qbt_project_root / "warehouse"

    @property
    def index_source_dir(self) -> Path:
        return self.qbt_index_dir or self.qbt_project_root / "data" / "index_membership_source"


settings = Settings()
