# REFERENCE_REPAIR_AUDIT_V02

V01 status: SUPERSEDED_PRESTART_REFERENCE_DEFECT (never started; ledger rows=0)
Defects: DEFECT_1 A-vs-F volume definition; DEFECT_2 missing component CDFs.
V01 files modified: false (hashes unchanged).

V02:
- original development case n = 206; reference eligible n = 195 (Architect
  exemption V02_DEVELOPMENT_MEMBERSHIP_EXCEPTION = APPROVED)
- excluded n = 11 (candidate_date 2026-06-08 / D1 2026-06-05 missing D1
  same-time 5m cumulative volume); reason =
  V02_REFERENCE_INELIGIBLE_MISSING_D1_SAME_TIME; no cross-provider backfill
- reference outcome fields read = 0
- excluded outcome counts = {'FAILED_BREAKOUT': 7, 'SUCCESS': 2, 'STRUCTURE_FAIL': 1, 'NO_LAUNCH': 1}
- eligible outcome counts = {'FAILED_BREAKOUT': 90, 'STRUCTURE_FAIL': 50, 'SUCCESS': 38, 'NO_LAUNCH': 11, 'UNKNOWN': 6}
- no reference change based on outcome
- primary volume definition = D0_CUM / D1_SAME_TIME_CUM
- percentile method = EMPIRICAL_MIDRANK_ECDF_V1 (mid-rank ECDF, below->0, above->1)
- component CDF saved per checkpoint (sorted values/n/p25/p50/p75)
- equal weights, quartile rule frozen
- score reproducibility max abs diff = 0.0

TDX compatibility (n = 18):
- volume pace median ratio 09:45 = 0.9999; 10:00 = 1.0
- session low/high/range max abs diff: 0.0 / 0.0 / 0.0
- quiet score abs diff median/p95/max = 0.000855 / 0.004274 / 0.005983
- quiet score spearman = 0.9999
- quartile agreement = 1.0 (reported; not a hard gate in V02)
- boundary-sensitive mismatches = 0; provider-material mismatches = 0

FORWARD_REFERENCE_COMPATIBILITY = PASS_TDX_V02
