# Repository Safety Rules

## Deletion Requires Explicit Confirmation

- Before deleting anything, obtain the user's explicit confirmation for the exact
  deletion operation. A request to fix, update, deploy, publish, restart, or clean
  up is not permission to delete.
- First perform a read-only inventory and tell the user the exact files, directories,
  database rows, containers, volumes, releases, or records that would be removed.
  State the reason, impact, backup or recovery path, and whether the action is
  reversible. Wait for a separate affirmative reply before proceeding.
- This rule applies to direct and indirect deletion, including `rm`, `unlink`,
  `rmtree`, retention cleanup, pruning, overwrite-based replacement, database
  `DELETE`/`DROP`/`TRUNCATE`, Docker volume or image pruning, destructive Git
  commands, and scripts or services that perform cleanup automatically.
- Never infer deletion approval from an earlier approval for another command or from
  a broad deployment request. Approval must identify the current deletion targets.

## Protected Production Data

- Never delete, truncate, overwrite, prune, or recreate backtest records, run
  artifacts, factor values, market-data panels, minute bars, benchmark data,
  corporate-action data, databases, or immutable data releases without the explicit
  confirmation described above.
- Treat `/data/research`, `/data/qbt/state`, `/data/qpf`, `panel_shards`,
  `5minbar_unadjusted`, `5minbar_post`, `warehouse_rqdata`, and all database and
  artifact paths as protected production data.
- Data publication must be additive and atomic. Build and validate a new candidate,
  preserve the current release and rollback target, and switch a pointer only after
  validation. Do not run automatic retention cleanup as part of deployment unless
  the user separately approves the exact releases to remove.
- Before any approved deletion, create or verify a usable backup when possible, and
  verify protected record counts and current data coverage again after the action.
