# SECOND_LAUNCH_FACTOR_R3A1_STATISTICAL_CORRECTION_REPORT

> R3A.1 — Mann-Whitney tie 校正 + BH-FDR 复核 + 报告计数/解释修正
> 未改 frozen feature/outcome dataset；未做 multivariate/ML/score 优化；未启动 R3B

STATUS: **COMPLETE** — ties 校正实现并验证；结果重算；解释修正（无 correctness blocker）

BRANCH: `research/second-launch-factor-r3a-univariate-v01`
HEAD_BEFORE: `6baf418d6030a08cf561f96a05e3e78cbeae5d4c`
HEAD_AFTER: 见 GIT 段

## INPUT_SHA_VERIFY

```text
FEATURE_SHA: a485a484…（与 R3A 原版完全一致）／OUTCOME_SHA: 01a9f2fa…（一致）
FEATURE_ROW_N / OUTCOME_ROW_N: 8,682 / 8,682
```

## JOIN_QA

```text
JOIN_ROWS: 8,682（episode_id 1:1；身份列一致；snapshot binding 一致）
PREDICTOR_UNIVERSE: 24 PRIMARY；#11 仅 identity QA
```

## TIE_CORRECTION

```text
公式（生产实现）:
  Var(U) = n1*n0/12 * (N + 1 - Σ(t³ - t) / (N*(N-1)))
  （pooled tie-group sizes t；average ranks 不变；two-sided；AUC 方向不翻转）
全相等值: variance=0 → U == null expectation 时 p=1.0；否则 RuntimeError FAIL CLOSED
  （无 epsilon hack）
```

## REFERENCE_VALIDATION

```text
独立 oracle（test）: rank 方差恒等式 Var(U) = n1*n0*Σ(r-r̄)²/(N(N-1))
  —— 与生产公式在 no-tie 与 heavy-tie 样本上 1e-9/1e-12 内一致
精确置换参考（n=10，252 置换）: 作为 loose sanity（渐近 vs 精确在小样本有 ~0.07 差距，
  容差 0.15，非正确性 oracle）
scipy: 环境未安装；按要求未引入 production dependency（tests 亦未依赖）
```

## TARGETED_TESTS

```text
A. no-tie synthetic（与独立 reference + 手算一致）: PASS
B. heavy-tie（与 identity oracle 1e-9 一致 + 置换 sanity）: PASS
C. all-equal values（AUC=0.5, p=1.0）: PASS
D. direction（AUC<0.5 不翻转）: PASS
E. BH-FDR 固定 p-vector（q 值精确 + 单调 + ≤1）: PASS
合计 5/5 passed
```

## P_VALUE_CHANGED_N

```text
19（24 中 19 个 p 变化；5 个无 ties 的 factor 不变）
max |Δp| = 0.2539（t0_close_location）
```

## Q_VALUE_CHANGED_N

```text
21（BH-FDR 随 p 更新）
```

## CLASSIFICATION_CHANGED_N

```text
0（PROMISING 6 / UNSTABLE 14 / NO_SIGNAL 2 / DATA_LIMITED 2 全部不变）
```

## PROMISING_SET_BEFORE

```text
close_vs_pullback_high / high_vs_pullback_high / median_range_ratio /
min_volume_ratio / pullback_volume_ratio / quiet_days_n
```

## PROMISING_SET_AFTER

```text
（与 before 完全一致）
close_vs_pullback_high / high_vs_pullback_high / median_range_ratio /
min_volume_ratio / pullback_volume_ratio / quiet_days_n
```

## HIGH_TIE_FACTORS old/new p/q

```text
quiet_days_n:      p 3.61e-08 -> 2.04e-10 | q 3.28e-07 -> 4.90e-09 | PROMISING
days_since_t0:     p 1.11e-01 -> 7.71e-02 | q 2.16e-01 -> 1.54e-01 | UNSTABLE
days_to_pullback_low: p 6.08e-02 -> 3.38e-02 | q 1.46e-01 -> 8.12e-02 | UNSTABLE
days_above_t0_mid: p 1.02e-01 -> 6.70e-02 | q 2.16e-01 -> 1.46e-01 | UNSTABLE
pullback_duration: p 4.79e-01 -> 2.46e-01 | q 6.77e-01 -> 3.93e-01 | NO_SIGNAL
t0_close_location: p 9.58e-01 -> 7.04e-01 | q 9.58e-01 -> 8.21e-01 | NO_SIGNAL
```

## DIRECTION_CONSISTENT_N

```text
20（程序化统计，非手写）
```

## DIRECTION_INCONSISTENT_N

```text
4
```

## DIRECTION_INCONSISTENT_FACTORS

```text
t0_range_pct / pullback_depth_close / t0_gain_retention / range_slope
（R3A 报告手写 “22/24（3 个不一致）” 有误：真实为 20/24、4 个不一致，已按程序化结果修正）
```

## PROMISING_BY_FAMILY

```text
F1（ATTACK/PRE/VOLUME）: （无）
F2（HOLD）: （无）
F3（CONTRACTION）: pullback_volume_ratio / min_volume_ratio / median_range_ratio / quiet_days_n（4）
F5（TIME）: （无）
F6（ACTIVATION）: close_vs_pullback_high / high_vs_pullback_high（2）
```

研究解释（不再使用 “与家族假设一致” 措辞）：

```text
F3 CONTRACTION：当前主要支持（量/振幅收缩 → SUCCESS，4 个 PROMISING 均负向 AUC 且 3 个 STABLE）
F6 ACTIVATION：有区分能力（2 个 PROMISING，MIXED 稳定性）
F2 HOLD：当前 simple univariate operationalization 未获明显支持（0 个 PROMISING）
F1 / F5：无支持
```

## FAILURE_CLASS_INTERPRETATION（保留，数值为重新计算值）

```text
close_vs_pullback_high:
  SUCCESS vs FAILED_BREAKOUT ≈ 0.51（0.5088）
  SUCCESS vs NO_LAUNCH ≈ 0.60（0.5978）
  SUCCESS vs STRUCTURE_FAIL ≈ 0.60（0.5999）
研究含义：DAILY ACTIVATION distinguishes launch/no-launch better than successful
acceptance；F7 acceptance remains unresolved（未验证 F7）
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R3B_RECOMMENDATION

```text
AUTHORIZED
```

（仅统计正确性门通过；本任务未启动 R3B。）

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

- `research/second_launch/factors_v01/r3a_univariate_screen_v01.py`（M：auc_pvalue ties 校正）
- `research/second_launch/factors_v01/r3a_univariate_factor_results.csv`（重新生成；AUC 列 0 变化，p/q 更新）
- `tests/test_r3a_univariate_screen_v01.py`（新增，5 tests）
- `research/reports/SECOND_LAUNCH_FACTOR_R3A1_STATISTICAL_CORRECTION_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: correct mann whitney ties and r3a reporting
PUSH: origin/research/second-launch-factor-r3a-univariate-v01
```

---

## VALIDATION NOTES

- 特征/outcome SHA 与 R3A 原版完全一致（未触碰 frozen dataset）
- AUC 列 0 变化（仅推断 p/q 更新）；classification 0 变化
- 全部计数程序化统计；无手工汇总；无新研究（无 TIME 非线性/阈值/相关性/多元/ML）
