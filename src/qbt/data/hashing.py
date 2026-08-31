"""内容哈希与运行编号 (规范 3.10 / 6.1 / 19)。"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import uuid
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "hash_bytes",
    "hash_files_cached",
    "hash_file",
    "hash_frame",
    "hash_matrix_frame",
    "hash_series",
    "hash_json",
    "hash_object",
    "hash_source_tree",
    "new_run_id",
    "git_code_version",
    "utc_now_iso",
]

_CHUNK = 1 << 20


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def hash_files_cached(paths: list[Path], cache_path: Path) -> dict[str, str]:
    """Return content hashes, re-reading only files whose size or mtime changed."""
    cache_path = Path(cache_path)
    entries: dict[str, Any] = {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") == 1 and isinstance(payload.get("files"), dict):
            entries = dict(payload["files"])
    except (OSError, json.JSONDecodeError, AttributeError):
        entries = {}

    result: dict[str, str] = {}
    changed = False
    for path in sorted(Path(item) for item in paths):
        resolved = path.resolve()
        key = str(resolved)
        stat = resolved.stat()
        cached = entries.get(key, {})
        if (
            cached.get("size") == stat.st_size
            and cached.get("mtime_ns") == stat.st_mtime_ns
            and cached.get("ctime_ns") == stat.st_ctime_ns
            and isinstance(cached.get("sha256"), str)
        ):
            digest = cached["sha256"]
        else:
            digest = hash_file(resolved)
            entries[key] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "ctime_ns": stat.st_ctime_ns,
                "sha256": digest,
            }
            changed = True
        result[path.name] = digest

    if changed or not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
        temp.write_text(
            json.dumps(
                {"schema_version": 1, "files": entries},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temp.replace(cache_path)
    return result


def _canonical(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if not math.isfinite(value) else round(value, 12)
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else round(obj, 12)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): _canonical(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if pd.isna(obj) if np.isscalar(obj) else False:
        return None
    return str(obj)


def hash_json(obj: Any) -> str:
    return hash_bytes(
        json.dumps(
            _canonical(obj), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode()
    )


def _update_blob(h: Any, payload: bytes) -> None:
    """Add a byte string without delimiter ambiguity."""
    h.update(len(payload).to_bytes(8, "big", signed=False))
    h.update(payload)


def _scalar_bytes(value: Any, *, decimals: int) -> bytes:
    """Type-tag one scalar while preserving nulls and full datetime precision."""
    if value is None or value is pd.NaT:
        return b"null"
    if isinstance(value, (pd.Timestamp, datetime, np.datetime64)):
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return b"null"
        return b"datetime:" + timestamp.isoformat().encode("utf-8")
    if isinstance(value, (bool, np.bool_)):
        return b"bool:1" if bool(value) else b"bool:0"
    if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        return b"int:" + str(int(value)).encode("ascii")
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return b"null"
        if math.isinf(number):
            return b"float:+inf" if number > 0 else b"float:-inf"
        number = round(number, decimals) + 0.0
        return b"float:" + number.hex().encode("ascii")
    if isinstance(value, bytes):
        return b"bytes:" + value
    if isinstance(value, tuple):
        h = hashlib.sha256()
        h.update(b"tuple")
        for item in value:
            _update_blob(h, _scalar_bytes(item, decimals=decimals))
        return b"tuple-hash:" + h.digest()
    try:
        if bool(pd.isna(value)):
            return b"null"
    except (TypeError, ValueError):
        pass
    return b"str:" + str(value).encode("utf-8")


def _hash_index(h: Any, index: pd.Index, *, label: str, decimals: int) -> None:
    _update_blob(h, label.encode("ascii"))
    _update_blob(h, f"{type(index).__module__}.{type(index).__qualname__}".encode("utf-8"))
    if isinstance(index, pd.MultiIndex):
        dtypes = [str(level.dtype) for level in index.levels]
        names = list(index.names)
    else:
        dtypes = [str(index.dtype)]
        names = [index.name]
    _update_blob(
        h,
        json.dumps(
            {"dtypes": dtypes, "names": _canonical(names)},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"),
    )
    for value in index.tolist():
        _update_blob(h, _scalar_bytes(value, decimals=decimals))


def _fast_hash_index(h: Any, index: pd.Index, *, label: str) -> None:
    """Hash an axis in vectorized C code while retaining its structural metadata."""
    _update_blob(h, label.encode("ascii"))
    _update_blob(h, f"{type(index).__module__}.{type(index).__qualname__}".encode("utf-8"))
    if isinstance(index, pd.MultiIndex):
        dtypes = [str(level.dtype) for level in index.levels]
        names = list(index.names)
    else:
        dtypes = [str(index.dtype)]
        names = [index.name]
    _update_blob(
        h,
        json.dumps(
            {"dtypes": dtypes, "names": _canonical(names)},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"),
    )
    hashed = pd.util.hash_pandas_object(index, index=False, categorize=True)
    _update_blob(h, hashed.to_numpy(dtype="uint64", copy=False).tobytes())


def _normalized_hash_series(series: pd.Series, *, decimals: int) -> pd.Series:
    """Match the public hash contract's finite-float rounding without Python scalar loops."""
    if not pd.api.types.is_float_dtype(series.dtype):
        return series
    values = series.to_numpy(dtype="float64", copy=True)
    finite = np.isfinite(values)
    values[finite] = np.round(values[finite], decimals=decimals)
    values[finite & (values == 0.0)] = 0.0
    return pd.Series(values, index=series.index, name=series.name)


def hash_frame(df: pd.DataFrame, *, decimals: int = 10) -> str:
    """Unambiguously hash values, axes, nulls, dtypes, and datetime precision."""
    if df is None:
        return hash_bytes(b"__none__")
    h = hashlib.sha256()
    h.update(b"qbt-frame-v3-vectorized")
    _update_blob(h, json.dumps(list(df.shape), separators=(",", ":")).encode("ascii"))
    _fast_hash_index(h, df.index, label="index")
    _fast_hash_index(h, df.columns, label="columns")
    for col in df.columns:
        s = df[col]
        _update_blob(h, str(s.dtype).encode("utf-8"))
        normalized = _normalized_hash_series(s, decimals=decimals)
        hashed = pd.util.hash_pandas_object(normalized, index=False, categorize=True)
        _update_blob(h, hashed.to_numpy(dtype="uint64", copy=False).tobytes())
    return h.hexdigest()


def hash_matrix_frame(df: pd.DataFrame, *, decimals: int = 10) -> str:
    """Hash a homogeneous numeric/bool matrix without per-column pandas calls.

    This is intended for the large, rectangular state matrices produced by the
    backtester.  Float values retain the public hash contract's rounding, NaN
    normalization and signed-zero normalization.  Mixed/object frames continue
    to use :func:`hash_frame`.
    """
    if df is None:
        return hash_bytes(b"__none__")
    if not all(
        pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_bool_dtype(dtype)
        for dtype in df.dtypes
    ):
        raise TypeError("hash_matrix_frame 只支持数值或布尔矩阵")

    h = hashlib.sha256()
    h.update(b"qbt-matrix-frame-v1")
    _update_blob(h, json.dumps(list(df.shape), separators=(",", ":")).encode("ascii"))
    _fast_hash_index(h, df.index, label="index")
    _fast_hash_index(h, df.columns, label="columns")
    _update_blob(h, json.dumps([str(dtype) for dtype in df.dtypes]).encode("utf-8"))

    if all(pd.api.types.is_bool_dtype(dtype) for dtype in df.dtypes):
        values = np.ascontiguousarray(df.to_numpy(dtype="bool", copy=False))
        _update_blob(h, values.view("uint8").tobytes())
        return h.hexdigest()

    values = np.ascontiguousarray(df.to_numpy(dtype="float64", copy=True))
    finite = np.isfinite(values)
    values[finite] = np.round(values[finite], decimals=decimals)
    values[finite & (values == 0.0)] = 0.0
    # Make all missing values byte-identical; infinities remain signed.
    values[np.isnan(values)] = np.nan
    _update_blob(h, values.tobytes())
    return h.hexdigest()


def hash_series(s: pd.Series, *, decimals: int = 10) -> str:
    if s is None:
        return hash_bytes(b"__none__")
    return hash_frame(s.to_frame(name=str(s.name or "value")), decimals=decimals)


def _fingerprint(obj: Any) -> Any:
    """Convert nested business objects into a deterministic hashable structure."""
    if isinstance(obj, pd.DataFrame):
        return {"type": "dataframe", "hash": hash_frame(obj)}
    if isinstance(obj, pd.Series):
        return {"type": "series", "hash": hash_series(obj)}
    if isinstance(obj, pd.Index):
        return {"type": "index", "values": [_canonical(v) for v in obj.tolist()]}
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            "type": f"{type(obj).__module__}.{type(obj).__qualname__}",
            "fields": {field.name: _fingerprint(getattr(obj, field.name)) for field in fields(obj)},
        }
    if isinstance(obj, dict):
        return {str(k): _fingerprint(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_fingerprint(v) for v in obj]
    if isinstance(obj, np.ndarray):
        arr = np.ascontiguousarray(obj)
        return {"type": "ndarray", "shape": arr.shape, "dtype": str(arr.dtype),
                "hash": hash_bytes(arr.tobytes())}
    if isinstance(obj, Path):
        return str(obj)
    return _canonical(obj)


def hash_object(obj: Any) -> str:
    """Hash nested dataclasses, pandas objects, mappings, records, and scalars."""
    return hash_json(_fingerprint(obj))


def hash_source_tree(repo_root: str | Path) -> str:
    """Hash executable project sources for environments without Git metadata."""
    root = Path(repo_root).resolve()
    paths: list[Path] = []
    for subtree in (root / "src", root / "scripts"):
        if subtree.exists():
            paths.extend(path for path in subtree.rglob("*") if path.is_file() and path.suffix == ".py")
    paths.extend(path for path in (root / "pyproject.toml", root / "requirements.txt") if path.exists())
    h = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        h.update(relative.encode("utf-8"))
        h.update(b"\0")
        h.update(hash_file(path).encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def new_run_id(prefix: str = "lof") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def git_code_version(repo_root: str | Path | None = None) -> str:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            dirty = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            suffix = (
                f"-dirty-{hash_source_tree(root)[:16]}"
                if dirty.stdout.strip() else ""
            )
            return out.stdout.strip() + suffix
    except Exception:  # noqa: BLE001 - 非 git 环境按规范标记
        pass
    return f"source-{hash_source_tree(root)[:16]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
