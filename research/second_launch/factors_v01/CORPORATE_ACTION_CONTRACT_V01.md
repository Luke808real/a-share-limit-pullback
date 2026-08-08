# CORPORATE ACTION CONTRACT V01

> R1B.1 — CA truth source、事件定义、factor 依赖矩阵与 V01 政策（冻结）
> 数据仅用于审计（未计算 factor value）；无 outcome-guided 决策

## 1. CA truth source（冻结）

```text
CA_MASK_TRUTH = validated adjustment-factor event
  source  : data/raw/tushare/adjustment_factor/*.parquet（35 files）
  schema  : (code, trade_date, adj_factor decimal128(28,10))
  coverage: 2024-01-02 .. 2026-07-31；5,657 codes；3,391,611 rows
            重复 (code, date) 44,658 组全部值一致（0 冲突，确定性去重安全）
            null adj_factor = 0；nonpositive = 0

PRECLOSE_DIVERGENCE = AUDIT / SECONDARY_CONFIRMATION（非唯一 truth）
  source  : warehouse reconciliation CORPORATE_ACTION_PRECLOSE_DIVERGENCE
            （tushare adjusted preclose vs akshare unadjusted preclose 分歧 +
             pct_change 一致性确认；tolerance price_relative 0.001 /
             price_absolute 0.01）
```

## 2. CA event 定义（冻结）

```text
CA_EVENT(s) = adj_factor(s) != adj_factor(previous stock session of same code)

规则：
  - 比较为精确 decimal 比较（adj_factor 为 decimal128(28,10)，无浮点容差问题；
    若未来源精度变化需显式 tolerance，默认 0）
  - 同一 stock 首次观测到的 adj_factor 行不算 CA event
  - 窗口内任一所需 session 缺少 adj_factor 行 => CA_UNKNOWN：
    不得当作 no-CA，跨 session factor 一律 NULL（CORPORATE_ACTION_UNSAFE）
  - 事件检测按该股自身 session 序（前一有数据的 session）
```

## 3. R1B.1 实测事件交叉（research-case 所需日期，非全市场）

```text
ADJ_FACTOR_EVENT_N:   530（全市场 22,208）
PRECLOSE_DIVERGENCE_N: 619
BOTH:                  35
ADJ_ONLY:              495
PRECLOSE_ONLY:         584
```

两定义一致性很低（BOTH 仅 6.6% of adj events）→ 不能互换。
adj-factor 为主 truth；preclose divergence 仅作 audit 交叉提示。
（未按 outcome 选择定义。）

## 4. case 窗口覆盖（8,682 cases，bounded）

```text
CASE_WINDOW（{T0} ∪ {D} ∪ PRE_T0_21 ∪ T0..D）:
  FULL 7,725 / PARTIAL 957 / NONE 0
PRE_T0_21-only:      FULL 7,805 / PARTIAL 877 / NONE 0
#5 窗口（19 prior + T0）: FULL 7,800 / PARTIAL 882 / NONE 0
#7 窗口（21 prior）:     FULL 7,805 / PARTIAL 877 / NONE 0
```

PARTIAL 的含义 = 窗口内部分 session 无 adj_factor 行 → 该 case 对应跨 session
factor = NULL（fail closed），不推断。

## 5. factor × CA 依赖矩阵（冻结；25 行完整表见 daily_factor_contract_v01.csv）

```text
CA_SAFE:                         #21 days_since_t0（纯 session 计数）
CA_SAFE_SAME_SESSION_GEOMETRY:   #4 t0_close_location、#18 median_range_ratio、
                                 #19 range_slope（同日内比值，不依赖前 session 尺度）
CA_UNSAFE_CROSS_SESSION_PRICE:   #1 #2 #3 #6 #7 #9 #10 #11 #12 #13 #24 #25
                                 （跨 session 价格比值/收益；#24/#25 额外要求 D 自身
                                  非 CA event，否则机械假突破 → NULL）
CA_UNSAFE_LEVEL_ORDERING:        #5 #14 #22 #23
                                 （跨 session 价格水平比较/极值序；raw LOW/HIGH 尺度
                                  在 CA 后改变；#22 不再默认 CA-safe）
CA_UNSAFE_CROSS_SESSION_VOLUME:  #8 #15 #16 #17 #20
                                 （无法区分现金分红与股本变化型 CA → 无法证明
                                  share-count scale 连续 → fail closed：
                                  比较窗口内 CA event 或 CA unknown → NULL）
```

## 6. V01 CA policy（冻结）

```text
1. 窗口内任何 CA_EVENT 或 CA_UNKNOWN → 跨 session factor = NULL + CORPORATE_ACTION_UNSAFE
2. same-session geometry（#4/#18/#19）不依赖 previous-session scale → CA_SAFE
3. 跨 session volume（#8/#15/#16/#17/#20）：share-scale 连续性未证明 → 同样 fail closed
4. #24/#25：reference 窗口 CA 或 D 自身 CA → NULL
5. 不构造 adjusted price series；不做数据修复
```

## 7. #5 / #7 解锁依据（R1B.1）

四项条件全部满足：

```text
1. required window 可靠 adj_factor coverage：FULL 7,800-7,805 / 8,682（89.8-89.9%），
   NONE = 0；PARTIAL 882-877 由 fail-closed NULL 处理
2. CA event 可 deterministic identify（adj_factor 精确比较 + 首行排除）
3. missing adj-factor fail closed（CA_UNKNOWN → NULL）
4. 无需 adjusted price series（raw formula 在无 CA 窗口直接有效）
```

→ #5 t0_position_20d、#7 pre_t0_return_20d：`FROZEN_FOR_R2`（带 CA-NULL 政策）。
