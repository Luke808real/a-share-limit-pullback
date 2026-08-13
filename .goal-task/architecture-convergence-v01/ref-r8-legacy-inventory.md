# REF-R8 Legacy Retirement Inventory (read-only, pre-deletion)

Date: 2026-08-13. No deletion performed. Every retirement set below is a
candidate only; each set still requires zero-dependency proofs and explicit
human approval before removal.

## Direct boundary debts (not deletion candidates by themselves)

- `screen/chunk_child.py`, `screen/chunks.py`, `screen/generation.py`,
  `screen/runner.py`, `screen/state.py` still import `limit_pullback.warehouse`
  directly. These are active runtime paths; retiring the imports requires the
  data-layer adapter to fully replace them first (REF-R3's remaining debt).
- `data/canonical.py` keeps the lazy `limit_pullback.screen.engine.pool_quality`
  import (recorded seam).
- `warehouse/asl_adapter.py` is `LEGACY_MIGRATION_FALLBACK`; referenced by
  `warehouse/asl_query_adapter.py`, `warehouse/asl_snapshot.py`, and their
  tests.

## Provider module reference counts (runtime + tests)

| Module | Referencing files |
| --- | --- |
| `warehouse/tushare_provider.py` | 8 |
| `warehouse/asl_adapter.py` | 6 |
| `providers/tdx_daily.py` | 2 |
| `providers/tencent_daily.py` | 3 |
| `providers/baostock_daily.py` | 3 |
| `providers/akshare_limit_pool.py` | 3 |
| `warehouse/akshare_provider.py` | 2 |
| `warehouse/baostock_provider.py` | 2 |
| `warehouse/akshare_worker.py` | 1 |

No module currently has zero runtime and zero test references, so no
retirement set satisfies the REF-R8 deletion gate yet.

## Blocking authority gates

Deletion of legacy warehouse/provider paths presupposes the ASL path being
the proven default. Current Brain-recorded authority:

- `ST_READY=NO` (`ST_DATA_NOT_READY`)
- `PROVENANCE_GAP=OPEN`
- `PRODUCTION_CUTOVER=NO_GO`

This architecture task cannot flip these gates: they are data-governance
closures on the Brain/ASL side and fail-closed semantics forbid a silent
cutover. REF-R8 therefore stays `needs_input` until those gates close and a
human approves each retirement set with rollback evidence.

## Next steps when the gates close

1. Re-run this inventory; for each set prove runtime_call=0, test dep=0,
   artifact dep=0, adapter unnecessary, differential parity PASS.
2. Request per-set explicit human approval with rollback evidence.
3. Delete only the approved set; never merge automatically.
