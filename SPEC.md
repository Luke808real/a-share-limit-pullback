# A股涨停回调盘后筛选器规格

## 1. 当前交付范围

当前版本交付至“阶段1.5：纯策略计算引擎”：

- 冻结策略语义和状态不变量；
- 提供严格配置、枚举、Pydantic 输入输出模型；
- 提供只有两个方法的 Provider Protocol；
- 提供完全本地、默认禁止网络的测试骨架；
- 提供无副作用的 CLI 帮助骨架。
- 提供只接受本项目模型的纯函数策略引擎。
- 使用调用者提供的已有信号完成无状态快照推进。

当前版本不调用 AKShare 或 BaoStock，不建立 DuckDB，不读写 Parquet，不生成
HTML，不实现回测，不扫描市场，也不实现缓存、重试、回退、注册系统或机器学习。

## 2. 数值与时间类型

- 所有价格、比例、金额、换手率、收益率和评分使用 `Decimal`。
- 模型拒绝 Python `float`，防止二进制浮点数悄然进入领域对象。
- 交易日期使用 `date`。
- 抓取时间、运行时间和生成时间使用带明确时区的 `datetime`。
- 整数计数、窗口长度和成交量可以使用 `int`。

## 3. 双价格体系

### 3.1 raw_price

原始价格用于：

- 涨停价；
- 支撑和压力；
- B2 触发价；
- 初始及当前失效价；
- 回测成交价（后续阶段）；
- K线展示（后续阶段）。

### 3.2 point_in_time_continuous_price

历史当时可知连续价格用于：

- MA5、MA10、MA20、MA30、MA120、MA250；
- 均线粘合；
- 120 日位置。

连续收盘价只使用当日及以前的 `close/preclose` 链式构造：

```text
continuous_close[0] = raw_close[0]
continuous_close[t] =
    continuous_close[t-1] * raw_close[t] / raw_preclose[t]
```

禁止用今天重新计算的历史前复权序列进行严格回测。若 `preclose` 缺失、非正数
或明显异常，则不猜测连续价格；受影响指标不可用并记录质量标记。

120 日位置使用连续收盘价序列：

```text
position_120 =
    (continuous_close - rolling_min(continuous_close, 120))
    / (rolling_max(continuous_close, 120)
       - rolling_min(continuous_close, 120))
```

连续均线参与 raw 价格空间中的支撑或价格比较前，按评价日 T 重定基：

```text
raw_equivalent_ma_n[T] =
    continuous_ma_n[T] * raw_close[T] / continuous_close[T]
```

## 4. 状态、事件和人工复核

每个交易日恰好有一个 `setup_stage`：

- `NORMAL`
- `LIMIT_ANCHOR`
- `WATCH_PULLBACK`
- `B1_READY`
- `B2_READY`
- `B2_CONFIRMED`
- `INVALID`

同一交易日可以同时存在多个 `event_flags`：

- `NEAR_S1`
- `S1_BREAKOUT`
- `S2_EXHAUSTED`
- `SUPPORT_WARNING`

人工复核分组为：

- `STANDARD`
- `OPEN_SPACE`

S1 不存在的可操作信号进入 `OPEN_SPACE`，其 S1 快照和风险收益比都为
`null`。不得虚构目标价，也不得仅因缺少 S1 自动淘汰。

## 5. B2 冻结和确认

B2 判断禁止同一根 K 线循环引用：

1. 在进入 `B2_READY` 时冻结 `B2TriggerSnapshot`。
2. `eligible_from` 必须严格晚于 `frozen_as_of`。
3. 评价交易日 T 是否突破时，只能使用 T 之前冻结且已生效的触发价。
4. `B2_CONFIRMED` 必须满足：
   - `frozen_as_of < trade_date`
   - `eligible_from <= trade_date`
5. 确认日最高价不得参与重新生成一个更高的确认日触发价。

## 6. 快照生命周期

最小快照包括：

- `AnchorSnapshot`
- `SupportSnapshot`
- `B2TriggerSnapshot`
- `S1Snapshot`

生命周期约定：

- 确认有效锚点时冻结 anchor；
- 首次形成可操作的 B1/B2 setup 时冻结 support、initial invalid 和 S1；
- 进入 B2_READY 时冻结 B2 trigger；
- 同一 `setup_id` 的历史快照不得被改写；
- 新锚点产生时创建新的 `setup_id`。

Pydantic 快照模型本身不可变。同一 setup 的历史不可改写属于状态仓库不变量，
当前版本不实现状态仓库或持久化逻辑。

失效价允许收紧但不允许向下放宽：

```text
invalid_price >= initial_invalid_price
```

## 7. 评分

评分 Profile：

- `FULL`：涨停池关键字段完整；
- `PRICE_ONLY`：锚点通过历史日线推断。

`PRICE_ONLY` 不是自动负面评分。仅依赖涨停池且不可获得的规则不参与评分。

`ScoreBreakdown` 保存可评价规则的得分和最大分，并派生：

```text
available_score = sum(component_scores)
available_max_score = sum(component_max_scores)
normalized_score =
    quantize(available_score / available_max_score * 100, 0.01)
```

量化使用 `ROUND_HALF_UP`。调用者不能直接传入这三个派生字段。

缺失评分字段的规则：

- 不进入 `component_scores`；
- 不进入 `component_max_scores`；
- 不计零分；
- 不形成加分或风险理由；
- 加入 `unavailable_rules`；
- 记录 `MISSING_SCORE_FIELD:<rule_id>` 质量标记。

已知且表现不佳的规则仍是“可评价规则”，可以获得零分并形成风险理由。

## 8. 数据质量

`DataQuality`：

- `OK`：当前模型所需关键字段完整；
- `PARTIAL`：例如缺少历史涨停池，仍可按 PRICE_ONLY 评价；
- `DEGRADED`：部分非关键字段异常或质量下降；
- `UNUSABLE`：关键字段不足，不能形成可靠信号。

质量状态与评分 Profile 相互独立。

## 9. Provider 边界

Provider 只冻结两个同步方法：

- `fetch_daily_bars`
- `fetch_limit_up_pool`

输入输出必须使用本项目 Pydantic 模型，不暴露 DataFrame 或第三方库类型。
当前版本没有任何 Provider 实现。

## 10. CLI

`python -m limit_pullback --help` 只展示未来命令名和当前阶段说明。所有子命令均为
未实现占位并以非零状态退出，不访问网络、不创建数据文件且不产生其他副作用。

## 11. 阶段1.5纯函数入口

```python
evaluate_strategy(
    *,
    bars: Sequence[DailyBar],
    as_of: date,
    config: StrategyConfig,
    generated_at: datetime,
    limit_pool: Sequence[LimitUpRecord] = (),
    previous_signal: StrategySignal | None = None,
) -> StrategySignal
```

输入允许包含未来行，但引擎在入口处丢弃 `trade_date > as_of` 的日线和涨停池记录。
`bars` 必须包含 `as_of` 当日，并且只包含一个代码、每个日期至多一行。
`previous_signal` 必须早于 `as_of`，且代码和策略版本一致。

## 12. 确定性结构规则

### 12.1 涨停锚点

- 理论涨停价为 `preclose * (1 + limit_rate)`，按价格 tick 和
  `ROUND_HALF_UP` 取整。
- 收盘与理论涨停价的差不超过配置容差即为涨停收盘。
- 一字板：OHLC 都等于理论涨停价。
- T字板：开、高、收等于涨停价，低价低于涨停价。
- 只评价回看窗口中最近一次涨停收盘；更晚的一字板、T字板或连板不会回退到旧锚点。
- 价格序列中前一交易日不能涨停，最近两个涨停不能相邻。
- FULL 还要求涨停池连板数为 1，首次封板不晚于配置时间。
- 涨停池字段不完整时使用 PRICE_ONLY，封板时间不作为失败项。

### 12.2 支撑与压力

- 支撑候选：锚点价、锚点前平台高点、可用的 raw-equivalent MA。
- 压力候选：锚点前左侧高点、最近高点、涨停后首个配置窗口的最高点。
- 候选先按 `(price, source)` 排序；簇内最高价相对最低价不得超过聚类阈值。
- 因此聚类结果不依赖输入顺序，也不使用会扩大端点距离的链式聚类。
- 支撑优先级：离当前价最近、来源更多、含锚点价或 MA10。
- S1 为当前价上方下沿最低的压力簇；不存在则进入 OPEN_SPACE。

## 13. 形态与状态规则

### 13.1 形态

AIR_REFUEL 对以下可用项等权计数：价格保持、当前不低于锚点、振幅收窄、
最近成交量收缩、位于短均线附近。BEARISH_PULLBACK 对以下可用项等权计数：
出现阴线、触及支撑、成交量收缩、没有放量破位、当前止跌 K 线。

缺失项不进入分母；命中比例达到 YAML 阈值即标记相应形态，两种形态可以同时存在。

### 13.2 setup_stage

- `NORMAL`：回看窗口内没有有效锚点。
- `LIMIT_ANCHOR`：评价日就是有效锚点日。
- `WATCH_PULLBACK`：有锚点但 B1 多数条件未达到。
- `B1_READY`：B1 可用条件命中比例达到阈值，且存在支撑和初始失效价。
- `B2_READY`：上一信号为同 setup 的 B1_READY 时冻结触发价；或已有未确认触发价。
- `B2_CONFIRMED`：当日最高价突破已冻结且已生效的触发价，B2 可用条件命中比例达到阈值。
- `INVALID`：触及当前失效价，或触发任一严重结构失效条件；同 setup 中为终态。

B2 触发价为冻结日最近配置窗口最高价乘 trigger buffer，按价格 tick 取整。
冻结日当天不能确认。

### 13.3 event_flags

- `SUPPORT_WARNING`：最低价进入支撑上沿配置距离内，且尚未触及失效价。
- `NEAR_S1`：最高价进入 S1 下沿配置距离内。
- `S1_BREAKOUT`：收盘站上 S1 上沿及配置 buffer。
- `S2_EXHAUSTED`：必须触及 S1，且回落、上影、放量、未站稳等可用条件达到多数阈值。

### 13.4 INVALID

以下任一条件触发：

- 收盘触及冻结失效价；
- 收盘有效跌破支撑下沿；
- 同时跌破锚点价和 raw-equivalent MA10；
- 放量跌破 B1 参考低点；
- 配置天数的连续放量阴线；
- 前一日破位且当前仍未收回。

## 14. 评分和快照

评分按 Profile 中规则逐项产生满分、部分分或零分解释。不可计算的规则从分子、
分母和理由中移除，并生成 `MISSING_SCORE_FIELD:<rule_id>`。PRICE_ONLY 本身不扣分。

锚点按 setup 创建时冻结；支撑、初始失效价和 S1 在首次可操作信号形成时冻结；
B2 触发价在从 B1 进入 B2_READY 时冻结。调用者传入同 setup 的上一信号后，引擎
复用快照。当前失效价使用已有值和新候选的较高者，绝不下移。状态持久化仍不在
当前范围内。
