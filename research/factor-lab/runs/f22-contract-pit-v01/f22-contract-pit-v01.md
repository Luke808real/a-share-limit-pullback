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
| 量比阈值 | `VOL_RATIO >= 1.5`（**已冻结阈值**：FACTOR_CATALOG 现定义 "vol 为 5 日均量 >= 1.5 倍"） |
| F22_TRUE | 形态条件（`UPPER_SHADOW > 0 AND UPPER_SHADOW >= K*BODY`）AND 量比条件（`VOL_RATIO >= 1.5`） |
| 上影/实体阈值 K | **未冻结**（FACTOR_CATALOG 仅 ">= 阈值" 占位）→ 见第 4 节 |

## 4. THRESHOLD DECISION REQUIRED（上影/实体阈值）

- F22_EXISTING_THRESHOLD：上影/实体比的**具体阈值在 Catalog 中未定义**
  （仅 ">= 阈值"占位）；量比 1.5x 已有定义
- THRESHOLD_SOURCE：FACTOR_CATALOG（2026-08-16 现状）
- **THRESHOLD_DECISION_REQUIRED = YES**
- 建议初始契约值（待 SOL 确认后冻结于预注册）：`UPPER_SHADOW >= BODY`
  （ratio >= 1.0，即上影不短于实体——"长上影"的最小自然定义）
- 备选（若 SOL 认为过宽/过窄）：1.5 / 2.0——**必须在预注册前冻结，
  禁止 outcome-aware 调整**（F20 审计确立的纪律）

## 5. BODY_ZERO_POLICY（乘法式，无除零）

- 判定式 `UPPER_SHADOW >= K * BODY` 在 BODY=0 时自然退化为
  `UPPER_SHADOW >= 0`；配合显式严格正上影规则 `UPPER_SHADOW > 0`：
  - BODY = 0 且 UPPER_SHADOW > 0（冲高回落 doji）→ 形态条件 **真**
  - BODY = 0 且 UPPER_SHADOW = 0（无影 doji / 一字线）→ 形态条件 **假**
- 全程无除法、无除零异常、无 NaN 占位（不做 inf 填充）

## 6. FACTOR DOMAIN 与验证人群

- FACTOR_DOMAIN：**EOD failure-risk diagnostic**（收盘后识别 B2 日假突破/
  出货形态）
- FUTURE_VALIDATION_POPULATION：B2-stage resolved episodes
  （WIN_S1/LOSS_INVALID/CANCEL_GAP_INVALID），`b2_date = signal_date`，
  F22 使用 B2 日数据（as_of = b2_date，PIT 安全——收盘后信息）；
  defined = F22 各组件全部可计算（BODY>0、PRE5_N==5、均值非零、量比与
  上影比通过阈值）；undefined 单独 accounting（INSUFFICIENT_PRE5 /
  ZERO_DENOMINATOR / BODY_ZERO / 其他）
- 验证设计（后续独立任务）：布尔/连续因子 → 预注册 outcome validation
  （F22 为假突破信号，方向性假设为"F22 为真 → 失败概率更高"，
  pre-register 后再定检验，本任务不预写）

## 7. PIT 纪律（与 F20 对齐）

- 禁止在 factor 调用前按 stage 预过滤（population 由预注册冻结）
- SHA 门禁、无 DataFrame bypass、accounting fail closed（沿用 F20 标准）
- future rows 由 factor 内部排除（`trade_date < b2_date`），caller
  pre-truncation 仅是 hygiene
- 本任务不读取 outcome、不跑验证、不搜索阈值

---

*本文件为 contract-PIT 决策，不含 outcome 结果。上影/实体阈值待 SOL 确认后
在预注册中冻结。*
