"""Fetch official comparison benchmarks from RQData into a staged warehouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

BENCHMARKS = {
    "000300.SH": ("沪深300", "000300.XSHG"),
    "000905.SH": ("中证500", "000905.XSHG"),
    "000852.SH": ("中证1000", "000852.XSHG"),
}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_benchmarks(
    output_dir: Path,
    *,
    start_date: date,
    end_date: date,
    client: Any,
) -> dict[str, Any]:
    """Fetch all configured indexes and atomically replace the benchmark directory."""
    output_dir = Path(output_dir).resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    items: list[dict[str, Any]] = []
    try:
        expected = pd.DatetimeIndex(
            client.get_trading_dates(start_date, end_date, market="cn")
        ).normalize()
        if expected.empty or expected[-1].date() != end_date:
            raise RuntimeError(f"RQData trading calendar is not ready through {end_date}")

        for benchmark_id, (name, rq_id) in BENCHMARKS.items():
            raw = client.get_price(
                rq_id,
                start_date=start_date,
                end_date=end_date,
                frequency="1d",
                fields="close",
                adjust_type="none",
                skip_suspended=False,
                expect_df=True,
                market="cn",
            )
            if isinstance(raw, pd.Series):
                close = raw
            elif "close" in raw.columns:
                close = raw["close"]
            else:
                raise ValueError(f"RQData response has no close column for {rq_id}")
            if isinstance(close.index, pd.MultiIndex):
                close.index = close.index.get_level_values(-1)
            close.index = pd.DatetimeIndex(close.index).normalize()
            close = pd.to_numeric(close, errors="coerce").reindex(expected)
            missing = expected[close.isna()]
            if len(missing):
                values = ", ".join(value.date().isoformat() for value in missing[:10])
                raise ValueError(f"{benchmark_id} missing trading dates: {values}")

            frame = pd.DataFrame({"date": expected, "close": close.to_numpy(dtype=float)})
            target = stage / f"{benchmark_id}.parquet"
            frame.to_parquet(target, index=False)
            items.append(
                {
                    "benchmark_id": benchmark_id,
                    "name": name,
                    "file": target.name,
                    "source_uri": f"rqdata:{rq_id}",
                    "content_sha256": f"sha256:{_hash_file(target)}",
                    "date_min": str(expected[0].date()),
                    "date_max": str(expected[-1].date()),
                    "rows": len(frame),
                    "price_field": "close",
                }
            )

        manifest = {
            "schema_version": "qbt_benchmark_quotes/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": {"vendor": "Ricequant RQData", "client": "rqdatac"},
            "benchmarks": items,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for path in stage.iterdir():
            path.chmod(0o644)
        stage.chmod(0o755)
        backup = output_dir.with_name(f".{output_dir.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if output_dir.exists():
            output_dir.rename(backup)
        os.replace(stage, output_dir)
        shutil.rmtree(backup, ignore_errors=True)
        return manifest
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    import rqdatac

    rqdatac.init()
    manifest = fetch_benchmarks(
        args.output,
        start_date=args.start_date,
        end_date=args.end_date,
        client=rqdatac,
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
