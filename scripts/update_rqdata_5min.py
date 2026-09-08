#!/usr/bin/env python3
"""Incrementally update raw A-share 5-minute HDF5 files from RQData."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

FIELDS = ("open", "high", "low", "close", "volume", "total_turnover", "num_trades")
DATA_DTYPE = np.dtype(
    [("datetime", "<i8"), *[(name, "<f8") for name in FIELDS[:-1]], ("num_trades", "<u8")]
)
INDEX_DTYPE = np.dtype([("date", "<i4"), ("line_no", "<u4")])
BAR_HHMM = np.array(
    [
        *range(935, 960, 5), *range(1000, 1060, 5), *range(1100, 1131, 5),
        *range(1305, 1360, 5), *range(1400, 1460, 5), 1500,
    ],
    dtype=np.int64,
)
BARS_PER_DAY = 48


@dataclass(frozen=True)
class FileRecord:
    filename: str
    ticker: str
    trading_days: int
    observations: int
    total_bytes: int
    sha256: str


def rq_ticker(ticker: str) -> str:
    if ticker.endswith(".SZ"):
        return f"{ticker[:-3]}.XSHE"
    if ticker.endswith(".SH"):
        return f"{ticker[:-3]}.XSHG"
    raise ValueError(f"unsupported panel ticker: {ticker}")


def filename(ticker: str) -> str:
    return f"{rq_ticker(ticker)}.h5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_settings(dataset: h5py.Dataset) -> dict[str, Any]:
    settings: dict[str, Any] = {"maxshape": (None,)}
    if dataset.chunks is not None:
        settings["chunks"] = dataset.chunks
    if dataset.compression is not None:
        settings["compression"] = dataset.compression
        settings["compression_opts"] = dataset.compression_opts
    if dataset.shuffle:
        settings["shuffle"] = True
    if dataset.fletcher32:
        settings["fletcher32"] = True
    return settings


def _frame_arrays(frame: pd.DataFrame, ticker: str) -> tuple[np.ndarray, np.ndarray]:
    if frame.empty:
        return np.empty(0, DATA_DTYPE), np.empty(0, INDEX_DTYPE)
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.droplevel(0)
    frame = frame.sort_index()
    stamps = pd.DatetimeIndex(frame.index)
    days = stamps.normalize()
    counts = pd.Series(1, index=days).groupby(level=0).sum()
    if not (counts == BARS_PER_DAY).all():
        bad = ", ".join(f"{day.date()}={count}" for day, count in counts[counts != BARS_PER_DAY].items())
        raise ValueError(f"{ticker}: expected 48 bars per trading day, got {bad}")
    hhmm = stamps.hour.to_numpy() * 100 + stamps.minute.to_numpy()
    expected = np.tile(BAR_HHMM, len(counts))
    if not np.array_equal(hhmm, expected):
        raise ValueError(f"{ticker}: unexpected 5-minute bar labels")

    data = np.empty(len(frame), dtype=DATA_DTYPE)
    data["datetime"] = stamps.strftime("%Y%m%d%H%M%S").astype(np.int64)
    for field in FIELDS[:-1]:
        data[field] = pd.to_numeric(frame[field], errors="coerce").to_numpy(np.float64)
    trades = pd.to_numeric(frame["num_trades"], errors="coerce").fillna(0).to_numpy(np.float64)
    data["num_trades"] = np.maximum(trades, 0).astype(np.uint64)
    index = np.empty(len(counts), dtype=INDEX_DTYPE)
    index["date"] = counts.index.strftime("%Y%m%d").astype(np.int64)
    index["line_no"] = np.arange(len(counts), dtype=np.uint32) * BARS_PER_DAY
    return data, index


def _write_file(path: Path, new_data: np.ndarray, new_index: np.ndarray) -> bool:
    old_data = np.empty(0, DATA_DTYPE)
    old_index = np.empty(0, INDEX_DTYPE)
    data_settings: dict[str, Any] = {"maxshape": (None,), "chunks": True}
    index_settings: dict[str, Any] = {"maxshape": (None,), "chunks": True}
    attrs: dict[str, Any] = {}
    if path.is_file():
        with h5py.File(path, "r") as source:
            old_data = source["data"][:]
            old_index = source["index"][:]
            data_settings = _dataset_settings(source["data"])
            index_settings = _dataset_settings(source["index"])
            attrs = dict(source.attrs)
        if len(old_index):
            keep = new_index["date"] > old_index["date"][-1]
            first = int(np.flatnonzero(keep)[0]) if keep.any() else len(new_index)
            new_index = new_index[first:]
            new_data = new_data[first * BARS_PER_DAY :]
    if not len(new_index):
        return False
    shifted = new_index.copy()
    shifted["line_no"] -= shifted["line_no"][0]
    shifted["line_no"] += len(old_data)
    combined_data = np.concatenate([old_data, new_data])
    combined_index = np.concatenate([old_index, shifted])
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with h5py.File(temporary, "w") as target:
            target.create_dataset("data", data=combined_data, **data_settings)
            target.create_dataset("index", data=combined_index, **index_settings)
            for key, value in attrs.items():
                target.attrs[key] = value
            target.attrs["stored_price_basis"] = "raw_unadjusted"
            target.flush()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _write_task(task: tuple[Path, np.ndarray, np.ndarray]) -> bool:
    return _write_file(*task)


def _split_result(frame: pd.DataFrame, ids: list[str]) -> dict[str, pd.DataFrame]:
    if frame.empty:
        return {}
    if len(ids) == 1 and not isinstance(frame.index, pd.MultiIndex):
        return {ids[0]: frame}
    if not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("RQData batch minute response must use a MultiIndex")
    return {str(key): value.droplevel(0) for key, value in frame.groupby(level=0, sort=False)}


def _get_price_with_retry(
    client: Any, *, attempts: int, retry_delay: float, **kwargs: Any
) -> pd.DataFrame:
    for attempt in range(1, attempts + 1):
        try:
            return client.get_price(**kwargs)
        except Exception as error:
            name = type(error).__name__.lower()
            transient = any(token in name for token in ("connection", "network", "quota", "timeout"))
            if not transient or attempt == attempts:
                raise
            delay = min(retry_delay * attempt, 120.0)
            print(
                f"RQData 5m batch attempt {attempt}/{attempts} failed: {error}; "
                f"retrying in {delay:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            reset = getattr(client, "reset", None)
            if reset is not None:
                reset()
            time.sleep(delay)
            initialize = getattr(client, "init", None)
            if initialize is not None:
                initialize()
    raise AssertionError("unreachable")


def update_five_minute_dataset(
    root: Path,
    panel_metadata: Path,
    *,
    end_date: date,
    client: Any,
    batch_size: int = 50,
    workers: int = 8,
    retry_attempts: int = 12,
    retry_delay: float = 10.0,
) -> dict[str, Any]:
    metadata_path = root / "metadata.json"
    old_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    panel = json.loads(panel_metadata.read_text(encoding="utf-8"))
    tickers = [str(value) for value in panel["tickers"]]
    start_date = date.fromisoformat(old_metadata["end_date"]) + timedelta(days=1)
    equities = root / "equities"
    equities.mkdir(parents=True, exist_ok=True)

    if workers < 1:
        raise ValueError("workers must be positive")
    updated = 0
    ids = [rq_ticker(ticker) for ticker in tickers]
    executor = (
        ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
        if workers > 1
        else None
    )
    try:
        for offset in range(0, len(ids), batch_size):
            batch = ids[offset : offset + batch_size]
            result = _get_price_with_retry(
                client,
                attempts=retry_attempts,
                retry_delay=retry_delay,
                order_book_ids=batch,
                start_date=start_date,
                end_date=end_date,
                frequency="5m",
                fields=list(FIELDS),
                adjust_type="none",
                skip_suspended=False,
                expect_df=True,
                market="cn",
            )
            frames = _split_result(result, batch)
            tasks: list[tuple[Path, np.ndarray, np.ndarray]] = []
            for ticker, order_book_id in zip(tickers[offset : offset + batch_size], batch):
                frame = frames.get(order_book_id)
                if frame is None or frame.empty:
                    continue
                data, index = _frame_arrays(frame, ticker)
                tasks.append((equities / filename(ticker), data, index))
            if executor is None:
                updated += sum(_write_task(task) for task in tasks)
            else:
                updated += sum(executor.map(_write_task, tasks))
            print(f"5m batches: {min(offset + batch_size, len(ids))}/{len(ids)}", flush=True)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)

    records: list[FileRecord] = []
    for path in sorted(equities.glob("*.h5")):
        with h5py.File(path, "r") as handle:
            records.append(
                FileRecord(
                    filename=path.name,
                    ticker=path.stem.replace(".XSHE", ".SZ").replace(".XSHG", ".SH"),
                    trading_days=len(handle["index"]),
                    observations=len(handle["data"]),
                    total_bytes=path.stat().st_size,
                    sha256=_sha256(path),
                )
            )
    manifest = root / "manifest.csv"
    temporary = manifest.with_name(f".{manifest.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(records[0])))
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
    os.replace(temporary, manifest)
    manifest_hash = _sha256(manifest)
    metadata = {
        **old_metadata,
        "vendor": "RQData",
        "end_date": end_date.isoformat(),
        "file_count": len(records),
        "trading_day_records": sum(item.trading_days for item in records),
        "observation_count": sum(item.observations for item in records),
        "total_bytes": sum(item.total_bytes for item in records),
        "manifest": manifest.name,
        "manifest_sha256": manifest_hash,
        "content_hash": f"sha256:{manifest_hash}",
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    temporary_meta = metadata_path.with_name(f".{metadata_path.name}.{os.getpid()}.tmp")
    temporary_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary_meta, metadata_path)
    return {"updated_files": updated, "file_count": len(records), "date_max": end_date.isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--panel-metadata", type=Path, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retry-attempts", type=int, default=12)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    args = parser.parse_args()
    import rqdatac

    rqdatac.init()
    result = update_five_minute_dataset(
        args.root,
        args.panel_metadata,
        end_date=args.end_date,
        client=rqdatac,
        batch_size=args.batch_size,
        workers=args.workers,
        retry_attempts=args.retry_attempts,
        retry_delay=args.retry_delay,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
