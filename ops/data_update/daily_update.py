#!/usr/bin/env python3
"""Build, validate, and atomically publish one shared QPF/QBT daily release."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


def run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(command, check=True, text=True, capture_output=True, env=env)
    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    return completed.stdout


def hardlink_tree(source: Path, target: Path) -> None:
    try:
        shutil.copytree(source, target, copy_function=os.link, symlinks=True)
    except OSError as error:
        raise RuntimeError(
            "candidate and current release must be on the same filesystem"
        ) from error


def latest_ready_date(python: Path, env: dict[str, str]) -> date:
    code = (
        "import rqdatac; rqdatac.init(); "
        "latest=rqdatac.get_latest_trading_date(market='cn'); "
        "d=rqdatac.get_previous_trading_date(latest, market='cn'); "
        "r=rqdatac.is_data_ready(categories=['stock_daybar','stock_minbar','exchange_index_daybar'], "
        "expected_date=d, market='cn'); "
        "assert bool(r['ready'].all()), r.to_string(); print(d.isoformat())"
    )
    value = run([str(python), "-c", code], env=env).splitlines()[-1]
    return date.fromisoformat(value)


def active_qbt_runs(database: Path) -> int:
    if not database.is_file():
        return 0
    with sqlite3.connect(database) as connection:
        return int(
            connection.execute(
                "SELECT count(*) FROM runs WHERE status IN ('pending', 'running')"
            ).fetchone()[0]
        )


def active_qpf_runs(database: str) -> int:
    query = (
        "SELECT count(*) FROM runs WHERE status NOT IN "
        "('succeeded','failed','cancelled','timed_out')"
    )
    value = run(["sudo", "-u", "postgres", "psql", "-d", database, "-Atc", query])
    return int(value.strip())


def build_release(args: argparse.Namespace, target_date: date, env: dict[str, str]) -> Path:
    current = args.current.resolve(strict=True)
    version = f"rqdata-a-share-{target_date:%Y%m%d}-full-v1"
    final = args.datasets / version
    if final.exists():
        run(
            [
                str(args.python),
                str(args.validator_script),
                "--release",
                str(final),
                "--expected-end",
                target_date.isoformat(),
            ]
        )
        return final
    partial = args.datasets / f".{version}.partial-{uuid.uuid4().hex[:8]}"
    print(json.dumps({"stage": "copy", "source": str(current), "candidate": str(partial)}))
    hardlink_tree(current, partial)

    update_env = env.copy()
    compatibility = Path(__file__).resolve().parent / "rqdata_compat"
    update_env["PYTHONPATH"] = os.pathsep.join(
        [str(compatibility), update_env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    run(
        [
            str(args.python),
            str(args.qpf_update_script),
            "--output",
            str(partial / "panel_shards"),
            "--cache-dir",
            str(args.cache_dir),
            "--end-date",
            target_date.isoformat(),
        ],
        env=update_env,
    )
    run(
        [
            str(args.python),
            str(args.minbar_update_script),
            "--root",
            str(partial / "5minbar_unadjusted"),
            "--panel-metadata",
            str(partial / "panel_shards" / "metadata.json"),
            "--end-date",
            target_date.isoformat(),
            "--batch-size",
            str(args.minbar_batch_size),
        ],
        env=env,
    )
    run(
        [
            str(args.python),
            str(args.minbar_adjust_script),
            "--raw-root",
            str(partial / "5minbar_unadjusted"),
            "--panel-shards",
            str(partial / "panel_shards"),
            "--output-root",
            str(partial / "5minbar_post"),
            "--workers",
            str(args.minbar_workers),
        ]
    )
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{partial}:/release",
            args.qbt_image,
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "from qbt.data.ingest_rq_snapshot import RQSnapshotIngestConfig,build_rq_snapshot_warehouse; "
                "build_rq_snapshot_warehouse(RQSnapshotIngestConfig(Path('/release/panel_shards'), "
                "Path('/release/warehouse_rqdata'), overwrite=True))"
            ),
        ]
    )
    run(
        [
            str(args.python),
            str(args.benchmark_script),
            "--output",
            str(partial / "warehouse_rqdata" / "benchmarks"),
            "--start-date",
            args.start_date.isoformat(),
            "--end-date",
            target_date.isoformat(),
        ],
        env=env,
    )
    validation = json.loads(
        run(
            [
                str(args.python),
                str(args.validator_script),
                "--release",
                str(partial),
                "--expected-end",
                target_date.isoformat(),
            ]
        )
    )
    release_manifest = {
        "schema_version": "qpf_qbt_shared_release/v1",
        "dataset_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "previous_release": str(current),
        "validation": validation,
    }
    (partial / "data_release.json").write_text(
        json.dumps(release_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    partial.rename(final)
    return final


def publish(current: Path, release: Path) -> None:
    previous = current.resolve(strict=True)
    previous_link = current.with_name("previous")
    temp_previous = current.with_name(f".previous-{uuid.uuid4().hex}")
    temp_current = current.with_name(f".current-{uuid.uuid4().hex}")
    os.symlink(previous, temp_previous)
    os.symlink(release, temp_current)
    os.replace(temp_previous, previous_link)
    os.replace(temp_current, current)


def prune_superseded_full_releases(current: Path, datasets: Path) -> None:
    protected = {current.resolve(strict=True)}
    previous = current.with_name("previous")
    if previous.exists():
        protected.add(previous.resolve(strict=True))
    for release in datasets.glob("rqdata-a-share-*-full-v1"):
        if release.resolve() not in protected:
            shutil.rmtree(release)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--current", type=Path, default=Path("/data/research/current"))
    result.add_argument("--datasets", type=Path, default=Path("/data/research/datasets"))
    result.add_argument("--python", type=Path, default=Path("/opt/qpf/venv/bin/python"))
    result.add_argument(
        "--qpf-update-script",
        type=Path,
        default=Path("/opt/qpf/app/scripts/update_rqdata_panel.py"),
    )
    result.add_argument(
        "--benchmark-script",
        type=Path,
        default=Path("/opt/qbt/app/scripts/fetch_rqdata_benchmarks.py"),
    )
    result.add_argument(
        "--minbar-update-script",
        type=Path,
        default=Path("/opt/qbt/app/scripts/update_rqdata_5min.py"),
    )
    result.add_argument(
        "--minbar-adjust-script",
        type=Path,
        default=Path("/opt/qpf/app/scripts/build_adjusted_5minbar.py"),
    )
    result.add_argument(
        "--validator-script",
        type=Path,
        default=Path("/opt/qbt/app/scripts/validate_data_release.py"),
    )
    result.add_argument("--qbt-image", default=os.getenv("QBT_DATA_IMAGE", "qbt-web:latest"))
    result.add_argument("--qbt-database", type=Path, default=Path("/data/qbt/state/qbt_web.db"))
    result.add_argument("--qpf-database", default="qpf")
    result.add_argument("--cache-dir", type=Path, default=Path("/data/research/rqdata_cache"))
    result.add_argument("--lock-file", type=Path, default=Path("/run/lock/qbt-data-update.lock"))
    result.add_argument("--start-date", type=date.fromisoformat, default=date(2019, 1, 2))
    result.add_argument("--minbar-batch-size", type=int, default=50)
    result.add_argument("--minbar-workers", type=int, default=8)
    result.add_argument("--target-date", type=date.fromisoformat)
    result.add_argument("--build-only", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    args.datasets.mkdir(parents=True, exist_ok=True)
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another data update is already running", file=sys.stderr)
            return 75
        env = os.environ.copy()
        target = args.target_date or latest_ready_date(args.python, env)
        current_release = args.current.resolve()
        panel_meta = json.loads((current_release / "panel_shards" / "metadata.json").read_text())
        raw_meta = json.loads((current_release / "5minbar_unadjusted" / "metadata.json").read_text())
        post_meta = json.loads((current_release / "5minbar_post" / "metadata.json").read_text())
        component_ends = {
            "daily": date.fromisoformat(panel_meta["dates"][-1][:10]),
            "5min_raw": date.fromisoformat(raw_meta["end_date"]),
            "5min_post": date.fromisoformat(post_meta["end_date"]),
        }
        if min(component_ends.values()) >= target:
            print(json.dumps({"status": "current", "date": target.isoformat(), "components": {key: str(value) for key, value in component_ends.items()}}))
            return 0
        active = active_qbt_runs(args.qbt_database)
        if active:
            raise RuntimeError(f"refusing publication while {active} QBT runs are active")
        active = active_qpf_runs(args.qpf_database)
        if active:
            raise RuntimeError(f"refusing publication while {active} QPF runs are active")
        version = f"rqdata-a-share-{target:%Y%m%d}-full-v1"
        try:
            release = build_release(args, target, env)
        except Exception:
            for partial in args.datasets.glob(f".{version}.partial-*"):
                shutil.rmtree(partial)
            raise
        if not args.build_only:
            publish(args.current, release)
            prune_superseded_full_releases(args.current, args.datasets)
        print(
            json.dumps(
                {
                    "status": "published" if not args.build_only else "built",
                    "release": str(release),
                    "date": target.isoformat(),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
