"""Build the qbt long-form warehouse from a qpf RQData panel snapshot."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .hashing import hash_file, hash_json

__all__ = ["RQSnapshotIngestConfig", "build_rq_snapshot_warehouse"]


_SOURCE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
    "float_shares",
    "total_shares",
    "float_market_cap",
    "market_cap",
    "pe",
    "pb",
    "ps",
    "pcf",
    "limit_up",
    "limit_down",
    "is_st",
    "listed_days",
)


@dataclass(frozen=True)
class RQSnapshotIngestConfig:
    snapshot_dir: Path
    output_dir: Path
    overwrite: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_dir", Path(self.snapshot_dir).resolve())
        object.__setattr__(self, "output_dir", Path(self.output_dir).resolve())


def _read_matrix(snapshot: Path, field: str, year: int, tickers: pd.Index) -> pd.DataFrame:
    path = snapshot / "fields" / field / f"year={year}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"RQData snapshot field partition missing: {path}")
    frame = pd.read_parquet(path)
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    frame.columns = frame.columns.astype(str)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"Invalid date axis: {path}")
    return frame.reindex(columns=tickers)


def _listing_bounds(
    snapshot: Path,
    years: list[int],
    tickers: pd.Index,
    snapshot_start: pd.Timestamp,
    snapshot_end: pd.Timestamp,
    metadata: dict,
) -> tuple[pd.Series, pd.Series, pd.Series, bool]:
    instruments_ref = metadata.get("instruments", {})
    instruments_path = snapshot / instruments_ref.get("path", "instruments.parquet")
    if instruments_path.is_file():
        instruments = pd.read_parquet(instruments_path)
        required = {"asset_id", "listed_date", "de_listed_date"}
        missing = sorted(required - set(instruments.columns))
        if missing:
            raise ValueError(f"RQData instrument master missing columns: {missing}")
        if instruments["asset_id"].astype(str).duplicated().any():
            raise ValueError("RQData instrument master contains duplicate asset_id")
        instruments = instruments.assign(asset_id=instruments["asset_id"].astype(str)).set_index(
            "asset_id"
        )
        unknown = tickers.difference(instruments.index)
        if len(unknown):
            raise ValueError(
                "RQData instrument master omitted snapshot assets: " + ", ".join(unknown[:5])
            )
        first = pd.to_datetime(instruments["listed_date"], errors="coerce").reindex(tickers)
        declared_delist = pd.to_datetime(
            instruments["de_listed_date"], errors="coerce"
        ).reindex(tickers)
        effective_last = declared_delist.where(declared_delist <= snapshot_end, snapshot_end)
        effective_last = effective_last.fillna(snapshot_end)
        return first, effective_last, declared_delist, True

    first = pd.Series(pd.NaT, index=tickers, dtype="datetime64[ns]")
    last = pd.Series(pd.NaT, index=tickers, dtype="datetime64[ns]")
    seen_at_start = pd.Series(False, index=tickers)
    for year in years:
        listed = _read_matrix(snapshot, "listed_days", year, tickers)
        valid = listed.notna()
        if year == years[0]:
            seen_at_start = valid.iloc[0]
        for ticker in tickers:
            values = listed[ticker]
            day_one = values.index[values.eq(1.0)]
            if len(day_one) and pd.isna(first[ticker]):
                first[ticker] = day_one[0]
            active = values.index[values.notna()]
            if len(active):
                last[ticker] = active[-1]
    # Exact listing dates are available for IPOs inside the snapshot. Older names only
    # need to be known as already listed at the snapshot boundary.
    first.loc[first.isna() & seen_at_start] = snapshot_start - pd.Timedelta(days=1)
    return first, last, pd.Series(pd.NaT, index=tickers, dtype="datetime64[ns]"), False


def _safe_divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    out = np.full(numerator.shape, np.nan, dtype="float64")
    np.divide(numerator, denominator, out=out, where=np.isfinite(denominator) & (denominator > 0))
    return out


def _build_year(
    snapshot: Path,
    year: int,
    tickers: pd.Index,
    listed_first: pd.Series,
    listed_last: pd.Series,
    previous_close: pd.Series,
) -> tuple[pd.DataFrame, pd.Series]:
    matrices = {field: _read_matrix(snapshot, field, year, tickers) for field in _SOURCE_FIELDS}
    close = matrices["close"]
    dates = close.index
    for field, frame in matrices.items():
        if not frame.index.equals(dates):
            raise ValueError(f"RQData field date mismatch for {field}, year={year}")

    extended = pd.concat(
        [pd.DataFrame([previous_close], index=[dates[0] - pd.Timedelta(days=1)]), close]
    )
    prev_close = extended.ffill().shift(1).iloc[1:]
    previous_close = close.ffill().iloc[-1].combine_first(previous_close)

    valid = matrices["listed_days"].notna() | close.notna()
    row_pos, col_pos = np.nonzero(valid.to_numpy())

    def take(field: str) -> np.ndarray:
        return matrices[field].to_numpy(dtype="float64", copy=False)[row_pos, col_pos]

    adj_open = take("open")
    adj_high = take("high")
    adj_low = take("low")
    adj_close = take("close")
    adj_prev_close = prev_close.to_numpy(dtype="float64", copy=False)[row_pos, col_pos]
    volume = take("volume")
    amount = take("amount")
    total_shares = take("total_shares")
    total_mktcap = take("market_cap")
    raw_close = _safe_divide(total_mktcap, total_shares)
    adj_factor = _safe_divide(adj_close, raw_close)
    raw_open = _safe_divide(adj_open, adj_factor)
    raw_vwap = _safe_divide(amount, volume)
    adj_vwap = raw_vwap * adj_factor
    pct_change = _safe_divide(adj_close, adj_prev_close) - 1.0
    raw_limit_up = _safe_divide(take("limit_up"), adj_factor)
    raw_limit_down = _safe_divide(take("limit_down"), adj_factor)

    asset_values = tickers.to_numpy()[col_pos]
    frame = pd.DataFrame(
        {
            "asset_id": pd.Categorical(asset_values, categories=tickers),
            "date": dates.to_numpy()[row_pos],
            "adj_open": adj_open.astype("float32"),
            "adj_high": adj_high.astype("float32"),
            "adj_low": adj_low.astype("float32"),
            "adj_close": adj_close.astype("float32"),
            "adj_prev_close": adj_prev_close.astype("float32"),
            "adj_vwap": adj_vwap.astype("float32"),
            "raw_open": raw_open.astype("float32"),
            "raw_close": raw_close.astype("float32"),
            "raw_vwap": raw_vwap.astype("float32"),
            "adj_factor": adj_factor.astype("float32"),
            "pct_change": pct_change.astype("float32"),
            "volume": volume,
            "amount": amount,
            "turnover_rate": take("turnover").astype("float32"),
            "float_mktcap": take("float_market_cap"),
            "total_mktcap": total_mktcap,
            "float_shares": take("float_shares"),
            "total_shares": total_shares,
            "pe": take("pe").astype("float32"),
            "pb": take("pb").astype("float32"),
            "ps": take("ps").astype("float32"),
            "pcf": take("pcf").astype("float32"),
            "raw_limit_up": raw_limit_up.astype("float32"),
            "raw_limit_down": raw_limit_down.astype("float32"),
            "is_st": take("is_st") > 0.5,
            "listed_days": take("listed_days").astype("float32"),
            "listed_first_date": pd.to_datetime(listed_first.reindex(asset_values).to_numpy()),
            "listed_last_date": pd.to_datetime(listed_last.reindex(asset_values).to_numpy()),
        }
    )
    frame["ohlc_violation"] = (
        (frame["adj_high"] < frame[["adj_open", "adj_close"]].max(axis=1))
        | (frame["adj_low"] > frame[["adj_open", "adj_close"]].min(axis=1))
        | (frame["adj_high"] < frame["adj_low"])
    ).fillna(False)
    return frame.sort_values(["date", "asset_id"], ignore_index=True), previous_close


def build_rq_snapshot_warehouse(cfg: RQSnapshotIngestConfig) -> dict:
    snapshot = cfg.snapshot_dir
    metadata_path = snapshot / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    missing = sorted(set(_SOURCE_FIELDS) - set(metadata.get("fields", {})))
    if missing:
        raise ValueError(f"RQData snapshot missing required fields: {missing}")
    if metadata.get("price_adjustment") != "post":
        raise ValueError("RQData snapshot must use post-adjusted prices")

    tickers = pd.Index([str(value) for value in metadata["tickers"]], name="asset_id")
    dates = pd.DatetimeIndex(metadata["dates"]).normalize()
    years = sorted(set(dates.year))
    output = cfg.output_dir
    target_prices = output / "daily_prices"
    if target_prices.exists() and not cfg.overwrite:
        raise FileExistsError(f"Target warehouse already exists: {target_prices}")
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".rqdata_warehouse_stage_", dir=output))
    stage_prices = stage / "daily_prices"
    stage_prices.mkdir()

    try:
        listed_first, listed_last, declared_delist, delist_data_available = _listing_bounds(
            snapshot, years, tickers, dates[0], dates[-1], metadata
        )
        previous_close = pd.Series(np.nan, index=tickers, dtype="float64")
        partitions = []
        total_rows = 0
        for year in years:
            frame, previous_close = _build_year(
                snapshot, year, tickers, listed_first, listed_last, previous_close
            )
            path = stage_prices / f"daily_prices_{year}.parquet"
            frame.to_parquet(path, index=False, compression="snappy")
            total_rows += len(frame)
            partitions.append(
                {
                    "path": f"daily_prices/{path.name}",
                    "year": year,
                    "rows": len(frame),
                    "date_min": str(frame["date"].min().date()),
                    "date_max": str(frame["date"].max().date()),
                    "sha256": f"sha256:{hash_file(path)}",
                }
            )

        calendar_path = stage / "trading_calendar.parquet"
        pd.DataFrame({"date": dates}).to_parquet(calendar_path, index=False)
        calendar_ref = {
            "path": calendar_path.name,
            "rows": len(dates),
            "date_min": str(dates[0].date()),
            "date_max": str(dates[-1].date()),
            "sha256": f"sha256:{hash_file(calendar_path)}",
            "source": "rqdata_snapshot_metadata.dates",
        }
        (stage / "trading_calendar.meta.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "source": "rqdata_snapshot_metadata.dates",
                    "source_content_hash": metadata.get("content_hash"),
                    "cache_hash": hash_file(calendar_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        asset_master_path = stage / "asset_master.parquet"
        pd.DataFrame(
            {
                "asset_id": tickers,
                "listed_first_date": listed_first.to_numpy(),
                "listed_last_date": listed_last.to_numpy(),
                "de_listed_date": declared_delist.to_numpy(),
                "present_at_snapshot_start": listed_first.le(dates[0]).to_numpy(),
                "present_at_snapshot_end": listed_last.ge(dates[-1]).to_numpy(),
            }
        ).to_parquet(asset_master_path, index=False)
        asset_master_ref = {
            "path": asset_master_path.name,
            "rows": len(tickers),
            "sha256": f"sha256:{hash_file(asset_master_path)}",
            "source": (
                "rqdata_snapshot_instruments"
                if delist_data_available
                else "legacy_derived_from_rqdata_listed_days"
            ),
        }

        manifest = {
            "schema_version": "qbt_rqdata_warehouse/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "uri": str(snapshot),
                "format_version": metadata.get("format_version"),
                "provider": metadata.get("provider"),
                "price_adjustment": metadata.get("price_adjustment"),
                "content_hash": metadata.get("content_hash"),
            },
            "date_min": str(dates[0].date()),
            "date_max": str(dates[-1].date()),
            "trading_days": len(dates),
            "assets": len(tickers),
            "delist_data_available": delist_data_available,
            "delisted_assets": int(declared_delist.le(dates[-1]).fillna(False).sum()),
            "rows": total_rows,
            "partitions": partitions,
            "trading_calendar": calendar_ref,
            "asset_master": asset_master_ref,
            "supported_indexes": [
                {
                    "index_id": "ALL_A_EQ",
                    "name": "流动性过滤后的非 ST A 股",
                    "source": "derived_from_rqdata_daily_panel",
                }
            ],
            "eligibility_policy": {
                "min_listed_days": 60,
                "exclude_st": True,
                "require_positive_amount": True,
                "average_amount_window": 20,
                "minimum_average_daily_amount": 20_000_000.0,
            },
            "limitations": (
                []
                if delist_data_available
                else [
                    "Legacy snapshot has no official de_listed_date instrument master; delisting status is inferred from listed_days.",
                    "Exact listing dates before the snapshot boundary are represented as already-listed boundary dates.",
                ]
            ),
        }
        manifest["warehouse_content_hash"] = (
            f"sha256:{hash_json({'partitions': partitions, 'trading_calendar': calendar_ref, 'asset_master': asset_master_ref})}"
        )
        (stage / "rqdata_warehouse_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        backup = output / ".daily_prices_previous"
        if backup.exists():
            shutil.rmtree(backup)
        if target_prices.exists():
            target_prices.rename(backup)
        try:
            stage_prices.rename(target_prices)
            for name in (
                "trading_calendar.parquet",
                "trading_calendar.meta.json",
                "asset_master.parquet",
                "rqdata_warehouse_manifest.json",
            ):
                (stage / name).replace(output / name)
            # An RQData-only warehouse must not retain membership copied from
            # another provider. Unsupported indexes are rejected by the portal.
            shutil.rmtree(output / "index_membership", ignore_errors=True)
        except Exception:
            if not target_prices.exists() and backup.exists():
                backup.rename(target_prices)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return manifest
    finally:
        shutil.rmtree(stage, ignore_errors=True)
