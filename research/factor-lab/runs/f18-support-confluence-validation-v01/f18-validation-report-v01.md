# F18 SUPPORT CONFLUENCE OUTCOME VALIDATION V01 — 预注册验证报告

- F18 CONTRACT = FROZEN（HEAD e37c57be4f65e314ed8a45763bb56d893be88289，Sol audit PASS）
- 函数：factor_lab.support_confluence_max_count；primary contrast：F18 >= 2 vs F18 <= 1
- episodes SHA: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093；daily SHA: e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
- EPISODES_TOTAL = 31422；RESOLVED_N = 9625（WIN_S1+LOSS_INVALID+CANCEL_GAP_INVALID）

## ACCOUNTING
- F18_DEFINED_N = 9594；F18_UNDEFINED_N = 31
- UNDEFINED_REASONS = {'DEFINED': 9594, 'NO_DEFINED_MA10': 31}

## PRIMARY CONTRAST（CONFLUENCE F18>=2 vs NON_CONFLUENCE F18<=1）
| 指标 | CONFLUENCE | NON_CONFLUENCE | Δ |
| --- | --- | --- | --- |
| N | 6634 | 2991 |  |
| WIN_S1 | 1586 | 742 |  |
| LOSS_INVALID | 3759 | 1770 |  |
| CANCEL_GAP_INVALID | 1289 | 479 |  |
| strict_win_rate | 0.296726 | 0.295382 | 0.001344 |
| R_DEFINED_N | 5345 | 2512 |  |
| mean_R | -0.072509 | -0.029919 | -0.04259 |
| median_R | -1.0 | -1.0 | 0.0 |
| P(R>0) | 0.241534 | 0.246019 | -0.004485 |
| P(R>=2) | 0.048082 | 0.035828 |  |

## ROBUST R DIAGNOSTICS（非 verdict gate）
- CONFLUENCE: {'p90_R': 0.6667, 'p95_R': 1.81736, 'p99_R': 16.479364, 'max_R': 69.25, 'top1pct_R_contribution': -3.577367, 'trim_top1pct_mean_R': -0.335223}
- NON_CONFLUENCE: {'p90_R': 0.57707, 'p95_R': 1.235985, 'p99_R': 19.654107, 'max_R': 109.0, 'top1pct_R_contribution': -11.834059, 'trim_top1pct_mean_R': -0.387837}

## RAW DEPTH TABLE（描述性，N<20 标 SMALL_CELL，不做强解释）
| F18 | N | strict_win_rate | P(R>0) | mean_R | median_R |
| --- | --- | --- | --- | --- | --- |
| 0 | 438 | 0.311688 | 0.264935 | 0.04627 | -1.0 |
| 1 | 2522 | 0.295909 | 0.24548 | -0.032336 | -1.0 |
| 2 | 6095 | 0.294988 | 0.241372 | -0.052275 | -1.0 |
| 3 | 539 | 0.314465 | 0.243187 | -0.279 | -1.0 |

## STAGE COMPOSITION（SMALL_CELL 排除）
- B1_READY: N 双方 4400/2011，Δstrict_win_rate=0.015104，ΔP(R>0)=0.015104
- B2_READY: N 双方 1122/521，Δstrict_win_rate=-0.023557，ΔP(R>0)=-0.023557
- B2_CONFIRMED: N 双方 1112/459，Δstrict_win_rate=-0.036566，ΔP(R>0)=-0.032179
- 方向汇总：{'STRICT_DIRECTION_POSITIVE_K': 1, 'ELIGIBLE_K': 3, 'RPOS_DIRECTION_POSITIVE_K': 1, 'RPOS_ELIGIBLE_K': 3}

## TIMING COMPOSITION（SMALL_CELL 排除）
- T1-2: N 双方 4790/2029，Δstrict_win_rate=0.005032，ΔP(R>0)=0.005032
- T3: N 双方 782/467，Δstrict_win_rate=-0.008915，ΔP(R>0)=-0.023719
- T4-5: N 双方 615/307，Δstrict_win_rate=0.080719，ΔP(R>0)=0.049071
- T6-10: N 双方 447/188，Δstrict_win_rate=0.0885，ΔP(R>0)=0.086017
- 方向汇总：{'STRICT_DIRECTION_POSITIVE_K': 3, 'ELIGIBLE_K': 4, 'RPOS_DIRECTION_POSITIVE_K': 3, 'RPOS_ELIGIBLE_K': 4}

## VERDICT（预注册 H4C）
- delta_strict_win_rate = 0.001344
- delta_p_r_gt_0 = -0.004485
- **H4C = REJECT**（SUPPORTED_DIRECTIONALLY != VALIDATED != PROMOTED）

## LIMITATIONS
- GitHub 无 CI；本报告为作者本地验证（SHA 门禁通过）
- mean_R 受 H4B 已确认的极端右尾风险影响，不作为 primary gate；见 ROBUST R
- CANCEL_GAP_INVALID 为数据中单一合并桶（无独立 GAP/INVALID 分类）
- R 仅定义于 WIN_S1/LOSS_INVALID 子集；P(R>0)/P(R>=2) 在该子集上计算
- F18 为合同冻结后首次 outcome 验证；SUPPORTED_DIRECTIONALLY 仅属 research evidence
- NEW_HYPOTHESES = []
- OUTCOME_AWARE_CONTRACT_CHANGE = False；THRESHOLD_SEARCH = False