"""Keep optional RQData fields from blocking core daily market-data updates."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

try:
    import rqdatac
    from rqdatac.share.errors import PermissionDenied
except ImportError:
    rqdatac = None


if rqdatac is not None:
    original_consensus = rqdatac.consensus.get_comp_indicators

    def optional_consensus(*args, **kwargs):
        try:
            return original_consensus(*args, **kwargs)
        except PermissionDenied:
            print(
                "RQData consensus permission unavailable; publishing new dates as null",
                file=sys.stderr,
                flush=True,
            )
            return pd.DataFrame()

    rqdatac.consensus.get_comp_indicators = optional_consensus

    try:
        from quant_private_fund_infra.data import rqdata_sync
    except ImportError:
        rqdata_sync = None

    if rqdata_sync is not None:

        def validate_latest_available_fields(frames):
            latest = frames["close"].index[-1]
            close = frames["close"].loc[latest].to_numpy(dtype=float, copy=False)
            reference = np.isfinite(close)
            count = int(reference.sum())
            if not count:
                raise rqdata_sync.RQDataSyncError(f"latest date {latest} has no close data")
            failures = []
            for alias in rqdata_sync.ALL_FIELDS:
                if alias in rqdata_sync.SPARSE_LATEST_FIELDS:
                    continue
                values = frames[alias].loc[latest].to_numpy(dtype=float, copy=False)
                valid = int((reference & np.isfinite(values)).sum())
                coverage = valid / count
                if coverage < rqdata_sync.MIN_DENSE_LATEST_COVERAGE:
                    failures.append(f"{alias}={coverage:.2%} ({valid}/{count})")
            if failures:
                raise rqdata_sync.RQDataSyncError(
                    f"Latest-date dense field coverage is incomplete on {latest}: "
                    + ", ".join(failures)
                )

        rqdata_sync._validate_latest_field_coverage = validate_latest_available_fields
