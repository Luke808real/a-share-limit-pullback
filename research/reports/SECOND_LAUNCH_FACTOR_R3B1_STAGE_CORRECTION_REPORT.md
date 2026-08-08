# SECOND_LAUNCH_FACTOR_R3B1_STAGE_CORRECTION_REPORT

> R3B.1 — correctness + stage-boundary patch（F5 连续 tail、F3×F6 语义、阶段重标）
> 未新增研究；未进入 R4/R6/Logistic/ML/backtest

STATUS: **COMPLETE** — F5 桶序修复 + 语义/阶段修正（无 correctness blocker）

BRANCH: `research/second-launch-factor-r3b-structure-v01`
HEAD_BEFORE: `aa00427f3df36448b59f264b608cd32bba52fce5`
HEAD_AFTER: 见 GIT 段

## INPUT_GATE

```text
FEATURE_SHA: a485a484… / OUTCOME_SHA: 01a9f2fa… / 8,682 / 1:1 / binding: PASS
```

## F5_BUCKET_ORDER_FIX

```text
实现：contiguous_time_buckets()（可测试纯函数）—— 自最小整数值顺序扫描；
  首次单值 n<30 的 K 起，全部值合并为单一连续 TAIL>=K；<K 保持自然单值桶
修复前: 1,2,3,4,5,7,tail(6,8,...)（非连续，T+7 在含 T+6 的 tail 之前）
修复后: 1/2/3/4/5/TAIL>=6（days_since_t0 与 days_to_pullback_low）；
        1/2/3/4/TAIL>=5（pullback_duration）
raw per-value 保留: section=F5_TIME_RAW（59 行，仅审计，不参与 shape）
shape 分类只使用有序连续桶；未调整阈值
```

## F5_SHAPE_BEFORE

```text
days_since_t0: INVERTED_U（旧非连续桶序，标签不可信）
days_to_pullback_low: INVERTED_U（同上）
pullback_duration: INVERTED_U（同上）
```

## F5_SHAPE_AFTER

```text
（有序连续桶，规则化标签）
days_since_t0: 0.0427/0.0538/0.0405/0.0560/0.0952(n=42)/TAIL>=6 0.0395 → INVERTED_U
days_to_pullback_low: 0.0418/0.0561/0.0407/0.0137/0.1000(n=40)/TAIL>=6 0.0411 → INVERTED_U
pullback_duration: 0.0460/0.0583/0.0246/0.1000(n=30)/TAIL>=5 0.0439 → INVERTED_U
解读不变：峰值桶 n 很小（42/40/30），属小样本噪声；无稳健 inverted-U/decay 证据；
  H4 未获支持（结论未因桶序修复改变）
```

## F3_F6_SEMANTIC_FIX

```text
median_range_ratio raw LOW → HIGH = contraction STRONG → WEAK
（数值未改：0.0770 → 0.0622 → 0.0451 是 activation-HIGH 行内 raw LOW→HIGH）
正确解释：stronger contraction is associated with higher SUCCESS rate
  within activation-HIGH rows
禁止再写 “contraction LOW → HIGH = 0.077 → 0.062 → 0.045”
```

## R3_EVIDENCE

```text
- F3 dose-response（单调收缩剂量）
- F5 nonlinear TIME shape（无稳健形状；H4 未获支持）
- F6 failure boundary（activation 区分 launch/no-launch，不区分 acceptance）
```

## EARLY_R4_SANITY_ONLY

```text
- calendar-quarter check（quiet 9/9、close 8/9 方向）
不得称 R4 stability completed
```

## EARLY_R6_EXPLORATORY_ONLY

```text
- F3 redundancy/correlation
- representative-F3 selection
- F3×F6 crosstab
不得称 R6 completed
```

## MFE_STATUS

```text
NOT_AVAILABLE_IN_CURRENT_FROZEN_OUTCOME（未读取 future bars；未修改 outcome artifact）
```

## MAE_STATUS

```text
NOT_AVAILABLE_IN_CURRENT_FROZEN_OUTCOME
```

## DAYS_TO_LAUNCH_STATUS

```text
TIME_TO_S1_10D = AVAILABLE
TIME_TO_INVALID_10D = AVAILABLE
DAYS_TO_LAUNCH_FORMAL_ANALYSIS = NOT_YET_CONTRACTED
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R3_STATUS

```text
COMPLETE（F5 ordering regression tests PASS 且无 blocker）
```

## R4_RECOMMENDATION

```text
AUTHORIZED
```

（下一正式阶段恢复为 R4 STABILITY；本任务未启动 R4。）

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

- `research/second_launch/factors_v01/r3b_factor_structure_v01.py`（M：contiguous tail 语义 + raw 审计）
- `research/second_launch/factors_v01/r3b_factor_structure_results.csv`（重新生成：F5 连续桶 + F5_TIME_RAW）
- `research/reports/SECOND_LAUNCH_FACTOR_R3B_STRUCTURE_DIAGNOSTICS_REPORT.md`（M：语义/阶段/metric gap 措辞）
- `tests/test_r3b_bucket_order_v01.py`（新增，5 tests）
- `research/reports/SECOND_LAUNCH_FACTOR_R3B1_STAGE_CORRECTION_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: fix r3b stage boundary and f5 bucket order
PUSH: origin/research/second-launch-factor-r3b-structure-v01
```

---

## VALIDATION NOTES

- 生产 p-value / AUC / factor results 未改动；仅 F5 桶构造与报告措辞
- 测试：test_r3b_bucket_order_v01.py（5）+ test_r3a_univariate_screen_v01.py（6）= 11 PASS
- 未新增研究；未进入 R4/R6/Logistic/ML/backtest
