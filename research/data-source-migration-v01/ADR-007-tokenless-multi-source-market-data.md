# ADR-007 — Tokenless Multi-Source Market Data (workspace mirror)

Mirror of /Users/luke808/AI/a-share-strategy-brain/03_Decisions/ADR-007-tokenless-multi-source-market-data.md

Key facts:
- DAILY_PRIMARY=AKSHARE_EASTMONEY; DAILY_CONFIRM=TDX; AUDIT=BAOSTOCK
- INTRADAY_PRIMARY=AKSHARE_EASTMONEY_5M; INTRADAY_CONFIRM=TDX_5M
- CONFIRMED = EM + TDX agreement within tolerance; PROVISIONAL never in screen
- Audit 2026-08-05: TDX daily parity 100% (n=300); TDX 5m BAR_END_TIME,
  forward volume-pace parity 0.9999/1.0000 (n=18); EM daily intermittent;
  EM 5m BLOCKED.
- STATUS = BLOCKED_EASTMONEY (implementation); Forward Epoch 1 deferred.
