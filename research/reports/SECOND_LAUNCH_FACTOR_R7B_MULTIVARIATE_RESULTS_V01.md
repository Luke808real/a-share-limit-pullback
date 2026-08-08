# SECOND_LAUNCH_FACTOR_R7B_MULTIVARIATE_RESULTS_V01

> R7B — Multivariate Attribution Execution V01（unregularized logistic）
> AS_OF: 2026-08-09 · research-only · 严格按 R7A execution freeze 执行

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r7b-multivariate-execution-v01
BASE_HEAD: b2aa8129aa64b993c01c949bae3af01fa21c68e0
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## INPUT_GATE / EXECUTION_CONTRACT

```text
FEATURE/OUTCOME/SIGNALS SHA + R7A registry SHA 828a3148… + SOURCE_HEAD：PASS
三方 episode 对齐 + identity binding：PASS（复用 R6B alignment）
fitter = statsmodels Logit（newton / maxiter=100 / tol=1e-8 / intercept / raw /
 无标准化）；metrics 公式与 statsmodels AIC/BIC 一致性检查 PASS；
CI_TYPE=MODEL_BASED_NON_CLUSTERED；CLUSTER_ROBUST_SE=DEFERRED
```

## CORE_SAMPLE

```text
common_eligible + finite pvr/mvr/mrr/quiet + known：
  3D N = 7,837（SUCCESS 370）；5D N = 7,834
N(M0)=N(M1)=N(M2)=N(M3)（同 target）——无 denominator drift
F6A/F6B matched sample N = 4,225（M2_REF 与 M4 同 denominator）
```

## PRIMARY_QUESTION_1_RANGE（M1 vs M0；3D primary）

```text
                AUC      LogLoss  Brier    AIC       BIC
M0 (benchmarks) 0.5750   0.1882   0.0448   2959.28   2994.11
M1 (+mrr)       0.5985   0.1878   0.0447   2955.12   2996.92
Delta          +0.0235  -0.0004  -0.0001  -4.17     +2.80

median_range_ratio (M1): beta = -0.3685（NEGATIVE，匹配 R3）
  odds_ratio = 0.69；95% CI [-0.70, -0.04]（不含 0，描述性）
5D：M1 AUC 0.6080 vs M0 0.5750（Delta +0.033）；5D mrr NEGATIVE（未反转）

=> RANGE_INDEPENDENT_SUPPORTED（frozen rule 全部满足）
```

## PRIMARY_QUESTION_2_QUIET（M2 vs M1）

```text
                AUC      LogLoss  Brier
M1 (+mrr)       0.5985   0.1878   0.0447
M2 (+quiet)     0.6022   0.1876   0.0447
Delta          +0.0038  -0.0002  0.0000-

quiet_days_n (M2): beta = +0.0659（POSITIVE，匹配 R3）
  odds_ratio = 1.07；95% CI [-0.01, 0.14]（含 0，描述性）
5D：Delta AUC +0.0044；5D quiet POSITIVE（未反转）
improvements = AUC + LogLoss + Brier（>=2）

=> QUIET_INCREMENTAL_SUPPORTED（frozen rule 满足）
```

## M3_VOLUME_REDUNDANCY（M3 vs M2；DIAGNOSTIC ONLY）

```text
M3 vs M2：
  Delta AUC     +0.0052168
  Delta LogLoss -0.0005773
  Delta Brier   -0.0000284
  Delta AIC     -5.048
  Delta BIC     +8.885
pullback_volume_ratio: beta = +0.3876（POSITIVE，与 R3 NEGATIVE 不匹配）
min_volume_ratio:      beta = -0.7199（NEGATIVE，匹配 R3；CI [-1.41,-0.02]）
median_range_ratio:    beta = -0.2011（NEGATIVE，CI 含 0 —— 控制 pvr/mvr 后弱化）
quiet_days_n:          beta = +0.0378（POSITIVE，CI 含 0）
pvr/mvr correlation = 0.957
pvr coefficient direction reverses；mvr remains negative

INTERPRETATION:
  INDIVIDUAL_ATTRIBUTION_UNSTABLE
  JOINT_INCREMENTAL_EVIDENCE=MIXED
（ΔAUC/ΔLogLoss/ΔBrier 整体小幅改善、ΔAIC 改善而 ΔBIC 恶化；
  单个 volume coefficient 方向不稳定 —— 不能写作
  "pvr/mvr completely absorbed" 或 "no joint incremental information"；
  也不能据此做 model selection）

M3 = DIAGNOSTIC ONLY（保持）
```

## F6_ROBUSTNESS（matched sample N=4,225；ROBUSTNESS_OBSERVATION ONLY）

```text
M4A vs M2_REF_A：Delta AUC +0.0011；high_vs_pullback_high beta = +4.24
  （POSITIVE 匹配 R3，OR 极大 = 描述性非 cluster-robust）
M4B vs M2_REF_B：Delta AUC +0.0203；close_vs_pullback_high beta = +7.97
  （POSITIVE 匹配 R3）
不升级正式候选；R4 结论保持：high = UNSTABLE；close = TIME_DEPENDENT
```

## 3D_RESULTS / 5D_SENSITIVITY

```text
3D：RANGE SUPPORTED / QUIET SUPPORTED；M3 诊断同上
5D：M1 ΔAUC +0.033 / M2 ΔAUC +0.0044；mrr 与 quiet 5D 方向均未反转
  （sensitivity 不推翻 3D 结论）
```

## MULTICOLLINEARITY

```text
CORE 样本（raw predictors，诊断 only）：
  pvr-mvr correlation = 0.9572（近共线，与 R3B 一致）
  pvr-mrr 0.292 / pvr-quiet -0.362 / mvr-quiet -0.397 / mrr-quiet -0.114
  condition number（standardized、intercept-excluded）= 7.45
不因共线自动删变量。
```

## CI_LIMITATION

```text
CI_TYPE = MODEL_BASED_NON_CLUSTERED（未做 cluster-robust）
CLUSTER_ROBUST_SE = DEFERRED
repeated episodes per symbol mean CI is descriptive and not cluster-robust；
CI 未用于 RANGE/QUIET success gate。
```

## OBSERVATIONS

```text
O1 median_range_ratio 在同时控制 B4/B5/B6/B7 后仍保留独立负向贡献
  （M1 ΔAUC +0.0235 / ΔLogLoss -0.0004 / ΔBrier -0.0001；3D/5D 一致）
O2 quiet_days_n 增加小幅但一致的正向贡献（M2 ΔAUC +0.0038）
O3 pvr/mvr 在 M3 多变量中符号分裂/不稳定（corr 0.957）——冗余确认
O4 F6 在 matched sample 有诊断性增量（M4B ΔAUC +0.0203）但不改变 R4
O5 全模型收敛、无完美分离、预测有限且 p∈[0,1]
```

## HYPOTHESES_SUPPORTED

```text
（SUPPORTED_HYPOTHESIS，非 VALIDATED —— 未进入 R8/R9）
range contraction（median_range_ratio）在 simple benchmark 之上具有
独立 multivariate 信息；quiet 时间提供小幅增量；volume 类因子冗余。
```

## HYPOTHESES_NOT_SUPPORTED

```text
pvr/mvr 的多变量独立贡献（被 B6/range/quiet 吸收；共线下不稳定）。
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R7_STATUS_RECOMMENDATION / R8_RECOMMENDATION

```text
R7_STATUS_RECOMMENDATION = COMPLETE
R8_RECOMMENDATION = AUTHORIZED（R8 研究 activation -> acceptance 的独立
  盘中问题，不依赖 R7 model performance；本任务未开始 R8）
```

## VALIDATION

```text
compile PASS；tests/test_r7b_multivariate_execution_v01.py 14 PASS（cloud_ci）
  （metric formulas / AIC-BIC / fitter 契约 / 完美分离 fail-closed /
  合成方向 / CORE 同 N / F6 matched N / range+quiet frozen rules /
  model set / episode shuffle invariance）
全量回归：R5A/R5B/R6A/R6B/R7A/R7B tests PASS
cloud 命令（6 文件）：PASS（cloud_ci and not local_data）
QA：CORE denominator 相等、F6 matched 相等、预测有限 p∈[0,1]、
  metric reconciliation、AIC/BIC 一致性、16 模型行无重复
确定性：两次运行输出哈希一致；git diff --check PASS
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
ASL_CHANGED=false
```
