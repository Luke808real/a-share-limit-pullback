# F20 B2 VOLUME VS 20D MEAN OUTCOME VALIDATION V01 — 预注册验证报告

- F20 CONTRACT = FROZEN / CLOSED（HEAD ff4ea77a80c2144fda181b6e412a795b6c1952d9，Sol audit PASS）
- 函数：factor_lab.b2_volume_vs_20d_mean；预注册：commit 758768e1dc0db16fa0d9d75a6c25652d2d789671
- b2 event date := signal_date for B2-stage episodes (frozen)；as_of = signal_date
- episodes SHA: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093；daily SHA: e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
- EPISODES_TOTAL = 31422；RESOLVED_N = 9625

## ACCOUNTING
- RESOLVED_N = 9625；F20_DEFINED_N = 3207；F20_UNDEFINED_N = 6418
- STRICT_N = 2891；R_DEFINED_N = 2891；CANCEL_GAP_ACCOUNTING_N = 316
- UNDEFINED_REASONS = {'NON_B2_STAGE': 6411, 'DEFINED': 3207, 'F20_UNDEFINED': 7}

## PRIMARY（H5A 连续 Spearman 双 gate）
- rho_strict = 0.033836（N=2891，direction=positive，p=0.068906，p 非 gate）
- rho_R_positive = -0.038309（N=2891，direction=nonpositive，p=0.039431，p 非 gate）
- **H5A = REJECT**（规则：rho_strict > 0 AND rho_R_positive > 0 -> SUPPORTED_DIRECTIONALLY else REJECT；SUPPORTED_DIRECTIONALLY != VALIDATED != PROMOTED）

## QUARTILE DESCRIPTIVE（仅描述，不得作为 threshold rule）
| Q | 上界 | N | strict_win_rate | P(R>0) | mean_R | median_R |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | None | 802 | 0.694678 | 0.595238 | 0.078148 | 0.1588 |
| Q2 | 1.110322 | 802 | 0.664374 | 0.544704 | -0.0421 | 0.0699 |
| Q3 | 1.48184 | 801 | 0.732218 | 0.562064 | -0.000343 | 0.0824 |
| Q4 | 2.011692 | 802 | 0.716235 | 0.526603 | -0.077427 | 0.0351 |

## ROBUSTNESS（非 verdict gate）
- F20 分布（defined population）：{'p10': 0.844528, 'p25': 1.110322, 'p50': 1.48184, 'p75': 2.011692, 'p90': 2.666961, 'p95': 3.214998, 'p99': 4.334905, 'max': 6.52962}
- R 尾部（R-defined，H4B right-tail caveat）：{'p90_R': 0.9457, 'p95_R': 1.36035, 'p99_R': 2.32399, 'max_R': 5.878, 'top1pct_R_contribution': -2.949084, 'trim_top1pct_mean_R': -0.043876}

## STAGE COMPOSITION（SMALL_CELL 排除；只报告方向，不改变 primary verdict）
- B2_READY: N=1643，rho_strict=0.056034（N=1329），rho_R_positive=0.056034（N=1329）
- B2_CONFIRMED: N=1564，rho_strict=-0.01451（N=1562），rho_R_positive=-0.092593（N=1562）
- 方向汇总：{'STRICT_DIRECTION_POSITIVE_K': 1, 'STRICT_ELIGIBLE_K': 2, 'RPOS_DIRECTION_POSITIVE_K': 1, 'RPOS_ELIGIBLE_K': 2}

## TIMING COMPOSITION（SMALL_CELL 排除；只报告方向，不改变 primary verdict）
- T1-2: N=865，rho_strict=0.053912（N=683），rho_R_positive=0.053912（N=683）
- T3: N=970，rho_strict=0.084744（N=849），rho_R_positive=-0.011448（N=849）
- T4-5: N=799，rho_strict=0.008228（N=786），rho_R_positive=-0.109695（N=786）
- T6-10: N=573，rho_strict=-0.041511（N=573），rho_R_positive=-0.109665（N=573）
- 方向汇总：{'STRICT_DIRECTION_POSITIVE_K': 3, 'STRICT_ELIGIBLE_K': 4, 'RPOS_DIRECTION_POSITIVE_K': 1, 'RPOS_ELIGIBLE_K': 4}

## CONCLUSION（frozen validation V01 最终记录）
- F20 OUTCOME VALIDATION V01 = REJECT
- PREDICTIVE_VALUE: global main effect not supported
- VALIDATED = False；PROMOTED = False
- quartile / stage / timing 观察仅作 OBSERVATION / NEW HYPOTHESIS，不升级为规则

## LIMITATIONS
- GitHub 无 CI；本报告为作者本地验证（SHA 门禁通过）
- mean_R 受 H4B 已确认的极端右尾风险影响，不作为 primary gate；见 R_TAIL
- CANCEL_GAP_INVALID 不进入 strict binary denominator，仅 accounting
- R 仅定义于 WIN_S1/LOSS_INVALID 子集；P(R>0) 在该子集上计算
- F20 为合同冻结后首次 outcome 验证；SUPPORTED_DIRECTIONALLY 仅属 research evidence
- NEW_HYPOTHESES = []
- OUTCOME_AWARE_CONTRACT_CHANGE = False；THRESHOLD_SEARCH = False