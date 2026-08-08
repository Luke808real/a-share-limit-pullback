# SECOND_LAUNCH_FACTOR_R6A_INCREMENTAL_VALUE_CONTRACT_V01

> R6A — Incremental Value Contract V01（contract + availability only）
> AS_OF: 2026-08-09 · research-only · R5 已完成（R5_STATUS=COMPLETE）

STATUS: **FROZEN（pre-registered；未执行任何 incremental outcome metric）**

```text
R6A actual source branch:
research/second-launch-factor-r5b-benchmark-execution-v01
R6A contract commit:
42bfb924191e75c2ba5d14cd098e821a472f3f87
final audited source head:
7e046c7ba14c8822ad042a2915e3ed4cf16df132
BASE_HEAD: ec3de4d265c5e9d191ab1845db92dfa370c0c665
（注：R6A contract 冻结于 R5B branch lineage，非独立 branch；
  此处如实记录真实 GitHub lineage）
```

## INPUT_GATE

```text
FEATURE_SHA: a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8
R5B SIGNALS SHA: ee1c132bf8baa9d479eb0fd01592fe0a44d4851503353986620fc978720995c8
  （r5b_benchmark_episode_signals_v01.csv，commit ec3de4d）
R3 direction 源：r3a_univariate_factor_results.csv（frozen）
R4 status 源：r4_stability_verdicts_3d.csv（frozen）
运行期自验证 pin，任一 drift -> FAIL CLOSED
```

## R5_FINAL_BINDING

```text
R5 统计 artifact（episode_signals / failure_profile / results_3d / results_5d）
在 R5 close commit 后字节不变；R5_STATUS=COMPLETE；CORRECTNESS_BLOCKER=NO
```

## BASELINE_SET（冻结；R5 后阶段选择，非事前 selection）

```text
PRIMARY_BASELINE:     B6 FIXED_VOLUME_CONTRACTION（R5 3D/5D 最强简单基线）
SECONDARY_BASELINE:   B4 FIXED_PULLBACK_TIME
WEAK_CONTROL_BASELINE: B5 FIXED_PULLBACK_DEPTH
WEAK_CONTROL_BASELINE: B7 POST_LIMIT_NEW_HIGH_PROXY
不得重新优化 B4-B7 threshold；不得只报告最好的一只
```

## FACTOR_SET（冻结）

```text
PRIMARY_INCREMENTAL_CANDIDATE（F3 CONTRACTION x4）：
  pullback_volume_ratio  R3 NEGATIVE  R4 OVERALL DATA_LIMITED
  min_volume_ratio       R3 NEGATIVE  R4 OVERALL DATA_LIMITED
  median_range_ratio     R3 NEGATIVE  R4 OVERALL DATA_LIMITED
  quiet_days_n           R3 POSITIVE  R4 OVERALL DATA_LIMITED
ROBUSTNESS_CONTROL（F6 x2）：
  high_vs_pullback_high  R3 POSITIVE  R4 OVERALL UNSTABLE
  close_vs_pullback_high R3 POSITIVE  R4 OVERALL TIME_DEPENDENT
（R4 OVERALL DATA_LIMITED = 维度覆盖受限，非不稳定；
  方向一律来自 R3 frozen artifact，不凭常识硬编码、不翻转）
```

## PRIMARY_INCREMENTAL_METHOD

```text
CONDITIONAL RESIDUAL DISCRIMINATION（非 R7 multivariate）：
  对每个 baseline x factor，在 baseline SIGNAL group 内：
    benchmark eligible AND signal == true AND factor nonmissing AND
    outcome known
  计算连续 factor 对 SUCCESS vs KNOWN_NON_SUCCESS 的：
    native AUC / direction / effect=|AUC-0.5| / N / SUCCESS N
  核心问题：episode 已满足 benchmark 后，factor 是否仍能继续区分。
```

## SECONDARY_CHECK

```text
同一 factor 在 baseline NON-SIGNAL group 计算相同 conditional AUC，
判断信息是否只在 benchmark passers 或两边一般性存在；
secondary 结果不得修改 PRIMARY contract。
```

## DIRECTION_CONTRACT

```text
factor direction 必须来自 R3 frozen global direction（上述 pin）；
R6B 不得看到 AUC<0.5 后自动 flip；
允许报告 native_auc / direction_match / effect=|AUC-0.5|。
```

## MATERIAL_EFFECT_CONTRACT

```text
复用 R4 frozen threshold：
  MATERIAL_EFFECT = 0.03
  来源：SECOND_LAUNCH_FACTOR_R4_STABILITY_CONTRACT_V01.md section 5
  （r4_stability_v01.py MATERIAL_EFFECT = 0.03）
不新增另一套 effect threshold。
```

## INCREMENTAL_CLASSIFICATION_CONTRACT（R6B 用，本轮不执行）

```text
INCREMENTAL_SUPPORTED: 条件 signal-group AUC 方向匹配 R3 方向 AND
  |AUC-0.5| >= 0.03 AND 3D/5D 方向一致
INCREMENTAL_WEAK: 方向匹配但 effect < 0.03
NO_INCREMENTAL_VALUE: near-neutral 或反向
DATA_LIMITED: 样本不足 / constant / missing
不得根据结果修改
```

## SAMPLE_CONTRACT

```text
优先使用 R5B frozen episode-signal artifact（SHA ee1c13…）；
R6B 必须同时报告 OWN_BASELINE_SAMPLE 与 COMMON_COMPARABLE_SAMPLE；
PRIMARY 对比优先 common comparable sample（避免 baseline coverage 差异
 造成假增量）；data-ineligible 不得当作 non-signal。
```

## PIT_CONTRACT

```text
AS_OF = candidate_date D；factor 与 benchmark 信号均只用 <=D 信息；
同 R5A/R5B frozen PIT 语义；无 future 数据。
```

## OUTCOME_BLINDNESS_CONFIRM

```text
R6A 未计算 conditional AUC / success rates / factor subgroup /
incremental classification；outcome artifact 仅 SHA/schema/identity 门禁
（本模块不读取 outcome 文件；回归测试守卫）。
```

## R6A_REGISTRY

```text
research/second_launch/factors_v01/r6a_incremental_registry_v01.csv
24 行 = 4 baselines x (4 F3 + 2 F6)；确定性生成（r6a_incremental_contract_v01.py）
```

## UNDERDEFINED / DATA_LIMITED / UNRESOLVED

```text
UNRESOLVED：MFE/MAE/days_to_launch companion outcome artifact（沿用 R5B）；
  B1/B2/B3 传统形态机械定义（UNDERDEFINED，R5A 状态）；B8 板块过滤。
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R6B_RECOMMENDATION

```text
AUTHORIZED（无 blocker；本任务未开始 R6B）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```
