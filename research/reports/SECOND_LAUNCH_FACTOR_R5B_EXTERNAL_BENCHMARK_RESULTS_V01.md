# SECOND_LAUNCH_FACTOR_R5B_EXTERNAL_BENCHMARK_RESULTS_V01

> R5B — External Benchmark Execution V01（frozen 8,682 cohort，B4-B7）
> AS_OF: 2026-08-09 · research-only · 严格复用 R5A frozen contract

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r5b-benchmark-execution-v01
BASE_HEAD: cb5b9eaba18e3d5f1a98209cb7c8ae2cd7de373d
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## INPUT_GATE

```text
FEATURE_SHA a485a484… / OUTCOME_SHA 01a9f2fa… / CANONICAL e7243dee… /
8,682 / episode 1:1 / anchor/candidate/symbol binding /
feature_snapshot_id binding: PASS（R5B 允许读取 frozen outcome label）
```

## REGISTRY_GATE

```text
执行集 = 精确 {B4, B5, B6, B7}（registry status 全 READY）
B1/B2/B3 = NOT_EXECUTED_UNDERDEFINED
B8 = NOT_EXECUTED_UNDERDEFINED_DATA_UNAVAILABLE
registry 未修改
```

## METRIC_AVAILABILITY

```text
outcome_3d / outcome_5d / 五类 label（SUCCESS/FAILED_BREAKOUT/NO_LAUNCH/
  STRUCTURE_FAIL/UNKNOWN）: READY（frozen outcome schema 确认）
MFE   = DATA_UNAVAILABLE（无合格 frozen companion artifact；
  episodes.parquet mfe_pct 有已知 provenance defect 且非 1:1；重建 future-path
  metric 被禁止 —— 与 R3B.1 记录一致）
MAE   = DATA_UNAVAILABLE（同上）
days_to_launch = DATA_UNAVAILABLE（未契约化）
缺失 metric 不阻塞核心 benchmark execution
```

## EPISODE_SIGNAL_QA

```text
8,682 行 / episode_id 唯一；signals artifact 仅含 episode 身份 + B4-B7
  eligible/signal/missing + common_eligible（无 F3/F6 列）
B4 缺失 0；B5 缺失 61（CA_T0 45 + CA_D 16）；B6 61（B5 不可用 61）；
B7 缺失 0；common_eligible = 8,621
```

## OWN_ELIGIBLE_RESULTS_3D（SUCCESS vs KNOWN_NON_SUCCESS；UNKNOWN 排除）

```text
benchmark    elig known signal  sig%   non%   sig_n  non_n  OR(95%CI)          AUC      cells(s/n, s/n)
B4 TIME      8682 8471   4363   0.0529 0.0426  231    175    1.256(1.027-1.537) 0.5283  231/4132,175/3933
B5 DEPTH     8621 8411   6303   0.0482 0.0455  304    96     1.062(0.840-1.343) 0.5056  304/5999,96/2012
B6 VOLUME    8621 8411   2448   0.0645 0.0406  158    242    1.631(1.327-2.005) 0.5546  158/2290,242/5721
B7 NEW_HIGH  8682 8471    672   0.0551 0.0473   37    369    1.173(0.829-1.661) 0.5062   37/635,369/7430
零细胞 correction：未触发（全部 cell > 0）
```

## COMMON_SAMPLE_RESULTS_3D（B4∧B5∧B6∧B7 eligible ∧ known = 8,411）

```text
benchmark    signal_n  sig%    non%    OR(95%CI)          AUC
B4 TIME      4327      0.0527  0.0421  1.265(1.033-1.549) 0.5292
B5 DEPTH     6303      0.0482  0.0455  1.062(0.840-1.343) 0.5056
B6 VOLUME    2448      0.0645  0.0406  1.631(1.327-2.005) 0.5546
B7 NEW_HIGH   666      0.0541  0.0470  1.159(0.815-1.648) 0.5057
（B5/B6 的 own == common：其 own eligible 集恰为四者交集）
```

## FAILURE_PROFILE_3D（signal group）

```text
benchmark  group_n  SUCCESS  FB      NL      SF
B4 TIME    4363     0.0529   0.1022  0.2120  0.6328
B5 DEPTH   6303     0.0482   0.1239  0.1893  0.6386
B6 VOLUME  2448     0.0645   0.0976  0.2610  0.5768
B7 NEW_HIGH 672     0.0551   0.0997  0.1503  0.6949
UNKNOWN 单独报告：OWN 3D 211 / COMMON 210（不进 rate 分母）
共性：失败主要由 STRUCTURE_FAIL 主导（57.7%-69.5%）；
B6 信号组 SF 最低、SUCCESS 最高
```

## SENSITIVITY_5D（同一信号，仅 3D→5D）

```text
benchmark  sig%    non%    OR(95%CI)          AUC      3D vs 5D
B4 TIME    0.0624  0.0509  1.240(1.030-1.493) 0.5267   SAME(POSITIVE)
B5 DEPTH   0.0565  0.0565  1.001(0.809-1.240) 0.5001   SAME(POSITIVE)
B6 VOLUME  0.0769  0.0482  1.646(1.361-1.991) 0.5555   SAME(POSITIVE)
B7 NEW_HIGH 0.0625 0.0563  1.117(0.806-1.549) 0.5042   SAME(POSITIVE)
描述性，不自动建规则
```

（B5 5D raw：signal = 356/6,298 = 5.652588%，non-signal = 119/2,108 =
5.645161%，delta ≈ +0.00743pp；formal classification 按 raw rate 判定
POSITIVE，见 R5B_CLASSIFICATION_PRECISION_PATCH）

## MFE_MAE_DAYS_TO_LAUNCH

```text
MFE = DATA_UNAVAILABLE（原因见 METRIC_AVAILABILITY）
MAE = DATA_UNAVAILABLE
days_to_launch = DATA_UNAVAILABLE
不阻塞核心结果
```

## BENCHMARK_CLASSIFICATION（预注册规则；3D primary + 5D sensitivity）

```text
B4 FIXED_PULLBACK_TIME:    3D POSITIVE_BENCHMARK / 5D POSITIVE_BENCHMARK
B5 FIXED_PULLBACK_DEPTH:   3D POSITIVE_BENCHMARK（弱）/ 5D POSITIVE_BENCHMARK
B6 FIXED_VOLUME_CONTRACTION: 3D POSITIVE_BENCHMARK / 5D POSITIVE_BENCHMARK
B7 POST_LIMIT_NEW_HIGH_PROXY: 3D POSITIVE_BENCHMARK（弱）/ 5D POSITIVE_BENCHMARK
说明：B5/B7 的 OR 95% CI 包含 1、AUC 接近 0.5 —— 区分能力弱；
  分类规则为预注册机械规则（raw rate> & OR>1 & AUC>0.5），不因弱而改写；
  B5 5D 为 formal-sign-rule 下的 near-neutral positive，无实际预测价值
```

## B4_RESULT / B5_RESULT / B6_RESULT / B7_RESULT

```text
B4（SIMPLE_SELF_BASELINE）：T+2..T+5 候选 SUCCESS 率高于其他回调时长
  （3D +1.03pp / OR 1.26 / AUC 0.528；5D 一致）——与项目自身 B1 最优窗口
  假设自洽，但效应为项目内自基准
B5（SIMPLE_SELF_BASELINE）：D 收盘深度 >= -4% 的候选略优（3D +0.27pp /
  OR 1.06 / AUC 0.506；5D raw 356/6298=5.6526% vs 119/2108=5.6452%，
  delta +0.0074pp / OR 1.001 / AUC 0.5001）——formal POSITIVE 但
  substantively near-neutral / negligible discrimination，无稳健区分能力
B6（SIMPLE_SELF_BASELINE）：D 日量 <=0.85×T0 量 是最强简单基线
  （3D +2.39pp / OR 1.63 / AUC 0.555；5D +2.87pp / OR 1.65 / AUC 0.556）
B7（MECHANICAL_EXTERNAL_PROXY）：D 收盘突破 pre-T0 60-session 前高的候选
  略优（3D +0.78pp / OR 1.17 / AUC 0.506；5D +0.62pp / OR 1.12 / AUC 0.504）
  ——方向正确但弱；"突破"变体未执行（非契约规则）
```

## OBSERVATIONS

```text
O1 四个 READY benchmark 的 signal SUCCESS rate 均高于 non-signal（3D）；
   B4 与 B6 的 OR 95% CI 严格 >1（B4 1.03-1.54；B6 1.33-2.00），
   B5 与 B7 的 CI 包含 1
O2 B6 固定缩量是最有区分度的简单基线（AUC 0.555）——与 R3 F3 contraction
   方向一致，但 R5B 不进行 F3/B6 组合（属 R6）
O3 B5（深度 >=-4%）3D formal POSITIVE、5D formal POSITIVE；
   但 5D raw 356/6298 = 5.652588% vs 119/2108 = 5.645161%，
   delta ≈ +0.00743pp，OR ≈ 1.001，AUC ≈ 0.50013，CI 包含 1
   —— substantive interpretation = near-neutral / negligible discrimination，
   无稳健区分能力
O4 B7 代理方向正确但极弱（AUC ~0.506，CI 含 1）
O5 失败模式普遍由 STRUCTURE_FAIL 主导（58%-70%），与 cohort 基数一致
```

## HYPOTHESES_SUPPORTED

```text
（OBSERVATION / SUPPORTED_HYPOTHESIS 级别，非 VALIDATED）
固定缩量条件（B6）作为简单基线对 SECOND_LAUNCH 有正向区分（3D/5D 一致）；
项目自身最优回调窗口（B4）有弱正向区分。
```

## HYPOTHESES_NOT_SUPPORTED

```text
固定回撤深度（B5）与 pre-T0 前高突破代理（B7）无稳健区分能力
（OR CI 含 1 / AUC ~0.50-0.51）。
```

## UNRESOLVED

```text
MFE/MAE/days_to_launch companion outcome artifact（未来冻结）
B1/B2/B3 传统形态（N字/龙回头/单阳不破）机械定义（UNDEFINED）
B8 板块过滤（UNDERDEFINED + DATA_UNAVAILABLE）
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R5_STATUS_RECOMMENDATION / R6_RECOMMENDATION

```text
R5_STATUS_RECOMMENDATION = COMPLETE
R6_RECOMMENDATION = AUTHORIZED（本任务未开始 R6；
  R6 将正式评估 benchmark + F3/F6 的 incremental value）
```

## VALIDATION

```text
1. compile: PASS
2. R5A targeted tests: 23 PASS
3. R5B targeted tests: 21 PASS
   （B4 边界 / B5 -4% 精确相等 / B6 0.85 精确相等与 zero-volume 守卫 /
     B7 <60/60/>60/NO_REFERENCE/equality / data-ineligible != non-signal /
     UNKNOWN 排除 / common 交集 / constant-signal AUC / zero-cell OR /
     3D/5D 同一信号 / registry gate 负向 / input gate 正向）
4. input SHA gates: PASS
5. episode signal 1:1/duplicate: PASS（8,682/8,682）
6. own/common denominator reconciliation: PASS（QA RECONCILIATION）
7. failure-profile sum reconciliation: PASS
8. 3D/5D signal byte invariance: PASS（同一 signals artifact）
9. deterministic rerun: PASS（输出哈希一致）
10. git diff --check: PASS
未运行 full-market / production / forward / R6 / ML。
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

```text
research/second_launch/factors_v01/r5b_benchmark_execution_v01.py（新增）
research/second_launch/factors_v01/r5b_benchmark_episode_signals_v01.csv（新增）
research/second_launch/factors_v01/r5b_benchmark_results_3d_v01.csv（新增）
research/second_launch/factors_v01/r5b_benchmark_results_5d_v01.csv（新增）
research/second_launch/factors_v01/r5b_benchmark_failure_profile_v01.csv（新增）
tests/test_r5b_benchmark_execution_v01.py（新增）
research/reports/SECOND_LAUNCH_FACTOR_R5B_EXTERNAL_BENCHMARK_RESULTS_V01.md（本报告）
```

## GIT

```text
COMMIT: research: add r5b external benchmark execution v01
PUSH: origin/research/second-launch-factor-r5b-benchmark-execution-v01
```

---

# R5B_CLASSIFICATION_PRECISION_PATCH

> 2026-08-09 · 最小 correctness patch（classification 精度）· 未改 signal/threshold

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r5b-benchmark-execution-v01
BASE_HEAD: 2fb9ededa27b62b35035830c0ad65e6c289d2bbf
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## ROOT_CAUSE

```text
classification 使用了 round(rate, 4) 的显示值：
  B5 5D raw 356/6298 = 0.0565259 vs 119/2108 = 0.0564516
  -> round 后均 0.0565 -> 误判 NEUTRAL_BENCHMARK
修复：classify 使用 raw rate（signal_success_n / signal_n），
  显示 CSV 保留 round(.,4)；无 epsilon、无显著性门槛、未改预注册规则。
```

## B5_5D_RAW_RATES

```text
signal     = 356 / 6298 = 5.652588%
non-signal = 119 / 2108 = 5.645161%
delta      = +0.00743pp
OR         = 1.001394 > 1
AUC        = 0.500131 > 0.5
95% CI     = 0.809-1.240（包含 1）
```

## B5_5D_CLASSIFICATION_FIXED

```text
B5 OWN 5D:   NEUTRAL_BENCHMARK -> POSITIVE_BENCHMARK
B5 COMMON 5D: NEUTRAL_BENCHMARK -> POSITIVE_BENCHMARK
B5 3D vs 5D: MIXED(POSITIVE->NEUTRAL) -> SAME(POSITIVE)
形式分类为正，但实质性解读保持 near-neutral / negligible discrimination：
  不得因 formal POSITIVE 升级为有效规则；
  HYPOTHESES_NOT_SUPPORTED（B5 无稳健/有意义区分能力）保留。
```

## RAW_METRIC_INVARIANCE

```text
episode signals / eligible N / signal N / SUCCESS N / failure subtype N /
OR / OR CI / AUC / cells：全部不变（cell-by-cell 核对）
B4/B6/B7 3D+5D 结果：不变
3D result CSV：byte-identical
5D result CSV：仅 B5 OWN/COMMON classification 字段变化
```

## SIGNAL_INVARIANCE

```text
r5b_benchmark_episode_signals_v01.csv:  byte-identical
r5b_benchmark_failure_profile_v01.csv:  byte-identical
```

## REPORT_CONSISTENCY_FIXED

```text
1. B5 5D "rate 完全相等" 措辞 -> 精确描述
   （356/6298 vs 119/2108，delta +0.00743pp，OR 1.001，AUC 0.50013，
   CI 包含 1；formal POSITIVE / substantive near-neutral）
2. O1 自相矛盾修正 -> 统一为：
   B4 与 B6 的 OR 95% CI 严格 >1；B5 与 B7 的 CI 包含 1
3. classification 矩阵（B4-B7 3D/5D 全 POSITIVE）与效应强弱区别保留
   （B4 weak / B5 near-neutral / B6 strongest / B7 weak）
```

## VALIDATION

```text
1. compile: PASS
2. R5A targeted tests: 23 PASS
3. R5B targeted tests: 24 PASS
   （新增：raw-rate 陷阱 synthetic、B5 5D 冻结 cells regression、
     classification 契约矩阵 B4-B7 3D/5D 全 POSITIVE）
4. new raw-rate classification regression: PASS
5. rerun R5B: PASS
6. signal artifact byte comparison: PASS
7. failure-profile byte comparison: PASS
8. raw metric cell-by-cell invariance: PASS
9. deterministic rerun: PASS
10. git diff --check: PASS
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R5_STATUS_RECOMMENDATION / R6_RECOMMENDATION

```text
R5_STATUS_RECOMMENDATION = COMPLETE
R6_RECOMMENDATION = AUTHORIZED（本任务未开始 R6）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## GIT（patch）

```text
COMMIT: research: r5b classification precision patch
PUSH: origin/research/second-launch-factor-r5b-benchmark-execution-v01
```
