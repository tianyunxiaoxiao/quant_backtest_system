# Mentor Compliance Audit - 2026-08-07

## Scope and authority

This audit uses the following sources as authoritative, in this order:

1. `/Users/a1/Desktop/添橙/5days20260806/19_portfolio_backtest_framework.md`
2. `/Users/a1/Desktop/添橙/5days20260806/待导师确认事项清单_副本.md`

The implementation under review is entirely contained in
`/Users/a1/Desktop/添橙/5days20260806/quant_backtest_system`.

## Final verification status

- Automated tests: 81 collected, 81 passed after the final code change.
- Python bytecode compilation: passed for `src/` and `tests/`.
- Ruff and mypy: not installed in the project virtual environment; no success is claimed for them.
- Engine import boundary: 36 package source files and 7,718 source lines scanned; no engine import of
  `qbt.reporting` or Matplotlib was found.
- Strict JSON: all 18 JSON files across the two final runs parse with non-standard constants rejected.
- Visual output: all 28 PNG charts have nonzero pixel variance; representative CJK, layout, legend,
  and axis rendering was manually inspected.
- Artifact reload: both final result sets reconstruct through `load_backtest_artifacts()`.
- Artifact integrity: both manifests register 36 references; all 36 hashes match; each directory has
  37 files including its manifest.

## Final real-data runs

### Daily 20-day reversal

- Directory: `artifacts/acceptance_daily_reversal_20260807`
- Run ID: `lof_20260807T042719Z_a9d0f46d`
- Result hash: `d76f383c625e647683b0293f777a8bdfba44883a37d22ef04c56aaf176ec2bf6`
- Code version: `source-38d893060ffee9b3`
- Factor hash: `e5b13db7e382473a8793648c0ee725a7aba18472ae8f025529b2b4502484108a`
- Effective dates: 2019-01-02 through 2026-03-31, 1,755 trading days.
- Configured start was 2018-01-01; the effective start is later because the first PIT index snapshot is
  2019-01-01. No historical membership was backfilled.
- Portfolio cumulative return: -35.1964%.
- Benchmark cumulative return: +111.3119%.
- Geometric excess return: -69.3327%.
- Annualized alpha: -15.2579%; beta: 1.019717.
- Maximum accounting residual: `6.21e-12` bps of NAV.
- Positive fills: 238,497 of 288,621 fill records.
- Maximum executed ADV participation: exactly 10%; actual ADV violations: 0; cap bindings: 2.
- Missing ADV: 13 orders rejected as `adv_missing`; none executed without an ADV limit.
- Post-close single-weight violations: 430. Exact rows are retained and disclosed as drift/unfilled
  outcomes rather than hidden.

### Monthly BP = 1/PB

- Directory: `artifacts/acceptance_monthly_bp_20260807`
- Run ID: `lof_20260807T043014Z_58e4641f`
- Result hash: `ff6af6de7cd822a7238a691856b5cd4b454ee237fcf6d72ba3b30d4dd915aa32`
- Code version: `source-38d893060ffee9b3`
- Factor hash: `8f11ffba02049cc30e0fc5d93c98bab785c31c339facfb77fa09ff77cea3d6db`
- Effective dates: 2019-01-02 through 2026-03-31, 1,755 trading days.
- Portfolio cumulative return: +103.5136%.
- Benchmark cumulative return: +111.3119%.
- Geometric excess return: -3.6904%.
- Annualized alpha: +2.3827%; beta: 0.759997.
- Maximum accounting residual: `5.64e-12` bps of NAV.
- Positive fills: 12,364 of 13,344 fill records.
- Maximum executed ADV participation: exactly 10%; actual ADV violations: 0; cap bindings: 4.
- Maximum turnover on non-rebalance dates: exactly 0.
- Post-close single-weight violations: 108, retained with exact evidence rows.

## Independent real-data cash and NAV recalculation

The first actual execution day in each final run was recalculated directly from fill records and
post-trade holdings. The equations were not sourced from the cash ledger:

```text
expected cash
= previous cash
+ sell notional
- buy notional
- explicit commission, stamp duty, and transfer fees

expected NAV = expected cash + sum(post-trade holding market values)
```

Daily reversal, 2019-01-03:

- Previous cash: 100,000,000.000000
- Buy notional: 96,856,884.570440
- Sell notional: 0
- Explicit fees: 26,151.358834
- Independently expected cash: 3,116,964.070726091
- Ledger cash: 3,116,964.070726068
- Holding market value: 96,082,861.804127
- Independently expected NAV: 99,199,825.874853
- Ledger NAV: 99,199,825.874853

Monthly BP, 2019-02-01:

- Previous cash: 100,000,000.000000
- Buy notional: 98,973,255.813561
- Sell notional: 0
- Explicit fees: 26,722.779070
- Independently expected cash: 1,000,021.407369734
- Ledger cash: 1,000,021.407369733
- Holding market value: 99,956,552.340533
- Independently expected NAV: 100,956,573.747903
- Ledger NAV: 100,956,573.747903

The differences are floating-point rounding below one-millionth of a currency unit.

## Section 20 completion conditions

1. Passed. A final factor and index ID are sufficient; CLI and API defaults cover dates, VWAP,
   selection, weights, constraints, costs, regression, and reporting.
2. Passed. The backtester consumes one final `FactorFrame`; it performs no factor combination,
   direction fitting, or weight learning.
3. Passed. PIT membership, eligibility intersection, deterministic tie-breaking, and `ceil(30%)`
   selection are implemented and tested.
4. Passed. Factor-strength weighting is the default; cutoff, fallback, target weights, and exclusion
   reasons are persisted.
5. Passed. Signals use data known at T close and orders execute on T+1. Future-truncation tests cover
   every demo factor, and terminal incomplete signals are dropped.
6. Passed. Target weights, orders, fills, holdings, cost bases, market values, cash, and daily ledgers
   are persisted and reloadable.
7. Passed. Suspension, price limits, PIT index exits, delisting-data availability, ADV partial fills,
   cancellation, and reject reasons have explicit paths and tests. Missing ADV now rejects execution.
8. Passed. Returns use actual holdings. Commission, historical stamp duty, transfer fee, embedded
   slippage/impact, and no-double-charge accounting are tested.
9. Passed. Gross/net/benchmark/excess NAV and portfolio/benchmark/excess drawdowns are persisted and
   rendered.
10. Passed. Full, IS, and OOS performance reports include all required metrics and definitions.
11. Passed. OLS and Newey-West alpha/beta statistics, R-squared, rolling estimates, and contribution
   series are persisted and rendered.
12. Passed within the mentor-approved data scope. Portfolio, index, and active exposures are present;
   active equals portfolio minus index exactly. Missing Growth/Quality/Leverage remain explicit.
13. Passed. Selection performance, coverage, holdings, executed turnover, costs, ADV, unfilled amount,
   unfilled ratio, and reason diagnostics are present.
14. Passed. Markdown contains all key measurements; Parquet/JSON artifacts retain original daily and
   event-level data.
15. Passed. Dataset, factor, configuration, source code, result, and artifact hashes are recorded.
   Caller-supplied factor hashes are recomputed and verified.
16. Passed. DataPortal loads and registers price, PIT membership/weights, synthesized benchmark,
   tradability, style proxies, and liquidity.
17. Passed. The engine has no reporting or plotting dependency and returns the complete frozen result.
18. Passed. The reporter only consumes the result. Pre/post result hashes are equal, and a serialized
   reload produces byte-identical Markdown/JSON and all 14 chart hashes.
19. Passed. Report fields and charts map back to result components; all persisted components pass
   round-trip equality and manifest inventory verification.
20. Passed for the agreed v1 scope. Unit, integration, regression, adversarial, real-data comparative,
   visual, artifact, and manual cash/NAV checks all pass.

## Mentor clarification coverage

- A1: real monthly PIT index membership is used; no latest-constituent backfill.
- A2: official total-return index data remains unavailable. The benchmark is synthesized from PIT
  weights and adjusted prices, with tracking-error disclosure.
- A3: historical delisted securities and reliable historical ST labels remain unavailable. Survivor
  bias and ST-limit uncertainty are disclosed; this is a pipeline-validity delivery, not evidence of
  strategy profitability.
- A4: Size, Value, Momentum, Volatility, and Liquidity are PIT-compatible proxies. Growth, Quality,
  Leverage, and industry constraints are explicitly unavailable rather than fabricated.
- A5: risk-free rate defaults to zero and 252 trading days; both are recorded configuration.
- A6: reversal and BP acceptance factors are fixed in advance. Five demo factor paths are tested.
- A7: both synthetic exact-ledger and real-data end-to-end acceptance levels are present.
- B1-B7: T+1 VWAP default, signal-day raw close sizing, whole-lot buys, allowed liquidation odd lots,
  sell-before-buy, same-day proceeds, cancel-at-close, buffered price limits, suspension valuation,
  and ex-ante/execution filter separation are implemented and disclosed.
- C1-C7: eligible denominator, first-rejected cutoff, deterministic ties, invalid factor handling,
  enabled/disabled constraint scope, daily/monthly frequency, and forced index exits are covered.
- D1-D3: adjusted-price accounting, raw/adjusted share conversion, holdings cost/PnL fields, and the
  daily accounting identity are covered. Explicit corporate-action events remain unavailable and are
  disclosed.
- E1-E2: time-varying fees and embedded slippage/impact are separated without double counting.
- F1-F2: OLS and Newey-West results plus all frozen metric definitions are included.
- G1-G3: valuation PIT assumption, incomplete terminal handling, OOS date, and effective-start behavior
  are recorded.
- H1: the Python package, tests, warehouse, reports, and audit outputs are contained in the project.

## Formal review closure

Bugbot findings closed:

- Missing ADV unrestricted fills: closed by explicit `adv_missing` rejection; real run proves 13
  missing-ADV daily orders did not execute.
- False factor lineage hash: closed by recomputation and mismatch rejection.
- Ignored request report configuration: closed and tested with SVG/no-Markdown/no-summary-JSON output.
- Ignored execution controls: supported fixed v1 semantics are enforced; unsupported alternatives fail
  during configuration construction rather than being silently recorded.
- Slippage could exceed ADV: closed by capping against slipped fill notional; boundary test passes.
- Incorrect open-price disclosure: closed; disclosure is generated from `fill_price_field` and final
  manifests state `adj_vwap`.
- Missing golden/manual evidence: closed by hardcoded five-day ledger regression and the real-data
  recalculations above.

Security Review findings closed:

- Frame hashing now uses type tags and length-prefixed encoding, preserving axes, MultiIndex structure,
  nulls, dtypes, and full timestamp precision.
- Index IDs and output containment are validated; weights must be finite and nonnegative with plausible
  snapshot totals.
- Calendar signatures include partition content hashes.
- JSON canonicalizes all non-finite floats to null and uses `allow_nan=False`.
- Manifest `artifact_uri` is reconciled to the actual published directory.
- Dirty Git versions include a deterministic source-tree hash.
- Reports render to a verified staging directory and publish atomically with rollback.
- Interrupted price-ingestion directory swaps restore the latest complete backup.
- Report dimensions, DPI, format, row limits, and required-section policy are validated.
- Three incomplete legacy artifact directories were preserved under
  `artifacts/_quarantine_invalid_preverification_20260807/` and explicitly marked invalid.

## Residual limitations

The delivery is acceptable for the mentor-approved v1/pipeline-validity scope. It must not be described
as a fully bias-free production strategy study until official benchmark points, historical delisted/ST
coverage, corporate-action events, PIT industry classifications, and institutional style data are
available. Those are source-data limitations, not hidden implementation fallbacks.
