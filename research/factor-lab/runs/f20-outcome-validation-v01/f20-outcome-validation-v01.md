# F20 B2 VOLUME VS 20D MEAN OUTCOME VALIDATION V01 — 预注册验证报告（prereg-compliant audit fix v01）

- F20 CONTRACT = FROZEN / CLOSED（AUTHORITY HEAD 0f068d4462adb4eb435791843259dbe11a646a2c，Sol audit PASS）
- 函数：factor_lab.b2_volume_vs_20d_mean（源码语义 HEAD ff4ea77a80c2144fda181b6e412a795b6c1952d9）；预注册：758768e1dc0db16fa0d9d75a6c25652d2d789671
- b2_date = episode.signal_date (frozen)；as_of = episode.signal_date
- defined population：all resolved episodes; F20 itself decides defined/undefined (PRE20_N==20 & nonzero window mean)
- Spearman：frozen: average ranks (method=average) then Pearson of ranks; PRIMARY_RHO_UNDEFINED fails closed
- episodes SHA: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093；daily SHA: e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
- EPISODES_TOTAL = 31422；RESOLVED_N = 9625
- RECONCILIATION: AUDIT_FIX=PREREG_COMPLIANCE_V01；SUPERSEDES_HEAD=648aa0695ce028ef5f5c24f012354646e97e4c23；OLD_RESULT_STATUS=NOT_ADJUDICATED_PREREG_MISMATCH；RESULT_CHANGED=True

## ACCOUNTING
- RESOLVED_N = 9625；F20_DEFINED_N = 9508；F20_UNDEFINED_N = 117
- STRICT_N = 7765；R_DEFINED_N = 7765；CANCEL_GAP_ACCOUNTING_N = 1743
- UNDEFINED_REASONS = {'DEFINED': 9508, 'INSUFFICIENT_PRE20': 117}

## PRIMARY（H5A 连续 Spearman 双 gate，frozen implementation）
- rho_strict = -0.112699（N=7765，direction=nonpositive）
- rho_R_positive = -0.118177（N=7765，direction=nonpositive）
- **H5A = REJECT**（规则：rho_strict > 0 AND rho_R_positive > 0 -> SUPPORTED_DIRECTIONALLY else REJECT; PRIMARY_RHO_UNDEFINED -> fail closed (no artifact)；SUPPORTED_DIRECTIONALLY != VALIDATED != PROMOTED）

## QUARTILE DESCRIPTIVE（仅描述，不得作为 threshold rule）
| Q | 上界 | N | STRICT_N | strict_win_rate | R_DEFINED_N | P(R>0) | mean_R | median_R |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Q1 | None | 2377 | 2006 | 0.347458 | 2006 | 0.298106 | 0.017468 | -1.0 |
| Q2 | 1.204124 | 2377 | 2012 | 0.333499 | 2012 | 0.273857 | -0.038693 | -1.0 |
| Q3 | 1.697379 | 2377 | 1962 | 0.296126 | 1962 | 0.234964 | -0.05008 | -1.0 |
| Q4 | 2.498667 | 2377 | 1785 | 0.210084 | 1785 | 0.165266 | -0.132638 | -1.0 |

## ROBUSTNESS（非 verdict gate）
- F20 分布（defined population）：{'p10': 0.896134, 'p25': 1.204124, 'p50': 1.697379, 'p75': 2.498667, 'p90': 3.726653, 'p95': 4.666875, 'p99': 6.678837, 'max': 13.144185}
- R 尾部（R-defined，H4B right-tail caveat）：{'p90_R': 0.6452, 'p95_R': 1.59932, 'p99_R': 17.586628, 'max_R': 109.0, 'top1pct_R_contribution': -5.991301, 'trim_top1pct_mean_R': -0.343587}

## STAGE COMPOSITION（SMALL_CELL 排除；只报告方向，不改变 primary verdict）
- B1_READY: N=6301，rho_strict=-0.009732（N=4874），rho_R_positive=-0.009732（N=4874）
- B2_READY: N=1643，rho_strict=0.056034（N=1329），rho_R_positive=0.056034（N=1329）
- B2_CONFIRMED: N=1564，rho_strict=-0.01451（N=1562），rho_R_positive=-0.092593（N=1562）
- 方向汇总：{'STRICT_DIRECTION_POSITIVE_K': 1, 'STRICT_ELIGIBLE_K': 3, 'RPOS_DIRECTION_POSITIVE_K': 1, 'RPOS_ELIGIBLE_K': 3}

## TIMING COMPOSITION（SMALL_CELL 排除；只报告方向，不改变 primary verdict）
- T1-2: N=6723，rho_strict=-0.059124（N=5195），rho_R_positive=-0.059124（N=5195）
- T3: N=1244，rho_strict=0.069638（N=1067），rho_R_positive=-0.006228（N=1067）
- T4-5: N=911，rho_strict=0.099904（N=884），rho_R_positive=-0.044738（N=884）
- T6-10: N=630，rho_strict=0.118439（N=619），rho_R_positive=-0.022971（N=619）
- 方向汇总：{'STRICT_DIRECTION_POSITIVE_K': 3, 'STRICT_ELIGIBLE_K': 4, 'RPOS_DIRECTION_POSITIVE_K': 0, 'RPOS_ELIGIBLE_K': 4}

## CONCLUSION（frozen validation V01 最终记录）
- F20 OUTCOME VALIDATION V01 = REJECT
- PREDICTIVE_VALUE: global main effect not supported
- VALIDATED = False；PROMOTED = False
- quartile / stage / timing 观察仅作 OBSERVATION / NEW HYPOTHESIS，不升级为规则

## LIMITATIONS
- GitHub 无 CI；本报告为作者本地验证（SHA 门禁通过）
- mean_R 受 H4B 已确认的极端右尾风险影响，不作为 primary gate；见 R_TAIL
- CANCEL_GAP_INVALID 不进入 strict binary denominator，仅 accounting
- R 仅定义于 WIN_S1/LOSS_INVALID 且 r_multiple 数值化的子集；P(R>0) 在该子集上计算
- F20 为合同冻结后首次 outcome 验证；SUPPORTED_DIRECTIONALLY 仅属 research evidence
- NEW_HYPOTHESES = []
- OUTCOME_AWARE_CONTRACT_CHANGE = False；THRESHOLD_SEARCH = False