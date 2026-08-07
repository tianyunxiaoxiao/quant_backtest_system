"""PortfolioDataPortal (规范 6.1)。

研究员只给 factor + index_id; 行情、成分、基准、可交易性、风格、流动性
全部由本层按 index_id 与因子日期自动加载、校验、登记。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..contracts import (
    DatasetRef,
    FactorFrame,
    LongOnlyFactorBacktestConfig,
    MarketPriceFrame,
    PortfolioInitialState,
    PortfolioLiquidityData,
    ResolvedLongOnlyBacktestData,
    TradabilityFrame,
)
from .benchmark import build_benchmark_returns, load_official_benchmark
from .hashing import hash_file, hash_frame, hash_json, hash_series
from .ingest_index import INDEX_SPECS, expand_monthly_to_daily, ingest_index_membership
from .panel import build_trading_calendar, load_price_panel
from .style import MISSING_STYLES, build_style_exposures
from .tradability import build_limit_matrices, build_suspension

__all__ = ["PortalConfig", "PortfolioDataPortal"]


@dataclass(frozen=True)
class PortalConfig:
    warehouse_dir: Path
    index_source_dir: Path
    calendar_min_active: int = 200
    adv_window: int = 20
    limit_buffer_ratio: float = 0.005
    # 确认清单 B1: 默认 T+1 VWAP。涨跌停判定口径随之对齐。
    fill_price_field: str = "adj_vwap"
    benchmark_drift_within_period: bool = True
    official_benchmark_files: dict[str, str] = field(default_factory=dict)
    style_warmup_days: int = 300
    cache_dir: Path | None = None


class PortfolioDataPortal:
    """按 index_id 与因子日期解析全部回测输入。"""

    def __init__(self, config: PortalConfig) -> None:
        self.config = config
        self._calendar: pd.DatetimeIndex | None = None

    # ---------- 公共入口 ----------

    def trading_calendar(self) -> pd.DatetimeIndex:
        if self._calendar is None:
            cache = Path(self.config.warehouse_dir) / "trading_calendar.parquet"
            cache_meta = cache.with_suffix(".meta.json")
            source_signature = self._calendar_source_signature()
            valid_cache = False
            if cache.exists() and cache_meta.exists():
                try:
                    meta = json.loads(cache_meta.read_text(encoding="utf-8"))
                    cached = pd.read_parquet(cache)
                    valid_cache = (
                        list(cached.columns) == ["date"]
                        and pd.api.types.is_datetime64_any_dtype(cached["date"])
                        and cached["date"].notna().all()
                        and cached["date"].is_monotonic_increasing
                        and not cached["date"].duplicated().any()
                        and meta.get("schema_version") == 1
                        and meta.get("calendar_min_active") == self.config.calendar_min_active
                        and meta.get("source_signature") == source_signature
                        and meta.get("cache_hash") == hash_file(cache)
                    )
                    if valid_cache:
                        self._calendar = pd.DatetimeIndex(cached["date"], name="date")
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    valid_cache = False
            if not valid_cache:
                self._calendar = build_trading_calendar(
                    Path(self.config.warehouse_dir),
                    pd.Timestamp("1990-01-01"),
                    pd.Timestamp("2100-01-01"),
                    min_active=self.config.calendar_min_active,
                )
                cache.parent.mkdir(parents=True, exist_ok=True)
                self._calendar.to_frame(index=False).to_parquet(cache, index=False)
                cache_meta.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "calendar_min_active": self.config.calendar_min_active,
                            "source_signature": source_signature,
                            "cache_hash": hash_file(cache),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        return self._calendar

    def _calendar_source_signature(self) -> str:
        price_dir = Path(self.config.warehouse_dir) / "daily_prices"
        partitions = []
        for path in sorted(price_dir.glob("*.parquet")):
            stat = path.stat()
            partitions.append(
                {
                    "name": path.name,
                    "bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "content_hash": hash_file(path),
                }
            )
        if not partitions:
            raise ValueError(f"交易日历源分区为空: {price_dir}")
        return hash_json(partitions)

    def resolve(
        self, factor: FactorFrame, index_id: str, config: LongOnlyFactorBacktestConfig
    ) -> ResolvedLongOnlyBacktestData:
        if index_id not in INDEX_SPECS:
            raise KeyError(f"未知 index_id: {index_id}; 已支持 {sorted(INDEX_SPECS)}")
        spec = INDEX_SPECS[index_id]
        dataset_refs: list[DatasetRef] = []
        notes: dict[str, object] = {}
        warnings_list: list[str] = []

        monthly, index_stats = ingest_index_membership(
            Path(self.config.index_source_dir), spec
        )
        dataset_refs.append(
            DatasetRef(
                name=f"index_membership:{index_id}",
                uri=str(Path(self.config.index_source_dir).resolve()),
                content_hash=hash_frame(monthly.drop(columns=["source_file"])),
                rows=len(monthly),
                columns=monthly.shape[1],
                date_min=index_stats["snapshot_first"],
                date_max=index_stats["snapshot_last"],
                notes=f"monthly PIT snapshots; missing_months={len(index_stats['missing_months'])}",
            )
        )
        notes["index_membership_stats"] = index_stats

        calendar = self.trading_calendar()
        start, end, warmup_start = self._resolve_window(factor, config, calendar, monthly)
        if config.start_date is not None and start > pd.Timestamp(config.start_date):
            warnings_list.append(
                f"请求开始日 {config.start_date} 早于首个可用 PIT 成分生效日; "
                f"有效回测从 {start.date()} 开始, 未做历史回填"
            )
        universe_assets = sorted(monthly["asset_id"].unique())

        panel = load_price_panel(
            Path(self.config.warehouse_dir),
            universe_assets,
            warmup_start,
            end,
            trading_days=calendar,
        )
        dataset_refs.append(
            DatasetRef(
                name="daily_prices",
                uri=str((Path(self.config.warehouse_dir) / "daily_prices").resolve()),
                content_hash=hash_json(
                    {
                        "wide_fields": {
                            name: hash_frame(frame)
                            for name, frame in sorted(panel.wide.items())
                        },
                        "raw_high": hash_frame(panel.raw_high),
                        "raw_low": hash_frame(panel.raw_low),
                        "listed_first": hash_series(panel.listed_first),
                        "listed_last": hash_series(panel.listed_last),
                        "source_partitions": {
                            name: hash_file(Path(self.config.warehouse_dir) / "daily_prices" / name)
                            for name in sorted(panel.source_files)
                        },
                    }
                ),
                rows=panel.n_source_rows,
                columns=len(panel.assets),
                date_min=str(panel.trading_days[0].date()),
                date_max=str(panel.trading_days[-1].date()),
                notes=f"partitions={len(panel.source_files)}",
            )
        )

        missing_assets = [a for a in universe_assets if a not in set(panel.assets)]
        no_data = [
            a for a in panel.assets if panel.wide["adj_close"][a].notna().sum() == 0
        ]
        if missing_assets or no_data:
            gap = sorted(set(missing_assets) | set(no_data))
            gap_weight = (
                monthly[monthly["asset_id"].isin(gap)].groupby("snapshot_date")["weight"].sum()
            )
            notes["price_missing_members"] = {
                "count": len(gap),
                "assets": gap[:80],
                "max_snapshot_weight": float(gap_weight.max()) if len(gap_weight) else 0.0,
                "mean_snapshot_weight": float(gap_weight.mean()) if len(gap_weight) else 0.0,
            }
            warnings_list.append(
                f"{len(gap)} 只历史成分股缺少行情数据 (疑似已退市), 最大单期权重缺口 "
                f"{float(gap_weight.max()) * 100 if len(gap_weight) else 0:.2f}%; 存在幸存者偏差"
            )

        member_full, weight_full = expand_monthly_to_daily(
            monthly, panel.trading_days, assets=panel.assets
        )

        fill_price_field = config.execution.fill_price_field
        price_bundle = self._build_price_frame(panel, fill_price_field)
        tradability = self._build_tradability(panel, price_bundle[1], fill_price_field)
        liquidity = self._build_liquidity(panel)
        styles, style_coverage = self._build_styles(panel, member_full)

        benchmark, bench_stats = self._build_benchmark(
            index_id, panel, weight_full, member_full, monthly
        )
        notes["benchmark_stats"] = bench_stats

        # 截到正式回测窗口 (预热段只用于滚动指标, 不进入回测)
        keep = (panel.trading_days >= start) & (panel.trading_days <= end)
        dates = panel.trading_days[keep]
        if len(dates) < 2:
            raise ValueError(f"回测窗口交易日不足: {start.date()} -> {end.date()}")

        member = member_full.loc[dates]
        weights = weight_full.loc[dates]
        prices = self._slice_price_frame(price_bundle, dates)
        tradability = self._slice_tradability(tradability, dates)
        liquidity = PortfolioLiquidityData(
            adv=liquidity.adv.loc[dates],
            turnover_rate=None if liquidity.turnover_rate is None else liquidity.turnover_rate.loc[dates],
            adv_window=liquidity.adv_window,
        )
        styles = {k: v.loc[dates] for k, v in styles.items()}
        style_coverage = style_coverage[style_coverage["date"].isin(dates)]
        benchmark = benchmark.loc[dates]

        rebalance_dates = self._rebalance_dates(dates, config, monthly)
        sample_masks = self._sample_masks(dates, config)

        dataset_refs.append(
            DatasetRef(
                name="benchmark_returns",
                uri=bench_stats.get("source", "synthetic:pit_monthly_weights"),
                content_hash=hash_series(benchmark),
                rows=len(benchmark),
                columns=1,
                date_min=str(dates[0].date()),
                date_max=str(dates[-1].date()),
                notes=bench_stats.get("method", ""),
            )
        )
        dataset_refs.append(
            DatasetRef(
                name="style_exposures",
                uri="derived:proxy_styles_v1",
                content_hash=hash_json({k: hash_frame(v) for k, v in sorted(styles.items())}),
                rows=len(dates),
                columns=len(styles),
                date_min=str(dates[0].date()),
                date_max=str(dates[-1].date()),
                notes=f"present={sorted(styles)}; missing={list(MISSING_STYLES)}",
            )
        )
        notes["style_coverage"] = style_coverage
        notes["missing_styles"] = list(MISSING_STYLES)
        notes["warnings"] = warnings_list
        notes["window"] = {
            "start": str(dates[0].date()),
            "end": str(dates[-1].date()),
            "warmup_start": str(warmup_start.date()),
            "n_days": int(len(dates)),
        }

        return ResolvedLongOnlyBacktestData(
            index_universe=member,
            index_weights=weights,
            benchmark_returns=benchmark,
            prices=prices,
            tradability=tradability,
            style_exposures=styles,
            liquidity_data=liquidity,
            sample_masks=sample_masks,
            rebalance_dates=tuple(rebalance_dates),
            initial_state=PortfolioInitialState(initial_capital=config.initial_capital),
            dataset_refs=tuple(dataset_refs),
            benchmark_basis=bench_stats.get("method", "unknown"),
            notes=notes,
        )

    # ---------- 内部构建 ----------

    def _resolve_window(
        self,
        factor: FactorFrame,
        config: LongOnlyFactorBacktestConfig,
        calendar: pd.DatetimeIndex,
        monthly: pd.DataFrame,
    ) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
        """确定回测窗口。成分数据生效前的日期一律截掉, 严禁回填历史成分。"""
        f_start, f_end = factor.dates[0], factor.dates[-1]
        first_snapshot = pd.Timestamp(monthly["snapshot_date"].min())
        start = max(f_start, first_snapshot)
        if config.start_date is not None:
            start = max(start, pd.Timestamp(config.start_date))
        end = f_end
        if config.end_date is not None:
            end = min(end, pd.Timestamp(config.end_date))
        end = min(end, calendar[-1])
        if start >= end:
            raise ValueError(f"回测窗口非法: start={start.date()} end={end.date()}")
        pos = calendar.searchsorted(start)
        warmup_pos = max(int(pos) - self.config.style_warmup_days, 0)
        return start, end, calendar[warmup_pos]

    def _build_price_frame(self, panel, fill_price_field: str | None = None) -> MarketPriceFrame:
        w = panel.wide
        prev_close = w["adj_prev_close"].copy()
        # 首行前收盘缺失时用当日收盘兜底, 保证限价推导不整行失效
        fallback = w["adj_close"].shift(1)
        prev_close = prev_close.where(prev_close.notna(), fallback)
        ratio = (w["raw_close"] / w["adj_close"].replace(0.0, np.nan))
        raw_prev_close = prev_close * ratio
        return MarketPriceFrame(
            adj_open=w["adj_open"],
            adj_high=w["adj_high"],
            adj_low=w["adj_low"],
            adj_close=w["adj_close"],
            adj_vwap=w["adj_vwap"],
            adj_prev_close=prev_close,
            raw_close=w["raw_close"],
            raw_open=w["raw_open"],
            raw_vwap=w["raw_vwap"],
            adj_factor=w["adj_factor"],
            volume=w["volume"],
            amount=w["amount"],
            price_basis="provider_backward_adjusted; raw rebuilt from mktcap/shares",
            fill_price_field=fill_price_field or self.config.fill_price_field,
        ), raw_prev_close

    def _raw_fill_field(self, fill_price_field: str | None = None) -> str:
        """把复权成交价字段映射到对应的原始价字段。"""
        field = fill_price_field or self.config.fill_price_field
        mapping = {"adj_open": "raw_open", "adj_vwap": "raw_vwap", "adj_close": "raw_close"}
        if field not in mapping:
            raise ValueError(
                f"不支持的 fill_price_field={field}, 可选 {sorted(mapping)}"
            )
        return mapping[field]

    def _build_tradability(
        self,
        panel,
        raw_prev_close: pd.DataFrame,
        fill_price_field: str | None = None,
    ) -> TradabilityFrame:
        w = panel.wide
        limits = build_limit_matrices(
            raw_prev_close=raw_prev_close,
            raw_high=panel.raw_high,
            raw_low=panel.raw_low,
            raw_open=w["raw_open"],
            # 判定口径必须跟成交价一致 (导师 B1: T+1 开盘价成交)
            raw_fill_price=w[self._raw_fill_field(fill_price_field)],
            listed_first=panel.listed_first,
            buffer_ratio=self.config.limit_buffer_ratio,
        )
        susp = build_suspension(
            volume=w["volume"],
            close=w["adj_close"],
            listed_first=panel.listed_first,
            listed_last=panel.listed_last,
            dates=panel.trading_days,
        )
        false_mat = pd.DataFrame(
            False, index=panel.trading_days, columns=panel.assets
        )
        alive = susp["is_listed"] & (~susp["is_delisted"]) & (~susp["is_suspended"])
        price_field = fill_price_field or self.config.fill_price_field
        has_price = w[price_field].notna() & (w[price_field] > 0)
        allow_buy = alive & has_price & (~limits["limit_up_block_buy"])
        allow_sell = alive & has_price & (~limits["limit_down_block_sell"])
        return TradabilityFrame(
            is_suspended=susp["is_suspended"],
            is_st=false_mat.copy(),
            is_delisted=susp["is_delisted"],
            is_listed=susp["is_listed"],
            limit_up_block_buy=limits["limit_up_block_buy"],
            limit_down_block_sell=limits["limit_down_block_sell"],
            allow_buy=allow_buy,
            allow_sell=allow_sell,
            st_data_available=False,
            delist_data_available=False,
            suspension_source="derived: zero-volume or missing row within listing window",
        )

    def _build_liquidity(self, panel) -> PortfolioLiquidityData:
        amount = panel.wide["amount"]
        window = self.config.adv_window
        adv = amount.rolling(window, min_periods=max(window // 2, 3)).mean().shift(1)
        return PortfolioLiquidityData(
            adv=adv, turnover_rate=panel.wide.get("turnover_rate"), adv_window=window
        )

    def _build_styles(self, panel, member: pd.DataFrame):
        w = panel.wide
        return build_style_exposures(
            adj_close=w["adj_close"],
            float_mktcap=w["float_mktcap"],
            pb=w["pb"],
            turnover_rate=w["turnover_rate"],
            valid_mask=member,
        )

    def _build_benchmark(self, index_id, panel, weights, member, monthly):
        official = self.config.official_benchmark_files.get(index_id)
        if official and Path(official).exists():
            return load_official_benchmark(official, panel.trading_days)
        snaps = pd.DatetimeIndex(sorted(monthly["snapshot_date"].unique()))
        return build_benchmark_returns(
            adj_close=panel.wide["adj_close"],
            index_weights=weights,
            index_member=member,
            snapshot_dates=snaps,
            drift_within_period=self.config.benchmark_drift_within_period,
        )

    @staticmethod
    def _slice_price_frame(bundle, dates: pd.DatetimeIndex) -> MarketPriceFrame:
        prices, _ = bundle
        kwargs = {
            name: getattr(prices, name).loc[dates] for name in MarketPriceFrame._MATRICES
        }
        return MarketPriceFrame(
            **kwargs,
            price_basis=prices.price_basis,
            fill_price_field=prices.fill_price_field,
            suspension_price_policy=prices.suspension_price_policy,
        )

    @staticmethod
    def _slice_tradability(t: TradabilityFrame, dates: pd.DatetimeIndex) -> TradabilityFrame:
        kwargs = {name: getattr(t, name).loc[dates] for name in TradabilityFrame._MATRICES}
        return TradabilityFrame(
            **kwargs,
            st_data_available=t.st_data_available,
            delist_data_available=t.delist_data_available,
            suspension_source=t.suspension_source,
        )

    def _rebalance_dates(
        self, dates: pd.DatetimeIndex, config: LongOnlyFactorBacktestConfig, monthly: pd.DataFrame
    ) -> list[pd.Timestamp]:
        freq = config.rebalance_frequency
        if freq == "daily":
            candidates = list(dates)
        elif freq == "weekly":
            s = pd.Series(dates, index=dates)
            candidates = list(s.groupby([dates.isocalendar().year, dates.isocalendar().week]).last())
        elif freq == "monthly":
            s = pd.Series(dates, index=dates)
            candidates = list(s.groupby([dates.year, dates.month]).last())
        else:
            raise ValueError(f"未知 rebalance_frequency: {freq}")

        if not config.clock.drop_incomplete:
            return candidates
        need = (
            config.clock.order_lag_days
            + config.clock.fill_lag_days
            + config.clock.return_lag_days
        )
        last_signal_pos = len(dates) - need - 1
        if last_signal_pos < 0:
            return []
        last_signal_date = dates[last_signal_pos]
        return [pd.Timestamp(d) for d in candidates if pd.Timestamp(d) <= last_signal_date]

    @staticmethod
    def _sample_masks(
        dates: pd.DatetimeIndex, config: LongOnlyFactorBacktestConfig
    ) -> dict[str, pd.Series]:
        full = pd.Series(True, index=dates, name="full_sample")
        masks = {"full_sample": full}
        if config.oos_start is not None:
            cut = pd.Timestamp(config.oos_start)
            masks["in_sample"] = pd.Series(dates < cut, index=dates, name="in_sample")
            masks["out_of_sample"] = pd.Series(dates >= cut, index=dates, name="out_of_sample")
        return masks
