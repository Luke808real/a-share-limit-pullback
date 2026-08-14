# H10 R-metric Reconciliation v01（2026-08-14，research / reconciliation only）

问题：H10 同样本里 entry_quality>=80 的 win-share 显著为负（10.07% vs
25.05%），而冻结基线历史 E[R] 为正（+0.0287 strict / 2D.1A T+1 10bp
+0.2605）。两者是否矛盾？

## 0. INPUT GATE / R source

- episodes SHA256: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093（31,422 行，未变）
- snapshot: snap-2026-07-31-b5f84004de8a（frozen，未变）
- R source: episodes.r_multiple = Phase 2D.0 corrected outcome study
  （FINAL_VINTAGE_CAUSAL，T+1 daily-bar 理论执行，strict 口径：
  WIN_S1 → (S1−fill)/(fill−invalid)；LOSS_INVALID → −1；无成交 → NULL）。
  frozen strict resolved E[R] = mean(r over WIN∪LOSS)。**本研究的 R 对账
  与该冻结口径同源同字段**（下方 frozen echo 逐位复现证明）。
- **口径差异 FAIL CLOSED**：Phase 2D.1A 的 T+1 摩擦 E[R]（10bp +0.2605）
  是另一套执行模型（execution-reality/execution_episodes.parquet），
  无法从 episodes.r_multiple 复现；本研究只引用其冻结 summary，不复算、
  不修正。另外旧基线数字 +0.0769/+0.0621 属于被取代的 pre-correction
  episodes（23d3ff93... SUPERSEDED），corrected 冻结值应为
  **+0.0287 / −0.0198**。

## 1. Same-sample reconciliation（resolved 全样本 n=9,625，全部 stage，
   含非 actionable；win_share 分母 = 该分层 N）

| 指标 | entry>=80 | entry<80 | delta |
| --- | --- | --- | --- |
| N | 556 | 9,069 | — |
| win_share | 0.1007 | 0.2505 | **−0.1498** |
| strict_win_rate (WIN/(WIN+LOSS)) | 0.1174 | 0.3079 | −0.1905 |
| n_with_r / r_missing_n | 477 / 79 | 7,380 / 1,689 | — |
| mean_R | **−0.0822** | −0.0574 | **−0.0248** |
| median_R | −1.0 | −1.0 | 0.0 |
| p25 / p75 | −1.0 / −1.0 | −1.0 / 0.0059 | — |
| P(R>0) / P(R≥2) | 0.1174 / 0.0839 | 0.2511 / 0.0416 | — |
| mean_pos_R / mean_neg_R | 6.8178 / −1.0 | 2.5826 / −0.9452 | — |

setup_quality control（同口径）：ge80 mean_R −0.0390 vs lt80 −0.0621
（+0.0231），win_share +4.69pp——与 H10 方向一致。

**要点**：在 H10 的同一 resolved 样本里，entry>=80 的 mean_R 也是负的
（−0.0822，比 lt80 还差 −0.0248）。win-share 与 E[R] **同向为负**，
并不存在矛盾。矛盾只出现在把「全 resolved 样本的 win share」与
「actionable 子集的冻结 E[R]」并排——这是样本/口径错配，不是因子矛盾。

## 2. Frozen echo（ACTIONABLE 子集，is_entry_candidate=True，
   与冻结 baseline 同口径，逐位复现）

| cohort | episodes | wins | losses | strict win rate | strict E[R] | conservative E[R] |
| --- | --- | --- | --- | --- | --- | --- |
| entry>=80 | 638 | 38 | 144 | 0.2088 | **+0.0287** | −0.0198 |
| entry<80 | 10,473 | 1,188 | 1,214 | 0.4946 | −0.0666 | −0.1370 |
| setup>=80 | 1,176 | 205 | 244 | 0.4566 | +0.0054 | −0.0375 |

entry>=80 / setup>=80 的 strict win rate 与 E[R] 与冻结
corrected-b2-trigger-outcome/summary.md **完全一致**（0.2088/0.0287/−0.0198；
0.4566/0.0054/−0.0375）→ 同口径成立。

win_rate_ge80 < win_rate_lt80 且 mean_R_ge80 > mean_R_lt80 的触发条件
**只在 actionable 子集成立**；按要求继续检查 median + tail（见 §3）。

## 3. Tail-driver check（actionable entry>=80 strict R，n=182 fills）

- mean_R +0.0287；**median_R −1.0；p25 −1.0；p75 −1.0**（≥75% 满损 −1R）
- P(R>0)=0.2088；P(R≥2)=0.1209；mean_pos_R=3.9268；mean_neg_R=−1.0
- total R = +5.2194
- **top 1%（2 个赢家）contribution = 5.2294**（前 2 名赢家的 R 之和
  超过全体 182 笔的总 R——其余 180 笔合计为负）
- top 5%（10 个赢家）contribution = 16.3013
- **trimmed_mean_top1pct = −0.1226**（剔除 top 1% 后均值转负）

对照 entry<80（actionable）：total R −160.0，trimmed −0.1899，top
contribution 无定义（总 R 为负）。

## 4. Timing strata（entry_quality，resolved 样本；n<20 不解释）

| bucket | ge80 n | ge80 mean_R | ge80 win | lt80 n | lt80 mean_R | lt80 win |
| --- | --- | --- | --- | --- | --- | --- |
| 1-2 | 519 | −0.0588 | 0.0906 | 6,300 | −0.1059 | 0.1032 |
| 3 | 23 | −0.2381 | 0.3043 | 1,226 | +0.0333 | 0.4584 |
| 4-5 | 11 | null | — | 911 | +0.0963 | 0.6608 |
| 6-10 | 3 | null | — | 632 | −0.0524 | 0.7247 |

## 5. Setup-stage strata（entry_quality，resolved 样本）

| stage | ge80 n | ge80 mean_R | ge80 win | lt80 n | lt80 mean_R | lt80 win |
| --- | --- | --- | --- | --- | --- | --- |
| B1_READY | 492 | −0.0556 | 0.0772 | 5,919 | −0.0898 | 0.0434 |
| B2_READY | 56 | −0.2823 | 0.2857 | 1,587 | +0.0026 | 0.5211 |
| B2_CONFIRMED | 8 | null | — | 1,563 | −0.0123 | 0.7601 |

B1_READY 是 resolved 样本中 entry>=80 相对改善主要出现的 stage：ge80 胜率
略高（0.0772 vs 0.0434）且 mean_R 更高（−0.0556 vs −0.0898），同向改善，
与冻结 B1_READY_ENTRY_GE_80 观察（平均赢 R 6.3、低胜率）一致；B2 阶段
ge80 无优势。注意：这不能证明 actionable strict 的 low-hit/high-payoff
现象集中于 B1_READY——该现象属于 actionable strict aggregate 口径。

## 6. VERDICT

**OBSERVATION: low-hit-rate / high-payoff profile**（仅 actionable strict
口径成立，绝不升级）：
- 同口径（resolved 全样本）里 win-share 与 mean_R 同向为负，无矛盾；
  entry>=80 的正 E[R] 只存在于 actionable 子集；
- actionable 子集里 entry>=80 胜率低（0.2088 vs 0.4946）而 strict E[R]
  为正（+0.0287 vs −0.0666）——但 median 与 lt80 相同（−1.0），且该
  正 E[R] 完全由 top-1% 尾部驱动（top2 赢家贡献 5.23× 总 R；trimmed
  mean −0.12；p75=−1.0）；conservative E[R] 为负（−0.0198）；
- 2D.1A T+1 摩擦口径（+0.2605）为不同执行模型，fail-closed 差异标注，
  未在本研究复算。

## Provenance

- episodes SHA256: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093
- snapshot id: snap-2026-07-31-b5f84004de8a
- execution/R source: episodes.r_multiple（Phase 2D.0 corrected outcome study, strict variant）；2D.1A 数字仅引用冻结 ER summary
- script SHA256: 9bcfa09192edcbd349a811066a5d97c29af16526d4776fc81fbb79f7557a7281
- output JSON SHA256: 700a4f5de10b24c2f8f430b8159833956f16c46c98847d663abfa8985fee5d42
- conclusion status: OBSERVATION（low-hit-rate/high-payoff，actionable strict only；不升级、不落地）
