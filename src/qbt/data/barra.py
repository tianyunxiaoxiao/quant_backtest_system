"""Point-in-time RQData Barra v2 style-exposure loading."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .hashing import hash_file

__all__ = [
    "BARRA_STYLE_MAPPING",
    "load_barra_factor_returns",
    "load_barra_style_exposures",
]


BARRA_STYLE_MAPPING = {
    "Size": "size",
    "Value": "book_to_price",
    "Momentum": "momentum",
    "Volatility": "residual_volatility",
    "Liquidity": "liquidity",
    "Growth": "growth",
    "Quality": "earnings_quality",
    "Leverage": "leverage",
}

_SUFFIXES = {"XSHE": "SZ", "XSHG": "SH", "XBEI": "BJ"}


def _to_asset_id(values: pd.Series) -> pd.Series:
    parts = values.astype("string").str.rsplit(".", n=1, expand=True)
    if parts.shape[1] != 2:
        raise ValueError("Barra order_book_id 格式错误")
    suffix = parts[1].map(_SUFFIXES)
    if suffix.isna().any():
        bad = values.loc[suffix.isna()].dropna().astype(str).unique()[:5]
        raise ValueError(f"Barra 含未知交易所代码: {bad.tolist()}")
    return parts[0] + "." + suffix


def load_barra_style_exposures(
    root: str | Path,
    *,
    dates: pd.DatetimeIndex,
    assets: pd.Index,
    valid_mask: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, object]]:
    """Load eight Barra styles without carrying the 31 industry dummies in memory."""
    root = Path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Barra 清单不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("model") != "v2":
        raise ValueError(f"仅支持 Barra v2, 实际为 {manifest.get('model')!r}")
    factor_columns = set(manifest.get("exposure_factor_columns", []))
    missing_columns = sorted(set(BARRA_STYLE_MAPPING.values()) - factor_columns)
    if missing_columns:
        raise ValueError(f"Barra 清单缺少风格字段: {missing_columns}")

    dates = pd.DatetimeIndex(pd.to_datetime(dates)).normalize().sort_values().unique()
    dates.name = "date"
    assets = pd.Index(sorted(map(str, assets)), name="asset_id")
    requested = pd.DataFrame(index=dates, columns=assets, dtype="float32")
    chunks: dict[str, list[pd.DataFrame]] = {name: [] for name in BARRA_STYLE_MAPPING}
    asset_set = set(assets)
    loaded_rows = 0
    loaded_partitions: list[Path] = []
    manifest_first = pd.Timestamp(manifest.get("factor_return_first_date", "1900-01-01"))
    manifest_last = pd.Timestamp(manifest.get("factor_return_last_date", "1900-01-01"))

    for period in dates.to_period("M").unique():
        path = (
            root
            / "exposures"
            / f"year={period.year}"
            / f"month={period.month:02d}"
            / "barra_v2_exposure.parquet"
        )
        if not path.is_file():
            month_start = period.to_timestamp(how="start")
            month_end = period.to_timestamp(how="end").normalize()
            if month_end >= manifest_first and month_start <= manifest_last:
                raise FileNotFoundError(f"Barra 清单覆盖期内缺少月度分区: {path}")
            continue
        frame = pd.read_parquet(
            path,
            columns=["date", "order_book_id", *BARRA_STYLE_MAPPING.values()],
        )
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        wanted_dates = dates[dates.to_period("M") == period]
        frame = frame.loc[frame["date"].isin(wanted_dates)].copy()
        frame["asset_id"] = _to_asset_id(frame["order_book_id"])
        frame = frame.loc[frame["asset_id"].isin(asset_set)]
        if frame.duplicated(["date", "asset_id"]).any():
            raise ValueError(f"Barra 暴露主键重复: {path}")
        loaded_rows += len(frame)
        loaded_partitions.append(path)
        for style, column in BARRA_STYLE_MAPPING.items():
            wide = frame.pivot(index="date", columns="asset_id", values=column)
            chunks[style].append(wide.astype("float32"))

    exposures: dict[str, pd.DataFrame] = {}
    coverage_rows: list[pd.DataFrame] = []
    universe = valid_mask.reindex(index=dates, columns=assets).fillna(False) if valid_mask is not None else None
    for style in BARRA_STYLE_MAPPING:
        panel = pd.concat(chunks[style]).sort_index() if chunks[style] else requested.copy()
        panel = panel.reindex(index=dates, columns=assets).astype("float32")
        panel.index.name = "date"
        panel.columns.name = "asset_id"
        exposures[style] = panel
        eligible_values = panel.where(universe) if universe is not None else panel
        denominator = universe.sum(axis=1) if universe is not None else pd.Series(len(assets), index=dates)
        coverage_rows.append(
            pd.DataFrame(
                {
                    "style": style,
                    "n_valid": eligible_values.notna().sum(axis=1),
                    "n_universe": denominator,
                },
                index=dates,
            )
        )

    coverage = pd.concat(coverage_rows)
    coverage["coverage"] = coverage["n_valid"] / coverage["n_universe"].where(
        coverage["n_universe"] > 0
    )
    coverage = coverage.reset_index()
    available_dates = pd.DatetimeIndex(
        sorted({date for panel in exposures.values() for date in panel.dropna(how="all").index})
    )
    integrity_path = root / "qbt_barra_integrity.json"
    content_hash = hash_file(integrity_path if integrity_path.is_file() else manifest_path)
    metadata: dict[str, object] = {
        "data_source": "rqdata_barra_v2",
        "uri": str(root.resolve()),
        "content_hash": content_hash,
        "rows": loaded_rows,
        "columns": len(BARRA_STYLE_MAPPING),
        "partitions": len(loaded_partitions),
        "date_min": str(available_dates.min().date()) if len(available_dates) else None,
        "date_max": str(available_dates.max().date()) if len(available_dates) else None,
        "mapping": dict(BARRA_STYLE_MAPPING),
        "missing_styles": [],
    }
    return exposures, coverage, metadata


def load_barra_factor_returns(
    root: str | Path,
    *,
    dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load the eight daily Barra style-factor returns without filling gaps."""
    root = Path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Barra 清单不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("model") != "v2":
        raise ValueError(f"仅支持 Barra v2, 实际为 {manifest.get('model')!r}")

    dates = pd.DatetimeIndex(pd.to_datetime(dates)).normalize().sort_values().unique()
    provider_columns = list(BARRA_STYLE_MAPPING.values())
    chunks: list[pd.DataFrame] = []
    loaded_files: list[Path] = []
    for year in sorted(set(dates.year)):
        path = root / "factor_returns" / f"barra_v2_factor_returns_{year}.parquet"
        if not path.is_file():
            continue
        frame = pd.read_parquet(path, columns=["date", *provider_columns])
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame = frame.loc[frame["date"].isin(dates)]
        chunks.append(frame)
        loaded_files.append(path)

    if not chunks:
        result = pd.DataFrame(
            index=dates,
            columns=[style.lower() for style in BARRA_STYLE_MAPPING],
            dtype="float64",
        )
    else:
        combined = pd.concat(chunks, ignore_index=True)
        if combined.duplicated("date").any():
            raise ValueError("Barra 因子收益日期重复")
        rename = {provider: style.lower() for style, provider in BARRA_STYLE_MAPPING.items()}
        result = combined.set_index("date")[provider_columns].rename(columns=rename)
        result = result.reindex(dates).astype("float64")
    result.index.name = "date"
    available = result.dropna(how="all").index
    return result, {
        "data_source": "rqdata_barra_v2_factor_returns",
        "files": len(loaded_files),
        "date_min": str(available.min().date()) if len(available) else None,
        "date_max": str(available.max().date()) if len(available) else None,
        "styles": list(result.columns),
    }
