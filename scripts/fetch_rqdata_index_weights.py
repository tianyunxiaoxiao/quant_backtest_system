#!/usr/bin/env python3
"""Fetch PIT index weights from RQData and atomically publish a shared release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


INDEXES = {
    "000300.SH": ("沪深300", "000300.XSHG", 300),
    "000905.SH": ("中证500", "000905.XSHG", 500),
    "000852.SH": ("中证1000", "000852.XSHG", 1000),
}
_SUFFIXES = {"XSHE": "SZ", "XSHG": "SH", "XBEI": "BJ"}


def _call_with_retry(func: Any, *args: Any, attempts: int = 5, **kwargs: Any) -> Any:
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(min(30, 2**attempt))


def _asset_ids(values: pd.Series) -> pd.Series:
    parts = values.astype("string").str.rsplit(".", n=1, expand=True)
    if parts.shape[1] != 2:
        raise ValueError("RQData 指数成分代码格式错误")
    suffix = parts[1].map(_SUFFIXES)
    if suffix.isna().any():
        bad = values.loc[suffix.isna()].dropna().astype(str).unique()[:5]
        raise ValueError(f"RQData 指数成分含未知交易所: {bad.tolist()}")
    return parts[0] + "." + suffix


def _snapshot_digest(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values("asset_id")[["asset_id", "weight"]]
    values = pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes()
    return hashlib.sha256(values).hexdigest()


def _fetch_one(
    client: Any,
    rq_id: str,
    *,
    start_date: date,
    end_date: date,
    expected_size: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    chunks: list[pd.DataFrame] = []
    for year in range(start_date.year, end_date.year + 1):
        chunk_start = max(start_date, date(year, 1, 1))
        chunk_end = min(end_date, date(year, 12, 31))
        raw = _call_with_retry(
            client.index_weights,
            rq_id,
            start_date=chunk_start,
            end_date=chunk_end,
            market="cn",
        )
        if raw is None or raw.empty:
            raise RuntimeError(f"{rq_id} 在 {chunk_start} 至 {chunk_end} 没有权重数据")
        frame = raw.reset_index()
        if not {"date", "order_book_id", "weight"}.issubset(frame.columns):
            raise ValueError(f"{rq_id} 返回字段异常: {list(frame.columns)}")
        chunks.append(frame[["date", "order_book_id", "weight"]])

    daily = pd.concat(chunks, ignore_index=True)
    daily["snapshot_date"] = pd.to_datetime(daily.pop("date")).dt.normalize()
    daily["asset_id"] = _asset_ids(daily.pop("order_book_id"))
    daily["weight"] = pd.to_numeric(daily["weight"], errors="coerce")
    daily = daily.drop_duplicates(["snapshot_date", "asset_id"], keep="last")
    daily = daily.sort_values(["snapshot_date", "asset_id"], ignore_index=True)

    counts = daily.groupby("snapshot_date").size()
    sums = daily.groupby("snapshot_date")["weight"].sum()
    invalid = counts.ne(expected_size) | sums.lt(0.9) | sums.gt(1.05)
    if invalid.any() or daily["weight"].isna().any() or (daily["weight"] < 0).any():
        sample = {
            str(day.date()): {"members": int(counts[day]), "weight_sum": float(sums[day])}
            for day in counts.index[invalid][:10]
        }
        raise ValueError(f"{rq_id} 指数权重完整性校验失败: {sample}")

    kept: list[pd.DataFrame] = []
    previous_digest: str | None = None
    for _, group in daily.groupby("snapshot_date", sort=True):
        digest = _snapshot_digest(group)
        if digest == previous_digest:
            continue
        snapshot = group[["snapshot_date", "asset_id", "weight"]].copy()
        snapshot["source_file"] = f"rqdata:{rq_id}"
        kept.append(snapshot)
        previous_digest = digest
    result = pd.concat(kept, ignore_index=True)
    latest = pd.Timestamp(result["snapshot_date"].max())
    if (pd.Timestamp(end_date) - latest).days > 45:
        raise ValueError(f"{rq_id} 最新权重快照 {latest.date()} 距检查日 {end_date} 超过 45 天")
    return result, {
        "rq_id": rq_id,
        "expected_size": expected_size,
        "snapshots": int(result["snapshot_date"].nunique()),
        "snapshot_first": str(pd.Timestamp(result["snapshot_date"].min()).date()),
        "snapshot_last": str(latest.date()),
        "rows": int(len(result)),
        "weight_sum_min": float(result.groupby("snapshot_date")["weight"].sum().min()),
        "weight_sum_max": float(result.groupby("snapshot_date")["weight"].sum().max()),
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release(
    root: Path,
    *,
    start_date: date,
    end_date: date,
    client: Any,
) -> tuple[Path, dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    releases = root / "releases"
    releases.mkdir(exist_ok=True)
    release = releases / f"rqdata-index-weights-{end_date:%Y%m%d}-v1"
    if release.exists():
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        return release, manifest

    stage = releases / f".{release.name}.partial-{uuid.uuid4().hex[:8]}"
    stage.mkdir()
    items: dict[str, Any] = {}
    for index_id, (name, rq_id, expected_size) in INDEXES.items():
        frame, stats = _fetch_one(
            client,
            rq_id,
            start_date=start_date,
            end_date=end_date,
            expected_size=expected_size,
        )
        path = stage / f"{index_id}_monthly.parquet"
        frame.to_parquet(path, index=False, compression="zstd")
        items[index_id] = {
            "name": name,
            "file": path.name,
            "sha256": _hash_file(path),
            **stats,
        }
    manifest = {
        "schema_version": "qbt_index_weights/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Ricequant RQData",
        "source_start": start_date.isoformat(),
        "checked_through": end_date.isoformat(),
        "indexes": items,
    }
    (stage / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(stage, release)
    return release, manifest


def publish(root: Path, release: Path) -> None:
    current = root / "current"
    temporary = root / f".current-{uuid.uuid4().hex}"
    os.symlink(release, temporary)
    os.replace(temporary, current)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/data/research/index_membership"))
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2019, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    import rqdatac

    rqdatac.init()
    release, manifest = build_release(
        args.root,
        start_date=args.start_date,
        end_date=args.end_date,
        client=rqdatac,
    )
    publish(args.root, release)
    print(json.dumps({"status": "published", "release": str(release), **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
