# SECOND_LAUNCH_FACTOR_R7A_MULTIVARIATE_CONTRACT_V01

> R7A — Multivariate Contract V01（contract + availability only）
> AS_OF: 2026-08-09 · research-only · R6B 已完成（alignment closeout PASS）

STATUS: **FROZEN（pre-registered；未执行任何模型）**

```text
BRANCH: research/second-launch-factor-r7a-multivariate-contract-v01
BASE_HEAD: 632390d4c34946d9964f9f34e269d4de5b1e6e6c
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## RESEARCH_QUESTION

```text
当 simple benchmark 与已确认的候选结构同时存在时，哪些因子仍保留独立
信息而非彼此重复？重点关注：
  B6 volume contraction + median_range_ratio（range contraction）
  以及 quiet_days_n 是否继续提供独立信息。
```

## MODEL_TYPE

```text
UNREGULARIZED LOGISTIC REGRESSION（descriptive multivariate attribution，
不是 ML）。禁止：RF / XGBoost / LightGBM / NN / lasso / ridge tuning /
elastic net / stepwise / automated feature selection / hyperparameter
optimization。
```

## SAMPLE_CONTRACT

```text
B4/B5/B6/B7 common_eligible == true（frozen R5 common universe）
AND 模型所需全部连续因子非 missing
AND outcome known（PRIMARY outcome_3d；SENSITIVITY outcome_5d；UNKNOWN 排除）
所有 nested model comparison 使用相同 complete-case sample ——
不同模型不得因 missing 导致 denominator 不同后直接比较 AUC。
```

## MODEL_LADDER（冻结；R7A 不执行）

```text
M0  SIMPLE_BENCHMARK       B4+B5+B6+B7（R5 frozen binary signals）—— baseline
M1  RANGE_INCREMENT        M0 + median_range_ratio —— PRIMARY candidate
M2  RANGE_QUIET            M1 + quiet_days_n
M3  FULL_F3_DIAGNOSTIC     M0 + pvr + mvr + mrr + quiet —— DIAGNOSTIC ONLY
                              （确认 pvr/mvr 多变量冗余；不得用于 model selection）
M4A ROBUSTNESS_CONTROL     M2 + high_vs_pullback_high（F6 单独）
M4B ROBUSTNESS_CONTROL     M2 + close_vs_pullback_high（F6 单独）
禁止 M4A/M4B 同时加入两个 F6；F6 结果不得覆盖 R4（UNSTABLE / TIME_DEPENDENT）。
```

## NO_INTERACTIONS_V01

```text
禁止 B6 x median_range_ratio、B6 x quiet、factor x factor、polynomial、
splines；先回答独立 additive information；interaction 留待明确授权。
```

## CONTINUOUS_FACTOR_HANDLING

```text
mrr / pvr / mvr 保留原连续值；quiet_days_n 作为连续整数；
禁止 cutoff search / binning optimization / winsor tuning /
看结果后 log transform；非有限值 -> complete-case exclude + 报告 missing N。
```

## DIRECTION_CONTRACT（R3 frozen；仅用于 consistency interpretation）

```text
median_range_ratio = NEGATIVE
pullback_volume_ratio = NEGATIVE
min_volume_ratio = NEGATIVE
quiet_days_n = POSITIVE
high_vs_pullback_high = POSITIVE
close_vs_pullback_high = POSITIVE
禁止自动乘 -1 / 按 coefficient flip feature / 看结果后重定义方向。
```

## MODEL_OUTPUT_METRICS（R7B）

```text
每个模型：N / SUCCESS_N / NON_SUCCESS_N / AUC / LogLoss / Brier / AIC / BIC
nested：Delta AUC / Delta LogLoss / Delta Brier（相对 M0）+ 逐级
  M1 vs M0、M2 vs M1、M3 vs M2
不得选择表现最好模型后隐藏其他模型。
```

## COEFFICIENT_OUTPUT / CLUSTER_SE

```text
每个 predictor：coefficient / sign / expected_direction / direction_match /
odds_ratio / 95% CI；优先 cluster-robust SE by symbol；
当前轻量依赖无法可靠实现 -> CLUSTER_SE_IMPLEMENTATION = UNRESOLVED
（R7B 前再决定；不自行写未经验证的 sandwich estimator）。
```

## MULTICOLLINEARITY_DIAGNOSTIC

```text
只报告（pairwise correlation / condition number；优先复用 R3B correlation
artifact）；禁止看到高 correlation 自动删除 predictor；
删除规则必须在执行前另行冻结。
```

## PRIMARY_SUCCESS_CRITERIA（冻结于看结果前）

```text
RANGE_INDEPENDENT_SUPPORTED：
  median_range_ratio 在 M1 的 coefficient direction == NEGATIVE
  AND M1 AUC > M0 AUC AND M1 LogLoss < M0 LogLoss AND M1 Brier <= M0 Brier
  AND 5D coefficient direction 不反转
  否则 RANGE_INDEPENDENT_NOT_SUPPORTED（反向或整体无增量/恶化）

QUIET_INCREMENTAL_SUPPORTED（M2 vs M1）：
  quiet coefficient POSITIVE
  AND AUC / LogLoss / Brier 至少两项改善
  AND 5D direction 不反转
  否则 QUIET_INCREMENTAL_NOT_SUPPORTED
不自行发明显著性阈值；不得结果后修改规则。
```

## M3_INTERPRETATION

```text
pvr / mvr 只回答：在 B6 + range + quiet 已存在时 volume-ratio factors
是否还有明显独立贡献；不得用于新的 model selection；
coefficient near zero / direction unstable 与 R6 redundancy 观察相符。
```

## R8_R9_BOUNDARY

```text
R7 = multivariate attribution；不是 intraday acceptance（R8）也不是
walk-forward（R9）；R7 禁止 random train/test split。
```

## OUTCOME_BLINDNESS_CONFIRM

```text
R7A 未计算 model coefficients / AUC / LogLoss / Brier / model ranking；
outcome artifact 仅 SHA pin（未 read_csv）。
```

## R7A_REGISTRY

```text
research/second_launch/factors_v01/r7a_multivariate_model_registry_v01.csv
6 行（M0/M1/M2/M3/M4A/M4B）；确定性生成（r7a_multivariate_contract_v01.py）
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R7B_RECOMMENDATION

```text
AUTHORIZED（contract frozen / sample contract deterministic / model set
frozen / metric set frozen / success criteria frozen / 无 outcome
contamination / CORRECTNESS_BLOCKER=NO；本任务未开始 R7B）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
ASL_SYNC_IMPLEMENTATION=false
DATA_LAYER_CHANGED=false
```
