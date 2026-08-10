"""报告器 (规范 14.3)。

报告器只读取 LongOnlyFactorBacktestResult, 生成图表、Markdown、JSON 与产物登记。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from qbt.contracts import (
    LongOnlyFactorBacktestResult,
    LongOnlyFactorReportRequest,
    LongOnlyFactorReportResult,
    PortfolioReportConfig,
    RunArtifact,
)
from qbt.data.hashing import hash_file

from .artifacts import (
    ArtifactWriter,
    _canonical,
    safe_artifact_path,
    verify_backtest_artifact_roundtrip,
    write_backtest_artifacts,
)
from .charts import ChartBuilder
from .md_builder import MarkdownReportBuilder

__all__ = ["LongOnlyFactorReporter"]


class LongOnlyFactorReporter:
    """报告器入口。"""

    def __init__(self, config: PortfolioReportConfig | None = None) -> None:
        self.config = config or PortfolioReportConfig()

    def render(
        self,
        request: LongOnlyFactorReportRequest,
    ) -> LongOnlyFactorReportResult:
        result = request.backtest
        self._validate(result)
        config = request.report_config or self.config
        if request.output_dir is None:
            raise ValueError("output_dir 不能为空")
        output_dir = Path(request.output_dir).resolve()
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError(f"报告输出路径不是目录: {output_dir}")
        stage_dir = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent)
        )

        try:
            rendered = self._render_staged(result, config, stage_dir, output_dir)
            self._verify_staged_inventory(stage_dir, output_dir, rendered.all_artifacts)
            backup_dir = self._publish(stage_dir, output_dir)
            try:
                verify_backtest_artifact_roundtrip(result, output_dir)
            except Exception:
                failed_dir = output_dir.parent / f".{output_dir.name}.failed-{uuid.uuid4().hex}"
                output_dir.rename(failed_dir)
                if backup_dir is not None:
                    backup_dir.rename(output_dir)
                shutil.rmtree(failed_dir)
                raise
            if backup_dir is not None:
                shutil.rmtree(backup_dir)
            return rendered
        finally:
            if stage_dir.exists():
                shutil.rmtree(stage_dir)

    def _render_staged(
        self,
        result: LongOnlyFactorBacktestResult,
        config: PortfolioReportConfig,
        stage_dir: Path,
        output_dir: Path,
    ) -> LongOnlyFactorReportResult:

        # 1. 写出数据产物
        data_artifacts = write_backtest_artifacts(
            result, stage_dir, include_manifest=False, uri_root=output_dir
        )

        # 2. 生成图表
        chart_builder = ChartBuilder(
            width=config.figure_width,
            height=config.figure_height,
            dpi=config.chart_dpi,
            format=config.chart_format,
        )
        chart_result = chart_builder.build(result)
        chart_artifacts: list[RunArtifact] = []
        writer = _ChartWriter(
            stage_dir, dpi=config.chart_dpi, fmt=config.chart_format, uri_root=output_dir
        )
        for name, fig in chart_result.figures.items():
            chart_artifacts.append(writer.write(fig, name))

        # 3. 生成 Markdown
        md_artifacts: list[RunArtifact] = []
        if config.write_markdown:
            md = MarkdownReportBuilder(
                title=config.title, max_table_rows=config.max_table_rows
            ).build(result)
            path = safe_artifact_path(stage_dir, "backtest_report", "md")
            path.write_text(md, encoding="utf-8")
            md_artifacts.append(
                RunArtifact(
                    name="backtest_report.md",
                    uri=str((output_dir / path.relative_to(stage_dir)).resolve()),
                    content_hash=hash_file(path),
                    bytes=path.stat().st_size,
                    kind="report",
                )
            )

        # 4. 生成汇总 JSON (与 Markdown 内容等价, 机器可读)
        json_artifacts: list[RunArtifact] = []
        if config.write_json:
            summary = self._build_summary(result)
            path = safe_artifact_path(stage_dir, "backtest_report", "json")
            path.write_text(
                json.dumps(
                    _canonical(summary), ensure_ascii=False, indent=2, allow_nan=False
                ),
                encoding="utf-8",
            )
            json_artifacts.append(
                RunArtifact(
                    name="backtest_report.json",
                    uri=str((output_dir / path.relative_to(stage_dir)).resolve()),
                    content_hash=hash_file(path),
                    bytes=path.stat().st_size,
                    kind="report",
                )
            )

        pre_manifest = data_artifacts + chart_artifacts + md_artifacts + json_artifacts
        manifest_writer = ArtifactWriter(stage_dir, uri_root=output_dir)
        manifest_writer.artifacts.extend(pre_manifest)
        published_manifest = replace(result.run_manifest, artifact_uri=str(output_dir))
        manifest_artifact = manifest_writer.write_manifest(published_manifest)
        data_artifacts = data_artifacts + [manifest_artifact]
        all_artifacts = tuple(pre_manifest + [manifest_artifact])
        return LongOnlyFactorReportResult(
            report_artifacts=tuple(md_artifacts + json_artifacts),
            chart_artifacts=tuple(chart_artifacts),
            data_artifacts=tuple(data_artifacts),
            all_artifacts=all_artifacts,
            output_dir=output_dir,
        )

    @staticmethod
    def _verify_staged_inventory(
        stage_dir: Path,
        output_dir: Path,
        artifacts: tuple[RunArtifact, ...],
    ) -> None:
        expected: set[Path] = set()
        for artifact in artifacts:
            published = Path(artifact.uri).resolve()
            try:
                relative = published.relative_to(output_dir)
            except ValueError as exc:
                raise ValueError(f"产物 URI 越界: {published}") from exc
            staged = (stage_dir / relative).resolve()
            if stage_dir != staged.parent and stage_dir not in staged.parents:
                raise ValueError(f"暂存产物路径越界: {staged}")
            if not staged.is_file() or hash_file(staged) != artifact.content_hash:
                raise ValueError(f"暂存产物校验失败: {staged}")
            expected.add(staged)
        actual = {path.resolve() for path in stage_dir.rglob("*") if path.is_file()}
        if actual != expected:
            raise ValueError(
                f"暂存产物清单不一致: extra={sorted(map(str, actual - expected))}, "
                f"missing={sorted(map(str, expected - actual))}"
            )

    @staticmethod
    def _publish(stage_dir: Path, output_dir: Path) -> Path | None:
        backup_dir: Path | None = None
        if output_dir.exists():
            backup_dir = output_dir.parent / f".{output_dir.name}.backup-{uuid.uuid4().hex}"
            output_dir.rename(backup_dir)
        try:
            stage_dir.rename(output_dir)
        except Exception:
            if backup_dir is not None and not output_dir.exists():
                backup_dir.rename(output_dir)
            raise
        return backup_dir

    @staticmethod
    def _validate(result: LongOnlyFactorBacktestResult) -> None:
        required = [
            "run_manifest", "selected_members", "target_weights", "actual_weights",
            "portfolio_equity", "benchmark_equity", "excess_equity", "performance",
            "alpha_beta", "style_exposure", "selection_report",
        ]
        missing = [k for k in required if getattr(result, k, None) is None]
        if missing:
            raise ValueError(f"回测结果缺少必要字段: {missing}")

    @staticmethod
    def _build_summary(result: LongOnlyFactorBacktestResult) -> dict[str, Any]:
        from qbt.reporting.artifacts import (
            _alphabeta_to_dict,
            _performance_to_dict,
            _selection_to_dict,
        )

        m = result.run_manifest
        return {
            "run_id": m.run_id,
            "strategy_id": m.strategy_id,
            "factor_id": m.factor_id,
            "index_id": m.index_id,
            "code_version": m.code_version,
            "config_version": m.config_version,
            "created_at": m.created_at,
            "result_hash": m.result_hash,
            "performance": _performance_to_dict(result.performance),
            "alpha_beta": _alphabeta_to_dict(result.alpha_beta),
            "selection_report": _selection_to_dict(result.selection_report),
            "disclosures": list(m.disclosures),
        }


class _ChartWriter:
    def __init__(
        self, output_dir: Path, *, dpi: int, fmt: str, uri_root: Path | None = None
    ) -> None:
        self.output_dir = output_dir
        self.uri_root = Path(uri_root).resolve() if uri_root is not None else output_dir.resolve()
        self.dpi = dpi
        self.fmt = fmt
        (self.output_dir / "charts").mkdir(parents=True, exist_ok=True)

    def write(self, fig, name: str) -> RunArtifact:
        path = safe_artifact_path(self.output_dir, name, self.fmt, subdir="charts")
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight", format=self.fmt)
        artifact = RunArtifact(
            name=f"charts/{name}.{self.fmt}",
            uri=str((self.uri_root / path.relative_to(self.output_dir)).resolve()),
            content_hash=hash_file(path),
            bytes=path.stat().st_size,
            kind="chart",
        )
        from matplotlib import pyplot as plt

        plt.close(fig)
        return artifact
