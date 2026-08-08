# SECOND_LAUNCH_FACTOR_R4_STABILITY_CONTRACT_V01

> R4 STABILITY — 预注册契约（先冻结定义，后计算/后看结果）
> AS_OF: 2026-08-08 · research-only · 本文件在运行任何 R4 分析之前定稿

STATUS: **FROZEN（pre-registered）**

## 0. 输入冻结（fail-closed gate，复用 R3A.1 实现）

```text
FEATURE_CSV : second_launch_factors_v01b_reproducible.csv
FEATURE_SHA : a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8
OUTCOME_CSV : second_launch_outcome_v01b_reproducible.csv
OUTCOME_SHA : 01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d
ROW_N       : 8,682（episode_id 唯一、两侧 1:1、anchor/candidate/symbol 一致、
              feature_snapshot_id = snap-2026-07-31-b5f84004de8a 绑定）
```

基线：R3B.1 HEAD `0f3473189babc3d014179f87d6f23e48b41316b2`（R3 STATUS=COMPLETE、
CORRECTNESS_BLOCKER=NO、R4_RECOMMENDATION=AUTHORIZED）。

## 1. 目标

回答：R3 发现的 signal 是否跨时间、市场环境、结构子样本稳定存在。

```text
F3 CONTRACTION（pullback_volume_ratio / min_volume_ratio / median_range_ratio /
  quiet_days_n）与 F6 ACTIVATION（high_vs_pullback_high / close_vs_pullback_high）
```

结论只允许：

```text
STABLE / TIME_DEPENDENT / REGIME_DEPENDENT / BOARD_DEPENDENT /
T0TYPE_DEPENDENT / UNSTABLE / DATA_LIMITED
```

## 2. 研究对象

### PRIMARY（R3 PROMISING 6）

```text
F3: pullback_volume_ratio, min_volume_ratio, median_range_ratio, quiet_days_n
F6: high_vs_pullback_high, close_vs_pullback_high
```

### NEGATIVE_CONTROL / COMPARISON（10）

```text
F1: t0_return, t0_gap, t0_close_location, t0_position_20d
F2: t0_gain_retention, low_vs_t0_mid, max_drawdown_from_post_t0_high
F5: days_since_t0, days_to_pullback_low, pullback_duration
```

负控因子只用于对照，不改变其 R3 状态（R3：F1/F2/F5 无 PROMISING）。

## 3. 稳定性维度（全部预注册；禁止看结果后调整）

### 3.1 TIME

```text
分层变量 = candidate_date（PIT 观察/决策日 = feature as-of D）
year      = candidate_date 的日历年（2024 / 2025 / 2026）
quarter   = candidate_date 的日历季度（2024Q3 .. 2026Q3）
```

这是对 R3A 季度表与 R3B `EARLY_R4_SANITY_ONLY` 的**正式升级**：
正式 AUC 稳定性协议（§5），不是复制旧表。

### 3.2 REGIME（R4 REGIME CONTRACT V01）

现状（核对时间 2026-08-08）：

```text
仓库无冻结 regime 定义；
无 PIT-safe 指数序列（raw 无指数数据；canonical limit_up_pool 仅覆盖
  2026-07-13..2026-07-31 共 15 日，不满足历史全期，不能用于 regime）；
```

V01 冻结代理（PIT-safe、确定性、预注册，不读取 SUCCESS）：

```text
市场宽度 breadth(s) = 当日 canonical 全市场股票中 pct_change > 0 的占比
  （pct_change 缺失 → 计入分母、不计入分子）
有效会话门禁：当日股票数 n >= 4000，否则该日 breadth 无效（不进入序列）
regime(D) = RISK_ON   if breadth(D) > median(breadth, 20 sessions < D)
          = RISK_OFF  if breadth(D) < median(breadth, 20 sessions < D)
          = NEUTRAL   if breadth(D) == median(...)
前置条件：D 之前至少 15 个有效 breadth 会话，否则该 D 标记 DATA_LIMITED
数据源：与 feature 同一 canonical 快照族
  snap-2026-07-31-b5f84004de8a（仅使用 trade_date <= D 的行）
  immutable gate（V01.1 修正，预注册）：
    文件 SHA256 == e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
      （pin 自 data/manifests/snap-2026-07-31-b5f84004de8a.json
        canonical_file_hashes[...]，与 outcome/extractor pin 相同）
    全部行的 dataset_snapshot_id == snap-2026-07-31-b5f84004de8a
    会话日期范围必须覆盖 cohort 的 candidate_date 范围
  任一失败 -> FAIL CLOSED（RuntimeError，不输出结果）
```

严格指数式 bull/bear regime（上证指数 close vs 60-session MA）需要独立
provenance 的指数 artifact，当前不可得 → 记为 **DEFERRED**（V01 不伪造）。

### 3.3 BOARD

确定性 symbol-prefix 映射（代码编码、PIT-correct、历史不迁移）：

```text
600/601/603/605 -> SH_MAIN
688/689         -> SH_STAR
000/001/002/003 -> SZ_MAIN
300/301/302     -> SZ_CHINEXT
920             -> BSE
其它            -> UNMAPPED（不计入任何板层，计数记录）
```

禁止因结果不佳合并/重划板层。

### 3.4 T0 TYPE

现状：仓库无 frozen T0 type 定义（STRATEGY_MASTER §4 识别一字/T字/首板/连板，
但 PRICE_ONLY、不伪造；frozen V01 feature 无连板/封板字段）。

V01 操作化（确定性，仅用 frozen feature 列，绝对边界，无阈值搜索）：

```text
T0_POSITION（策略"低位/中低位"概念的直接操作化，t0_position_20d 原生 [0,1] 尺度）:
  LOW  = t0_position_20d <  1/3
  MID  = 1/3 <= t0_position_20d < 2/3
  HIGH = t0_position_20d >= 2/3
  t0_position_20d 缺失 -> 该 episode 不计入 T0_POSITION 分层（计数记录）

T0_GAP_UP（次要维度）:
  GAP_UP    = t0_gap > 0
  NO_GAP_UP = t0_gap <= 0
  t0_gap 缺失 -> 不计入（计数记录）
```

记录为 **UNAVAILABLE_FOR_V01**：一字板/T字板/首板/连板类型（需未来冻结
label/feature 扩展，例如历史期 limit_up_pool / consecutive_count）。

禁止看 SUCCESS 后再创造 T0 分组。

## 4. 统计口径（与 R3A.1 一致）

```text
Primary   : outcome_3d, SUCCESS vs KNOWN_NON_SUCCESS（UNKNOWN 排除）
Sensitivity: outcome_5d（仅 PRIMARY 6 因子）
指标      : binary AUC（R3A.1 同一实现，不翻转方向）
direction = sign(AUC - 0.5)（严格语义）
  AUC > 0.5 -> POSITIVE；AUC < 0.5 -> NEGATIVE；AUC == 0.5（精确）-> NEUTRAL
  NEUTRAL 层：effect = 0，计入 reportable 分母，不计入 same/opposite，
  永不构成 material reversal
effect    = |AUC - 0.5|
空值      : factor NULL 按 R3A 语义排除（结构化 missing 不入列）
层报告门槛 REPORTABLE：n_known >= 60 且 success_n >= 10 且 nonsuccess_n >= 10
  不足 -> 该层记录 n 并标 DATA_LIMITED
```

## 5. 判定规则（预注册；对每个 factor x dimension）

```text
global_dir  = direction(global AUC, 3D)
stratum_dir_s = direction(AUC_s, 3D)
consistency = (# reportable strata 与 global_dir 同向) / # reportable strata
material_reversal =
  存在 reportable stratum: stratum_dir != global_dir 且 effect_s >= 0.03

verdict(dimension)：
  reportable strata < 3                        -> DATA_LIMITED
  consistency >= 0.80 且无 material_reversal    -> STABLE
  （>=2 opposite strata 且有 material_reversal）
  或 consistency <= 0.50                        -> UNSTABLE
  否则                                          -> MIXED
      （对外报告为 <DIM>_DEPENDENT：
        TIME_DEPENDENT / REGIME_DEPENDENT /
        BOARD_DEPENDENT / T0TYPE_DEPENDENT）

OVERALL(factor)：
  任一维度 UNSTABLE        -> UNSTABLE
  任一维度 MIXED           -> 对应 <DIM>_DEPENDENT
                              （多维度时按 TIME < BOARD < T0TYPE < REGIME 取首个）
  任一维度 DATA_LIMITED    -> DATA_LIMITED（无 UNSTABLE/MIXED 时）
  否则                     -> STABLE

BINARY_DIMENSION_CLAUSE（V01 定稿修正，预注册）：
  适用于二值/近二值维度：regime（实际观测到 RISK_ON/RISK_OFF 两态，
  NEUTRAL 未出现）与 t0_gap_up（构造上二值）。
  泛用"reportable >= 3"规则对二值维度结构性不适用（永远无法达到 3 层），
  修正为：
    - 两态均 reportable（n/succ/nonsucc 门槛）且均 directional
      （effect >= 0.03） -> 否则 DATA_LIMITED
    - 两态与 global_dir 同向 -> STABLE
    - 两态方向相反 -> UNSTABLE
  修正理由：规则结构不适用（非 SUCCESS-rate 驱动、未调整任何边界/阈值）。

BOARD_COVERAGE_NOTE（预注册）：
  冻结 cohort 若仅含部分板块（如只有 SH_MAIN/SZ_MAIN），board 维度按
  泛用 >=3 规则判 DATA_LIMITED，并在报告记录实际板块覆盖；禁止因覆盖不足
  把 board 结论改写为 STABLE。

5D SENSITIVITY（PRIMARY 6）：
  重算 global + 各维度 verdict；若与 3D 结论不一致 -> 报告 SENSITIVITY_DIFF，
  3D 仍为主结论。

NO_GLOBAL_SIGNAL 保护：
  |global AUC - 0.5| < 0.01 -> 该因子整体标 NO_GLOBAL_SIGNAL
  （各层 verdict 仍输出供审计，但不作为稳定性结论解读）
```

## 6. R4 禁止事项

```text
factor combination optimization / factor selection automation /
threshold optimization / score construction / Logistic / tree / RF /
XGBoost / ML / random train-test / backtest optimization /
strategy rule change / forward / TradePlan / production promotion
```

## 7. 输出（V01）

```text
research/second_launch/factors_v01/r4_stability_v01.py
research/second_launch/factors_v01/r4_stability_global_3d.csv
research/second_launch/factors_v01/r4_stability_strata_3d.csv
research/second_launch/factors_v01/r4_stability_verdicts_3d.csv
research/second_launch/factors_v01/r4_stability_sensitivity_5d.csv
research/reports/SECOND_LAUNCH_FACTOR_R4_STABILITY_REPORT.md
tests/test_r4_stability_v01.py
```

## 8. 结论状态

R4 V01 只允许 OBSERVATION / SUPPORTED_HYPOTHESIS（沿用 R3 术语）；
不允许 VALIDATED RULE / trading factor。
