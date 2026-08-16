# F22 OUTCOME VALIDATION PREREGISTRATION V01 — 预注册统计设计

状态：**PREREGISTERED / NOT RUN**（本文件冻结统计设计；未读取任何 F22×outcome 数字，未运行正式验证）

日期：2026-08-16
分支：`research/f22-outcome-prereg-v01`
BASE_HEAD（implementation authority）：cd3d676c756a85e4c0ef2d3ffb82d2edc61ea43f
CONTRACT_HEAD：d3325e298a5c518afae6c82499c4c6acd71352dc

---

## 1. FACTOR AUTHORITY

- F22 authority：`factor_lab.b2_huge_upper_shadow_volume(bars, b2_date) -> bool | None`
- Contract：F22 CONTRACT/PIT FROZEN（d3325e2，K=1.0 OWNER_FROZEN，
  VOLUME_THRESHOLD=1.5）
- Implementation：PASS / CLOSED（cd3d676）
- FACTOR_DOMAIN：**B2 event EOD failure-risk diagnostic**；
  INTRADAY_B2_ENTRY_ELIGIBLE = NO（上影与全天量仅收盘后确定）
- F22 布尔因子：`F22_TRUE = SHAPE_TRUE AND VOLUME_TRUE`；数据可计算但未触发
  → `F22_FALSE`（DEFINED）；None 仅数据不可计算（INSUFFICIENT_PRE5 /
  ZERO_DENOMINATOR / MISSING_B2_BAR / OTHER_ERROR）

## 2. PRIMARY HYPOTHESIS — H22A

**B2 日出现巨量长上影（F22_TRUE）的 episode，其 SECOND_LAUNCH 成功概率
更低（失败风险更高）**——F22 是假突破/出货的 EOD 证据，方向为**负面
信号**（failure-risk），不是正向确认。预注册未冻结 significance test，
verdict 仅由第 6 节的 DELTA_FAIL_RATE / OR_FAILURE 方向 gate 决定
（不写"显著"）。

- 不预注册任何人为倍数阈值（K=1.0、VOLUME_THRESHOLD=1.5 已冻结，不得调整）
- F22 为布尔因子（TRUE/FALSE），不做连续化、不做分位切分

## 3. VALIDATION POPULATION

```
resolved episodes（outcome ∈ {WIN_S1, LOSS_INVALID, CANCEL_GAP_INVALID}）
AND setup_stage ∈ {B2_READY, B2_CONFIRMED}
```

- b2_date = episode.signal_date（frozen）
- 域内禁止：outcome pre-filter、F22_TRUE/FALSE pre-filter——每个 episode
  都必须尝试 materialize F22
- defined population = F22 数据可计算（B2 OHLCV 可用 + PRE5_N==5 +
  PRE5 mean volume > 0）
- undefined（INSUFFICIENT_PRE5 / ZERO_DENOMINATOR / MISSING_B2_BAR /
  OTHER_ERROR）**单独 accounting**，不进 primary population（F18/F20
  undefined-isolation 纪律）

## 3b. MATERIALIZATION ACCOUNTING（required output contract，冻结）

validation artifact 必须固定输出以下五项（缺一不可，fail closed）：

```
POPULATION_N         域内 episode 总数（resolved AND B2-stage）
DEFINED_TRUE_N       materialize 后 F22_TRUE 数
DEFINED_FALSE_N      materialize 后 F22_FALSE 数
UNDEFINED_N          materialize 后 undefined 数
UNDEFINED_REASONS    各 reason 计数（INSUFFICIENT_PRE5 / ZERO_DENOMINATOR /
                      MISSING_B2_BAR / OTHER_ERROR）
```

守恒约束（fail closed）：`DEFINED_TRUE_N + DEFINED_FALSE_N + UNDEFINED_N
== POPULATION_N`；任何 OTHER_ERROR 必须阻止 artifact 产出。

## 4. OUTCOME MAPPING

- strict binary：`WIN_S1 = 1`（成功），`LOSS_INVALID = 0`（失败）
- **CANCEL_GAP_INVALID 不进入 strict binary denominator**（仅 accounting；
  CANCEL_GAP_PRIMARY_POLICY = EXCLUDED_FROM_STRICT_DENOMINATOR）
- R 定义：仅 WIN_S1 + LOSS_INVALID 且 r_multiple 数值化（R-defined 子集）；
  `P(R>0)`、`mean_R`、`median_R` 在该子集上计算

## 5. PRIMARY METRICS（F22_TRUE vs F22_FALSE 两组对比，冻结）

strict denominator：WIN_S1 + LOSS_INVALID（CANCEL_GAP_INVALID 排除）。

- `FAIL_RATE = LOSS_INVALID / (WIN_S1 + LOSS_INVALID)`（即 1 − strict_win_rate）
- `DELTA_FAIL_RATE = FAIL_RATE(F22_TRUE) − FAIL_RATE(F22_FALSE)`
- `OR_FAILURE = odds(LOSS_INVALID | F22_TRUE) / odds(LOSS_INVALID | F22_FALSE)`，
  其中 odds(LOSS_INVALID | group) = LOSS_INVALID / WIN_S1（组内）
- 报告：各组 N、WIN_S1、LOSS_INVALID、CANCEL_GAP、FAIL_RATE、
  strict_win_rate、OR_FAILURE、DELTA_FAIL_RATE，以及 R-defined 子集的
  P(R>0)、mean_R、median_R（**P(R>0) 仅 secondary/descriptive，不进 gate**）

## 6. VERDICT GATE（预注册唯一 gate，冻结不变）

```
DELTA_FAIL_RATE > 0 AND OR_FAILURE > 1  →  SUPPORTED_DIRECTIONALLY
（F22_TRUE 组失败率更高 → 支持"F22_TRUE 预示失败风险"）
否则                                      →  REJECT
```

- SUPPORTED_DIRECTIONALLY ≠ VALIDATED ≠ PROMOTED
- 若 DELTA_FAIL_RATE < 0（F22_TRUE 反而更成功）→ REJECT 该假设并记录
  方向反转（observation）
- 不允许替换/增补 metric 改变 verdict；P(R>0) 不得进入 gate
- **PRIMARY_METRIC_UNDEFINED**（F22 primary 无 rho；此术语替代 F20 时代的
  rho-undefined 概念）→ **FAIL CLOSED**（抛错不产出 artifact），不得映射为
  REJECT：
  - 任一组 strict denominator N < 2（zero cell）
  - odds denominator 为 0（组内 WIN_S1 = 0 或 LOSS_INVALID = 0 → OR_FAILURE
    无法计算）
  - 其他 primary metric undefined
- **禁止 continuity correction / 0.5 correction**（预注册不冻结修正项）

## 7. PRIMARY SMALL_CELL POLICY（verdict precedence 冻结）

- F22_TRUE 或 F22_FALSE 组 strict denominator **N < 20** →
  `PRIMARY_SMALL_CELL` → `STATUS = INSUFFICIENT_PRIMARY_N`
  - **禁止 SUPPORTED_DIRECTIONALLY**（小样本不得产生支持结论）
  - primary metrics 仍可 descriptive 输出，但结论级别固定为
    INSUFFICIENT_PRIMARY_N（不是 REJECT、不是 SUPPORTED）

## 8. SECONDARY DESCRIPTIVE（仅描述，不改变 verdict）

- stage composition：B2_READY / B2_CONFIRMED 每层 F22_TRUE vs F22_FALSE 的
  FAIL_RATE、P(R>0) 方向；任一层任一侧 N < 20 → SMALL_CELL 排除
- timing composition：T1-2 / T3 / T4-5 / T6-10（days_since_anchor）同上
- R 尾部诊断（H4B right-tail caveat）：R-defined 子集的
  p90/p95/p99/max/top1pct_contribution/trim_mean——不作为 gate
- 各组 descriptive 表（N、strict_win_rate、FAIL_RATE、P(R>0)、mean_R、
  median_R、CANCEL_GAP 计数）

## 9. PIT

- b2_date = as_of = episode.signal_date（B2 日收盘后信息；EOD）
- F22 内部只使用 trade_date < b2_date 的 visible sessions（PRE5）；
  future rows 物理存在但不得影响（F22 内部排除 + 测试锁定）
- INVALID_B2_OHLCV 由 canonical DailyBar validation 上游 fail closed
- 禁止 full-market 再生、禁止 forward/生产路径

## 10. PROVENANCE

- episodes：66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093
  （outcome-snap corrected-b2-trigger-outcome，31422）
- daily：e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
  （canonical daily bars）
- CONTRACT_HEAD：d3325e2；IMPLEMENTATION_HEAD：cd3d676；
  PREREG_HEAD：（本 commit）
- SHA 门禁、无 DataFrame bypass、accounting fail closed（沿用 F20 标准）

## 11. FORBIDDEN ANALYSES（冻结禁令）

- 禁止 threshold mining（K、1.5 或任何新 cut）
- 禁止 outcome-aware 子组挖掘（stage/timing/其他切分后看 outcome 再选组）
- 禁止用 F22 分布（quantile/比值区间）做 outcome-conditioned 切分
- 禁止修改 population 后重跑、禁止同样本 rescue F22
- 若发现有趣区间：只能记 NEW_HYPOTHESIS，留给 future / new sample 验证

## 12. 预注册纪律

- `OUTCOME_AWARE_CONTRACT_CHANGE = False`
- `THRESHOLD_SEARCH = False`
- `SUBGROUP_RESCUE_ALLOWED = No`
- `NEW_HYPOTHESES = []`（正式报告时如实填写）
- undefined F22 只做 accounting，不进入 primary population

---

*本文件为预注册设计，不含任何 outcome 结果。正式验证脚本与报告将在后续
独立任务中实现（SHA 门禁 + fail-closed + 冻结 gate）。验证未运行。*
