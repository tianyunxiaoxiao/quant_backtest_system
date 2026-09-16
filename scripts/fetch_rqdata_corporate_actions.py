#!/usr/bin/env python3
"""Fetch normalized A-share cash-dividend and split events from RQData."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rqdatac


def rq_ticker(ticker: str) -> str:
    if ticker.endswith(".SZ"):
        return f"{ticker[:-3]}.XSHE"
    if ticker.endswith(".SH"):
        return f"{ticker[:-3]}.XSHG"
    if ticker.endswith(".BJ"):
        return f"{ticker[:-3]}.XBSE"
    raise ValueError(f"unsupported panel ticker: {ticker}")


def qbt_ticker(ticker: str) -> str:
    return ticker.replace(".XSHE", ".SZ").replace(".XSHG", ".SH").replace(".XBSE", ".BJ")


def batches(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def normalized_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    return frame.reset_index()


def fetch(panel_metadata: Path, output: Path, start_date: str, end_date: str, batch_size: int) -> None:
    metadata = json.loads(panel_metadata.read_text(encoding="utf-8"))
    tickers = [rq_ticker(str(value)) for value in metadata["tickers"]]
    dividend_parts: list[pd.DataFrame] = []
    split_parts: list[pd.DataFrame] = []
    rqdatac.init()
    for group in batches(tickers, batch_size):
        dividend_parts.append(
            normalized_frame(
                rqdatac.get_dividend(group, start_date=start_date, end_date=end_date, expect_df=True)
            )
        )
        split_parts.append(
            normalized_frame(rqdatac.get_split(group, start_date=start_date, end_date=end_date))
        )

    dividends = pd.concat(dividend_parts, ignore_index=True) if dividend_parts else pd.DataFrame()
    if dividends.empty:
        cash = pd.DataFrame(columns=["date", "asset_id", "cash_dividend_per_share"])
    else:
        cash = dividends.assign(
            date=pd.to_datetime(dividends["ex_dividend_date"]).dt.normalize(),
            asset_id=dividends["order_book_id"].astype(str).map(qbt_ticker),
            cash_dividend_per_share=(
                pd.to_numeric(dividends["dividend_cash_before_tax"], errors="coerce")
                / pd.to_numeric(dividends["round_lot"], errors="coerce")
            ),
        )[["date", "asset_id", "cash_dividend_per_share"]]
        cash = cash.replace([np.inf, -np.inf], np.nan).dropna()
        cash = cash.groupby(["date", "asset_id"], as_index=False)["cash_dividend_per_share"].sum()

    splits = pd.concat(split_parts, ignore_index=True) if split_parts else pd.DataFrame()
    if splits.empty:
        split = pd.DataFrame(columns=["date", "asset_id", "split_ratio"])
    else:
        split = splits.assign(
            date=pd.to_datetime(splits["ex_dividend_date"]).dt.normalize(),
            asset_id=splits["order_book_id"].astype(str).map(qbt_ticker),
            split_ratio=(
                pd.to_numeric(splits["split_coefficient_to"], errors="coerce")
                / pd.to_numeric(splits["split_coefficient_from"], errors="coerce")
            ),
        )[["date", "asset_id", "split_ratio"]]
        split = split.replace([np.inf, -np.inf], np.nan).dropna()
        split = split.groupby(["date", "asset_id"], as_index=False)["split_ratio"].prod()

    events = cash.merge(split, on=["date", "asset_id"], how="outer")
    events["cash_dividend_per_share"] = events["cash_dividend_per_share"].fillna(0.0)
    events["split_ratio"] = events["split_ratio"].fillna(1.0)
    events = events.sort_values(["date", "asset_id"], ignore_index=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    events.to_parquet(output, index=False, compression="snappy")
    print(json.dumps({"output": str(output), "events": len(events), "date_max": end_date}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    fetch(args.panel_metadata, args.output, args.start_date, args.end_date, args.batch_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
