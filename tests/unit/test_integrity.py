"""Provenance, ingestion transaction, and artifact-path integrity."""

import json
import subprocess

import numpy as np
import pandas as pd
import pytest

from qbt.data.hashing import (
    git_code_version,
    hash_files_cached,
    hash_frame,
    hash_matrix_frame,
    hash_source_tree,
)
from qbt.data.ingest_prices import IngestConfig, ingest_prices
from qbt.reporting.artifacts import ArtifactWriter


@pytest.mark.parametrize("name", ["../escape", "a/b", "/absolute", ".."])
def test_artifact_writer_rejects_path_traversal(tmp_path, name):
    writer = ArtifactWriter(tmp_path / "artifacts")
    with pytest.raises(ValueError):
        writer.write_json({"ok": True}, name)


def test_source_tree_hash_fallback_is_deterministic_and_content_bound(tmp_path):
    source = tmp_path / "src" / "pkg"
    source.mkdir(parents=True)
    module = source / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    first = hash_source_tree(tmp_path)
    assert git_code_version(tmp_path) == f"source-{first[:16]}"
    module.write_text("VALUE = 2\n", encoding="utf-8")
    assert hash_source_tree(tmp_path) != first


def test_dirty_git_version_includes_source_tree_hash(tmp_path):
    source = tmp_path / "src" / "pkg"
    source.mkdir(parents=True)
    module = source / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "qbt@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "QBT Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    clean = git_code_version(tmp_path)
    module.write_text("VALUE = 2\n", encoding="utf-8")
    dirty = git_code_version(tmp_path)
    assert dirty.startswith(f"{clean}-dirty-")
    assert dirty.endswith(hash_source_tree(tmp_path)[:16])


def test_hash_frame_has_unambiguous_labels_values_and_datetime_precision():
    index = pd.DatetimeIndex([pd.Timestamp("2020-01-01 00:00:00.000000001")], name="date")
    left = pd.DataFrame({"a": ["x|y"], "b": ["z"]}, index=index)
    right = pd.DataFrame({"a": ["x"], "b": ["y|z"]}, index=index)
    assert hash_frame(left) != hash_frame(right)

    later = left.copy()
    later.index = pd.DatetimeIndex(
        [pd.Timestamp("2020-01-01 00:00:00.000000002")], name="date"
    )
    assert hash_frame(left) != hash_frame(later)
    assert hash_frame(left) != hash_frame(left.rename_axis("other"))


def test_hash_matrix_frame_is_stable_and_content_bound():
    index = pd.date_range("2020-01-01", periods=3, name="date")
    frame = pd.DataFrame(
        [[0.0, np.nan], [1.234567890123, 2.0], [-0.0, np.inf]],
        index=index,
        columns=pd.Index(["A", "B"], name="asset_id"),
    )
    same = frame.copy()
    same.iloc[1, 0] += 1e-12
    changed = frame.copy()
    changed.iloc[1, 0] += 1e-5

    assert hash_matrix_frame(frame) == hash_matrix_frame(same)
    assert hash_matrix_frame(frame) != hash_matrix_frame(changed)
    assert hash_matrix_frame(frame) != hash_matrix_frame(frame.rename_axis("other"))
    assert hash_matrix_frame(frame.astype("float32")) != hash_matrix_frame(frame)


def test_file_hash_cache_invalidates_when_content_changes(tmp_path):
    source = tmp_path / "partition.parquet"
    source.write_bytes(b"first")
    cache = tmp_path / "hash-cache.json"
    first = hash_files_cached([source], cache)
    second = hash_files_cached([source], cache)
    assert second == first

    source.write_bytes(b"second-value")
    third = hash_files_cached([source], cache)
    assert third[source.name] != first[source.name]


def test_artifact_json_replaces_all_nonfinite_values(tmp_path):
    writer = ArtifactWriter(tmp_path / "artifacts")
    artifact = writer.write_json(
        {"nan": np.nan, "positive_infinity": np.inf, "negative_infinity": -np.inf},
        "strict",
    )
    text = (tmp_path / "artifacts" / "strict.json").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text) == {
        "nan": None, "positive_infinity": None, "negative_infinity": None
    }
    assert artifact.bytes > 0


def test_failed_ingestion_preserves_existing_partitions(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "BAD.CSV").write_text("坏列\n1\n", encoding="gb18030")
    output_dir = tmp_path / "warehouse"
    existing_dir = output_dir / "daily_prices"
    existing_dir.mkdir(parents=True)
    existing = existing_dir / "daily_prices_2020.parquet"
    sentinel = pd.DataFrame({"sentinel": [1]})
    sentinel.to_parquet(existing, index=False)

    with pytest.raises(ValueError, match="缺少"):
        ingest_prices(
            IngestConfig(source_dir=source_dir, output_dir=output_dir, max_workers=1),
            verbose=False,
        )

    pd.testing.assert_frame_equal(pd.read_parquet(existing), sentinel)


def test_ingestion_restores_interrupted_backup_before_work(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "BAD.CSV").write_text("坏列\n1\n", encoding="gb18030")
    output_dir = tmp_path / "warehouse"
    backup = output_dir / ".daily_prices_backup_interrupted"
    backup.mkdir(parents=True)
    sentinel = pd.DataFrame({"sentinel": [7]})
    sentinel.to_parquet(backup / "daily_prices_2020.parquet", index=False)

    with pytest.raises(ValueError, match="缺少"):
        ingest_prices(
            IngestConfig(source_dir=source_dir, output_dir=output_dir, max_workers=1),
            verbose=False,
        )
    restored = output_dir / "daily_prices" / "daily_prices_2020.parquet"
    pd.testing.assert_frame_equal(pd.read_parquet(restored), sentinel)
