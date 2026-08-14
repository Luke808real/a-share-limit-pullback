# H4 MA10 Support Outcome Validation — Report v01

研究问题（两个预注册问题，独立 verdict）：

- **H4A**：MA10 收盘跌破（E02_MA10_CLOSE_BREAK）是否为负向结构？
- **H4B**：已发生跌破（E02=True 子集）后，3 个可见交易日内收回
  （E03_MA10_RECLAIM_3D）是否具有恢复意义？

E01（touch+hold）仅作 secondary descriptive，不参与主 verdict。

## 1. Input Provenance / Strict PIT Boundary

| 项 | 值 |
| --- | --- |
| episodes | `data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet` |
| episodes SHA256 | `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093` ✓ |
| daily bars | `data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet` |
| daily bars SHA256 | `e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514` |
| snapshot id | `snap-2026-07-31-b5f84004de8a`（bars dataset_snapshot_id 校验一致） |
| frozen as_of | 2026-07-31（max signal_date ≤ 2026-07-31 校验通过） |
| E01/E02/E03 合同来源 | commit 7741ba5（H4 MA10 contract v01，Sol 复核 PASS） |

**严格 PIT 物化**：每个 episode 只向纯函数传入 `trade_date <= signal_date`
的 canonical bars（anchor + anchor 前最近 9 个可见 session + (anchor, signal]
全部 session）；无未来 bar 传入；duplicate/multi-code/missing-anchor →
DATA_ERROR FAIL CLOSED（本运行未触发）。

## 2. Sample Accounting

| 项 | 值 |
| --- | --- |
| EPISODES_TOTAL | 31,422 |
| RESOLVED_N | 9,625 |
| E01_DEFINED_N / UNDEFINED_N | 9,594 / 31 |
| E02_DEFINED_N / UNDEFINED_N | 9,594 / 31 |
| E03_DEFINED_N / UNDEFINED_N | 9,594 / 31 |
| undefined reasons | 全部 INSUFFICIENT_MA10_HISTORY（31）；NO_POST_ANCHOR_BAR=0；MISSING_CANONICAL_WINDOW=0；DATA_ERROR=0（出现即 fail closed） |
| MIN_N | 20（小样本解释性统计置 null） |

## 3. H4A — Primary（E02=True vs E02=False）

| 指标 | BREAK (n=1,485) | NO_BREAK (n=8,109) | DELTA (BREAK−NO_BREAK) |
| --- | --- | --- | --- |
| WIN / LOSS / CANCEL | 380 / 858 / 247 | 1,948 / 4,646 / 1,515 | — |
| win_share | 0.2559 | 0.2402 | **+0.0157** |
| strict_win_rate | 0.3069 | 0.2954 | **+0.0115** |
| mean_R | +0.2245 | -0.1085 | **+0.3330** |
| median_R | -1.0 | -1.0 | 0.0 |
| P(R>0) / P(R>=2) | 0.2512 / 0.0614 | 0.2423 / 0.0411 | — |

预注册负向方向：strict_win_rate_delta < 0 AND mean_R_delta < 0。
实际两者均为正 → 共同方向不满足 → **H4A_VERDICT = REJECT**。

含义：在 frozen 样本中，"跌破 MA10" 并不构成负向结构；跌破组胜率与
mean_R 反而更高（右尾更强，P(R>=2) 0.0614 vs 0.0411）。

## 4. H4B — Conditional Primary（仅 E02=True 子集，n=1,485）

| 指标 | RECLAIM (n=525) | NO_RECLAIM (n=960) | DELTA (RECLAIM−NO_RECLAIM) |
| --- | --- | --- | --- |
| WIN / LOSS / CANCEL | 290 / 177 / 58 | 90 / 681 / 189 | — |
| win_share | 0.5524 | 0.0938 | **+0.4586** |
| strict_win_rate | 0.6210 | 0.1167 | **+0.5043** |
| mean_R | +0.1866 | +0.2474 | **-0.0608** |
| median_R | -0.0218 | -1.0 | +0.9782 |
| P(R>0) / P(R>=2) | 0.4882 / 0.0578 | 0.1077 / 0.0636 | — |

预注册正向方向：strict_win_rate_delta > 0 AND mean_R_delta > 0。
strict_win_rate +0.5043 ✓，但 mean_R −0.0608 ✗ → 共同方向不满足 →
**H4B_VERDICT = REJECT**。

含义：3 日内收回是**强胜率效应**（strict win rate 62.1% vs 11.7%，各
stage/timing 分层全部正向），但不是 E[R] 改善效应——NO_RECLAIM 组的
mean_R 略高，由其极端右尾驱动（仅 90 个 WIN 撑起 +0.2474，P(R>=2)
0.0636 且中位数 -1.0）。"收回"改善的是命中概率而非赔率结构。

## 5. E01 — Secondary（仅 E02=False 子集，descriptive）

| 指标 | E01=True (n=1,630) | E01=False (n=6,479) | delta |
| --- | --- | --- | --- |
| win_share | 0.2890 | 0.2280 | +0.0610 |
| strict_win_rate | 0.3541 | 0.2806 | +0.0735 |
| mean_R | -0.0995 | -0.1108 | +0.0113 |
| median_R | -1.0 | -1.0 | 0.0 |

标签：**OBSERVATION**（触而不破 MA10 的胜率略高；不得据此修改
H4A/H4B verdict，不得 promotion）。

## 6. Pre-registered Confounding Strata

### H4A（BREAK vs NO_BREAK，strict_win_rate_delta / mean_R_delta）

| stratum | break_n / no_break_n | swr_delta | mr_delta |
| --- | --- | --- | --- |
| B1_READY | 1,069 / 5,311 | +0.0122 | +0.3674 |
| B2_READY | 153 / 1,490 | +0.0076 | +0.0515 |
| B2_CONFIRMED | 263 / 1,308 | +0.1714 | +0.4055 |
| T+1~2 | 852 / 5,938 | -0.0430 | +0.1938 |
| T+3 | 242 / 1,006 | -0.0992 | +0.5671 |
| T+4~5 | 212 / 709 | -0.0822 | +0.6418 |
| T+6~10 | 179 / 456 | -0.1535 | +0.1988 |

stage 分层 0/3 负向、timing 分层 4/4 负向（与 H6/F23 相同的构成模式）；
所有分层 mean_R delta 均为正。H4A 的 REJECT 在分层上稳定。

### H4B（RECLAIM vs NO_RECLAIM，E02=True 子集）

| stratum | reclaim_n / no_reclaim_n | swr_delta | mr_delta |
| --- | --- | --- | --- |
| B1_READY | 181 / 888 | +0.0393 | -0.1949 |
| B2_READY | 114 / 39 | +0.0967 | +0.1083 |
| B2_CONFIRMED | 230 / 33 | +0.0602 | -0.0613 |
| T+1~2 | 141 / 711 | +0.1687 | +0.1511 |
| T+3 | 144 / 98 | +0.4746 | -0.3843 |
| T+4~5 | 148 / 64 | +0.5288 | -1.4541 |
| T+6~10 | 92 / 87 | +0.5050 | -0.3062 |

strict_win_rate delta 全部为正（收回与更高胜率在所有分层一致）；
mean_R delta 方向混合（4/7 为负）→ mean_R 不稳，进一步支持 H4B REJECT。

## 7. Verdicts

```text
H4A_VERDICT = REJECT   （跌破 MA10 非负向结构；方向相反）
H4B_VERDICT = REJECT   （收回 = 强胜率效应，非 E[R] 改善；共同方向不满足）
E01 = OBSERVATION（secondary，不影响 verdict）
```

判定逻辑（Sol 冻结合同）：primary strict_win_rate 与 mean_R 未按预注册
方向（H4A 负向 / H4B 正向）共同成立 → REJECT；primary 成立但
strata/composition 不稳定 → OBSERVE_ONLY；共同成立且 win_share 不反向、
主分层无关键反转 → SUPPORTED。SUPPORTED != PROMOTED，不改任何生产规则。

## 8. Artifacts

| 项 | 值 |
| --- | --- |
| 研究脚本 | `research/factor-lab/h4_ma10_support_validation_v01.py` |
| script SHA256 | `7bde39e9b0bc051f2fae1539a754b56ac368bebe32de043b4d7060b8326540d1` |
| 输出 JSON | `research/factor-lab/runs/h4-ma10-v01/h4-ma10-v01.json` |
| output JSON SHA256 | `94ca96d3e50aa9e34de16c61edebda3046098e5b383e080687bd95734b3dd58c` |

未修改 E01/E02/E03 contract、未做 threshold search、未引入 MA5/MA20、
未读 frozen boundary 之后数据、未 full-market、未 PR。
