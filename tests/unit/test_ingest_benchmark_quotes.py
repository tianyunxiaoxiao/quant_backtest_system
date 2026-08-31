from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.ingest_benchmark_quotes import SPECS, ingest_benchmark_quotes


def test_ingest_benchmark_quotes_normalizes_and_records_provenance(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    for _, filename in SPECS.values():
        pd.DataFrame(
            {
                "交易日期": ["2024-01-03", "2024-01-02", "2024-01-04"],
                "收盘价": ["1,020", "1,000", "1,010"],
            }
        ).to_excel(source_dir / filename, index=False)

    manifest = ingest_benchmark_quotes(source_dir, output_dir)

    assert manifest["schema_version"] == "qbt_benchmark_quotes/v1"
    assert len(manifest["benchmarks"]) == 3
    first = manifest["benchmarks"][0]
    assert first["source_sha256"].startswith("sha256:")
    assert first["content_sha256"].startswith("sha256:")
    assert first["date_min"] == "2024-01-02"
    normalized = pd.read_parquet(output_dir / first["file"])
    assert normalized["date"].is_monotonic_increasing
    assert normalized["close"].tolist() == [1000, 1020, 1010]
