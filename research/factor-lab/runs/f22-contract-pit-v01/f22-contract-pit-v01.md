# F22 CONTRACT PIT V01 — 巨量长上影 PIT 语义契约

日期：2026-08-16
分支：`research/f22-contract-pit-v01`
性质：contract-PIT 决策（**不实现、不跑 outcome、不搜索阈值**；先锁定"F22 是什么时点可用的因子"）

---

## 0. 决策背景

SOL（评审者）在 FACTOR LAB PHASE SYNTHESIS V01 收口（PASS / CLOSED，
AUTHORITY_HEAD 8322e8d）后指出：**F22 的 PIT 语义必须先于实现锁定**——
"完整长上影 K 线和全天 volume 只有收盘后才能确定"，因此 F22 很可能是
**EOD failure-risk diagnostic**（收盘后假突破识别），而不是 intraday B2
entry confirmation（盘中 B2 入场确认）。若语义不清，可能研究出统计有用、
但实盘 B2 入场时不可用的因子。

## 1. DECISION TIME CLASSIFICATION（决策时点分类）

**F22 = EOD（收盘后）因子**。

- 上影线 = high − max(open, close)，依赖当日完整 high/close → 仅收盘后确定
- 全天 volume → 仅收盘后确定
- **不可用于盘中 B2 买点决策**（INTRADAY_B2_ENTRY_ELIGIBLE = NO）
- 用途定位：收盘后识别"B2 日是否出现假突破/出货形态"（failure-risk
  diagnostic），与 F20（B2 放量主效应）互补：F20 回答"放量是否预示成功"
  （REJECT），F22 回答"B2 日形态是否预示失败/假突破"

## 2. B2 DATE SEMANTICS（冻结，与 F20 同构）

- `b2_date = episode.signal_date`（B2-stage episodes：B2_READY / B2_CONFIRMED，
  frozen semantics，与 h9 / F20 验证一致）
- `as_of = b2_date`（B2 日收盘后；PIT 窗口内全部 bar 的 trade_date <= as_of）
- 非 B2-stage episodes 不参与（与 F20 defined population 规则一致：
  population 由预注册确定，PIT 层不预过滤——见第 7 节）

## 3. F22 定义（契约草案）

| 组件 | 定义 |
| --- | --- |
| UPPER_SHADOW | `high(B2) − max(open(B2), close(B2))`；Decimal，可为 0 |
| BODY | `abs(close(B2) − open(B2))`；Decimal，可为 0 |
| 长上影判定式 | **乘法形式（无除法、无除零异常）**：`UPPER_SHADOW >= K * BODY`，且 `UPPER_SHADOW > 0`（严格正上影）——K 为待冻结阈值 |
| **BODY == 0 语义** | `K * BODY = 0`，判定退化为 `UPPER_SHADOW > 0`：冲高回落 doji（BODY=0 且 UPPER_SHADOW>0）→ 形态条件真；无影 doji/一字线（BODY=0 且 UPPER_SHADOW=0）→ 形态条件假。**不产生除零/NaN** |
| PRE5 | B2 之前**严格最后 5 个 visible trading sessions**（`trade_date < b2_date`；与 PRE20 同构；future rows 内部自动排除） |
| PRE5_N < 5 | → None（INSUFFICIENT_PRE5；与 F20 INSUFFICIENT_PRE20 同构） |
| 5 日均量 | `mean(vol, PRE5)`；均量为 0 → None（ZERO_DENOMINATOR） |
| VOL_RATIO | `vol(B2) / mean(vol, PRE5)` |
| 量比阈值 | `VOL_RATIO >= 1.5`（**已冻结阈值**：FACTOR_CATALOG 现定义 "vol 为 5 日均量 >= 1.5 倍"）；VOLUME_TRUE iff `VOL_RATIO >= 1.5` |
| SHAPE_TRUE | `UPPER_SHADOW > 0 AND UPPER_SHADOW >= K * BODY`（K=1.0 冻结后：`UPPER_SHADOW >= BODY`，且上影严格为正） |
| SHAPE_FALSE | 数据可计算但 SHAPE_TRUE 不成立（含 BODY=0 且 UPPER_SHADOW=0；UPPER_SHADOW < BODY）——**defined FALSE，非 undefined** |
| F22_TRUE | `SHAPE_TRUE AND VOLUME_TRUE`；否则 **F22_FALSE（defined）** |
| 上影/实体阈值 K | **OWNER_FROZEN = 1.0**（SOL 决策：`UPPER_SHADOW >= BODY`，"上影至少不短于实体"；理由：Catalog 无既有数值 authority；1.0 最小自然可解释；VOL_RATIO>=1.5 已有强量能条件无需收窄；冻结后禁止在当前 frozen outcome 上重选 K） |

## 4. THRESHOLD STATUS（已冻结，不再 DECISION_REQUIRED）

- F22_K = **1.0**；THRESHOLD_STATUS = **OWNER_FROZEN**（SOL 2026-08-16 决策）
- THRESHOLD_SOURCE：FACTOR_CATALOG 占位（"上影线/实体 >= 阈值"）→ 由 Owner 补全为 1.0
- 冻结后禁止：在当前 frozen sample 上重新选择 K / outcome-aware 调整
- 量比 1.5x 维持 CATALOG 既有定义

## 5. BODY_ZERO_POLICY（BODY_ZERO ≠ undefined）

- BODY = 0 是**合法 K 线状态**（doji / 十字星），不是 undefined
- 判定式 `UPPER_SHADOW >= K * BODY`（K=1.0）在 BODY=0 时退化为
  `UPPER_SHADOW >= 0`；配合严格正上影规则 `UPPER_SHADOW > 0`：
  - BODY = 0 且 UPPER_SHADOW > 0（冲高回落 doji）→ **SHAPE_TRUE**
  - BODY = 0 且 UPPER_SHADOW = 0（无影 doji / 一字线）→ **SHAPE_FALSE（defined）**
- **BODY_ZERO 不得进入 undefined reasons**（与第 6 节一致）
- 全程无除法、无除零异常、无 NaN 占位（不做 inf 填充）

## 6. FACTOR DOMAIN、BOOLEAN DEFINED SEMANTICS 与验证人群

- FACTOR_DOMAIN：**B2 event EOD failure diagnostic**（收盘后识别 B2 日假
  突破/出货形态）
- **BOOLEAN DEFINED SEMANTICS**：F22 是布尔因子（F22_TRUE / F22_FALSE）。
  defined 条件**只取决于数据是否可计算**：
  - B2 OHLCV 存在且合法（INVALID_B2_OHLCV → undefined）
  - PRE5_N == 5（不足 → INSUFFICIENT_PRE5 → undefined）
  - PRE5 mean volume > 0（为 0 → ZERO_DENOMINATOR → undefined）
  - 以上全部满足 → **F22 必须 defined**：F22_TRUE iff
    `SHAPE_TRUE AND VOLUME_TRUE`，否则 F22_FALSE
  - **不得**因 UPPER_SHADOW < BODY 或 VOL_RATIO < 1.5 记为 undefined
    （否则未来验证只剩 F22_TRUE，没有对照组）
- UNDEFINED_REASONS（仅数据不可计算类）：INSUFFICIENT_PRE5 /
  ZERO_DENOMINATOR / MISSING_B2_BAR / INVALID_B2_OHLCV / OTHER_ERROR
  **不得有**：BODY_ZERO / THRESHOLD_NOT_MET
- FUTURE_VALIDATION_POPULATION：resolved episodes（WIN_S1/LOSS_INVALID/
  CANCEL_GAP_INVALID）AND `setup_stage ∈ {B2_READY, B2_CONFIRMED}`
  （**domain selection**——F22 的 factor domain 本身就是 B2 event failure
  diagnostic，与 F20 的"不得 stage 预过滤"不同；F20 是 prereg population
  已冻结为全部 resolved，F22 是 domain 定义即 B2-stage）
  - `b2_date = episode.signal_date`；F22 用 B2 日数据（as_of = b2_date，
    PIT 安全——收盘后信息）
  - **population 内禁止**：outcome pre-filter、F22_TRUE/FALSE pre-filter；
    每个 episode 都必须尝试 materialize F22
- 验证设计（后续独立任务）：布尔因子预注册 outcome validation（方向性
  假设"F22_TRUE → 失败概率更高"，pre-register 后再定检验，本任务不预写）

## 7. PIT 纪律（与 F20 对齐，population 差异已明确）

- **F20 vs F22 population 差异**：F20 的 prereg population 冻结为全部
  resolved（不得 stage 预过滤）；F22 的 FACTOR_DOMAIN 本身就是 B2 event
  failure diagnostic → population = resolved AND stage ∈ {B2_READY,
  B2_CONFIRMED} 是 **domain selection**，不是 population bug
- population 内禁止：outcome pre-filter、F22_TRUE/FALSE pre-filter（每个
  episode 都必须尝试 materialize F22）
- SHA 门禁、无 DataFrame bypass、accounting fail closed（沿用 F20 标准）
- future rows 由 factor 内部排除（`trade_date < b2_date`），caller
  pre-truncation 仅是 hygiene
- 本任务不读取 outcome、不跑验证、不搜索阈值（K 已由 Owner 冻结为 1.0）

---

*本文件为 contract-PIT 决策，不含 outcome 结果。F22_K = 1.0（OWNER_FROZEN）；
契约一致性问题（BODY_ZERO、THRESHOLD_NOT_MET）已按 SOL review 修正。*
