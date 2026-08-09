# SECOND_LAUNCH_FACTOR_R8B_INTRADAY_ACCEPTANCE_RESULTS_V01

> R8B — Intraday Acceptance Execution V01（frozen ASL 5m lake）
> AS_OF: 2026-08-09 · research-only · DEVELOPMENT_REANALYSIS

```text
PREVIOUS_R8B_HEAD =
056cb2b4223284ed8ff7988b77cd3aba705a18c2

PREVIOUS_RESULTS_STATUS =
INVALIDATED_BY_UNSORTED_BAR_ORDER
```

STATUS: **COMPLETE（chronology fix 后干净重跑）**

```text
BRANCH: research/second-launch-factor-r8b-intraday-acceptance-v01
BASE_HEAD: d5daffbbaad46ec084bef24584ad7a4a656ad42c
HEAD_AFTER: 见 GIT 段（本修订：chronology fix commit）
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## ROOT_CAUSE

```text
frozen lake curated parquet 的 PHYSICAL ROW ORDER 非时间序：
  OUT_OF_ORDER_SYMBOL_DAY_N_BEFORE_CANONICALIZATION = 5,625 / 5,625（全部）
（物理顺序如 14:45, 09:45, 13:25, 09:35…）
旧实现依赖 parquet 物理行序做 touch 定位与 post-touch 窗口
  （iloc 切片）-> 所有 checkpoint/touch/D1 计算基于乱序 bars
  -> 旧 acceptance 结果无效。
```

## FIX

```text
consumer-side canonicalization（不改 dataset lock / 不重写 parquet）：
  loader（r8b_asl5m_dataset_readiness_v01.load_frozen_5m）按
  [symbol, trade_date, bar_time] 排序 + 每组 assert bar_time 严格递增/唯一
  feature_row 内再次 sort（防 shuffle 输入）+
  新增 post_activation_bar_n（diagnostic metadata）
  acceptance_stats 分母分离：SUCCESS/FAILED_ACTIVATED_N 与
  SUCCESS/FAILED_FEATURE_N（finite feature sample；AUC/mean/median 仅用
  finite sample）
```

## DATASET_INVARIANCE

```text
DATASET_LOCK_SHA = 3914887a…（不变；recompute == pin PASS）
TOTAL_RAW_ROWS = 270,000 / 40 partitions / 0 dup（不变）
ASL_CANDIDATE_SHA = 04bd949…（不变）；无 network、无 backfill
```

## CHRONOLOGY_QA

```text
OUT_OF_ORDER_SYMBOL_DAY_N_BEFORE_CANONICALIZATION = 5,625
FIRST_TOUCH_PREFIX_VIOLATION_N_AFTER_FIX = 0（146 episodes x 4 checkpoints）
TOUCH_AT_CHECKPOINT_N = {09:45: 0, 10:00: 0, 10:30: 0, 11:30: 0}
FEATURE_FINITE_N（breakout/vwap/retest）：09:45 75 / 10:00 89 / 10:30 106 /
  11:30 119；false_break_duration 146（no-post-bar -> 0，finite）
```

## DENOMINATOR_QA

```text
acceptance stats 现同时报告：
  SUCCESS_ACTIVATED_N / FAILED_ACTIVATED_N（activated 分母）
  SUCCESS_FEATURE_N / FAILED_FEATURE_N（finite feature 样本）
AUC / mean / median 只基于 finite feature sample；
SUCCESS_FEATURE_N + FAILED_FEATURE_N == AUC 实际 denominator；
touch-at-checkpoint（post_activation_bar_n=0）不计入连续 F7 AUC 有效样本。
```

## INPUT / DATASET_FREEZE

```text
S1 provenance PASS（146/146）；bar semantics RIGHT_LABELED_VERIFIED；
dataset lock sha 3914887a…（40 partitions / 270,000 rows / 0 dup）；
coverage：146/146 morning complete（SUCCESS 43 / FAILED 103）；
VWAP READY（amount/volume 单位实测通过）；D1 control 141 symbols
```

## CHECKPOINT_FEATURES

```text
146 episodes x 4 checkpoints = 584 rows（r8b_intraday_checkpoint_features_v01.csv）
字段：activated / activation_time / acceptance_eligible /
  post_activation_bar_n / F7-1..4 /
  dist_to_s1 / high_vs_s1 / vwap_distance / prev_close_state / open_gap /
  opening_drawdown / high_progression / cum_volume_relative_d1
```

## ACTIVATION_RESULTS（Layer A；denominator = 全 event cohort）

```text
checkpoint  SUCCESS_act%  FAILED_act%  rate_diff  OR      AUC
09:45       46.5         59.2         -12.7pp    0.599   0.436
10:00       55.8         68.9         -13.1pp    0.569   0.434
10:30       62.8         78.6         -15.9pp    0.458   0.421
11:30       72.1         85.4         -13.3pp    0.440   0.433
解读：FAILED_BREAKOUT 更容易/更早攻击 S1（activation 本身不区分
  acceptance，AUC < 0.5）；acceptance 质量在 activation 之后才显现。
  ACTIVATE != ACCEPT 在数据上成立。
```

## ACCEPTANCE_RESULTS（Layer B；denominator = activated & eligible）

```text
checkpoint  feature                S_ACT F_ACT S_FEAT F_FEAT  AUC     dir      rank-bis
09:45       breakout_hold_ratio    20    61    20     55      0.5455  POSITIVE  0.091
09:45       vwap_acceptance_ratio  20    61    20     55      0.5764  POSITIVE  0.153
09:45       retest_depth           20    61    20     55      0.5427  POSITIVE  0.086
09:45       false_break_duration   20    61    20     61      0.4844  NEGATIVE -0.031
10:00       breakout_hold_ratio    24    71    23     66      0.6482  POSITIVE  0.296
10:00       vwap_acceptance_ratio  24    71    23     66      0.6281  POSITIVE  0.256
10:00       retest_depth           24    71    23     66      0.6041  POSITIVE  0.208
10:00       false_break_duration   24    71    24     71      0.3961  NEGATIVE -0.208
10:30       breakout_hold_ratio    27    81    26     80      0.7108  POSITIVE  0.422
10:30       vwap_acceptance_ratio  27    81    26     80      0.5697  POSITIVE  0.139
10:30       retest_depth           27    81    26     80      0.6438  POSITIVE  0.288
10:30       false_break_duration   27    81    27     81      0.3169  NEGATIVE -0.366
11:30       breakout_hold_ratio    31    88    31     88      0.6893  POSITIVE  0.379
11:30       vwap_acceptance_ratio  31    88    31     88      0.5869  POSITIVE  0.174
11:30       retest_depth           31    88    31     88      0.6569  POSITIVE  0.314
11:30       false_break_duration   31    88    31     88      0.2980  NEGATIVE -0.404
```

## CHECKPOINT_SUMMARY

```text
F7-1 breakout_hold_ratio：AUC 随 checkpoint 上升（0.55 -> 0.71，10:30 峰
  0.7108）——activation 后持续收在 S1 上方是 acceptance 稳健信号
F7-2 vwap_acceptance_ratio：10:00 相对最强（0.6281）
F7-3 retest_depth：方向 POSITIVE（SUCCESS 回踩更浅/retest_depth 更接近 0；
  AUC 0.54 -> 0.66）——与 F7-1 故事一致
F7-4 false_break_duration：方向 NEGATIVE 且随 checkpoint 增强
  （SUCCESS 连续低于 S1 的 bar 更少；11:30 AUC 0.298 / rank-bis -0.404）
所有 checkpoint 完整报告，无 BEST_CHECKPOINT 选择；
样本均满足 SUCCESS>=20 / FAILED>=20（activated 与 feature N 均）
```

## OLD_VS_NEW（reconciliation；OLD_HEAD=056cb2b）

```text
activation rows：byte-identical（激活布尔量本身与行序无关，root cause 记录）
checkpoint feature rows：变化（584 rows 重算，内容变）
每 checkpoint x F7（old AUC -> new AUC，delta；direction；effective N）：
  09:45 bhr 0.5298 -> 0.5455 (+0.016)；vwr 0.6111 -> 0.5764 (-0.035)；
       rd 0.3644 -> 0.5427 (+0.178，方向 NEG->POS 反转)；fbd 0.5189 -> 0.4844
  10:00 bhr 0.5783 -> 0.6482 (+0.070)；vwr 0.6821 -> 0.6281 (-0.054)；
       rd 0.4602 -> 0.6041 (+0.144，NEG->POS 反转)；fbd 0.4918 -> 0.3961
  10:30 bhr 0.6541 -> 0.7108 (+0.057)；vwr 0.5738 -> 0.5697 (-0.004)；
       rd 0.4501 -> 0.6438 (+0.194，NEG->POS 反转)；fbd 0.3877 -> 0.3169
  11:30 bhr 0.6701 -> 0.6893 (+0.019)；vwr 0.5698 -> 0.5869 (+0.017)；
       rd 0.4619 -> 0.6569 (+0.195，NEG->POS 反转)；fbd 0.3829 -> 0.2980
effective N：现为 finite feature N（early checkpoints < activated N）
旧结论（含 11:30 bhr 0.6701、10:00 vwr 0.6821、retest NEGATIVE）全部视为
  INVALIDATED_BY_CHRONOLOGY_BUG；新结论只依据新 committed result。
```

## DEVELOPMENT_DATA_DISCLOSURE

```text
旧 intraday evidence（S1/VWAP/high progression/quiet volume/session low）
在开发期已被查看 -> DEVELOPMENT_REANALYSIS，非 clean holdout；
R8 结果最多 SUPPORTED_HYPOTHESIS；真正时间外验证在 R9 walk-forward。
```

## VALIDATION

```text
compile PASS；tests/test_r8b_intraday_acceptance_execution_v01.py 9 PASS
  （checkpoint PIT / touch anchor / NOT_YET_ACTIVATED / VWAP amount-volume /
  F7 formulas / rank-biserial / direction / OR zero-cell / 全流程确定性 local）
frozen lake 上两次运行哈希一致；无未来泄漏（bar_time <= checkpoint only）；
无 threshold scan；无 composite；raw bars 未提交。
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R8_STATUS_RECOMMENDATION / R9_RECOMMENDATION

```text
R8_STATUS_RECOMMENDATION = COMPLETE
R9_RECOMMENDATION = AUTHORIZED（walk-forward / time-out-of-sample；
  不代表 R8 feature VALIDATED；本任务未开始 R9）
```

## CONFIRM

```text
NETWORK_FETCH=true（scope=rootSunc/ashare-lake code clone + bounded TDX 5m）
ASL_ACTIVE_CHANGED=false
DATA_LAYER_PRODUCTION_CHANGED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```
