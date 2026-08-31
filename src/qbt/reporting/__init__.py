"""报告层: 图表、Markdown、JSON、产物登记。"""

from qbt.reporting.artifacts import (
    ArtifactWriter,
    load_backtest_artifacts,
    verify_backtest_artifact_roundtrip,
    write_backtest_artifacts,
)
from qbt.reporting.md_builder import MarkdownReportBuilder
from qbt.reporting.reporter import LongOnlyFactorReporter


def __getattr__(name: str):
    if name in {"ChartBuilder", "ChartResult"}:
        from qbt.reporting.charts import ChartBuilder, ChartResult

        return {"ChartBuilder": ChartBuilder, "ChartResult": ChartResult}[name]
    raise AttributeError(name)

__all__ = [
    "ArtifactWriter",
    "ChartBuilder",
    "ChartResult",
    "LongOnlyFactorReporter",
    "MarkdownReportBuilder",
    "write_backtest_artifacts",
    "verify_backtest_artifact_roundtrip",
    "load_backtest_artifacts",
]
