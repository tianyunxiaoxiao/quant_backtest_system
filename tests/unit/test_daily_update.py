from __future__ import annotations

import os
from pathlib import Path

from ops.data_update.daily_update import prune_superseded_full_releases, publish


def test_publish_and_prune_keep_current_previous_and_legacy(tmp_path: Path) -> None:
    datasets = tmp_path / "datasets"
    datasets.mkdir()
    old = datasets / "rqdata-a-share-20260901-full-v1"
    current_release = datasets / "rqdata-a-share-20260902-full-v1"
    next_release = datasets / "rqdata-a-share-20260903-full-v1"
    legacy = datasets / "rqdata-a-share-20260828-5m-dual-v4"
    for path in (old, current_release, next_release, legacy):
        path.mkdir()
    current = tmp_path / "current"
    previous = tmp_path / "previous"
    os.symlink(current_release, current)
    os.symlink(old, previous)

    publish(current, next_release)
    prune_superseded_full_releases(current, datasets)

    assert current.resolve() == next_release
    assert previous.resolve() == current_release
    assert not old.exists()
    assert current_release.exists()
    assert next_release.exists()
    assert legacy.exists()
