"""回测结果持久化与产物登记 (规范第 19 节)。

大矩阵落 Parquet, 指标与配置落 JSON, 每个产物计算 SHA-256。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qbt.contracts import LongOnlyFactorBacktestResult, RunArtifact, RunManifest
from qbt.contracts.records import fills_to_frame, orders_to_frame
from qbt.data.hashing import hash_file

__all__ = [
    "ArtifactWriter", "write_backtest_artifacts", "safe_artifact_path",
    "verify_backtest_artifact_roundtrip", "load_backtest_artifacts",
]


def safe_artifact_path(output_dir: Path, name: str, suffix: str, *, subdir: str = "") -> Path:
    """Resolve a single-component artifact name and reject path traversal."""
    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(f"非法产物名称: {name!r}")
    if not suffix.isalnum():
        raise ValueError(f"非法产物扩展名: {suffix!r}")
    root = Path(output_dir).resolve()
    parent = (root / subdir).resolve() if subdir else root
    if parent != root and root not in parent.parents:
        raise ValueError(f"非法产物子目录: {subdir!r}")
    path = (parent / f"{name}.{suffix}").resolve()
    if path.parent != parent:
        raise ValueError(f"产物路径越界: {name!r}")
    return path


class ArtifactWriter:
    """把 LongOnlyFactorBacktestResult 写入规范 §19 目录结构。"""

    def __init__(self, output_dir: Path, *, uri_root: Path | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.uri_root = Path(uri_root).resolve() if uri_root is not None else self.output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "charts").mkdir(parents=True, exist_ok=True)
        self.artifacts: list[RunArtifact] = []

    def write_dataframe(
        self,
        df: pd.DataFrame,
        name: str,
        *,
        index: bool = True,
        compression: str = "snappy",
    ) -> RunArtifact:
        path = safe_artifact_path(self.output_dir, name, "parquet")
        df.to_parquet(path, index=index, compression=compression)
        return self._register(path, name, kind="data")

    def write_json(self, obj: Any, name: str) -> RunArtifact:
        path = safe_artifact_path(self.output_dir, name, "json")
        payload = json.dumps(
            _canonical(obj), ensure_ascii=False, indent=2, allow_nan=False
        ).encode("utf-8")
        path.write_bytes(payload)
        return self._register(path, name, kind="data")

    def write_text(self, text: str, name: str, suffix: str = "md") -> RunArtifact:
        path = safe_artifact_path(self.output_dir, name, suffix)
        path.write_text(text, encoding="utf-8")
        return self._register(path, name, kind="report")

    def write_chart(self, figure, name: str, fmt: str = "png", dpi: int = 140) -> RunArtifact:
        path = safe_artifact_path(self.output_dir, name, fmt, subdir="charts")
        figure.savefig(path, dpi=dpi, bbox_inches="tight", format=fmt)
        return self._register(path, f"charts/{name}.{fmt}", kind="chart")

    def _register(self, path: Path, name: str, kind: str) -> RunArtifact:
        relative = path.resolve().relative_to(self.output_dir.resolve())
        published_path = (self.uri_root / relative).resolve()
        artifact = RunArtifact(
            name=name,
            uri=str(published_path),
            content_hash=hash_file(path),
            bytes=path.stat().st_size,
            kind=kind,
        )
        self.artifacts.append(artifact)
        return artifact

    def write_manifest(self, manifest: RunManifest) -> RunArtifact:
        d = asdict(manifest)
        # 产物哈希追加到 manifest
        d["artifact_refs"] = [
            {"name": a.name, "uri": a.uri, "content_hash": a.content_hash, "bytes": a.bytes}
            for a in self.artifacts
        ]
        d["result_hash"] = manifest.result_hash
        return self.write_json(d, "run_manifest")


def write_backtest_artifacts(
    result: LongOnlyFactorBacktestResult,
    output_dir: Path,
    *,
    include_manifest: bool = True,
    uri_root: Path | None = None,
) -> list[RunArtifact]:
    """一次性写出全部规范产物。"""
    writer = ArtifactWriter(output_dir, uri_root=uri_root)

    writer.write_dataframe(result.selected_members, "selected_members")
    writer.write_dataframe(result.target_weights, "target_weights")
    writer.write_dataframe(result.actual_weights, "actual_weights")
    writer.write_dataframe(orders_to_frame(result.orders), "orders", index=False)
    writer.write_dataframe(fills_to_frame(result.fills), "fills", index=False)
    writer.write_dataframe(result.holdings, "holdings")
    writer.write_dataframe(result.cash_ledger, "cash_ledger")

    daily_returns = pd.DataFrame(
        {
            "portfolio_gross_return": result.gross_returns,
            "portfolio_net_return": result.net_returns,
            "benchmark_return": result.benchmark_returns,
            "excess_return": result.excess_returns,
            "portfolio_nav": result.portfolio_equity,
            "portfolio_gross_nav": result.gross_equity,
            "benchmark_nav": result.benchmark_equity,
            "excess_nav": result.excess_equity,
            "portfolio_drawdown": result.portfolio_drawdown,
            "benchmark_drawdown": result.benchmark_drawdown,
            "excess_drawdown": result.excess_drawdown,
        }
    )
    writer.write_dataframe(daily_returns, "daily_returns")
    writer.write_dataframe(result.costs, "costs")
    style_exposures = pd.concat(
        {
            "portfolio": result.style_exposure.portfolio_exposure,
            "index": result.style_exposure.index_exposure,
            "active": result.style_exposure.active_exposure,
        },
        axis=1,
    )
    style_exposures.columns.names = ["exposure_type", "style"]
    writer.write_dataframe(style_exposures, "style_exposures")
    writer.write_json(
        {
            "summary": _canonical(result.style_exposure.summary),
            "coverage": _canonical(result.style_exposure.coverage),
            "excess_return_relation": _canonical(
                result.style_exposure.excess_return_relation
            ),
            "missing_styles": result.style_exposure.missing_styles,
            "data_source": result.style_exposure.data_source,
        },
        "style_exposure_report",
    )
    writer.write_dataframe(result.diagnostics.exclusion_reasons, "exclusion_reasons")
    writer.write_dataframe(result.diagnostics.unfilled_summary, "unfilled_summary", index=False)
    writer.write_dataframe(result.diagnostics.accounting_identity, "accounting_identity")
    writer.write_dataframe(
        result.position_period_analysis,
        "position_period_analysis",
        index=False,
    )
    writer.write_json(
        _position_period_summary(result.position_period_analysis),
        "position_analysis_summary",
    )
    writer.write_json(
        {
            "timeline": result.diagnostics.timeline,
            "data_quality": result.diagnostics.data_quality,
            "warnings": result.diagnostics.warnings,
            "disclosures": result.diagnostics.disclosures,
        },
        "diagnostics",
    )

    writer.write_json(_performance_to_dict(result.performance), "performance_report")
    writer.write_json(_alphabeta_to_dict(result.alpha_beta), "alpha_beta")
    writer.write_json(_selection_to_dict(result.selection_report), "index_selection_report")
    writer.write_json(
        {"constraint_reports": [_constraint_to_dict(c) for c in result.constraint_reports]},
        "constraint_reports",
    )

    request_config = dict(result.run_manifest.config)
    writer.write_json(request_config, "request_config")

    if include_manifest:
        writer.write_manifest(result.run_manifest)
    return writer.artifacts


def verify_backtest_artifact_roundtrip(
    result: LongOnlyFactorBacktestResult,
    output_dir: Path,
) -> None:
    """Reload every persisted result component and prove equality plus file integrity."""
    root = Path(output_dir).resolve()

    def frame(name: str, expected: pd.DataFrame) -> None:
        actual = pd.read_parquet(safe_artifact_path(root, name, "parquet"))
        pd.testing.assert_frame_equal(
            actual,
            expected,
            check_dtype=False,
            check_freq=False,
            rtol=1e-10,
            atol=1e-12,
        )

    def payload(name: str, expected: Any) -> None:
        actual = json.loads(safe_artifact_path(root, name, "json").read_text(encoding="utf-8"))
        if actual != _canonical(expected):
            raise AssertionError(f"JSON round-trip mismatch: {name}")

    frame("selected_members", result.selected_members)
    frame("target_weights", result.target_weights)
    frame("actual_weights", result.actual_weights)
    frame("orders", orders_to_frame(result.orders))
    frame("fills", fills_to_frame(result.fills))
    frame("holdings", result.holdings)
    frame("cash_ledger", result.cash_ledger)
    frame(
        "daily_returns",
        pd.DataFrame(
            {
                "portfolio_gross_return": result.gross_returns,
                "portfolio_net_return": result.net_returns,
                "benchmark_return": result.benchmark_returns,
                "excess_return": result.excess_returns,
                "portfolio_nav": result.portfolio_equity,
                "portfolio_gross_nav": result.gross_equity,
                "benchmark_nav": result.benchmark_equity,
                "excess_nav": result.excess_equity,
                "portfolio_drawdown": result.portfolio_drawdown,
                "benchmark_drawdown": result.benchmark_drawdown,
                "excess_drawdown": result.excess_drawdown,
            }
        ),
    )
    frame("costs", result.costs)
    frame(
        "style_exposures",
        pd.concat(
            {
                "portfolio": result.style_exposure.portfolio_exposure,
                "index": result.style_exposure.index_exposure,
                "active": result.style_exposure.active_exposure,
            },
            axis=1,
        ).rename_axis(columns=["exposure_type", "style"]),
    )
    frame("exclusion_reasons", result.diagnostics.exclusion_reasons)
    frame("unfilled_summary", result.diagnostics.unfilled_summary)
    frame("accounting_identity", result.diagnostics.accounting_identity)
    frame("position_period_analysis", result.position_period_analysis)

    payload("performance_report", _performance_to_dict(result.performance))
    payload("alpha_beta", _alphabeta_to_dict(result.alpha_beta))
    payload("index_selection_report", _selection_to_dict(result.selection_report))
    payload(
        "constraint_reports",
        {"constraint_reports": [_constraint_to_dict(c) for c in result.constraint_reports]},
    )
    payload("request_config", dict(result.run_manifest.config))
    payload(
        "style_exposure_report",
        {
            "summary": _canonical(result.style_exposure.summary),
            "coverage": _canonical(result.style_exposure.coverage),
            "excess_return_relation": _canonical(result.style_exposure.excess_return_relation),
            "missing_styles": result.style_exposure.missing_styles,
            "data_source": result.style_exposure.data_source,
        },
    )
    payload(
        "diagnostics",
        {
            "timeline": result.diagnostics.timeline,
            "data_quality": result.diagnostics.data_quality,
            "warnings": result.diagnostics.warnings,
            "disclosures": result.diagnostics.disclosures,
        },
    )
    payload(
        "position_analysis_summary",
        _position_period_summary(result.position_period_analysis),
    )

    manifest_path = safe_artifact_path(root, "run_manifest", "json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("result_hash") != result.run_manifest.result_hash:
        raise AssertionError("manifest result_hash mismatch")
    refs = manifest.get("artifact_refs", [])
    registered: set[Path] = set()
    for ref in refs:
        path = Path(ref["uri"]).resolve()
        if root != path.parent and root not in path.parents:
            raise AssertionError(f"manifest artifact outside output directory: {path}")
        if not path.is_file() or hash_file(path) != ref["content_hash"]:
            raise AssertionError(f"artifact hash mismatch: {path}")
        registered.add(path)
    actual_files = {path.resolve() for path in root.rglob("*") if path.is_file()}
    expected_files = registered | {manifest_path.resolve()}
    if actual_files != expected_files:
        missing = sorted(map(str, actual_files - expected_files))
        stale = sorted(map(str, expected_files - actual_files))
        raise AssertionError(f"manifest inventory mismatch: unregistered={missing}, missing={stale}")


def _frame_from_split(payload: dict, *, datetime_index: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame(payload["data"], columns=payload["columns"])
    for column in frame.columns:
        original_non_null = frame[column].notna()
        non_null_values = frame.loc[original_non_null, column]
        if len(non_null_values) and all(
            isinstance(value, (bool, np.bool_)) for value in non_null_values
        ):
            frame[column] = frame[column].astype(bool)
            continue
        if len(non_null_values) and all(isinstance(value, str) for value in non_null_values):
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.notna().sum() == original_non_null.sum():
            if (
                converted.notna().all()
                and len(converted)
                and np.allclose(converted.to_numpy(dtype="float64") % 1.0, 0.0)
                and all(isinstance(value, (int, np.integer)) for value in frame[column])
            ):
                frame[column] = converted.astype("int64")
            else:
                frame[column] = converted
    raw_index = payload.get("index", [])
    if datetime_index:
        frame.index = pd.to_datetime(raw_index)
    elif raw_index == [str(i) for i in range(len(raw_index))]:
        frame.index = pd.RangeIndex(len(raw_index))
    else:
        frame.index = pd.Index(raw_index)
    frame.index.name = payload.get("index_name")
    if payload.get("column_names"):
        frame.columns.names = payload["column_names"]
    return frame


def _series_from_mapping(payload: dict, name: str) -> pd.Series:
    return pd.Series(
        list(payload.values()), index=pd.to_datetime(list(payload.keys())), name=name,
        dtype="float64",
    )


def load_backtest_artifacts(output_dir: Path) -> LongOnlyFactorBacktestResult:
    """Safely reconstruct the frozen result from Parquet and JSON artifacts."""
    from qbt.contracts import (
        AlphaBetaReport,
        DatasetRef,
        FillRecord,
        IndexSelectionReport,
        OrderRecord,
        PerformanceStats,
        PortfolioBacktestDiagnostics,
        PortfolioConstraintReport,
        PortfolioPerformanceReport,
        StyleExposureReport,
    )

    root = Path(output_dir).resolve()

    def read_json(name: str) -> dict:
        return json.loads(safe_artifact_path(root, name, "json").read_text(encoding="utf-8"))

    manifest_payload = read_json("run_manifest")
    for ref in manifest_payload.get("artifact_refs", []):
        path = Path(ref["uri"]).resolve()
        if root != path.parent and root not in path.parents:
            raise ValueError(f"manifest artifact outside output directory: {path}")
        if not path.is_file() or hash_file(path) != ref["content_hash"]:
            raise ValueError(f"artifact hash mismatch: {path}")
    manifest_kwargs = {
        key: value for key, value in manifest_payload.items()
        if key in RunManifest.__dataclass_fields__
    }
    manifest_kwargs["dataset_refs"] = tuple(
        DatasetRef(**item) for item in manifest_payload.get("dataset_refs", [])
    )
    manifest_kwargs["disclosures"] = tuple(manifest_payload.get("disclosures", []))
    manifest = RunManifest(**manifest_kwargs)

    performance_payload = read_json("performance_report")

    def stats(name: str) -> PerformanceStats | None:
        payload = performance_payload[name]
        return None if payload is None else PerformanceStats(**payload)

    full_sample = stats("full_sample")
    if full_sample is None:
        raise ValueError("performance_report.full_sample cannot be null")

    yearly = _frame_from_split(performance_payload["yearly"])
    monthly = _frame_from_split(performance_payload["monthly"])
    rolling = _frame_from_split(performance_payload["rolling"], datetime_index=True)
    drawdown = _frame_from_split(performance_payload["drawdown_table"])
    for column in ("peak_date", "trough_date", "recovery_date"):
        if column in drawdown:
            drawdown[column] = pd.to_datetime(drawdown[column])
    performance = PortfolioPerformanceReport(
        full_sample=full_sample,
        in_sample=stats("in_sample"),
        out_of_sample=stats("out_of_sample"),
        yearly=yearly,
        monthly=monthly,
        rolling=rolling,
        drawdown_table=drawdown,
        definitions=performance_payload.get("definitions", {}),
    )

    alpha_payload = read_json("alpha_beta")
    alpha_kwargs = {
        key: value for key, value in alpha_payload.items()
        if key not in {"rolling", "contributions"}
    }
    alpha_beta = AlphaBetaReport(
        **alpha_kwargs,
        rolling=_frame_from_split(alpha_payload["rolling"], datetime_index=True),
        contributions=_frame_from_split(
            alpha_payload["contributions"], datetime_index=True
        ),
    )

    style_frame = pd.read_parquet(safe_artifact_path(root, "style_exposures", "parquet"))
    style_payload = read_json("style_exposure_report")
    style_exposure = StyleExposureReport(
        portfolio_exposure=style_frame["portfolio"],
        index_exposure=style_frame["index"],
        active_exposure=style_frame["active"],
        summary=_frame_from_split(style_payload["summary"]),
        coverage=_frame_from_split(style_payload["coverage"]),
        excess_return_relation=_frame_from_split(style_payload["excess_return_relation"]),
        missing_styles=tuple(style_payload.get("missing_styles", [])),
        data_source=style_payload.get("data_source", "unknown"),
    )

    selection_payload = read_json("index_selection_report")
    selection_report = IndexSelectionReport(
        daily=_frame_from_split(selection_payload["daily"], datetime_index=True),
        yearly=_frame_from_split(selection_payload["yearly"]),
        by_sample=_frame_from_split(selection_payload["by_sample"]),
        diagnostic_equal_weight_returns=_series_from_mapping(
            selection_payload["diagnostic_equal_weight_returns"],
            "equal_weight_diagnostic_return",
        ),
        diagnostic_target_weight_returns=_series_from_mapping(
            selection_payload["diagnostic_target_weight_returns"],
            "target_weight_diagnostic_return",
        ),
        notes=selection_payload.get("notes", {}),
    )

    constraint_payload = read_json("constraint_reports")["constraint_reports"]
    constraint_reports = []
    for item in constraint_payload:
        kwargs = dict(item)
        kwargs["violations"] = _frame_from_split(kwargs["violations"])
        for column in ("date", "signal_date", "order_date", "fill_date"):
            if column in kwargs["violations"]:
                kwargs["violations"][column] = pd.to_datetime(kwargs["violations"][column])
        constraint_reports.append(PortfolioConstraintReport(**kwargs))

    diagnostics_payload = read_json("diagnostics")
    diagnostics = PortfolioBacktestDiagnostics(
        timeline=diagnostics_payload["timeline"],
        data_quality=diagnostics_payload["data_quality"],
        exclusion_reasons=pd.read_parquet(
            safe_artifact_path(root, "exclusion_reasons", "parquet")
        ),
        unfilled_summary=pd.read_parquet(
            safe_artifact_path(root, "unfilled_summary", "parquet")
        ),
        accounting_identity=pd.read_parquet(
            safe_artifact_path(root, "accounting_identity", "parquet")
        ),
        warnings=tuple(diagnostics_payload.get("warnings", [])),
        disclosures=tuple(diagnostics_payload.get("disclosures", [])),
    )

    order_frame = pd.read_parquet(safe_artifact_path(root, "orders", "parquet"))
    orders = []
    for item in order_frame.to_dict(orient="records"):
        item["signal_date"] = pd.Timestamp(item["signal_date"])
        item["order_date"] = pd.Timestamp(item["order_date"])
        orders.append(OrderRecord(**item))
    fill_frame = pd.read_parquet(safe_artifact_path(root, "fills", "parquet"))
    record_columns = FillRecord.__dataclass_fields__.keys()
    fills = []
    for row in fill_frame.to_dict(orient="records"):
        item = {key: row[key] for key in record_columns}
        item["order_date"] = pd.Timestamp(item["order_date"])
        item["fill_date"] = pd.Timestamp(item["fill_date"])
        fills.append(FillRecord(**item))

    daily = pd.read_parquet(safe_artifact_path(root, "daily_returns", "parquet"))
    return LongOnlyFactorBacktestResult(
        run_manifest=manifest,
        selected_members=pd.read_parquet(safe_artifact_path(root, "selected_members", "parquet")),
        target_weights=pd.read_parquet(safe_artifact_path(root, "target_weights", "parquet")),
        actual_weights=pd.read_parquet(safe_artifact_path(root, "actual_weights", "parquet")),
        orders=tuple(orders),
        fills=tuple(fills),
        holdings=pd.read_parquet(safe_artifact_path(root, "holdings", "parquet")),
        cash_ledger=pd.read_parquet(safe_artifact_path(root, "cash_ledger", "parquet")),
        gross_returns=daily["portfolio_gross_return"],
        net_returns=daily["portfolio_net_return"],
        benchmark_returns=daily["benchmark_return"],
        excess_returns=daily["excess_return"],
        portfolio_equity=daily["portfolio_nav"],
        benchmark_equity=daily["benchmark_nav"],
        excess_equity=daily["excess_nav"],
        performance=performance,
        alpha_beta=alpha_beta,
        style_exposure=style_exposure,
        selection_report=selection_report,
        constraint_reports=tuple(constraint_reports),
        diagnostics=diagnostics,
        gross_equity=daily["portfolio_gross_nav"],
        costs=pd.read_parquet(safe_artifact_path(root, "costs", "parquet")),
        portfolio_drawdown=daily["portfolio_drawdown"],
        benchmark_drawdown=daily["benchmark_drawdown"],
        excess_drawdown=daily["excess_drawdown"],
        position_period_analysis=pd.read_parquet(
            safe_artifact_path(root, "position_period_analysis", "parquet")
        ),
    )


def _canonical(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        d = obj.where(obj.notna(), None).astype(object).to_dict(orient="split")
        d["index"] = [_ts_to_str(x) for x in d["index"]]
        d["columns"] = [str(c) for c in d["columns"]]
        d["data"] = [[_scalar(v) for v in row] for row in d["data"]]
        d["index_name"] = _scalar(obj.index.name)
        d["column_names"] = [_scalar(name) for name in obj.columns.names]
        d["dtypes"] = [str(dtype) for dtype in obj.dtypes]
        return d
    if isinstance(obj, pd.Series):
        return {_ts_to_str(k): _canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _canonical(v) for k, v in obj.items()}
    return _scalar(obj)


def _scalar(v):
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (float, np.floating)):
        value = float(v)
        return value if np.isfinite(value) else None
    if isinstance(v, np.integer):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, pd.Period):
        return str(v)
    return v


def _ts_to_str(x):
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if pd.isna(x):
        return None
    return str(x)


def _performance_to_dict(report):
    from qbt.contracts.reports import PerformanceStats

    def _stats(s: PerformanceStats | None):
        if s is None:
            return None
        d = asdict(s)
        for k, v in d.items():
            if isinstance(v, float) and pd.isna(v):
                d[k] = None
        return d

    return {
        "full_sample": _stats(report.full_sample),
        "in_sample": _stats(report.in_sample),
        "out_of_sample": _stats(report.out_of_sample),
        "yearly": _canonical(report.yearly),
        "monthly": _canonical(report.monthly),
        "rolling": _canonical(report.rolling),
        "drawdown_table": _canonical(report.drawdown_table),
        "definitions": report.definitions,
    }


def _alphabeta_to_dict(report):
    return {
        "alpha_daily": report.alpha_daily,
        "alpha_annual": report.alpha_annual,
        "beta": report.beta,
        "alpha_tstat_ols": report.alpha_tstat_ols,
        "alpha_tstat_nw": report.alpha_tstat_nw,
        "alpha_pvalue_ols": report.alpha_pvalue_ols,
        "alpha_pvalue_nw": report.alpha_pvalue_nw,
        "beta_tstat_ols": report.beta_tstat_ols,
        "beta_tstat_nw": report.beta_tstat_nw,
        "r_squared": report.r_squared,
        "residual_volatility_annual": report.residual_volatility_annual,
        "n_observations": report.n_observations,
        "beta_contribution_total": report.beta_contribution_total,
        "alpha_contribution_total": report.alpha_contribution_total,
        "by_sample": report.by_sample,
        "config": report.config,
        "rolling": _canonical(report.rolling),
        "contributions": _canonical(report.contributions),
    }


def _selection_to_dict(report):
    return {
        "daily": _canonical(report.daily),
        "yearly": _canonical(report.yearly),
        "by_sample": _canonical(report.by_sample),
        "diagnostic_equal_weight_returns": _canonical(report.diagnostic_equal_weight_returns),
        "diagnostic_target_weight_returns": _canonical(report.diagnostic_target_weight_returns),
        "notes": report.notes,
    }


def _position_period_summary(df: pd.DataFrame) -> dict:
    """生成持仓迁移表的轻量级 JSON 摘要。"""
    if df.empty:
        return {
            "n_rows": 0,
            "n_dates": 0,
            "n_assets": 0,
            "action_counts": {},
            "status_counts": {},
            "total_buy_shares": 0.0,
            "total_sell_shares": 0.0,
            "avg_fill_ratio": None,
        }
    action_counts = df["action"].value_counts().to_dict()
    status_counts = df["status"].value_counts().to_dict()
    buy_mask = df["fill_quantity_raw"] > 0
    sell_mask = df["fill_quantity_raw"] < 0
    total_buy = float(df.loc[buy_mask, "fill_quantity_raw"].sum())
    total_sell = float(-df.loc[sell_mask, "fill_quantity_raw"].sum())
    ordered_mask = df["order_quantity_raw"].abs() > 1e-9
    avg_fill_ratio = (
        float(df.loc[ordered_mask, "fill_ratio"].mean())
        if ordered_mask.any()
        else None
    )
    return {
        "n_rows": int(len(df)),
        "n_dates": int(df["date"].nunique()),
        "n_assets": int(df["asset_id"].nunique()),
        "action_counts": {str(k): int(v) for k, v in action_counts.items()},
        "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "total_buy_shares": _canonical_value(total_buy),
        "total_sell_shares": _canonical_value(total_sell),
        "avg_fill_ratio": _canonical_value(avg_fill_ratio),
    }


def _canonical_value(v):
    if isinstance(v, float):
        return None if not np.isfinite(v) else float(v)
    return v


def _constraint_to_dict(report):
    d = asdict(report)
    if isinstance(d.get("violations"), pd.DataFrame):
        d["violations"] = _canonical(d["violations"])
    return d
