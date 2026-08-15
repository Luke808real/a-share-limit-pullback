# H4B R Distribution Reconciliation — Report v01

性质：**reconciliation / diagnostic only**（非新假设验证）。解释 H4 V01 中
RECLAIM strict win rate 62.10% vs NO_RECLAIM 11.67%、但 RECLAIM mean_R
反而低 0.0608 的矛盾。**H4B_VERDICT 保持 REJECT**，E03 不升级，不改任何
生产规则。

## 1. Input Provenance / Population Gate

| 项 | 值 |
| --- | --- |
| episodes SHA256 | `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093` ✓ |
| snapshot | `snap-2026-07-31-b5f84004de8a`（bars dataset_snapshot_id 一致 ✓；max signal ≤ 07-31 ✓） |
| R source | episodes.r_multiple，Phase 2D.0 corrected strict variant only |
| E02/E03 语义 | 复用 H4 contract v01（7741ba5）/ validation（6a4bbe0），未重新定义 |
| PIT | 纯函数仅收到 trade_date ≤ signal_date 的 bars（anchor + 前 9 可见 session + (anchor, signal]） |

**Population exact reproduction gate：PASS**

```text
RECLAIM_N        = 525（strict WIN/LOSS = 290/177）
NO_RECLAIM_N     = 960（strict WIN/LOSS = 90/681）
```

与 H4 V01 完全一致；不一致则 FAIL CLOSED（未触发）。

## 2. R Distribution（strict R）

| 指标 | RECLAIM (n=467) | NO_RECLAIM (n=771) |
| --- | --- | --- |
| positive_R / negative_R / zero_R | 228 / 238 / 1 | 83 / 687 / 1 |
| mean_R | +0.1866 | +0.2474 |
| median_R | **-0.0218** | **-1.0** |
| p10 / p25 / p75 | -1.0 / -1.0 / 0.4667 | -1.0 / -1.0 / -1.0 |
| p90 / p95 / p99 | 1.2676 / 2.1094 / 6.7669 | 0.211 / 4.0667 / 29.0 |
| max_R | 26.381 | 69.25 |
| P(R>0) | 0.4882 | 0.1077 |
| P(R>=1) | 0.1542 | 0.0739 |
| P(R>=2) | 0.0578 | 0.0636 |
| P(R>=5) | 0.0321 | 0.0506 |
| P(R>=10) | 0.0086 | 0.0376 |
| mean_positive_R | 1.2213 | 10.5271 |
| median_positive_R | 0.4815 | 3.5641 |
| mean_negative_R | -0.8038 | -0.9942 |

**Outcome vs payoff 口径核对（Sol 评审发现，已修正）**：本脚本的
`winner_payoff()` 按 **R>0**（payoff-positive）而非 `outcome==WIN_S1` 定义
"winner"。核对结果如实记录：

| 项 | RECLAIM | NO_RECLAIM |
| --- | --- | --- |
| WIN_S1（frozen outcome） | 290 | 90 |
| payoff_positive（R>0） | 228 | 83 |
| r==0 | 1 | 1 |
| WIN_S1 且 r<=0 | **62**（61 负 + 1 零） | **7**（6 负 + 1 零） |
| LOSS_INVALID 且 r>0 | 0 | 0 |

即：frozen outcome 标签与 r_multiple 符号存在系统性分歧——**WIN_S1 行可能
携带 r<=0**（RECLAIM 62 行 / NO_RECLAIM 7 行）；LOSS_INVALID 全部为负。
两口径各自独立报告，绝不混用。此分歧不影响 tail analysis（完整 R 向量）。

**LOSS_INVALID outcome-filtered R 核对（Sol final QC 要求：直接按
outcome 统计，禁止从全体负 R 向量推断）**：

| 项 | RECLAIM | NO_RECLAIM |
| --- | --- | --- |
| loss_invalid_n / r_defined_n / r_missing_n | 177 / 177 / 0 | 681 / 681 / 0 |
| **loss_r_eq_minus1_n** | **177** | **681** |
| **loss_r_non_minus1_n** | **0** | **0** |
| loss_r_zero_n / positive_n / negative_n | 0 / 0 / 177 | 0 / 0 / 681 |

**旧版断言"LOSS_INVALID 并非全部为 -1（61/7 个非(-1)负R）"是错误的，
特此更正**：outcome-filtered 核对证明 **LOSS_INVALID 行全部 R == -1**
（RECLAIM 177/177，NO_RECLAIM 681/681）。此前观察到的非 (-1) 负值
（61/6 个）实际全部来自 **WIN_S1 的负 R 行**（win_s1_r_negative_n 61/6，
win_s1_r_zero_n 1/1），与 outcome_vs_payoff 核对完全吻合。strict 口径按
episodes.r_multiple 原值使用，未改变 execution semantics。

## 3. Tail Driver

| 指标 | RECLAIM | NO_RECLAIM |
| --- | --- | --- |
| total_R | +87.14 | +190.75 |
| top1% n / sum / contribution | 5 / +76.68 / **0.880** | 8 / +361.21 / **1.894** |
| top5% n / sum / contribution | 24 / +158.89 / **1.824** | 39 / +821.56 / **4.307** |
| trimmed_mean_remove_top1pct | **+0.0226** | **-0.2234** |
| trimmed_mean_remove_top5pct | **-0.1620** | **-0.8618** |
| wins_required_to_make_total_positive | 0 | 0 |
| top_winner_R | 26.381 | 69.25 |
| top5_winner_R | 26.38 / 19.81 / 12.40 / 10.14 / 7.94 | 69.25 / 60.33 / 52.33 / 45.09 / 36.67 |

NO_RECLAIM 的 top1%（8 行）贡献 **1.89× 总 R**，top5%（39 行）贡献
4.31× —— 即去掉 top1% 后总 R 转负（trimmed mean -0.2234）。均值完全由
极端右尾撑起。

## 4. Winner Payoff Decomposition（双口径，绝不混用）

### 4a. payoff-positive 口径（R>0 行）

| 指标 | RECLAIM (n=228) | NO_RECLAIM (n=83) |
| --- | --- | --- |
| mean_payoff_positive_R | **1.2213** | **10.5271** |
| median_payoff_positive_R | 0.4815 | 3.5641 |
| p90_payoff_positive_R | 2.125 | 26.3529 |
| max_payoff_positive_R | 26.381 | 69.25 |

mean ratio（NO_RECLAIM / RECLAIM）= **8.62×**

### 4b. WIN_S1 outcome 口径（frozen outcome 标签）

| 指标 | RECLAIM (n=290) | NO_RECLAIM (n=90) |
| --- | --- | --- |
| mean_win_s1_R | **0.9108** | **9.6861** |
| median_win_s1_R | 0.2923 | 3.1678 |
| p90_win_s1_R | 1.8822 | 26.3529 |
| max_win_s1_R | 26.381 | 69.25 |

mean ratio（NO_RECLAIM / RECLAIM）= **10.63×**

**两个口径方向完全一致**：NO_RECLAIM 的 winner 平均 R 是 RECLAIM 的
8.6–10.6 倍。低命中的 NO_RECLAIM 依赖少数巨大 winner（83/90 个
R>0/WIN_S1 行平均 R 10.53/9.69，中位 3.56/3.17，p90 26.35）。RECLAIM
的 winner 多而小（228/290 行平均 R 1.22/0.91，中位 0.48/0.29）。
"winner payoff 反向"的解释在两种口径下均成立，且 WIN_S1 口径下更强。

## 5. Pre-registered Strata（stage / timing，N<20 不解释；mean_payoff_positive_r 为 R>0 口径）

| stratum | RECLAIM n / swr / mean_R / mean_pos_R | NO_RECLAIM n / swr / mean_R / mean_pos_R |
| --- | --- | --- |
| B1_READY | 181 / 0.1029 / +0.0588 / null | 888 / 0.0636 / +0.2537 / 18.7251 |
| B2_READY | 114 / 0.6634 / +0.0634 / 0.603 | 39 / 0.5667 / -0.0449 / null |
| B2_CONFIRMED | 230 / 0.9087 / +0.3163 / 0.7351 | 33 / 0.8485 / +0.3776 / 0.9271 |
| T+1~2 | 141 / 0.2364 / +0.1973 / 4.0655 | 711 / 0.0677 / +0.0462 / 14.4456 |
| T+3 | 144 / 0.6371 / +0.3371 / 1.1897 | 98 / 0.1625 / +0.7214 / null |
| T+4~5 | 148 / 0.7552 / +0.1984 / 0.7956 | 64 / 0.2264 / +1.6525 / null |
| T+6~10 | 92 / 0.8556 / -0.0527 / 0.3878 | 87 / 0.3506 / +0.2535 / 3.5764 |

胜率方向：RECLAIM 在全部 7 个分层中 strict_win_rate 更高（与 H4 V01
一致）；mean_payoff_positive_R 在可解释 cell 中 RECLAIM 全部更低 ——
winner payoff 反向在分层中同样成立。

## 6. Conclusion

```text
A. NO_RECLAIM +0.2474 mean_R 是否由 tail concentration 驱动？
   YES —— top1% 贡献 1.89× 总 R，去 top1% 后 trimmed mean = -0.2234（转负）。

B. RECLAIM 优势是否主要为 hit probability / median outcome，而非右尾 payoff？
   YES —— median_R -0.0218 vs -1.0，P(R>0) 48.8% vs 10.8%，
   winner payoff 双口径均反向（R>0 口径 1.22 vs 10.53 ratio 8.62×；
   WIN_S1 口径 0.91 vs 9.69 ratio 10.63×）。

C. 去除 top1% / top5% 后两组 mean_R 相对方向？
   翻转：top1% 去除后 +0.0226 vs -0.2234；top5% 去除后 -0.162 vs -0.862
   → RECLAIM 更高。

CONCLUSION = REJECT_EXPLANATION
H4B_VERDICT_UNCHANGED = REJECT
```

结论：H4B 的 mean_R 矛盾被完整解释——**NO_RECLAIM 的正 mean_R 是极端
右尾集中（少数超级赢家）的产物，不是稳健收益**；**RECLAIM 的优势体现在
命中概率与中位结果**（快速收回 MA10 的样本胜率更高、亏损更浅），而非
赔率结构。winner payoff 反向在 payoff-positive 与 WIN_S1 双口径下均成立
（ratio 8.62× / 10.63×）。任何"快速收回 = 更好"的表述仍停留在
OBSERVATION 层面：不改 E01/E02/E03 合同、不搜索阈值、不升级 E03、不做
production promotion。

**核心指标保持 gate（Sol final QC 第 4 节）**：RECLAIM_N=525 /
NO_RECLAIM_N=960 / WIN·LOSS 290·177 vs 90·681 / WIN_S1 mean_R
0.9108·9.6861 / payoff-positive mean_R 1.2213·10.5271 / top1 贡献
0.8800·1.8937 / trim1 +0.0226·-0.2234 —— 全部与冻结 run（48081e3）
exact 一致，任何漂移 FAIL CLOSED（PASS）。R 符号字段在 JSON authority
中已改名 positive_r_count / negative_r_count / zero_r_count（不再用
win/loss 命名）。

## 7. Artifacts

| 项 | 值 |
| --- | --- |
| 研究脚本 | `research/factor-lab/h4b_r_distribution_reconciliation_v01.py` |
| script SHA256 | `e0a59b8d63f07fa2f4e3a190fb87219d3180d29be26e3f577a41529d336eb5a2` |
| 输出 JSON | `research/factor-lab/runs/h4b-r-v01/h4b-r-v01.json` |
| output JSON SHA256 | `93986818da050d2760af06a963675c82faaba920af73976649919f81c88ca537` |
| 语义测试 | `tests/test_h4b_r_reconciliation_semantics.py` |
