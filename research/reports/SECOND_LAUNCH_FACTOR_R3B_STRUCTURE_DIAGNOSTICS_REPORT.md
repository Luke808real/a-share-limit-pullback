# SECOND_LAUNCH_FACTOR_R3B_STRUCTURE_DIAGNOSTICS_REPORT

> R3B — F3/F5/F6 结构诊断（exploratory research；无 ML/score 优化/回测；未改 strategy）

STATUS: **COMPLETE** — 结构诊断完成（无 correctness blocker；无 “VALIDATED trading factor”）

BRANCH: `research/second-launch-factor-r3b-structure-v01`
BASE_HEAD: `eaff770cbabc28d431718a4d9cb7a8cab81eabad`
HEAD_AFTER: 见 GIT 段

## INPUT_GATE

```text
FEATURE_SHA: a485a484… / OUTCOME_SHA: 01a9f2fa…（PASS）
ROW_N: 8,682 / episode_id 1:1 / snapshot binding: PASS
仅 PRIMARY factors + outcome_3d/5d；#11 仅 identity QA
```

## TEST_HYGIENE_FIX

```text
_exact_permutation_p() 修正：two-sided 按 |U_perm − μ| >= |U_obs − μ| 累计
  （原实现只统计 U 恰好等于 observed/mirror，低估两尾）
新增回归测试：n=6 手算案例（mid-U: 14/20；extreme-U: 2/20）PASS
heavy-tie 测试精确 p 由 0.1905 更新为 0.2381（容差 0.15 的 loose sanity 内）
测试合计 6/6 PASS；生产 p-value 与 factor results 未改动
```

## F3_REDUNDANCY

```text
（pairwise-complete Spearman；完整矩阵见 r3b_f3_correlation_matrix.csv）
pullback_volume_ratio ~ min_volume_ratio:  0.928（近重复代理）
min_volume_ratio ~ quiet_days_n:          −0.835
pullback_volume_ratio ~ quiet_days_n:     −0.766
median_range_ratio ~ 其余:                 0.33-0.38（最独立）
volume_slope ~ 其余:                       0.09-0.30（但 coverage 49.9%，仅辅助）
SUCCESS 组与非 SUCCESS 组相关性与全体基本一致（结构在组内保持）
OBSERVATION：4 个 PROMISING F3 中，量能类（pvr/mvr）高度冗余（0.93），
  quiet_days 与量能强负相关（−0.84/−0.77）；median_range_ratio 携带最独立信息
```

## F3_DOSE_RESPONSE

```text
（完整表见 r3b_factor_structure_results.csv section=F3_DOSE_RESPONSE）
pullback_volume_ratio（quintile）: 0.0651 → 0.0312（MONOTONIC_DECREASING）
median_range_ratio（quintile）:    0.0625 → 0.0312（MONOTONIC_DECREASING）
min_volume_ratio（quintile）:      0.0670/0.0638/0.0357/0.0415/0.0281（整体下降，bin3-4 微升）
quiet_days_n（自然组 0/1/2+）:     0.0343 / 0.0673 / 0.0632
  （n=4,695 / 2,542 / 601；2+ 保留实际 N 未合并；峰在 1，2+ 平台，非单调）
OBSERVATION：连续 F3 存在近似单调 dose-response（量/振幅收缩越强 SUCCESS 率越高）；
  quiet_days 呈 inverted-U/平台（0 天最低，1 天最高，2+ 与 1 接近）
```

## F5_TIME_NONLINEAR

```text
（完整表见 results CSV section=F5_TIME_SHAPE；tail 仅在单值 n<30 时合并）
days_since_t0: T+1 0.0427(n=3,956) / T+2 0.0538(n=3,752) / T+3 0.0405(n=444) /
  T+4 0.0560(n=125) / T+5 0.0952(n=42) / T+7 0.0000(n=35) / tail 0.0513(n=117)
days_to_pullback_low: 1→0.0418(n=4,287) / 2→0.0561(n=2,996) / 3→0.0407 / 4→0.0137 / 5→0.1000 / tail 0.0411
pullback_duration: 1→0.0460(n=6,785) / 2→0.0583(n=875) / 3→0.0246 / 4→0.1000(n=30) / tail 0.0439
形状标签（规则化）：三因子均被标记 INVERTED_U —— 但峰值桶 n 很小（42/40/30），
  属小样本噪声，无稳健 inverted-U/decay 证据
OBSERVATION：无单调 decay；无稳健最优窗口；主导样本集中在 T+1/T+2（差异 ~1pp）；
  H4 TIME_NONLINEAR_DECAY 在该 operationalization 下未获支持（非否定存在性，
  仅指日线 session 距离无可见非线性衰减结构）
```

## F6_FAILURE_BOUNDARY

```text
（quintile 表见 results CSV section=F6_FAILURE_BOUNDARY；failure-class AUC 见 R3A CSV）
close_vs_pullback_high quintile SUCCESS rate: 0.0234/0.0376/0.0680/0.0751/0.0563
high_vs_pullback_high quintile:                0.0258/0.0481/0.0645/0.0751/0.0469
failure-class（R3A.1 重算）:
  close_vs_ph vs FAILED_BREAKOUT ≈ 0.51 / vs NO_LAUNCH ≈ 0.60 / vs STRUCTURE_FAIL ≈ 0.60
OBSERVATION：F6 主要识别“有无 activation”（NL/SF vs SUCCESS 区分强），
  对 activation 后的 acceptance（FB vs SUCCESS）几乎无区分 → 
  DAILY ACTIVATION distinguishes launch/no-launch better than successful
  acceptance；F7（acceptance）仍 unresolved（未引入 5m）
```

## F3_F6_CROSSTAB

```text
（代表性 F3 选择规则：STABLE + coverage>=0.90 + 与其余 F3 最低 median |corr|
  → median_range_ratio；选择先于查看 interaction 结果）
median_range_ratio 三分位 × close_vs_pullback_high 中位数（LOW/HIGH）:
  低收缩×LOW 0.0436(n=344) / 低收缩×HIGH 0.0770(n=1,065)
  中收缩×LOW 0.0474(n=781) / 中收缩×HIGH 0.0622(n=627)
  高收缩×LOW 0.0274(n=987) / 高收缩×HIGH 0.0451(n=421)
OBSERVATION（纯描述）: 每个收缩层内 activation HIGH > LOW（+1.7~+3.3pp）；
  activation HIGH 下收缩从低到高 SUCCESS 0.0770→0.0622→0.0451（收缩仍有负向作用）
```

## TEMPORAL_STABILITY

```text
（quarterly 表见 results CSV section=TEMPORAL_QUARTERLY）
quiet_days_n>=1 vs =0: 9/9 quarters hi>lo（方向稳定）
close_vs_pullback_high 中位分: 8/9 quarters hi>lo（2025Q1 翻转，幅度 0.3pp）
结论：关键方向在 calendar quarter 上大致保持
```

## OBSERVATIONS

```text
O1: F3 量能类因子高度冗余（pvr~mvr 0.93）；median_range_ratio 携带独立信息
O2: 连续 F3 存在近似单调 dose-response（收缩越强 SUCCESS 越高）
O3: quiet_days_n 呈 0<1≈2+ 的非单调形状
O4: F5 三个 TIME 因子无稳健形状（小样本噪声主导）
O5: F6 区分 launch/no-launch 强、区分 acceptance（FB）弱
O6: F3×F6 交叉中 activation 效应在每个收缩层内保持
```

## HYPOTHESES_SUPPORTED

```text
（exploratory support，非 VALIDATED）
- F3 CONTRACTION dose-response：支持（连续收缩因子单调；见 O2/O6）
- F6 DAILY ACTIVATION 对 launch/no-launch 的区分能力：支持（O5）
```

## HYPOTHESES_NOT_SUPPORTED

```text
- H4 TIME_NONLINEAR_DECAY：未获支持（O4；无 decay/最优窗口证据）
- F2 HOLD 简单日线操作化：R3A.1 已无 PROMISING；本轮未新增支持
```

## UNRESOLVED

```text
- F7 acceptance（activation 后的接受质量）：需 5m/分钟数据，后续阶段
- quiet_days_n 2+ 平台行为：样本 601，需更大样本或自然分组细化
- F5 小样本尾桶的真实形状：当前 n<50 无法判定
- F3 冗余归并后的独立信息量：需 multivariate 诊断（后续授权）
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R3C_RECOMMENDATION

```text
AUTHORIZED（exploratory 结构诊断门通过；本任务未启动 R3C 及任何下游研究）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

- `research/second_launch/factors_v01/r3b_factor_structure_v01.py`（新增）
- `research/second_launch/factors_v01/r3b_factor_structure_results.csv`（新增，主表）
- `research/second_launch/factors_v01/r3b_f3_correlation_matrix.csv`（新增）
- `research/second_launch/factors_v01/r3b_f3_f6_crosstab.csv`（新增）
- `tests/test_r3a_univariate_screen_v01.py`（M：permutation helper 修正 + 回归测试）
- `research/reports/SECOND_LAUNCH_FACTOR_R3B_STRUCTURE_DIAGNOSTICS_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: add r3b factor structure diagnostics
PUSH: origin/research/second-launch-factor-r3b-structure-v01
```

---

## VALIDATION NOTES

- 全部结构统计从 frozen CSV 程序化重算；未搜索 cutoff；未做 logistic/regression/tree/ML
- F3 代表因子选择规则先于结果注册（STABLE+coverage+最独立）
- 时间桶为 calendar quarter；F5 tail 仅在 n<30 时合并并明确标注
- 术语纪律：OBSERVATION/HYPOTHESIS 严格区分；无 “VALIDATED trading factor”
