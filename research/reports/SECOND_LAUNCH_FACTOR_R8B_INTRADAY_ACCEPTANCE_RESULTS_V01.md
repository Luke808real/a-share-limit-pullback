# SECOND_LAUNCH_FACTOR_R8B_INTRADAY_ACCEPTANCE_RESULTS_V01

> R8B — Intraday Acceptance Execution V01（frozen ASL 5m lake）
> AS_OF: 2026-08-09 · research-only · DEVELOPMENT_REANALYSIS

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r8b-intraday-acceptance-v01
BASE_HEAD: d5daffbbaad46ec084bef24584ad7a4a656ad42c
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
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
字段：activated / activation_time / acceptance_eligible / F7-1..4 /
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
checkpoint  feature                SUCCESS_N FAILED_N  AUC     dir      rank-bis
09:45       breakout_hold_ratio    20        61        0.5298  POSITIVE  0.060
09:45       vwap_acceptance_ratio  20        61        0.6111  POSITIVE  0.222
09:45       retest_depth           20        61        0.3644  NEGATIVE -0.271
09:45       false_break_duration   20        61        0.5189  POSITIVE  0.038
10:00       breakout_hold_ratio    24        71        0.5783  POSITIVE  0.157
10:00       vwap_acceptance_ratio  24        71        0.6821  POSITIVE  0.364
10:00       retest_depth           24        71        0.4602  NEGATIVE -0.080
10:00       false_break_duration   24        71        0.4918  NEGATIVE -0.016
10:30       breakout_hold_ratio    27        81        0.6541  POSITIVE  0.308
10:30       vwap_acceptance_ratio  27        81        0.5738  POSITIVE  0.148
10:30       retest_depth           27        81        0.4501  NEGATIVE -0.100
10:30       false_break_duration   27        81        0.3877  NEGATIVE -0.225
11:30       breakout_hold_ratio    31        88        0.6701  POSITIVE  0.340
11:30       vwap_acceptance_ratio  31        88        0.5698  POSITIVE  0.140
11:30       retest_depth           31        88        0.4619  NEGATIVE -0.076
11:30       false_break_duration   31        88        0.3829  NEGATIVE -0.234
```

## CHECKPOINT_SUMMARY

```text
F7-1 breakout_hold_ratio：AUC 随 checkpoint 单调上升（0.53 -> 0.67）——
  activation 后持续收在 S1 上方是 acceptance 的稳健信号（10:30/11:30 最强）
F7-2 vwap_acceptance_ratio：10:00 最强（0.68）——早盘收复 VWAP 后站住
F7-3 retest_depth：方向稳定 NEGATIVE（SUCCESS 回踩更浅；AUC 0.36-0.46）
F7-4 false_break_duration：方向不稳定（弱）
所有 checkpoint 完整报告，无 BEST_CHECKPOINT 选择；
样本均满足 SUCCESS>=20 / FAILED>=20
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
