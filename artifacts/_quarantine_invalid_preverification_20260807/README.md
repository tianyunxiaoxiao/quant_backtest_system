# Quarantined pre-verification artifacts

These directories were generated before the complete result contract existed. They are retained
only for forensic comparison and are not valid deliverables:

- `lof_20260806T132121Z_34d0d0ce/`
- `lof_20260806T132254Z_1f724749/`
- `test_report/`

Each directory is missing required result components such as `style_exposure_report.json`, so the
safe artifact loader cannot reconstruct a complete `LongOnlyFactorBacktestResult`. Do not use these
outputs for analysis or reproduction. Verified acceptance outputs live directly under `artifacts/`.
