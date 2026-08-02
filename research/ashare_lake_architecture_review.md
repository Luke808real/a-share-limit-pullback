# Ashare-Lake Architecture Review

Read-only review of architecture ideas only; package not integrated.

## ADOPT

- DuckDB as a query layer over existing Parquet (no migration).
- Staging / curated / derived separation in concept: canonical = source of
  truth, derived projections = strategy-friendly reads.
- Manifest / watermark / hash tracking for derived artifacts.
- Incremental daily concept: advance only the new session when state is valid.

## ADAPT

- Code-major derived Parquet projection (`derived/daily_by_code/`) for
  selective per-code reads.
- Date-major projection (`derived/daily_by_date/`) for latest-day and
  cross-section reads.
- DuckDB catalog as metadata query surface, not the primary store.

## SKIP

- Replacing the current provider/ingestion stack.
- Integrating ashare-lake as a package.
- Rewriting strategy semantics.
- Adding minute data or new providers for storage reasons.

## Recommendation

Keep canonical Parquet as source of truth; add DuckDB query layer over it.
Code/date projections are optional derived artifacts, not a migration target.
