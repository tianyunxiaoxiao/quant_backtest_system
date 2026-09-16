#!/usr/bin/env python3
"""Incrementally update RQData Barra v2 data and atomically sync mirrors."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import rqdatac


INDEX_CODE = "000985.XSHG"
MODEL = "v2"
INDUSTRY_MAPPING = "sws_2021"
FACTOR_RETURN_UNIVERSE = "whole_market"
FACTOR_RETURN_METHOD = "implicit"


def call_with_retry(func, *args, attempts: int = 5, **kwargs):
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception:
            if attempt == attempts:
                raise
            delay = min(30, 2**attempt)
            print(f"request failed; retry {attempt}/{attempts} after {delay}s", flush=True)
            time.sleep(delay)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def latest_ready_date() -> date:
    latest = rqdatac.get_latest_trading_date(market="cn")
    return rqdatac.get_previous_trading_date(latest, market="cn")


def normalize_exposure(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.reset_index()
    required = {"date", "order_book_id"}
    if not required.issubset(result.columns):
        raise RuntimeError(
            f"Unexpected exposure result: index={frame.index.names}, "
            f"columns={list(frame.columns)}"
        )
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    result["order_book_id"] = result["order_book_id"].astype("string")
    return result


def month_ranges(start: pd.Timestamp, end: pd.Timestamp):
    cursor = start.to_period("M")
    final = end.to_period("M")
    while cursor <= final:
        yield max(start, cursor.start_time), min(end, cursor.end_time.normalize())
        cursor += 1


def refresh_factor_returns(root: Path, target: pd.Timestamp) -> Path:
    start = pd.Timestamp(target.year, 1, 1)
    raw = call_with_retry(
        rqdatac.get_factor_return,
        start,
        target,
        factors=None,
        universe=FACTOR_RETURN_UNIVERSE,
        method=FACTOR_RETURN_METHOD,
        industry_mapping=INDUSTRY_MAPPING,
        model=MODEL,
        market="cn",
    )
    frame = raw.reset_index()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.drop_duplicates(subset=["date"]).sort_values("date")
    if frame.empty or frame["date"].max() != target:
        raise RuntimeError(
            f"Barra factor returns not ready through {target.date()}; "
            f"observed={None if frame.empty else frame['date'].max().date()}"
        )
    yearly = root / "factor_returns" / f"barra_v2_factor_returns_{target.year}.parquet"
    atomic_parquet(frame, yearly)

    files = sorted((root / "factor_returns").glob("barra_v2_factor_returns_*.parquet"))
    combined = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.normalize()
    combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    atomic_parquet(combined, root / "barra_v2_factor_returns_2019_2026.parquet")
    return yearly


def refresh_components(root: Path, target: pd.Timestamp) -> tuple[pd.DataFrame, Path]:
    start = pd.Timestamp(target.year, 1, 1)
    mapping = call_with_retry(
        rqdatac.index_components,
        INDEX_CODE,
        start_date=start,
        end_date=target,
        market="cn",
    )
    records = [
        (pd.Timestamp(day).normalize(), order_book_id)
        for day, members in mapping.items()
        for order_book_id in members
    ]
    frame = pd.DataFrame.from_records(records, columns=["date", "order_book_id"])
    frame["order_book_id"] = frame["order_book_id"].astype("string")
    frame = frame.drop_duplicates().sort_values(["date", "order_book_id"])
    if frame.empty or frame["date"].max() != target:
        raise RuntimeError(
            f"CSI All Share components not ready through {target.date()}; "
            f"observed={None if frame.empty else frame['date'].max().date()}"
        )
    path = root / "components" / f"csi_all_share_components_{target.year}.parquet"
    atomic_parquet(frame, path)
    previous_path = (
        root / "components" / f"csi_all_share_components_{target.year - 1}.parquet"
    )
    if previous_path.is_file():
        previous = pd.read_parquet(previous_path)
        previous["date"] = pd.to_datetime(previous["date"]).dt.normalize()
        frame = pd.concat([previous, frame], ignore_index=True)
    return frame, path


def refresh_exposures(
    root: Path,
    membership: pd.DataFrame,
    target: pd.Timestamp,
    *,
    refresh_months: int,
    chunk_size: int,
) -> list[Path]:
    refresh_start = (target.to_period("M") - max(refresh_months - 1, 0)).start_time
    refreshed: list[Path] = []
    for month_start, month_end in month_ranges(refresh_start, target):
        month_members = membership.loc[
            membership["date"].between(month_start, month_end),
            ["date", "order_book_id"],
        ].drop_duplicates()
        if month_members.empty:
            raise RuntimeError(f"No component membership for {month_start:%Y-%m}")

        securities = sorted(month_members["order_book_id"].unique().tolist())
        pieces: list[pd.DataFrame] = []
        for offset in range(0, len(securities), chunk_size):
            ids = securities[offset : offset + chunk_size]
            raw = call_with_retry(
                rqdatac.get_factor_exposure,
                ids,
                start_date=month_start,
                end_date=month_end,
                factors=None,
                industry_mapping=INDUSTRY_MAPPING,
                model=MODEL,
                market="cn",
            )
            exposed = normalize_exposure(raw)
            valid = month_members[month_members["order_book_id"].isin(ids)]
            pieces.append(exposed.merge(valid, on=["date", "order_book_id"], how="inner"))
            print(
                f"exposure {month_start:%Y-%m}: "
                f"{min(offset + chunk_size, len(securities))}/{len(securities)} securities",
                flush=True,
            )

        frame = pd.concat(pieces, ignore_index=True)
        frame = frame.drop_duplicates(subset=["date", "order_book_id"])
        frame = frame.sort_values(["date", "order_book_id"])
        expected_end = pd.Timestamp(month_members["date"].max()).normalize()
        if frame.empty or frame["date"].max() != expected_end:
            raise RuntimeError(
                f"Barra exposure {month_start:%Y-%m} ends at "
                f"{None if frame.empty else frame['date'].max().date()}, "
                f"expected {expected_end.date()}"
            )
        path = (
            root
            / "exposures"
            / f"year={month_start.year}"
            / f"month={month_start.month:02d}"
            / "barra_v2_exposure.parquet"
        )
        atomic_parquet(frame, path)
        refreshed.append(path)
    return refreshed


def parquet_rows(paths: list[Path]) -> int:
    return sum(pq.ParquetFile(path).metadata.num_rows for path in paths)


def write_manifest(root: Path, target: pd.Timestamp) -> Path:
    combined = pd.read_parquet(
        root / "barra_v2_factor_returns_2019_2026.parquet", columns=["date"]
    )
    component_files = sorted((root / "components").glob("csi_all_share_components_*.parquet"))
    exposure_files = sorted(
        (root / "exposures").glob("year=*/month=*/barra_v2_exposure.parquet")
    )
    latest_schema = pq.ParquetFile(exposure_files[-1]).schema_arrow.names
    factor_columns = [c for c in latest_schema if c not in {"date", "order_book_id"}]
    payload = {
        "index_name": "中证全指",
        "index_code": INDEX_CODE,
        "requested_start": "2019-01-01",
        "requested_end": str(target.date()),
        "model": MODEL,
        "industry_mapping": INDUSTRY_MAPPING,
        "factor_return_universe": FACTOR_RETURN_UNIVERSE,
        "factor_return_method": FACTOR_RETURN_METHOD,
        "factor_return_rows": int(len(combined)),
        "factor_return_first_date": str(pd.to_datetime(combined["date"]).min().date()),
        "factor_return_last_date": str(pd.to_datetime(combined["date"]).max().date()),
        "component_membership_rows": parquet_rows(component_files),
        "exposure_rows": parquet_rows(exposure_files),
        "exposure_factor_columns": factor_columns,
        "credentials_stored_in_output": False,
        "update_mode": "daily_incremental_atomic",
    }
    path = root / "manifest.json"
    atomic_json(payload, path)
    return path


def sync_files(root: Path, mirror: Path, paths: list[Path]) -> None:
    for source in paths:
        atomic_copy(source, mirror / source.relative_to(root))


def validate(root: Path, target: pd.Timestamp) -> dict[str, str | int]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    factor_end = pd.to_datetime(
        pd.read_parquet(
            root / "barra_v2_factor_returns_2019_2026.parquet", columns=["date"]
        )["date"]
    ).max()
    exposure_files = sorted(
        (root / "exposures").glob("year=*/month=*/barra_v2_exposure.parquet")
    )
    exposure_end = pd.to_datetime(
        pd.read_parquet(exposure_files[-1], columns=["date"])["date"]
    ).max()
    if factor_end != target or exposure_end != target:
        raise RuntimeError(
            f"Validation failed for {root}: factor={factor_end.date()}, "
            f"exposure={exposure_end.date()}, target={target.date()}"
        )
    return {
        "root": str(root),
        "target_date": str(target.date()),
        "factor_return_last_date": str(factor_end.date()),
        "exposure_last_date": str(exposure_end.date()),
        "factor_return_rows": int(manifest["factor_return_rows"]),
        "exposure_rows": int(manifest["exposure_rows"]),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--root",
        type=Path,
        default=Path("/data/research/barra/rqdata_barra_v2_2019_2026"),
    )
    result.add_argument("--mirror", type=Path, action="append", default=[])
    result.add_argument("--target-date", type=date.fromisoformat)
    result.add_argument("--refresh-months", type=int, default=2)
    result.add_argument("--chunk-size", type=int, default=500)
    result.add_argument(
        "--lock-file", type=Path, default=Path("/run/lock/qbt-barra-update.lock")
    )
    return result


def main() -> int:
    args = parser().parse_args()
    if not os.environ.get("RQDATAC2_CONF") and not os.environ.get("RQDATAC_CONF"):
        raise RuntimeError("RQDATAC2_CONF/RQDATAC_CONF is required")
    args.root = args.root.resolve(strict=True)
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another Barra update is already running", file=sys.stderr)
            return 75

        rqdatac.init()
        target = pd.Timestamp(args.target_date or latest_ready_date()).normalize()
        try:
            reports = [validate(args.root, target)]
            reports.extend(validate(mirror.resolve(strict=True), target) for mirror in args.mirror)
        except (FileNotFoundError, KeyError, RuntimeError, ValueError):
            reports = []
        if reports:
            print(json.dumps({"status": "current", "datasets": reports}, ensure_ascii=False))
            return 0

        yearly_factor = refresh_factor_returns(args.root, target)
        membership, component_path = refresh_components(args.root, target)
        exposure_paths = refresh_exposures(
            args.root,
            membership,
            target,
            refresh_months=max(1, args.refresh_months),
            chunk_size=max(1, args.chunk_size),
        )
        manifest_path = write_manifest(args.root, target)
        changed = [
            yearly_factor,
            args.root / "barra_v2_factor_returns_2019_2026.parquet",
            component_path,
            *exposure_paths,
            manifest_path,
        ]
        reports = [validate(args.root, target)]
        for mirror in args.mirror:
            mirror = mirror.resolve(strict=True)
            sync_files(args.root, mirror, changed)
            reports.append(validate(mirror, target))
        print(json.dumps({"status": "updated", "datasets": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
