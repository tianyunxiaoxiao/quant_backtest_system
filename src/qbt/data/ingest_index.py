"""指数月度 PIT 成分与权重摄取 (规范 6.3, 确认清单 A1)。

原始数据: 每月月初快照 (指数月度成分股/*.xlsx), 含成分代码与权重(%)。
月度快照按"生效日期 <= t 的最近一次快照"前向填充到日频, 严禁用最新成分回填历史。
缺月按上一次可用快照延续, 并在数据质量报告中登记缺口。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ALL_A_INDEX_ID = "ALL_A_EQ"
ALL_A_INDEX_NAME = "流动性过滤后的非 ST A 股"
DEFAULT_INDEX_ID = ALL_A_INDEX_ID

__all__ = [
    "IndexSpec",
    "INDEX_SPECS",
    "ALL_A_INDEX_ID",
    "ALL_A_INDEX_NAME",
    "DEFAULT_INDEX_ID",
    "ingest_index_membership",
    "expand_monthly_to_daily",
]


@dataclass(frozen=True)
class IndexSpec:
    index_id: str
    name: str
    file_patterns: tuple[str, ...]
    expected_size: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.index_id):
            raise ValueError(f"非法 index_id: {self.index_id!r}")
        if self.expected_size < 1:
            raise ValueError("expected_size 必须为正整数")


INDEX_SPECS: dict[str, IndexSpec] = {
    "000905.SH": IndexSpec("000905.SH", "中证500", ("500_*.xlsx",), 500),
    "000300.SH": IndexSpec("000300.SH", "沪深300", ("300_*.xlsx",), 300),
    "000852.SH": IndexSpec("000852.SH", "中证1000", ("1000_*.xlsx",), 1000),
}

_COL_DATE = "日期"
_COL_INDEX = "Wind代码"

# 快照列名在不同导出批次里带不同前缀 ("每月月初..." / "2024年1月到2026年5月每月初..."),
# 按后缀识别而不是精确匹配。
_SUFFIX_CODE = "指数成份代码"
_SUFFIX_WEIGHT = "指数成份权重(%)"


def _resolve_snapshot_columns(columns: list[str]) -> tuple[str, str]:
    """定位快照成分代码列与权重列。第一列 '指数成份代码' 是全期并集, 必须排除。"""
    code_cols = [c for c in columns if c.endswith(_SUFFIX_CODE) and c != _SUFFIX_CODE]
    weight_cols = [c for c in columns if c.endswith(_SUFFIX_WEIGHT)]
    if not code_cols or not weight_cols:
        raise ValueError(
            f"无法定位快照列 (code={code_cols}, weight={weight_cols}); 现有列: {columns}"
        )
    return code_cols[0], weight_cols[0]


def ingest_index_membership(
    source_dir: Path, spec: IndexSpec, output_dir: Path | None = None
) -> tuple[pd.DataFrame, dict]:
    """读取月度快照, 返回 (长表[snapshot_date, asset_id, weight], 质量统计)。"""
    files: list[Path] = []
    for pattern in spec.file_patterns:
        files.extend(sorted(Path(source_dir).glob(pattern)))
    if not files:
        raise FileNotFoundError(f"{spec.index_id} 没有匹配的成分文件: {spec.file_patterns}")

    frames = []
    for path in files:
        df = pd.read_excel(path)
        if _COL_DATE not in df.columns:
            raise ValueError(f"{path.name} 缺少日期列; 现有列: {list(df.columns)}")
        col_code, col_weight = _resolve_snapshot_columns(list(df.columns))
        out = pd.DataFrame(
            {
                "snapshot_date": pd.to_datetime(df[_COL_DATE], errors="coerce"),
                "asset_id": df[col_code].astype("string").str.strip().str.upper(),
                "weight": pd.to_numeric(df[col_weight], errors="coerce") / 100.0,
                "source_file": path.name,
            }
        )
        if _COL_INDEX in df.columns:
            codes = df[_COL_INDEX].dropna().astype(str).str.strip().unique()
            if len(codes) and spec.index_id not in set(codes):
                raise ValueError(f"{path.name} 指数代码 {codes[:3]} 与 {spec.index_id} 不符")
        out = out[out["snapshot_date"].notna() & out["asset_id"].notna()]
        frames.append(out)

    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates(subset=["snapshot_date", "asset_id"], keep="last")
    data = data.sort_values(["snapshot_date", "asset_id"], ignore_index=True)
    invalid_weight = (~np.isfinite(data["weight"])) | (data["weight"] < 0)
    if invalid_weight.any():
        sample = data.loc[invalid_weight, ["snapshot_date", "asset_id", "weight"]].head(5)
        raise ValueError(f"{spec.index_id} 包含缺失、无穷或负权重:\n{sample}")

    # 导出批次边界上会出现残缺快照 (成分数远低于指数规模, 权重和明显不足 1),
    # 用残缺快照生效会凭空缩小股票池, 因此剔除并登记。
    raw_counts = data.groupby("snapshot_date").size()
    raw_wsum = data.groupby("snapshot_date")["weight"].sum()
    implausible = raw_wsum[(raw_wsum <= 0) | (raw_wsum > 1.05)]
    if not implausible.empty:
        raise ValueError(
            f"{spec.index_id} 快照权重和不可信: "
            f"{ {str(pd.Timestamp(d).date()): float(v) for d, v in implausible.items()} }"
        )
    incomplete = sorted(
        {
            d for d in raw_counts.index
            if raw_counts[d] < 0.9 * spec.expected_size or raw_wsum[d] < 0.9
        }
    )
    if incomplete:
        data = data[~data["snapshot_date"].isin(incomplete)].reset_index(drop=True)
    if data.empty:
        raise ValueError(f"{spec.index_id} 剔除残缺快照后没有可用成分数据")

    counts = data.groupby("snapshot_date").size()
    weight_sums = data.groupby("snapshot_date")["weight"].sum()
    snapshots = counts.index
    expected_months = pd.period_range(
        snapshots.min().to_period("M"), snapshots.max().to_period("M"), freq="M"
    )
    have = set(snapshots.to_period("M"))
    missing_months = [str(p) for p in expected_months if p not in have]

    stats = {
        "index_id": spec.index_id,
        "index_name": spec.name,
        "source_files": [f.name for f in files],
        "snapshots": int(len(snapshots)),
        "snapshot_first": str(snapshots.min().date()),
        "snapshot_last": str(snapshots.max().date()),
        "members_min": int(counts.min()),
        "members_max": int(counts.max()),
        "expected_size": spec.expected_size,
        "size_mismatch_snapshots": [
            str(d.date()) for d, n in counts.items() if n != spec.expected_size
        ],
        "weight_sum_min": float(weight_sums.min()),
        "weight_sum_max": float(weight_sums.max()),
        "weight_missing_rows": int(data["weight"].isna().sum()),
        "missing_months": missing_months,
        "unique_assets": int(data["asset_id"].nunique()),
        "rows": int(len(data)),
        "dropped_incomplete_snapshots": [str(pd.Timestamp(d).date()) for d in incomplete],
    }

    if output_dir is not None:
        root = Path(output_dir).resolve()
        out_dir = (root / "index_membership").resolve()
        if root not in out_dir.parents:
            raise ValueError("指数输出目录越界")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = (out_dir / f"{spec.index_id}_monthly.parquet").resolve()
        if output_path.parent != out_dir:
            raise ValueError("指数输出路径越界")
        data.to_parquet(output_path, index=False)

    return data, stats


def expand_monthly_to_daily(
    monthly: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    *,
    assets: pd.Index | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """月度快照 -> 日频 PIT 成分矩阵与权重矩阵。

    生效规则: 快照日期 d 的成分自 d 当天 (或之后第一个交易日) 起生效,
    直到下一个快照生效日前一交易日, 只使用当日已知信息。
    """
    required = {"snapshot_date", "asset_id", "weight"}
    missing = required - set(monthly.columns)
    if missing:
        raise ValueError(f"月度指数快照缺少字段: {sorted(missing)}")
    weights = pd.to_numeric(monthly["weight"], errors="coerce")
    if ((~np.isfinite(weights)) | (weights < 0)).any():
        raise ValueError("月度指数快照权重必须有限且非负")
    totals = weights.groupby(monthly["snapshot_date"]).sum()
    if ((totals <= 0) | (totals > 1.05)).any():
        raise ValueError("月度指数快照权重和不可信")
    snaps = sorted(monthly["snapshot_date"].unique())
    universe_assets = sorted(monthly["asset_id"].unique()) if assets is None else sorted(assets)
    asset_pos = {a: i for i, a in enumerate(universe_assets)}

    member = pd.DataFrame(False, index=trading_days, columns=universe_assets)
    weight = pd.DataFrame(float("nan"), index=trading_days, columns=universe_assets)

    grouped = {d: g for d, g in monthly.groupby("snapshot_date")}
    for i, snap in enumerate(snaps):
        eff_start = trading_days[trading_days >= snap]
        if len(eff_start) == 0:
            continue
        start = eff_start[0]
        if i + 1 < len(snaps):
            nxt = trading_days[trading_days >= snaps[i + 1]]
            end = nxt[0] if len(nxt) else trading_days[-1] + pd.Timedelta(days=1)
        else:
            end = trading_days[-1] + pd.Timedelta(days=1)
        rows = (trading_days >= start) & (trading_days < end)
        if not rows.any():
            continue
        g = grouped[snap]
        cols = [asset_pos[a] for a in g["asset_id"] if a in asset_pos]
        vals = [w for a, w in zip(g["asset_id"], g["weight"]) if a in asset_pos]
        member.iloc[rows, cols] = True
        weight.iloc[rows, cols] = vals

    # 权重按行归一化, 消除快照四舍五入导致的 ±0.02% 偏差
    row_sum = weight.sum(axis=1, skipna=True)
    weight = weight.div(row_sum.where(row_sum > 0), axis=0)
    return member, weight
