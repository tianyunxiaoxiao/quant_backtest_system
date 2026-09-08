from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "ops" / "data_update" / "refresh_factor_values.py"
SPEC = spec_from_file_location("refresh_factor_values", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeRepository:
    def __init__(self, factors, requests, runs=()):
        self.factors = factors
        self.requests = requests
        self.runs = list(runs)

    def list_factors(self):
        return self.factors

    def list_runs(self):
        return self.runs

    def get_request(self, run_id):
        return self.requests[run_id]


def factor(factor_id, run_id):
    return {"factor_id": factor_id, "source_run_id": run_id}


def request(factor_id, *, mode="factor_code", frequency="daily", end="2026-09-04"):
    return {
        "owner_subject": "render:7",
        "owner_user_id": 7,
        "factor_id": factor_id,
        "input_mode": mode,
        "data_frequency": frequency,
        "end_date": end,
    }


def test_build_plan_selects_only_stale_reviewed_code_factors():
    repository = FakeRepository(
        [factor("visible", "r1"), factor("hidden", "r2"), factor("upload", "r3")],
        {
            "r1": request("visible", frequency="5m"),
            "r2": request("hidden"),
            "r3": request("upload", mode="uploaded_values"),
        },
    )

    planned, skipped = MODULE.build_plan(
        repository,
        {"visible": {"hidden": False}, "hidden": {"hidden": True}, "upload": {"hidden": False}},
        {"daily": date(2026, 9, 7), "5m": date(2026, 9, 7)},
        max_attempts=3,
    )

    assert [row["factor_id"] for row in planned] == ["visible"]
    assert planned[0]["request"]["end_date"] == "2026-09-07"
    assert planned[0]["idempotency_key"] == "factor-refresh:2026-09-07:visible:1"
    assert skipped == [{"factor_id": "upload", "reason": "uploaded_values"}]


def test_build_plan_skips_current_and_active_factors():
    repository = FakeRepository(
        [factor("active", "r1"), factor("current", "r2")],
        {"r1": request("active"), "r2": request("current", end="2026-09-07")},
        [{"owner_subject": "render:7", "factor_id": "active", "status": "running"}],
    )
    reviews = {name: {"hidden": False} for name in ("active", "current")}

    planned, skipped = MODULE.build_plan(
        repository,
        reviews,
        {"daily": date(2026, 9, 7), "5m": date(2026, 9, 7)},
        max_attempts=3,
    )

    assert planned == []
    assert skipped == [
        {"factor_id": "active", "reason": "run_already_active"},
        {"factor_id": "current", "reason": "already_current"},
    ]


def test_build_plan_retries_failed_refresh_up_to_limit():
    prefix = "factor-refresh:2026-09-07:visible:"
    runs = [
        {"idempotency_key": f"{prefix}{attempt}", "status": "failed"}
        for attempt in (1, 2)
    ]
    repository = FakeRepository(
        [factor("visible", "source")], {"source": request("visible")}, runs
    )

    planned, _ = MODULE.build_plan(
        repository,
        {"visible": {"hidden": False}},
        {"daily": date(2026, 9, 7), "5m": date(2026, 9, 7)},
        max_attempts=3,
    )

    assert planned[0]["idempotency_key"] == f"{prefix}3"
