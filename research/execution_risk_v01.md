# B1/B2 EXECUTION + POSITION SIZING RESEARCH v0.1 — 结论报告

> 只读研究。未修改 production strategy / config / threshold / frozen forward artifact。
> 未使用 2026-08-03 及之后行情；未针对当前 5 只样本反向调参。
> 输入：corrected episodes `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093`
> （31,422 行，`evaluate_strategy_calls=0`）+ Phase 2D.1A execution-reality episodes
> + snapshot `snap-2026-07-31-b5f84004de8a`。

日期口径：`plan_date=2026-07-31`，`next trading session=2026-08-03`；
**2026-08-01 不是交易日（周六）**。
`603185 未进入 frozen watch = universe/state timing coverage gap，不是行情日期落后；本轮不修。`

产物：
- 脚本 `research/execution_risk_v01.py`
- 数据 `data/tmp/execution-risk-v01/metrics.json`

---

## 1. METRIC AUDIT（口径核对）

### A. B1 P1 两个数字的口径差（-0.20 vs -0.383）

原 stop 表 P1=-0.20 来自早期模拟器，三处与冻结 Phase 2D.1A 口径不符：

1. 缺 `GAP_STOP@open`：次日开盘≤invalid 时以 invalid 价退出，canonical 用开盘价（更低）；
2. fill-day 触及 S1 被当作当日 target 退出，而 canonical 语义是 T+1 当日不能卖
   （只记 `MISSED_SAME_DAY_TARGET_T1`，不产生退出）；
3. 10 日窗口未解析 episode 按末日收盘计入，canonical 标记 TIMEOUT/CENSORED/AMBIGUOUS 并排除。

对齐后（同日 stop-first、GAP_STOP/GAP_TARGET@open、fill-day T+1、10bp 单笔摩擦、
10 会话窗口、未解析剔除）的唯一数字：

| cohort | 唯一数字（canonical conservative 10bp E[R]） | 修正模拟器（resolved-only） | 残差 |
|---|---:|---:|---:|
| B1 P1 | **-0.383**（n=733） | -0.391（n=733） | 0.008（Decimal 量化精度） |
| B2_ALL P1 | **-0.149**（n=2,045） | -0.149（n=2,045） | 0 |

### B. 100k 组合模拟口径

确认：`FIXED_PRINCIPAL_SEQUENTIAL_PROXY` —— 固定 100k 本金、按 fill_date 逐笔、单仓、
不复利、可穿仓（equity 可低于 0）。其中的“maxDD 103%+”只是顺序代理累计亏损，
**不是真实 portfolio maxDD / risk of ruin**。

---

## 2. ENTRY EPISODES（actionable filled）

| cohort | n |
|---|---:|
| B1_READY | 747 |
| B2_READY | 1,627 |
| B2_CONFIRMED | 637 |
| B2 add-on（同 anchor 先有 B1 fill） | 170（占 B2 的 7.5%） |

---

## 3. ENTRY 后路径（会话 1..10，日 K 内不做顺序假设）

| 指标 | B1 | B2_READY | B2_CONFIRMED |
|---|---:|---:|---:|
| 10d return med / mean | -0.93% / +0.43% | -1.38% / +0.08% | -1.23% / +0.03% |
| MFE_10d med / p90 | +6.9% / +24.2% | +7.5% / +28.8% | +7.0% / +26.7% |
| MAE_10d med / p10 | -6.3% / -16.5% | -7.6% / -19.0% | -6.8% / -17.9% |
| S1 hit rate（≤10d） | 42.2% | 61.9% | 56.0% |
| time_to_S1 med | 3d | 1d | 1d |
| invalid hit rate（≤10d） | 87.6% | 58.1% | 53.4% |
| time_to_invalid med | 1d | 3d | 3d |
| 先到 S1 / 先到 invalid | 18% / 78% | 51% / 40% | 48% / 40% |

**一般能走多远**：B1 中位数先触 -1R（第 1-2 天），右尾靠少数 S1 赢家（avg win R≈7.3）；
B2 中位数 1 天即触 S1（+0.5~0.7R），但约 40% 概率 3 天内先触 invalid，均值被 gap/尾部亏损拖负。

---

## 4. STOP LOSS（对齐口径，10bp conservative 风格）

| 规则 | B1 mean / med / win | B2_ALL mean / med / win |
|---|---:|---:|
| STRUCTURAL（P1，invalid+S1 全出，≤10d） | -0.305 / -1.05 / 35% | **-0.130 / +0.036 / 52%** |
| FAILED_BREAKOUT（B2 收盘回 trigger 下方→次日开） | N/A | -0.165 / -0.217 / 40%（更差） |
| TIME_STOP_3 | -0.301 / -1.05 / 35% | -0.139 / -0.042 / 47%（更差） |
| TIME_STOP_5 | -0.305 / -1.05 / 35% | -0.137 / +0.003 / 50%（略差） |

结论：**没有任何证据支持比 structural invalid 更早退出。** B2 的 failed-breakout 早退会砍掉
次日反包赢家；time stop 只是把中位 R 从 +0.04 压向 0。

---

## 5. TAKE PROFIT（B2_ALL，10bp）

| 规则 | mean | median | win | p90 | mean@20bp |
|---|---:|---:|---:|---:|---:|
| P1 S1 全出 | **-0.130** | **+0.036** | **52.3%** | 0.94 | -0.147 |
| P2 S1 50% + 结构余仓 | -0.191 | -0.085 | 46.9% | 0.83 | -0.209 |
| P3 1/3 S1 + 1/3 S2代理 + 1/3 结构 | -0.190 | -0.166 | 45.9% | 0.87 | -0.207 |
| P4_H5 / H8 / H10 | -0.239 / -0.246 / -0.253 | 全负 | 43-45% | 0.73-0.81 | 全负 |

结论：**P1（S1 全部退出）是唯一 median/win 相对稳定的规则。**
P2/P3 只小幅抬高 p90，却把 median 打负；P4 均值更差且回撤大。
S2：冻结策略只有事件标志 `S2_EXHAUSTED`，**没有 S2 价格目标**；
研究代理（S1+1R）显示等待 S2 无增量价值。

---

## 6. B1 vs B2 ALLOCATION（frozen canonical，10bp conservative）

| cohort | E[R] | median | win rate |
|---|---:|---:|---:|
| B1 | -0.383 | -1.05 | 34.1% |
| B2 standalone | -0.145 | +0.082 | 54.1% |
| B2 add-on（B1 后加仓） | -0.194 | -0.462 | 45.2% |

**NO EVIDENCE FOR B2 STANDALONE FULL-SIZE ENTRY。**
B2 只有“中位正、均值负”的弱结构；B1→B2 加仓子集比 standalone 更差，B2 应作为确认/持有依据，
不是加仓点。

---

## 7. POSITION SIZING（100k，fixed-principal sequential proxy）

- 12 种策略（250/500/750/1000 × cap 20/30/40%）**全部亏损**（conservative -103k~-369k）。
- B1-only @500/30%：-40.7k（连亏 13）；B2-only @500/30%：-156.3k（连亏 12）。
- 结论：**负期望信号全集上不存在“最优风险参数”；规模只线性放大亏损。**
- 因 EDGE GATING 无通过子集，position sizing promotion 停止。

---

## 8. CHRONOLOGICAL VALIDATION（conservative 10bp）

| cohort | DISCOVERY mean/med/win | VALIDATION mean/med/win | 2024→2025→2026 med |
|---|---:|---:|---:|
| B1 | -0.69 / -1.06 / 32% | -0.10 / -1.04 / 36% | -1.08 / -1.05 / -1.05 |
| B2_READY | -0.15 / +0.10 / 55% | -0.16 / +0.02 / 52% | +0.12 / +0.06 / +0.03 |
| B2_CONFIRMED | -0.12 / +0.11 / 55% | -0.15 / +0.03 / 52% | +0.16 / +0.11 / **-0.99** |

SUPPORTED：B1/B2 全量 mean 为负（两时段同方向）。
NOT SUPPORTED：任何“B2 正期望开仓/加仓”规则；B2 median 逐年衰减，2026 B2_CONFIRMED 已转负。

---

## 9. EDGE GATING（预定义 subgroup，无新阈值）

阈值仅使用 production 既有值：`entry_quality/setup_quality >= 80`（已研究）、
`minimum_risk_reward=1.50`、`near_s1_distance=0.02`、EntryRoom 既有分类。
anchor quality / data quality 因 episodes 侧数据覆盖不足标 **INSUFFICIENT_DATA**。

| cohort | subgroup | n_ep/n_res | mean/med/win | S1-first/inv-first | D/V mean | 2024/25/26 med | gate |
|---|---|---:|---:|---:|---:|---:|---|
| B1 | ALL | 747/733 | -0.383/-1.05/34% | 18%/78% | -0.69/-0.10 | 全负 | REJECT |
| B1 | entry_q≥80 | 130/129 | -0.010/-1.01/33% | 24%/72% | +0.05/-0.07 | 两负 | OBSERVE_ONLY |
| B1 | setup_q≥80 | 151/150 | -0.157/-1.05/31% | 24%/73% | -0.04/-0.26 | 全负 | REJECT |
| B1 | room=SUFFICIENT | 641/628 | -0.572/-1.05/33% | 16%/80% | -1.05/-0.11 | 全负 | REJECT |
| B1 | room=THIN | 106/105 | +0.746/-1.05/39% | 31%/66% | +1.73/-0.02 | 全负 | OBSERVE_ONLY |
| B1 | entry≥80 & setup≥80 | 130/129 | -0.010/-1.01/33% | 24%/72% | +0.05/-0.07 | 两负 | OBSERVE_ONLY |
| B1 | entry≥80 & setup≥80 & room=SUFF | 126/125 | +0.035/-1.01/33% | 25%/71% | +0.01/+0.06 | 全负 | OBSERVE_ONLY |
| B2_READY | ALL | 1627/1492 | -0.154/+0.07/53% | 51%/40% | -0.15/-0.16 | +0.12/+0.06/+0.03 | REJECT |
| B2_READY | entry_q≥80 | 67/53 | -0.382/-1.02/32% | 24%/60% | -0.12/-0.63 | 全负 | REJECT |
| B2_READY | room=THIN | 1035/994 | -0.123/+0.15/61% | 62%/32% | -0.06/-0.19 | +0.24/+0.16/+0.08 | REJECT |
| B2_READY | rr≥1.5 | 261/218 | -0.227/-1.02/29% | 21%/61% | -0.37/-0.10 | 全负 | REJECT |
| B2_READY | near_S1≤2% | 329/319 | -0.166/+0.08/67% | 71%/24% | -0.16/-0.17 | +0.08/+0.09/+0.06 | REJECT |
| B2_CONFIRMED | ALL | 637/553 | -0.136/+0.07/54% | 48%/40% | -0.12/-0.15 | +0.16/+0.11/-0.99 | REJECT |
| B2_CONFIRMED | setup_q≥80 | 134/119 | -0.069/+0.17/59% | 54%/37% | +0.06/-0.16 | +0.20/+0.11/+0.15 | OBSERVE_ONLY |
| B2_CONFIRMED | rr≥1.5 | 138/104 | -0.015/-1.02/34% | 24%/51% | -0.07/+0.04 | 全负 | OBSERVE_ONLY |
| B2_CONFIRMED | near_S1≤2% | 121/117 | -0.195/+0.08/70% | 71%/27% | -0.21/-0.18 | +0.04/+0.11/+0.04 | REJECT |

**SUPPORTED_SUBGROUPS = 无。NO_PROVEN_ENTRY_EDGE。**

最接近的 B1 `entry≥80 & setup≥80 & room=SUFFICIENT`：两时段 mean 均正（+0.01/+0.06），
但 median 三年全负（-0.45/-1.07/-0.49）、win 33% → 门禁失败。

---

## 10. CURRENT_5_MAPPING（均不属于 proven edge 类）

| code | stage | 所属 subgroup | 历史结论 |
|---|---|---|---|
| 603980 | B2_READY | entry_q 56<80；setup 74<80；room=THIN；rr 1.14<1.5；near_S1 4.3%>2% | 全部 REJECT |
| 600756 | B2_READY | entry_q 37；setup 65；room=THIN；rr 0.99；near_S1 2.9%>2% | 全部 REJECT；DATA_LIMITED |
| 603232 | B2_CONFIRMED | entry_q 32；setup 70；room=SUFFICIENT；rr 0.69；near_S1 7.6%>2% | 全部 REJECT |
| 601858 | B2_READY | entry_q 65；setup 65；room=SUFFICIENT；rr 1.81≥1.5；near_S1 5.4%>2% | rr≥1.5 历史为弱组（REJECT） |
| 603185 | B1_READY | entry_q 58；setup 71；room=SUFFICIENT；rr 1.23；near_S1 6.0%>2% | 全部 REJECT |

---

## 11. 10万元执行手册候选 v0.1（未通过 promotion，仅供研究参考）

- B1_ENTRY：仅 buy zone 内、entry_candidate=true；小仓/纸面；S1 全出。
- B2_ENTRY：**NO EVIDENCE FOR B2 STANDALONE FULL-SIZE ENTRY**。
- B2_ADD：不加仓（add-on 历史 median -0.46R）。
- RISK_PER_TRADE：证据不支持任何盈利档；如必须 250 RMB（0.25%），>500 无支持。
- MAX_POSITION：≤20%（20,000 RMB）。
- MAX_SIMULTANEOUS_POSITIONS：1（单仓顺序代理，无并发证据）。
- HARD_STOP：invalid；次日 open≤invalid 开盘走；盘中 low≤invalid 按 invalid 走。
- EARLY_FAILURE_EXIT：无（failed-breakout / time stop 均不改善）。
- TIME_STOP：无独立时间止损；仅 10 会话结构窗口。
- S1_TAKE_PROFIT：S1 全部退出（P1）。
- S2_TAKE_PROFIT：N/A（无冻结 S2 价格目标）。
- TRAILING_REMAINDER：不使用（P2/P3 更差）。
- EXPECTED_MAE（10d）：B1 中位 -6.3%；B2 中位 -7.4%。
- EXPECTED_MFE（10d）：B1 中位 +6.9%；B2 中位 +7.2%。
- MEDIAN_DAYS_TO_S1：B1=3；B2=1。
- MEDIAN_DAYS_TO_INVALID：B1=1；B2=3。

## 12. 十个问题简答

1. 单笔合理风险：历史证据下 0 或纸面；若必须 250 RMB。
2. 普通 B1 仓位：不构成常规开仓依据（E[R]=-0.38R）。
3. B2 是新开仓还是加仓：都不是 full-size；B2=确认/观察点。
4. T+1 无法卖的情形：fill-day stop、fill-day target order unknown、同日双触、跌停锁死（未建模）。
5. 次日最迟止损：open≤invalid 开盘走 / 盘中 low≤invalid 当日走，无“再看一天”。
6. 成功交易第几天最大收益：B2 赢家中位第 1 天触 S1；B1 第 3 天。
7. S1 全卖还是部分卖：全卖（P1）。
8. S2 是否值得等待：不值得（无冻结目标；代理无增量）。
9. 连亏降仓：历史最大连亏 14；启发式（未验证）：连亏 3 减半、连亏 5 停一周。
10. 当前 5 只配置：603980 B2 900 股（观察）；603185 B1 600 股（纸面）；
    601858 B2 200 股（等触发）；600756=0（DATA_LIMITED）；603232=0（NO_NEW_ENTRY）。

---

## 13. INSUFFICIENT_EVIDENCE 清单

- S2 价格止盈（冻结语义缺失）
- price-limit 执行（数据缺失）
- 并发多仓组合（仅单仓顺序代理）
- 最优风险档位（负期望下不存在）
- 时间止损（不改善）
- anchor quality / data quality 分组（episodes 侧覆盖不足）

---

## 14. 结论

**NO_PROVEN_ENTRY_EDGE → 停止 position sizing promotion → NEXT: IMPROVE_ENTRY_SELECTION。**

验证：compileall 通过、`git diff --check` 通过；src/tests 零改动；
`evaluate_strategy_calls=0`。
