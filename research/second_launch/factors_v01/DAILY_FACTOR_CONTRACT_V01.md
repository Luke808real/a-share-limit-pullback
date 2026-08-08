# DAILY FACTOR CONTRACT V01

> R1B — 25 个 DAILY factors 的冻结数学合同（formula pre-registration）
> AS_OF: 2026-08-08 · research-only；不实现 extractor、不计算全量、不做归因
> 输入冻结：`SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE`（8,682 行，immutable verify PASS）

## 0. Notation 与 PIT 边界（冻结）

```text
T0 = case.anchor_date   （首个启动日，冻结 episodes 的 anchor）
D  = case.candidate_date（候选日 / feature as-of 日）

所有 factor 仅使用 data_date <= D 的信息：
  - 该股自身 canonical bar 序列（feature snapshot snap-2026-07-31-b5f84004de8a）
  - T0 / D / s1 / invalid 等来自冻结 case 的 D-1 字段
禁止进入 formula：outcome_3d / outcome_5d / first_event_* / time_to_* / D 之后任何 bar
标签只能以后 join。
```

## 1. 时间窗口（冻结）

```text
PRE_T0_n        = T0 之前的 n 个该股 trading session（不含 T0）
T0              = session offset 0
PULLBACK_PRE_D  = T0 < date < D
PULLBACK_ASOF_D = T0 < date <= D
D               = candidate session
```

逐 factor 使用窗口见 contract CSV 的 `window` 列。关键规则：

- F2 / F3 / F5 默认窗口 = `PULLBACK_ASOF_D`（**含 D**；D 的 bar 在 D 收盘可得，
  PIT 安全）。T0 自身永不进入 pullback 窗口（T0 的 low/close 是启动日属性，不是回调整理）。
- F6 的 reference（`pullback_high_pre_D`）= `PULLBACK_PRE_D`，**绝不含 D**（避免 self-reference）；
  D 只作为被比较的 current/candidate session。

## 2. Trading-session 契约（冻结）

```text
session = 该股票实际存在的 canonical bar 行（按 trade_date 升序）
时间距离 = stock session index，不是 calendar day
停牌 / no-bar 日：该日不存在 session
  missing session != zero-volume session
  禁止伪造 volume=0、禁止把 missing 日算作 quiet day / contraction
```

counting convention（冻结）：

```text
T0 = offset 0
T0 之后第一个 session = offset 1
... D = offset days_since_t0
```

## 3. Price basis / corporate action 契约

canonical daily 为 **raw/unadjusted price**（R0 确认；不构造新 adjusted series）。

```text
PRICE_BASIS =
  RAW_WITH_CA_EXCLUSION（默认）
  | BLOCKED_PENDING_CA_POLICY（长窗口 factor）

CA 检测（fail closed，不依赖新数据）：
  session s 为除权除息日 ⇔ |preclose_s − close_{s-1}| > 0.005 * close_{s-1}
  （tushare 在除权日提供 adjusted preclose；AKShare 提供未调整前收；
   canonical 的 preclose 在 CA 日可能为调整口径 —— 见
   tests/test_corporate_action_preclose.py 与
   warehouse.reconciliation.CORPORATE_ACTION_PRECLOSE_DIVERGENCE）

政策：
  - factor 窗口内检测到 CA session → NULL + CORPORATE_ACTION_UNSAFE
  - T0 日为 CA 日 → 所有引用 PRECLOSE0 / T0 OHLC 的 factor → NULL
  - 长窗口 factor（pre_t0_return_20d / t0_position_20d）→ BLOCKED_PENDING_CA_POLICY
    （待 R1B.1 冻结 CA 排除/连续价政策后解除）
  - 本轮不做数据修复
```

可用数据（targeted 检查）：

- raw tushare `adjustment_factor`（35 files，2024-01-02 ~ 2026-07-31）—— 存在但未验证为
  PIT 连续价 helper，本轮不使用
- 仓库无已验证的 PIT-safe continuous-price research helper（检查
  src/limit_pullback/warehouse/* 与 tests/test_corporate_action_preclose.py）

## 4. 数值通用契约（冻结）

```text
returns / ratios : decimal fraction（0.10 = 10%）
count            : integer
slope            : per stock trading session（OLS，numpy polyfit degree 1）
storage          : full precision，存储值不做显示舍入
无 winsorization / clipping / imputation；UNKNOWN != 0
分母 <= 0 或 == 0 → NULL + 对应 reason（禁止 inf / 任意 epsilon）
```

## 5. 日线 OHLC 顺序安全（冻结）

Daily OHLC 不提供日内顺序：禁止假设同日 high 先于 low。

- `max_drawdown_from_post_t0_high` 使用 **previous-session running peak** 定义：
  session j 的 prior_peak_j = max(T0_high, pullback sessions 中严格早于 j 的 highs)；
  dd_j = low_j / prior_peak_j − 1；factor = min(dd_j over window)。**包含 T0_high** 作为初始峰值。
- 其余 factor 只使用 daily close / high / low 的各自序列，不做同日 high-vs-low 排序假设
  （唯一同日组合是 t0_close_location 的 (H0, L0)，其语义即为“当日振幅内的收盘位置”，
   不涉及顺序）。

## 6. Formula contract（25 个）

窗口简记：`PB = PULLBACK_ASOF_D`（T0<date<=D）；`PRE_D = PULLBACK_PRE_D`（T0<date<D）。

### F1 — ATTACK / PRE / VOLUME（1–8）

| # | factor | formula | 备注 |
|---|---|---|---|
| 1 | t0_return | `C0 / PRECLOSE0 − 1` | T0 日 CA → NULL |
| 2 | t0_gap | `O0 / PRECLOSE0 − 1` | 同上 |
| 3 | t0_range_pct | `(H0 − L0) / PRECLOSE0` | 同上 |
| 4 | t0_close_location | `(C0 − L0) / (H0 − L0)` | `H0 == L0 → NULL`（ZERO_DENOMINATOR） |
| 5 | t0_position_20d | `(C0 − min_low_20) / (max_high_20 − min_low_20)` | 窗口 = **19 个 prior sessions + T0**（共 20）；需 ≥20 sessions；BLOCKED_PENDING_CA_POLICY |
| 6 | pre_t0_return_5d | `close(T0−1) / close(T0−6) − 1` | 5 个 return intervals；需 ≥6 prior sessions；窗口内 CA → NULL |
| 7 | pre_t0_return_20d | `close(T0−1) / close(T0−21) − 1` | 需 ≥21 prior sessions；BLOCKED_PENDING_CA_POLICY |
| 8 | t0_volume_ratio_5d | `V0 / mean(volume(T0−5..T0−1))` | 需 5 个 prior sessions；T0 不入 denominator；prior volume 非正 → NULL |

### F2 — HOLD（9–14）

| # | factor | formula | 备注 |
|---|---|---|---|
| 9 | pullback_depth_close | `min(close over PB) / C0 − 1` | PB 含 D |
| 10 | max_drawdown_from_post_t0_high | `min_j( low_j / prior_peak_j − 1 )`，prior_peak_j = max(T0_high, highs of PB sessions < j) | daily-order-safe；PB 含 D；无 PB session → NULL（EMPTY_PULLBACK_WINDOW） |
| 11 | impulse_retrace_ratio | `(C0 − min_pullback_close) / (C0 − PRECLOSE0)` | min_pullback_close over PB；`C0 − PRECLOSE0 <= 0 → NULL`；与 #12 EXACT_COLLINEAR |
| 12 | t0_gain_retention | `(min_pullback_close − PRECLOSE0) / (C0 − PRECLOSE0)` | 同上；`retention == 1 − impulse`（同一 min_pullback_close 时恒等） |
| 13 | low_vs_t0_mid | `min_pullback_low / T0_BODY_MID − 1` | `T0_BODY_MID = (O0 + C0) / 2`（非 (H0+L0)/2） |
| 14 | days_above_t0_mid | `count(close >= T0_BODY_MID over PB)` | **close-based**（非 low-based）；PB 含 D |

### F3 — CONTRACTION（15–20）

| # | factor | formula | 备注 |
|---|---|---|---|
| 15 | pullback_volume_ratio | `median(volume over PB) / V0` | V0<=0 → NULL |
| 16 | min_volume_ratio | `min(volume over PB) / V0` | 同上 |
| 17 | volume_slope | `OLS slope(log(volume_i / V0) ~ session_index_i)` | 需 ≥2 PB sessions 且 volume>0 |
| 18 | median_range_ratio | `median(range_i) / t0_range_pct`；`range_i = (H_i − L_i) / PRECLOSE_i` | t0_range_pct<=0 → NULL |
| 19 | range_slope | `OLS slope((range_i / t0_range_pct) ~ session_index_i)` | 需 ≥2 PB sessions |
| 20 | quiet_days_n | `count(volume_i / V0 < 1 AND range_i / t0_range_pct < 1)` | 固定结构定义（<1/<1），非阈值扫描；仓库无可比冻结定义（quiet_score 为未提交 forward-paper 日内百分位概念，不冲突） |

### F5 — TIME（21–23）

| # | factor | formula | 备注 |
|---|---|---|---|
| 21 | days_since_t0 | `D session offset`（T0=0，首个 post-T0 session=1） | integer |
| 22 | days_to_pullback_low | `first session offset of minimum LOW over PB`（1-based，从 T0+1 起） | 用 LOW；同值多次取 first |
| 23 | pullback_duration | **DECISION_REQUIRED**（见 §8 候选） | 候选 A：`D_offset − offset(last session attaining post-T0 running high)`；候选 B：`days_to_pullback_low`（= 完全重复，拒绝）；候选 C：`days_since_t0 − 1`（= 完全重复，拒绝） |

### F6 — ACTIVATION（24–25）

| # | factor | formula | 备注 |
|---|---|---|---|
| 24 | high_vs_pullback_high | `H_D / pullback_high_pre_D − 1` | `pullback_high_pre_D = max(high over PRE_D)`；**D 不入 reference**；无 PRE_D bar → NULL（EMPTY_PULLBACK_WINDOW） |
| 25 | close_vs_pullback_high | `C_D / pullback_high_pre_D − 1` | 同上 |

## 7. Contract collision audit

```text
EXACT_COLLINEAR:
  #11 impulse_retrace_ratio 与 #12 t0_gain_retention：
    同一 min_pullback_close + 同一分母 (C0 − PRECLOSE0)
    => t0_gain_retention == 1 − impulse_retrace_ratio（恒等，golden sanity 验证 =1.0 精确）
    R1B.1 处置（冻结）：#12 = PRIMARY；#11 = DERIVED_ALIAS（保留于 25-row 合同供 R2 QA 输出；
    univariate 独立维度只算 #12；multivariate 禁止同时放 #11+#12）

NEAR_STRUCTURAL:
  #15/#16/#17（pullback_volume_ratio / min_volume_ratio / volume_slope）：
    同一 PB 窗口 + 同一 V0 分母，median/min/slope 同一序列
  #18/#19（median_range_ratio / range_slope）：同一 range_i 定义与 t0_range_pct 基准
  #24/#25（high_vs_pullback_high / close_vs_pullback_high）：同一 reference 与窗口，
    仅 H_D vs C_D 差异
  #21/#22/#23（days_since_t0 / days_to_pullback_low / pullback_duration）：
    结构性依赖；#23 候选 B/C 与 #21/#22 完全重复（已拒绝）
  #3/#18（t0_range_pct 与 median_range_ratio 的分母基准）：
    共享 range 定义，但窗口不同（T0 vs PB），非 exact
```

## 8. DECISION_REQUIRED（6 项，含推荐）

1. **PULLBACK 窗口是否含 D**：推荐 **含 D**（PULLBACK_ASOF_D）——D 的 bar 在 D 收盘
   PIT 可得，且候选日几何是 setup 的本质信息。F6 reference 例外（不含 D，已冻结）。
   状态：已按推荐冻结（F2/F3/F5）。
2. **raw price 跨 corporate action 如何 fail closed**：CA session 检测
   （preclose_s vs close_{s-1} divergence）→ 窗口内命中即 NULL（CORPORATE_ACTION_UNSAFE）；
   长窗口 #5/#7 → BLOCKED_PENDING_CA_POLICY。
3. **max_drawdown 如何避免 daily OHLC 顺序假设**：previous-session running peak 定义
   （含 T0_high）→ 已冻结（#10）。
4. **days_above_t0_mid 用 close 还是 low**：推荐 **close-based**（`close >= T0_BODY_MID`）→
   已冻结（#14）。
5. **pullback_duration 到底是什么**：仓库无可信既有定义；候选 A（自最近新高以来的 session 数）
   是唯一与 #21/#22 不重复的独立概念 → **R1B.1 已冻结**（见 §13：#23 正式公式）。
6. **quiet_days_n 的 <1/<1 是否接受**：推荐接受为 V01 冻结定义（固定结构，非阈值扫描；
   与既有 quiet_score 概念不同）→ 已冻结（#20）。

## 12b. R1B.1 冻结决策汇总

```text
A. #11/#12 exact-collinear：PRIMARY / DERIVED_ALIAS（analysis_role 列）
B. metadata：#9 unit → decimal fraction（无 <=0 限制、不 clamp）；
   #14/#20 known_collinearity += NEAR_STRUCTURAL_WITH_TIME_EXPOSURE；
   #17 记录恒等 slope(log(vol_i/V0)) == slope(log(vol_i))
C. #23 pullback_duration 正式冻结（见下）
D. CA truth = validated adjustment-factor event；preclose divergence = audit only
E. 25 个 factor 全部完成 CA 依赖分类（ca_class 列；见 CORPORATE_ACTION_CONTRACT_V01.md）
F. #5/#7 解锁 → FROZEN_FOR_R2（CA 覆盖 FULL 89.8-89.9% / NONE 0；缺失 fail-closed NULL）
```

## 13. #23 pullback_duration（R1B.1 冻结）

```text
PEAK_REFERENCE_WINDOW = {T0} ∪ PULLBACK_PRE_D
peak_high = max(HIGH over PEAK_REFERENCE_WINDOW)
最高 HIGH 多次出现 → PRE_D_PEAK_OFFSET = LAST session offset attaining peak_high
pullback_duration = D_offset − PRE_D_PEAK_OFFSET

语义：candidate day D 到来之前，距最近一次有效价格峰值已过多少 stock trading sessions
T0 可以是 peak；D 绝不进入 peak reference
示例：T0 最高、D=T+4 → 4；T+2 创新高、D=T+5 → 3；T+3 与旧高相同、D=T+5 → 2（last occurrence）
无 T0/D bar → NULL（MISSING_T0_BAR / MISSING_D_BAR）
CA 政策：跨 session HIGH level → CA_UNSAFE_LEVEL_ORDERING（窗口 CA/unknown → NULL）
```

## 9. Missingness contract（冻结）

```text
MISSING_REASON ∈ {
  MISSING_T0_BAR, MISSING_D_BAR, INSUFFICIENT_PRE_T0_HISTORY,
  EMPTY_PULLBACK_WINDOW, INSUFFICIENT_PULLBACK_SESSIONS,
  ZERO_DENOMINATOR, NONPOSITIVE_VOLUME, CORPORATE_ACTION_UNSAFE,
  MISSING_PRECLOSE, MISSING_REQUIRED_COLUMN, OTHER
}
```

禁止填 0；`NULL + reason` 是唯一缺失表达。

## 10. Quality stratification（冻结，非 factor）

```text
candidate_reconciliation_status
feature_3d_has_provisional
label_5d_has_provisional
data_quality
quality_flags（含 INFERRED_LIMIT_ANCHOR / anchor_quality）
```

以上仅为 attribution strata，禁止混入 factor score。

## 11. 已知既有定义差异说明

- committed repo 中未发现任何已冻结的上述 25 个 factor 公式（targeted rg 无命中）
- `quiet_score` 仅存在于主 worktree 未提交的 forward-paper artifacts
  （research/bpoint/forward/*，intraday percentile 公式）——概念不同，不构成冲突；
  若未来需冻结，另行登记
- 研究文档（a-share-strategy-brain 04_Research/Second-Launch-Factor-Research-V01.md）
  的 F3/F5 均列出 quiet_days_n（双家族登记）——本契约归入 F3（CONTRACTION），
  在 F5 下不重复

## 12. 状态汇总

```text
FROZEN_FOR_R2: 25（含 #11 DERIVED_ALIAS）
DERIVED_ALIAS: 1（#11 impulse_retrace_ratio）
BLOCKED: 0
```
