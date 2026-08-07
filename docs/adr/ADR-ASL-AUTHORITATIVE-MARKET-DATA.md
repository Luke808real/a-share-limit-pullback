# ADR — ASL as Authoritative Market Data

## Decision

`rootSunc/ashare-lake` (ASL) is the authoritative local A-share market-data
source for V Flash.

## Context

The legacy multi-provider architecture (TDX / Tencent / EastMoney / AKShare /
Baostock / Sina with failover, repair and cross-provider reconciliation)
became expensive and inconsistent: preclose semantics differed, historical
rows went missing, units varied by provider, historical ST was PIT-ambiguous,
and maintenance time competed with strategy research.

## Consequences

Positive:

* single market-data fact source
* simpler provenance
* fewer repair / reconciliation paths
* easier historical research
* reproducible strategy inputs

Tradeoffs:

* some derived / enrichment fields remain nullable (e.g. turnover)
* ST completeness must have explicit readiness evidence
* legacy backend remains temporarily available for audit / rollback

## Status

`ACCEPTED`
