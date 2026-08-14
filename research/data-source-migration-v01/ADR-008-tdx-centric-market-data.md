# ADR-008 — TDX-Centric Market Data (workspace mirror)

Mirror of KB 03_Decisions/ADR-008-tdx-centric-market-data.md.
TDX primary (daily+5m); Tencent daily confirm; BaoStock audit; Sina 5m audit;
Eastmoney optional/disabled. RAW unadjusted price domain. CONFIRMED only for
production screen. Forward provider lock = TDX_5M once PASS_TDX.
Audit 2026-08-05: daily gates PASS (TDX 100%, Tencent 100%); forward gate
FAIL (quartile agreement 94.4% < 95%, n=18; reference artifact defects
recorded). FORWARD_REFERENCE_COMPATIBILITY = FAIL.
