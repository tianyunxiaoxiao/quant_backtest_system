#!/usr/bin/env python3
"""Queue fresh runs for every reviewed, non-hidden code factor."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

ACTIVE_STATUSES = {"queued", "leased", "running", "uploading", "cancelling"}
SUCCESS_STATUSES = {"succeeded"}
RETRYABLE_TERMINAL_STATUSES = {"failed", "cancelled", "timed_out"}


class Repository(Protocol):
    def list_factors(self) -> list[dict[str, Any]]: ...

    def list_runs(self) -> list[dict[str, Any]]: ...

    def get_request(self, run_id: str) -> dict[str, Any]: ...

    def create_run(
        self, request: dict[str, Any], *, idempotency_key: str
    ) -> dict[str, Any]: ...


def dataset_end_dates(research_root: Path) -> dict[str, date]:
    panel = json.loads((research_root / "panel_shards" / "metadata.json").read_text())
    raw = json.loads((research_root / "5minbar_unadjusted" / "metadata.json").read_text())
    adjusted = json.loads((research_root / "5minbar_post" / "metadata.json").read_text())
    return {
        "daily": date.fromisoformat(str(panel["dates"][-1])[:10]),
        "5m": min(
            date.fromisoformat(str(raw["end_date"])[:10]),
            date.fromisoformat(str(adjusted["end_date"])[:10]),
        ),
    }


def build_plan(
    repository: Repository,
    reviews: dict[str, dict[str, Any]],
    end_dates: dict[str, date],
    *,
    max_attempts: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    runs = repository.list_runs()
    active = {
        (str(run.get("owner_subject")), str(run.get("factor_id")))
        for run in runs
        if str(run.get("status")) in ACTIVE_STATUSES
    }
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for factor in sorted(repository.list_factors(), key=lambda row: str(row["factor_id"])):
        factor_id = str(factor["factor_id"])
        review = reviews.get(factor_id)
        if not review or bool(review.get("hidden")):
            continue
        try:
            request = dict(repository.get_request(str(factor["source_run_id"])))
        except (KeyError, ValueError, TypeError):
            skipped.append({"factor_id": factor_id, "reason": "source_request_unavailable"})
            continue
        mode = str(request.get("input_mode", "factor_code"))
        frequency = str(request.get("data_frequency", "daily"))
        if mode != "factor_code":
            skipped.append({"factor_id": factor_id, "reason": "uploaded_values"})
            continue
        if frequency not in end_dates:
            skipped.append({"factor_id": factor_id, "reason": "unsupported_frequency"})
            continue
        target = end_dates[frequency]
        source_end = _request_end_date(request)
        if source_end is not None and source_end >= target:
            skipped.append({"factor_id": factor_id, "reason": "already_current"})
            continue
        identity = (str(request["owner_subject"]), str(request["factor_id"]))
        if identity in active:
            skipped.append({"factor_id": factor_id, "reason": "run_already_active"})
            continue

        prefix = f"factor-refresh:{target.isoformat()}:{factor_id}:"
        prior = [run for run in runs if str(run.get("idempotency_key", "")).startswith(prefix)]
        if any(str(run.get("status")) in SUCCESS_STATUSES for run in prior):
            skipped.append({"factor_id": factor_id, "reason": "refresh_succeeded"})
            continue
        failed_attempts = sum(
            str(run.get("status")) in RETRYABLE_TERMINAL_STATUSES for run in prior
        )
        if failed_attempts >= max_attempts:
            skipped.append({"factor_id": factor_id, "reason": "retry_limit_reached"})
            continue

        request["end_date"] = target.isoformat()
        planned.append(
            {
                "factor_id": factor_id,
                "frequency": frequency,
                "target_date": target.isoformat(),
                "request": request,
                "idempotency_key": f"{prefix}{failed_attempts + 1}",
            }
        )
        active.add(identity)
    return planned, skipped


def _request_end_date(request: dict[str, Any]) -> date | None:
    value = str(request.get("end_date") or "")[:10]
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _repository_from_environment() -> Repository:
    from quant_private_fund_infra.task_queue import PostgresTaskRepository

    dsn = os.environ.get("QPF_DATABASE_URL")
    if not dsn:
        raise RuntimeError("QPF_DATABASE_URL is required")
    return PostgresTaskRepository(dsn)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--research-root", type=Path, default=Path("/data/research/current"))
    result.add_argument(
        "--review-file",
        type=Path,
        default=Path("/data/qpf/factor_correlations/full_latest.json"),
    )
    result.add_argument("--manifest-dir", type=Path, default=Path("/data/qpf/batches"))
    result.add_argument("--restart-service", default="")
    result.add_argument("--max-attempts", type=int, default=3)
    result.add_argument("--dry-run", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    repository = _repository_from_environment()
    review_payload = json.loads(args.review_file.read_text(encoding="utf-8"))
    end_dates = dataset_end_dates(args.research_root.resolve(strict=True))
    planned, skipped = build_plan(
        repository,
        dict(review_payload.get("reviews", {})),
        end_dates,
        max_attempts=args.max_attempts,
    )
    if planned and args.restart_service and not args.dry_run:
        subprocess.run(["systemctl", "restart", args.restart_service], check=True)

    submitted = []
    submission_errors = []
    if not args.dry_run:
        for item in planned:
            try:
                status = repository.create_run(
                    item["request"], idempotency_key=item["idempotency_key"]
                )
            except Exception as error:
                submission_errors.append(
                    {
                        "factor_id": item["factor_id"],
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            submitted.append(
                {
                    "factor_id": item["factor_id"],
                    "frequency": item["frequency"],
                    "target_date": item["target_date"],
                    "run_id": status["run_id"],
                    "status": status["status"],
                }
            )

    reasons = Counter(row["reason"] for row in skipped)
    payload = {
        "schema_version": "qpf_factor_refresh/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "dry_run": args.dry_run,
        "dataset_end_dates": {key: value.isoformat() for key, value in end_dates.items()},
        "reviewed_kept_count": sum(
            bool(review) and not bool(review.get("hidden"))
            for review in review_payload.get("reviews", {}).values()
        ),
        "planned_count": len(planned),
        "submitted_count": len(submitted),
        "submission_error_count": len(submission_errors),
        "skipped_count": len(skipped),
        "skip_reasons": dict(sorted(reasons.items())),
        "submitted": submitted,
        "submission_errors": submission_errors,
        "skipped": skipped,
    }
    stamp = max(end_dates.values()).isoformat()
    manifest = args.manifest_dir / f"factor-refresh-{stamp}.json"
    if not args.dry_run:
        _write_json_atomic(manifest, payload)
    print(json.dumps({**payload, "manifest": str(manifest)}, ensure_ascii=False))
    return 1 if submission_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
