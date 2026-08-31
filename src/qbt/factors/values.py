"""外部因子值直接回测 (2026-08-18 新增)。

系统职责边界 (规范 6.2) 始终不变: 回测器只消费一个已经构造完成的
最终 ``FactorFrame``, 不做标准化、合成、权重学习或符号反转。此前该
``FactorFrame`` 只能由 ``factors/demo.py`` 的公式因子现场计算; 本模块
补充另一条等价入口 —— 直接加载外部算好的因子值矩阵 (例如多因子研究
平台导出的 ``factor_values/*.parquet``), 构建同一份 ``FactorFrame``。

导入格式约定 (参考外部导出包 ``factor_values_export``):
- Parquet 宽表: 行 = 交易日 (DatetimeIndex), 列 = asset_id (如 000001.SZ);
- 值为数值型因子分值, 缺失保留 NaN, 由 missing_policy 在选股层剔除;
- 方向 ``direction`` 必须在回测前显式声明 (+1 越大越好 / -1 越小越好),
  与演示因子 "方向事前写死、跑完不许改符号" 的纪律一致。

本模块同样遵守 PIT 纪律: 只按值本身回测, 不对未来做任何填充或修补。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from ..contracts.frames import FactorFrame
from ..data.hashing import hash_frame

__all__ = [
    "FactorValuesStats",
    "inspect_factor_values",
    "load_target_weights",
    "load_factor_values",
]


@dataclass(frozen=True)
class FactorValuesStats:
    """因子值矩阵的导入体检结果, 供上传校验与界面展示使用。"""

    n_dates: int
    n_assets: int
    date_start: pd.Timestamp | None
    date_end: pd.Timestamp | None
    coverage_ratio: float
    n_duplicate_columns: int = 0


def _coerce_wide_matrix(raw: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """把外部 parquet 规范化为 (DatetimeIndex, asset_id 列) 的 float64 宽表。

    校验规则全部显式失败, 不静默修复:
    - 必须是二维 DataFrame 且非空;
    - 索引必须可转成日期 (外部导出常见 datetime64[us]);
    - 列必须是非空字符串 asset_id, 不允许重复 (重复会让选股并列判定不确定);
    - 值必须可转数值, Inf 统一转 NA (与演示因子口径一致);
    - 行列排序确定性化 (日期升序、列升序), 保证内容哈希稳定。
    """
    if not isinstance(raw, pd.DataFrame):
        raise TypeError(f"{source}: 因子值必须是二维 DataFrame, 实际 {type(raw).__name__}")
    if raw.empty:
        raise ValueError(f"{source}: 因子值矩阵为空")

    index = raw.index
    if not isinstance(index, pd.DatetimeIndex):
        try:
            with warnings.catch_warnings():
                # 字符串索引逐元素解析会发 UserWarning; 转换失败本身按错误处理。
                warnings.simplefilter("ignore", UserWarning)
                coerced = pd.to_datetime(index)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{source}: 行索引必须是交易日日期, 实际 {type(index).__name__}") from exc
        index = pd.DatetimeIndex(coerced)
    if index.has_duplicates:
        dup = index[index.duplicated()].unique()[:3]
        raise ValueError(f"{source}: 行索引存在重复日期: {[str(d) for d in dup]}")

    columns = [str(c).strip() for c in raw.columns]
    if any(not c for c in columns):
        raise ValueError(f"{source}: 存在空 asset_id 列")
    if len(set(columns)) != len(columns):
        seen: set[str] = set()
        dup_assets: list[str] = []
        for c in columns:
            if c in seen:
                dup_assets.append(c)
            else:
                seen.add(c)
        raise ValueError(f"{source}: asset_id 列重复: {dup_assets[:5]}")

    non_numeric = [
        c for c in raw.columns if not pd.api.types.is_numeric_dtype(raw[c])
    ]
    if non_numeric:
        # 允许 object 列在值本身可转数值时通过 (部分导出工具写成 object)。
        bad: list[str] = []
        for c in non_numeric:
            try:
                pd.to_numeric(raw[c])
            except (TypeError, ValueError):
                bad.append(str(c))
        if bad:
            raise TypeError(f"{source}: 存在非数值因子列: {bad[:5]}")

    values = raw.copy()
    values.index = pd.DatetimeIndex(index).normalize()
    values.columns = columns
    values = values.sort_index(axis=0).sort_index(axis=1)
    # FactorFrame 使用固定轴名称；先完成规范化再计算内容哈希，避免构造前后
    # 仅轴名称变化却被误判为因子值遭到篡改。
    values.index = values.index.copy().rename("date")
    values.columns = values.columns.copy().rename("asset_id")
    values = values.astype("float64")
    # Inf 统一转 NaN (float64 原生缺失), 与演示因子口径一致
    values = values.where(np.isfinite(values))
    return values.astype("float64")


def _read_source(source: Path | str | pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """读入 parquet 文件或直接接收内存 DataFrame, 返回 (原始表, 来源标签)。"""
    if isinstance(source, pd.DataFrame):
        return source, "dataframe"
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"{path}: 文件不存在")
    return pd.read_parquet(path), str(path)


def inspect_factor_values(source: Path | str | pd.DataFrame) -> FactorValuesStats:
    """读取并体检因子值矩阵, 不构建 FactorFrame。上传校验用它快速失败。"""
    raw, label = _read_source(source)
    values = _coerce_wide_matrix(raw, source=label)
    n_dates, n_assets = values.shape
    if n_dates:
        return FactorValuesStats(
            n_dates=n_dates,
            n_assets=n_assets,
            date_start=values.index[0],
            date_end=values.index[-1],
            coverage_ratio=round(float(values.notna().to_numpy().mean()), 6),
        )
    return FactorValuesStats(n_dates=0, n_assets=n_assets, date_start=None, date_end=None, coverage_ratio=0.0)


def load_factor_values(
    source: Path | str | pd.DataFrame,
    *,
    factor_id: str,
    direction: int,
    description: str = "",
    data_version: str = "unversioned",
    code_version: str = "unversioned",
    metadata: Mapping[str, Any] | None = None,
) -> FactorFrame:
    """从 parquet 宽表 (或内存 DataFrame) 构建可直接回测的 FactorFrame。

    - ``direction`` 必须显式传入且只能是 +1 / -1, 系统不做任何隐式方向推断;
    - 内容哈希每次重新计算 (调用方声明不一致时由 FactorFrame 使用本哈希);
    - 元数据记录来源、形状、区间与覆盖率, 保证血缘可审计。
    """
    if not factor_id or not str(factor_id).strip():
        raise ValueError("factor_id 不能为空")
    if direction not in (1, -1):
        raise ValueError("direction 必须是 +1 或 -1 (回测前显式声明, 不许事后翻转)")

    raw, label = _read_source(source)
    values = _coerce_wide_matrix(raw, source=label)
    stats = inspect_factor_values(values)

    meta: dict[str, Any] = {
        "source_path": label if not isinstance(source, pd.DataFrame) else "<in-memory>",
        "n_dates": stats.n_dates,
        "n_assets": stats.n_assets,
        "date_start": str(stats.date_start.date()) if stats.date_start is not None else None,
        "date_end": str(stats.date_end.date()) if stats.date_end is not None else None,
        "coverage_ratio": stats.coverage_ratio,
        "direction_locked_before_backtest": True,
        "source": "imported factor values (pre-computed, formula external)",
    }
    if metadata:
        meta.update(dict(metadata))

    return FactorFrame(
        values=values,
        factor_id=str(factor_id).strip(),
        direction=direction,
        description=description or f"外部导入因子值 {factor_id}",
        missing_policy="exclude_from_eligible",
        data_version=data_version,
        content_hash=hash_frame(values),
        code_version=code_version,
        metadata=meta,
    )


def load_target_weights(
    source: Path | str | pd.DataFrame,
    *,
    portfolio_id: str,
    description: str = "",
    data_version: str = "unversioned",
    code_version: str = "unversioned",
    metadata: Mapping[str, Any] | None = None,
) -> FactorFrame:
    """Load an exact long-only target-weight schedule.

    Each row is one signal date. NaN means zero target weight, row sums below one
    leave cash, and no ranking or normalization is applied downstream.
    """
    raw, label = _read_source(source)
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    if np.isinf(numeric.to_numpy(dtype="float64")).any():
        raise ValueError(f"{label}: 目标权重不能包含 Inf")
    values = _coerce_wide_matrix(raw, source=label).fillna(0.0)
    if (values.to_numpy() < 0.0).any():
        row, col = np.argwhere(values.to_numpy() < 0.0)[0]
        raise ValueError(
            f"{label}: 目标权重不能为负: {values.index[row].date()} {values.columns[col]}"
        )
    row_sums = values.sum(axis=1)
    overflow = row_sums > 1.0 + 1e-8
    if overflow.any():
        day = row_sums.index[overflow][0]
        raise ValueError(f"{label}: {day.date()} 权重和 {row_sums.loc[day]:.8f} 超过 1")
    values = values.mask(values.abs() < 1e-15, 0.0)
    meta = {
        "source_path": label if not isinstance(source, pd.DataFrame) else "<in-memory>",
        "n_dates": int(values.shape[0]),
        "n_assets": int(values.shape[1]),
        "date_start": str(values.index[0].date()),
        "date_end": str(values.index[-1].date()),
        "coverage_ratio": round(float((values > 0).to_numpy().mean()), 6),
        "value_type": "target_weights",
        "weight_semantics": "exact_long_only_targets; nan_is_zero; residual_is_cash",
        "source": "imported target weights (pre-computed externally)",
    }
    if metadata:
        meta.update(dict(metadata))
    return FactorFrame(
        values=values,
        factor_id=str(portfolio_id).strip(),
        direction=1,
        description=description or f"直接目标权重 {portfolio_id}",
        missing_policy="nan_is_zero_target",
        data_version=data_version,
        content_hash=hash_frame(values),
        code_version=code_version,
        metadata=meta,
    )
