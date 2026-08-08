# SECOND_LAUNCH_FACTOR_R3A_UNIVARIATE_REPORT

> R3A — immutable outcome join + univariate factor screen（research-only ranking）
> 未做 multivariate / ML / score 优化 / 回测 / forward / TradePlan；未改 strategy

STATUS: **COMPLETE** — 24 个 PRIMARY factors 单因子筛查完成（无 correctness blocker）

BRANCH: `research/second-launch-factor-r3a-univariate-v01`
BASE_HEAD: `24e1f86c7db8f9e288ca430b4a1df7f4704e5fc2`
HEAD_AFTER: 见 GIT 段

## INPUT_GATE

```text
FEATURE_SHA: a485a484…（文件 + manifest 双向校验 PASS）
OUTCOME_SHA: 01a9f2fa…（文件 + manifest 双向校验 PASS）
FEATURE_ROW_N: 8,682 / OUTCOME_ROW_N: 8,682
EPISODE_ID_UNIQUE: true（两侧）
EPISODE_ID_1:1_EXACT_MATCH: true
IDENTITY_COLUMNS（anchor_date/candidate_date/symbol）两侧一致: true
FEATURE_SNAPSHOT_BINDING: snap-2026-07-31-b5f84004de8a（outcome 列 + feature manifest 一致）
```

## JOIN_QA

```text
JOIN_ROWS: 8,682（episode_id 1:1；无缺失/额外/重复）
PREDICTOR_UNIVERSE: 24 PRIMARY（#11 impulse_retrace_ratio 仅 identity QA）
禁止列未入 predictor：*__missing_reason / reconciliation / provisional / data_quality /
  quality_flags / outcome_reason* / time_to_* / first_event_* / window_incomplete* —— 全部未使用
```

## LABEL_COUNTS_3D/5D

```text
3D: SUCCESS 406 / FAILED_BREAKOUT 949 / NO_LAUNCH 1,724 / STRUCTURE_FAIL 5,392 / UNKNOWN 211
5D: SUCCESS 481 / FAILED_BREAKOUT 1,143 / NO_LAUNCH 1,016 / STRUCTURE_FAIL 5,826 / UNKNOWN 216
主二分类 SUCCESS vs KNOWN_NON_SUCCESS（=FB+NL+SF）: 3D n=8,471；UNKNOWN 3D=211（排除，不当作失败）
```

## FACTOR_COVERAGE

```text
coverage_3d（known-label 内非空）: t0_close_location / days_since_t0 100%；
  T0 日因子 94.6%；PB 因子 92.5%；#5 83.3%；#7 83.0%；#24/#25 50.3%；
  volume_slope / range_slope 49.9%（<50% → DATA_LIMITED）
```

## UNIVARIATE_RESULTS

（完整 24 行见 `r3a_univariate_factor_results.csv`；核心列：n_3d / coverage_3d /
auc_3d / p_3d / q_bh_3d / spearman_3d / auc_5d / succ/nonsucc median+P25+P75 /
quintile rates / OR+CI / direction_consistent_3d_5d / buckets / stability / classification）

```text
AUC 最高（3D，SUCCESS vs KNOWN_NON_SUCCESS，方向不翻转）:
  close_vs_pullback_high 0.590（q 3.1e-05）  quiet_days_n 0.585（q 3.3e-07）
  high_vs_pullback_high 0.556（q 0.017）      min_volume_ratio 0.412（q 2.7e-07）
  median_range_ratio 0.416（q 3.3e-07）       pullback_volume_ratio 0.421（q 1.7e-06）
方向说明：CONTRACTION 家族为负向 AUC（量/振幅收缩 → SUCCESS 概率更高），保留原始方向
quintile OR（top vs bottom）：close_vs_ph 2.48 [1.46,4.22]；quiet_days 1.40 [0.99,1.99]；
  min_vol_ratio 0.40 [0.28,0.58]；median_range 0.48 [0.34,0.69]
ties 导致的 reduced bins：t0_close_location / pullback_duration bins_n=1（OR NA）；
  days_since_t0 / quiet_days / days_to_pullback_low bins_n=2-3（已记录，确定性）
3D/5D 方向一致性：22/24 一致（t0_range_pct、pullback_depth_close、t0_gain_retention
  不一致，均接近 0.50 的噪声区）
```

## FAILURE_CLASS_COMPARISON

```text
（SUCCESS vs 单类，3D AUC；完整 24 行见 CSV auc_3d_vs_* 列）
quiet_days_n: vs FB 0.591 / vs NL 0.537 / vs SF 0.599
close_vs_pullback_high: vs FB 0.509 / vs NL 0.598 / vs SF 0.600
min_volume_ratio: vs FB 0.409 / vs NL 0.464 / vs SF 0.396
注：activation 家族（#24/#25）对 NL/SF 区分强、对 FB 弱 —— 与“接受失败不可赎回”语义一致
```

## TEMPORAL_STABILITY

```text
方法：candidate_date 按 calendar quarter 分桶；每桶要求 n≥30 且两类各 ≥10；
  每 factor 报告 bucket N / SUCCESS N / direction / AUC（CSV buckets_n / bucket_pos_n /
  bucket_auc_min / bucket_auc_max）
规则：全部桶同向 → STABLE；少数反向（≤1/3）→ MIXED；否则 UNSTABLE；有效桶 <3 → DATA_LIMITED
STABLE（4）：min_volume_ratio（0/8 反向）、median_range_ratio、volume_slope、quiet_days_n（8/8 正向）
MIXED / UNSTABLE（其余）：多为 0.50 附近噪声因子的桶方向抖动（如 t0_gap 3/8、t0_range_pct 4/8）
```

## PROVENANCE_SENSITIVITY

```text
（full vs feature_3d_has_provisional=false vs label_5d_has_provisional=false，逐 factor AUC）
DELTA_FEATURE_MAX: 0.0039（t0_volume_ratio_5d）；DELTA_LABEL_MAX: 0.0064（t0_volume_ratio_5d）
结论：AUC 不受 reconciliation/provisional 分层驱动（全部 ≤0.0064）；
  data_quality 层 OK 仅 33 例（样本过小，仅记录）
missing reason 仅 QA 用，未入 predictor
```

## MULTIPLE_TESTING

```text
24 个 PRIMARY factors 统一 BH-FDR（3D 主二分类 p 值）
q_bh 范围: 2.72e-07 .. 0.958
q < 0.10 的 factor（9）：close_vs_pullback_high、high_vs_pullback_high、quiet_days_n、
  min_volume_ratio、median_range_ratio、pullback_volume_ratio、volume_slope、
  t0_volume_ratio_5d、t0_return
```

## TOP_PROMISING_FACTORS

```text
（research ranking 候选；非交易 score；不使用 “VALIDATED trading factor” 表述）
1. close_vs_pullback_high（AUC 0.590, q 3.1e-05, 3D/5D 一致, MIXED 稳定性）
2. quiet_days_n（AUC 0.585, q 3.3e-07, STABLE, bins_n=2 ties 注意）
3. high_vs_pullback_high（AUC 0.556, q 0.017, 3D/5D 一致）
4. median_range_ratio（AUC 0.416, q 3.3e-07, STABLE, 负向）
5. min_volume_ratio（AUC 0.412, q 2.7e-07, STABLE, 负向）
6. pullback_volume_ratio（AUC 0.421, q 1.7e-06, MIXED, 负向）
```

## WEAK/UNSTABLE_FACTORS

```text
WEAK: 0（0.02≤|AUC−0.5|<0.05 且非 MIXED 的因子无 —— 该区间因子均为 MIXED → UNSTABLE）
UNSTABLE（14）：t0_return、t0_gap、t0_range_pct、t0_position_20d、pre_t0_return_5d、
  pre_t0_return_20d、t0_volume_ratio_5d、pullback_depth_close、max_drawdown_from_post_t0_high、
  t0_gain_retention、low_vs_t0_mid、days_above_t0_mid、days_since_t0、days_to_pullback_low
NO_SIGNAL（2）：t0_close_location、pullback_duration
DATA_LIMITED（2）：volume_slope、range_slope（coverage 49.9%）
```

## KNOWN_ERRATA（记录，不改 contract）

```text
1. R2B 报告 “#9-#16/#18/#20/#22 共 12 个 PB 类 factor” 实为 11 个（#9-#16 为 8 个，
   + #18/#20/#22 = 11）
2. R2B CA_EVENT 合计 3,100 正确，但正文拆分遗漏 #6 pre_t0_return_5d=194、
   volume_slope=58，并把普通 PB 81×11 写成 81×12
3. max_drawdown_from_post_t0_high 正值（467/8,030）按冻结公式合法（全跳空高于 running peak）；
   禁止 clip/winsorize/改 0；契约 #10 unit “(<=0)” 仅记录为 metadata errata
```

## CORRECTNESS_BLOCKER

```text
NO
```

## NEXT_RECOMMENDATION

```text
人工评审 ranking（PROMISING 6 个属研究候选，方向与 F2/F3/F6 家族假设一致）；
若推进：R3B 可做失败类拆分 / 时间稳定性细化 / 多因子诊断（仍需逐轮授权）；
禁止在本轮基础上直接形成交易 score 或策略规则
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

- `research/second_launch/factors_v01/r3a_univariate_screen_v01.py`（新增，分析脚本）
- `research/second_launch/factors_v01/r3a_univariate_factor_results.csv`（新增，24 行 × 50 列）
- `research/reports/SECOND_LAUNCH_FACTOR_R3A_UNIVARIATE_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: add r3a univariate factor screen
PUSH: origin/research/second-launch-factor-r3a-univariate-v01
```

---

## VALIDATION NOTES

- 全部统计从 CSV 重算（未复制 R2B 手工汇总）；BH-FDR 实现经反向累计最小修正并复核
- 未训练 ML；未做 multivariate；未做 score/threshold 优化；未 join 除 outcome_3d/5d 外的字段
- 脚本记录输入哈希 pin；输出 CSV 即研究产物
