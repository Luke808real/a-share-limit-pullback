# A股涨停回调盘后筛选器规格

## 1. 当前交付范围

当前版本交付至“阶段2C.2A：多数据源历史行情仓库与每日增量更新”（叠加在已冻结
的Phase 2C.1之上）：

- Tushare Pro 主日线、交易日历、股票基本信息、复权因子、`daily_basic`、
  停复牌与每日涨跌停价格；
- AKShare（sina 日线端点）日线交叉验证，AKShare/东方财富涨停池
  （首次/最后封板时间、炸板次数、连板数、行业）；
- BaoStock 历史补录与第三来源校验，不作为当日数据新鲜度唯一门禁；
- Parquet 原始层 + DuckDB 元数据 + Parquet canonical 层 + 不可变快照；
- `bootstrap` 历史回填与 `update` 每日幂等增量；
- `provider-probe`、`data-status`、`data-validate` 运维命令；
- 显式对账（`PROVISIONAL / CONFIRMED / INCOMPLETE / CONFLICTED /
  QUARANTINED`）与 point-in-time 读取保证。

### 1.1 Phase 2C.1 冻结内容（不变）

- 冻结策略语义和状态不变量；
- 提供严格配置、枚举、Pydantic 输入输出模型和纯函数策略引擎；
- 提供固定职责的 BaoStock 日线与 AKShare 涨停池适配器；
- 提供任意合法沪深主板单股票的单日 `inspect` 和逐日内存 `replay`；
- 默认测试完全封锁网络，真实 Provider 测试必须显式选择 `integration`。

### 1.2 阶段边界（2C.2A 不实现）

- 不实现全市场 screen、候选排名、HTML 报告、信号收益统计、成交模拟、
  资金管理、回测、自动交易或分钟级策略；
- 不自动选择冲突数据、不静默回退 Provider、不把不同 Provider 的字段拼成
  一根K线；
- 真实行情、Token 与 `.env` 一律不进 Git。

### 1.3 数据源职责

| 数据源 | 职责 |
| --- | --- |
| Tushare Pro | 主日线、交易日历、股票基本信息、复权因子、daily_basic、停复牌、涨跌停价 |
| AKShare / 东方财富 | 涨停池（封板时间/炸板/连板/行业）、日线交叉验证 |
| BaoStock | 历史补录、第三来源校验 |

### 1.4 对账与 canonical 规则

- 不同来源同一 `code/date` 分别保留完整记录（`raw/<provider>/daily_bars`）；
- 禁止字段级拼接：canonical 行整体取自 `selected_provider` 的原始行；
- 主源（Tushare）与校验源（AKShare）一致 → `CONFIRMED`；
- BaoStock 明确延迟但 Tushare 与 AKShare 一致 → 仍 `CONFIRMED`，并在审计
  记录 `BAOSTOCK_LAGGING`；
- OHLC 超出容差 → `CONFLICTED`，进入 quarantine，不发布 canonical；
- 容差只吸收格式/单位微差（价格相对 0.1% 且绝对 0.01 元，量额相对 0.5%），
  不得掩盖真实价格冲突；
- 单来源或缺少主/校验配对 → `PROVISIONAL`；日历交易日无任何来源 →
  `INCOMPLETE`；所有选择与拒绝原因进入 `reconciliation_results`。

### 1.5 Point-in-time 保证

- 每个快照包含 `snapshot_id / created_at / as_of / provider_versions /
  source_file_hashes / canonical_file_hashes / reconciliation_policy_version`；
- `as_of=T` 读取只使用 `trade_date <= T` 且快照边界（as_of）不晚于 T 的
  最早发布版本；旧快照文件不可变；
- Provider 修订只产生新快照，未来数据不会改写历史读取结果。

## 1.6 Phase 2C.2B 离线全市场 setup 扫描

- 只读取已发布 canonical 快照：日线仅消费 `CONFIRMED` 行，锚点来自 canonical
  limit_up_pool；screen 全程禁止联网；
- 初次运行按有效锚点窗口建立活动 setup；日常运行只推进昨日活动 setup 与当日
  新 Anchor；状态按代码持久化并绑定 `bars_prefix_hash`，基础行情被修订时自动
  丢弃状态并重算；
- 复用冻结策略引擎（`evaluate_strategy` 与 replay 相同调用序列），不复制或
  重写 B1/B2 逻辑；`strategy.yaml` 阈值不变；
- 输出状态：`NEW_ANCHOR / WATCH_PULLBACK / B1_READY / B2_READY /
  B2_CONFIRMED / INVALID / EXPIRED`；保存 setup 快照、评分、Support、Invalid、
  B2 Trigger、S1、Entry Room、事件与数据质量；
- 每次运行绑定 strategy commit、config hash、dataset snapshot 与 output hash；
  相同输入必须产生相同输出；全量重建与逐日增量一致；未来快照不修改历史结果；
  全市场结果与随机单股 replay 逐字段一致；对既有 8 案例回归；
- 不实现 B1_PREP、挂单、持仓、S 点卖出、回测、HTML 报告或自动交易。

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

同一交易日可以同时存在多个 `event_flags`，但 `NEAR_S1` 与 `S1_BREAKOUT`
严格互斥：

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
   - 当日最高价达到或突破冻结触发价
   - 当日收盘价不低于冻结触发价
   - 除上述两个强制门槛外，其余可用 B2 量价条件命中比例达到配置阈值
5. 确认日最高价不得参与重新生成一个更高的确认日触发价。

若最高价突破但收盘未站稳，setup 保持 `B2_READY`，并在 `b2_quality` 风险解释中
记录“盘中突破B2触发价但收盘未站稳”。

## 6. 快照生命周期

最小快照包括：

- `AnchorSnapshot`
- `SupportSnapshot`
- `InvalidPriceSnapshot`
- `B2TriggerSnapshot`
- `ResistanceSnapshot`
- `S1Snapshot`

生命周期约定：

- 确认有效锚点时冻结 anchor；
- `LIMIT_ANCHOR` 只冻结 anchor；
- 首次形成 `B1_READY` 时冻结 support、initial/current invalid、
  immediate resistance 和 target S1；
- 进入 B2_READY 时冻结 B2 trigger；
- support、invalid、S1 和 B2 trigger 都同时保存 `frozen_as_of` 与
  `eligible_from`，并满足 `eligible_from > frozen_as_of`；
- T 日事件和失效判断只能使用从 T-1 信号沿用且 `eligible_from <= T` 的快照；
- T 日新形成的快照可以输出给下一交易日，但不能反向影响 T 日事件或失效；
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

策略信号另外派生两层分数：

- `setup_quality_score = score.normalized_score`，只评价锚点、回调、支撑、
  量价、K线、均线、形态和B1/B2结构质量；不得读取S1、risk/reward或entry room；
- `entry_quality_score`只在`B1_READY`、`B2_READY`、`B2_CONFIRMED`存在，
  用setup质量作为基准，再应用入场空间和可用risk/reward的折减；结构未到入场阶段
  时为null，已被入场规则淘汰时为0。

缺少可靠target S1不会作为零分条件：OPEN_SPACE不应用entry room或risk/reward
折减，继续人工复核。

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
当前固定实现为 BaoStock 原始历史日线和 AKShare 涨停池；不实现静默切换、工厂、
注册、缓存、重试或回退。

BaoStock在返回`DailyBarsResult`前按`(code, trade_date)`检查重复。完全相同的
重复行确定性保留一条，质量至少为PARTIAL并记录
`DUPLICATE_DAILY_ROW_DEDUPED:<code>:<date>`；字段冲突则抛出
`CONFLICTING_DUPLICATE_DAILY_ROW:<code>:<date>`。最终日线按代码和日期排序。
query失败时仍尝试logout，logout失败不能覆盖原始query异常；query成功后logout
失败则明确报错。

## 10. CLI

`python -m limit_pullback --help` 展示当前阶段说明；`inspect` 与 `replay` 是唯一
已实现子命令，均仅支持指定单股票、以内存 JSON 输出且不自动写文件。`--code`
使用第21节的共享主板代码解析器。成功退出码为0，参数错误为2，Provider或业务
错误为1；参数与业务错误均只向stderr输出结构化JSON。任何未实现子命令都以非零
状态退出且不产生副作用。

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
- 压力候选：涨停前左侧有效高点、涨停后首次上冲高点、最近20日和60日有效
  高点，以及最近60日局部摆动高点形成的密集压力簇。
- 冻结支撑时以当日收盘价为 `reference_close`。默认
  `support_center <= reference_close`；YAML 只允许
  `max_above_reference_close` 的极小上方容差，超过上限的候选转为压力候选。
- 候选先按 `(price, source)` 排序；簇内最高价相对最低价不得超过聚类阈值。
- 因此聚类结果不依赖输入顺序，也不使用会扩大端点距离的链式聚类。
- 支撑优先级：离当前价最近、来源更多、含锚点价或 MA10。
- 锚点价作为仅用于识别排除簇的reference，不直接成为压力候选。
- 与锚点reference同簇、与SupportSnapshot重叠、或下沿不高于B1冻结参考收盘价的
  压力簇全部排除。
- `immediate_resistance` 是剩余簇中距离B1参考价最近的压力。
- B1当日的`expected_b2_trigger_price`只用B1当日及以前数据，基础值为B1日最高价
  乘trigger buffer。若immediate簇与该预期位重叠，它被视为预期B2平台；
  `target_s1`继续选择其上方最近的有效簇。否则immediate可以同时成为target S1。
- target S1的下沿必须严格高于预期B2触发价。下一日实际冻结的B2触发价可以因
  新K线而高于旧target；此时不改写target，而由entry room输出`NONE`。
- 每个真实压力候选输出`source`、`price`、所属`cluster`、
  `excluded_reason`和`selected_reason`。候选审计与压力快照在B1冻结后沿用。
- 没有可靠target S1时进入OPEN_SPACE，不合成目标价。

## 13. 形态与状态规则

### 13.1 形态

AIR_REFUEL 对以下可用项等权计数：价格保持、当前不低于锚点、振幅收窄、
最近成交量收缩、位于短均线附近。BEARISH_PULLBACK 对以下可用项等权计数：
出现阴线、触及支撑、成交量收缩、没有放量破位、当前止跌 K 线。

缺失项不进入分母；命中比例达到 YAML 阈值即标记相应形态，两种形态可以同时存在。

振幅收窄至少需要 4 根锚点后 K 线。序列按 `midpoint = n // 2` 切分；当数量为
奇数时，前半段取 `[:midpoint]`，后半段取 `[midpoint:]`，即多出的一根归入后半段。
少于 4 根时 `amplitude_contraction` 为 unavailable，不计零分、不进入形态分母，
对应策略评分规则也从 `available_max_score` 移除。

输出同时包含：

- `matched_patterns`：所有达到阈值的形态；
- `pattern_scores`：两个形态各自的可用条件命中百分比；
- `primary_pattern`：唯一主形态。

主形态先按 `pattern_scores` 降序选择；同分时使用固定优先级：
`BEARISH_PULLBACK > AIR_REFUEL`。后续互斥统计只能使用 `primary_pattern`。

### 13.2 setup_stage

- `NORMAL`：回看窗口内没有有效锚点。
- `LIMIT_ANCHOR`：评价日就是有效锚点日。
- `WATCH_PULLBACK`：有锚点但 B1 多数条件未达到。
- `B1_READY`：B1结构条件命中比例达到阈值，且存在支撑和初始失效价。结构条件
  只包括锚点后交易日窗口、价格回调区间、支撑触及/守住、缩量、无放量长阴和
  止跌K线；不得包含target S1、S1候选数量/质量、risk/reward、entry reference、
  headroom或entry room。
- `B2_READY`：上一信号为同 setup 的 B1_READY 时冻结触发价；或已有未确认触发价。
- `B2_CONFIRMED`：最高价触发、收盘站稳冻结价，且其余纯B2量价条件命中比例达到
  阈值；S1空间和risk/reward不参与该比例。
- `INVALID`：触及当前失效价，或触发任一严重结构失效条件；同 setup 中为终态。

`setup_stage`只表达结构生命周期。`immediate_resistance`、`target_s1`、
`risk_reward_ratio`、entry room相关字段以及所有S1压力事件只能改变入场评价、
风险解释和候选排序，不得把WATCH升级为B1、把B1降回WATCH或改写B2阶段。
`INVALID`仍可优先终止setup，因为它是结构失效。

B2 触发价为冻结日最近配置窗口最高价乘 trigger buffer，按价格 tick 取整。
冻结日当天不能确认。

### 13.3 event_flags

- `SUPPORT_WARNING`：仅在收盘接近支撑下沿、收盘接近 initial invalid、盘中跌破
  支撑后收回、支撑附近异常放量或连续测试支撑时触发。正常缩量触及支撑不触发。
- `NEAR_S1`：尚未确认突破时，最高价进入 S1 下沿配置距离内。
- `S1_BREAKOUT`：收盘站上 S1 上沿及配置 buffer。
- `S2_EXHAUSTED`：必须触及 S1，且回落、上影、放量、未站稳等可用条件达到多数阈值。

若收盘突破 S1，只输出 `S1_BREAKOUT`，不同时输出 `NEAR_S1`。

### 13.4 INVALID

以下任一条件触发：

- 收盘触及冻结失效价；
- 收盘有效跌破支撑下沿；
- 同时跌破锚点价和 raw-equivalent MA10；
- 放量跌破 B1 参考低点；
- 配置天数的连续放量阴线；
- 前一日破位且当前仍未收回。

INVALID 输出非空 `invalidation_reasons`。进入 INVALID 后清除 `NEAR_S1`、
`S1_BREAKOUT` 和 `SUPPORT_WARNING`；仅当 T 日自身确实满足 S2 条件时，允许保留
`S2_EXHAUSTED`。

## 14. 评分和快照

评分按 Profile 中规则逐项产生满分、部分分或零分解释。不可计算的规则从分子、
分母和理由中移除，并生成 `MISSING_SCORE_FIELD:<rule_id>`。PRICE_ONLY 本身不扣分。

锚点按 setup 创建时冻结；支撑、初始/当前失效价、immediate resistance和
target S1在首次B1_READY形成时冻结；B2触发价在从B1进入B2_READY时冻结。风险/
目标快照的新值在冻结当天都不参与事件与失效，只能由下一真实交易日起、通过
同setup上一信号复用。
当前失效价绝不低于初始失效价。状态持久化仍不在当前范围内。

## 15. is_entry_candidate

`is_entry_candidate` 表示当前信号“适合新建仓”，不是泛化的“可操作”
状态；它是不可由调用者传入的派生字段：

```text
is_entry_candidate =
    setup_stage in {B1_READY, B2_READY, B2_CONFIRMED}
    and data_quality != UNUSABLE
    and S2_EXHAUSTED not in event_flags
    and S1_BREAKOUT not in event_flags
    and entry_room_state != NONE
    and current close has not confirmed target S1 breakout
```

因此 `NORMAL`、`LIMIT_ANCHOR`、`WATCH_PULLBACK` 和 `INVALID` 都为 false，
且 INVALID 不受评分高低影响。`NEAR_S1`和`THIN`暂不强制淘汰，但必须在风险
提示中明确标记接近压力区或剩余空间偏薄。未来主候选过滤必须同时检查分数阈值与
`is_entry_candidate`，不能只按 score。

`NEAR_S1`、`S1_BREAKOUT`和`S2_EXHAUSTED`不改写`setup_stage`。其中NEAR_S1
只形成风险提示；S1_BREAKOUT和S2_EXHAUSTED把`is_entry_candidate`置为false，
但原结构阶段保持不变。

## 16. 阶段2A真实数据边界

阶段2A只有两个固定职责的适配器，不静默切换或混用来源：

| 项目模型字段 | 固定来源 | 第三方字段/参数 |
|---|---|---|
| DailyBar.trade_date | BaoStock 日线 | date |
| DailyBar.code | BaoStock 日线 | code，去除 sh./sz. |
| open/high/low/close | BaoStock 日线 | 同名字段，adjustflag=3 原始价 |
| preclose | BaoStock 日线 | preclose |
| volume/amount | BaoStock 日线 | volume/amount |
| turnover_rate/pct_change | BaoStock 日线 | turn/pctChg |
| trade_status/is_st | BaoStock 日线 | tradestatus/isST |
| LimitUpRecord.code/name | AKShare 涨停池 | 代码/名称 |
| limit_price | AKShare 涨停池 | 最新价 |
| first_seal_time/last_seal_time | AKShare 涨停池 | 首次封板时间/最后封板时间 |
| open_count/consecutive_count | AKShare 涨停池 | 炸板次数/连板数 |
| turnover_rate | AKShare 涨停池 | 换手率 |
| float_market_cap/total_market_cap | AKShare 涨停池 | 流通市值/总市值 |
| industry | AKShare 涨停池 | 所属行业 |

第三方空值、哨兵值、代码格式和时间格式只在 Provider 层清洗。交易状态不是正常
交易的日线行因无法构造有效 OHLC 而被跳过，并生成
`NON_TRADING_BAR_SKIPPED`。缺失可选字段保持 null，并生成
`MISSING_DAILY_FIELD` 或 `MISSING_LIMIT_FIELD`；不得伪造。

`inspect --code ... --as-of ... --days ...` 一次只评价一个合法沪深主板代码。
`days` 是含评价日在内的日历日回看长度。命令在内存中先用日线定位
锚点，再只为该代码和锚点日读取涨停池，最后调用纯函数引擎；stdout 输出 JSON，
不写文件。涨停池不可用时返回 PRICE_ONLY，相关 FULL 规则从可用分母移除。

默认 pytest 通过 `not integration` 选择并封锁 socket；只有显式
`pytest -m integration` 才允许真实网络。阶段2A仍不包含数据库、Parquet、HTML、
报告、回测、全市场扫描、盘中逻辑或自动交易。

## 17. 阶段2B单股票内存回放

`replay_stock` 只获取一个代码的一段真实日线。它按日线推断出的涨停收盘日期，
为同一代码逐日请求涨停池；这些日期只用于补充封板信息，不作为选股扫描。完成
数据获取后，严格按交易日升序执行：

```text
bars = bars[:T]
limit_pool = records where record.trade_date <= T
signal[T] = evaluate_strategy(..., previous_signal=signal[T-1])
```

任何 T 日时间线项目都不得读取或输出 T 日之后的价格或涨停池记录。`start` 只
控制返回时间线的起点；为了正确形成 `previous_signal`，引擎仍从已获取的最早
交易日开始内部推进。

时间线输出冻结快照、评分、入场候选、失效原因，并增加：

- `event_reasons`：每个 event flag 的确定性规则 ID；
- `pattern_conditions`：AIR_REFUEL 和 BEARISH_PULLBACK 各自 matched、failed、
  unavailable 子条件；
- `primary_pattern_reason`：唯一命中、最高分或同分优先级原因；
- `b1_conditions`、`b2_conditions`：用于解释人工标签和状态结果的条件集合。
- `setup_quality_score`：与压力/入场空间无关的结构质量分；
- `entry_quality_score`：只用于新建仓评价的派生分。
- `review_group`、`risk_reward_ratio`：随逐日入场评价一起输出，不参与结构状态。

SUPPORT_WARNING 的“支撑附近异常放量”和“连续测试”必须同时满足支撑上下
配置距离，远低于支撑的低点不能只因单边比较被视作“附近”。单纯触及支撑不会
产生预警；必须命中收盘接近支撑下沿、接近失效价、盘中跌破收回、附近异常放量
或连续测试之一。INVALID 仍按第13.4节清理普通事件。

ReplayOutput 保存请求日期、实际末根日线、Provider 名称和版本、实际请求的每个
涨停池日期、逐日期质量报告、聚合缺失字段及完整时间线。质量分为：

- `replay_data_quality`：整个请求范围内所有实际数据源的最差质量；
- `timeline[*].data_quality`：策略质量与该日实际相关的数据源质量合并值；
- `current_setup_data_quality`：仅当前 setup 内时间线项目的最差质量。

旧 setup 的缺失可以使 `replay_data_quality=PARTIAL`，但不会自动降低使用完整
涨停池的当前 setup。若
`actual_last_bar_date < requested_as_of`，必须：

```text
is_stale = true
quality_flags includes STALE_DATA
replay_data_quality is at least DEGRADED
```

回放是状态语义验证，不模拟买卖、资金或收益，不属于历史回测。阶段2B仍禁止
数据库、Parquet、HTML、报告、全市场扫描、盘中数据、自动交易和自动写文件。

## 18. 阶段2B.1快照时序与 setup 摘要

### 18.1 生效时序

`SupportSnapshot`、`InvalidPriceSnapshot`、`S1Snapshot` 和
`B2TriggerSnapshot` 统一采用“先冻结、后生效”：

```text
eligible(snapshot, T) =
    snapshot came from previous_signal
    and snapshot.eligible_from <= T
```

因此锚点日不能依赖临时候选产生结构事件或 INVALID；首次 B1 日虽然输出 support、
invalid 和 S1 快照，但同日不产生基于这些新快照的 SUPPORT_WARNING、NEAR_S1、
S1_BREAKOUT、S2_EXHAUSTED 或 INVALID。`FAILED_SUPPORT_RECOVERY` 还要求该
support 在 T-1 已经生效，锚点日和首次 B1 日不产生恢复义务。

### 18.2 setup 摘要

`setup_summaries` 按 `setup_id` 分组并分别计算 anchor、first B1、first B2 ready、
first B2 confirmed、first S1 events、invalid 和 final stage；不得使用全回放的首个
日期填充当前 setup。`current_setup_summary` 只指向最后一个仍在时间线中的 setup。
旧的回放级 `transitions` 仅保留为整个请求范围的兼容摘要，不能代替 setup 摘要。

## 19. 阶段2B.2压力与入场空间

### 19.1 EntryRoomState

仅对`B1_READY`、`B2_READY`和`B2_CONFIRMED`派生入场空间：

```text
entry_reference_price =
    close                              if B1_READY
    max(close, frozen b2_trigger)      if B2_READY
    close                              if B2_CONFIRMED

entry_headroom_pct =
    (target_s1.low - entry_reference_price) / entry_reference_price
```

- target下沿不高于reference：`NONE`；
- `0 < headroom < 5%`：`THIN`；
- `headroom >= 5%`：`SUFFICIENT`；
- 没有可靠target：`OPEN_SPACE`，headroom和risk/reward均为null。

5%边界同时以`entry_room.thin_headroom_max`和
`entry_room.sufficient_headroom_min`保存在YAML，模型要求两值相等，避免空档或
重叠。所有价格和比例继续使用Decimal。entry room只影响新建仓候选，不改写B1、
B2或失效阈值。

### 19.2 setup终止

`SetupSummary`增加`closed_date`和`termination_reason`：

- `ACTIVE`：尚未闭合，closed_date为null；
- `INVALIDATED`：在首次INVALID日闭合；
- `SUPERSEDED_BY_NEW_ANCHOR`：在下一个有效锚点日闭合；
- `EXPIRED`：锚点离开有效回看窗口且没有新有效锚点时闭合。

INVALIDATED优先于后续新锚点。旧setup即使最后一个逐日状态是LIMIT_ANCHOR，也会
在新锚点出现时明确标记SUPERSEDED，不再呈现为永久活动状态。

## 20. 阶段2B.3 Setup识别与入场价值解耦

### 20.1 生命周期不读取压力价值

WATCH_PULLBACK到B1_READY只评价第13.2节列出的B1结构条件。S1不存在、S1改变、
risk/reward为null或低于入场参考值、entry room为NONE，都不能反向改变
`setup_stage`。因此允许：

```text
setup_stage = B1_READY
review_group = OPEN_SPACE
target_s1 = null
risk_reward_ratio = null
entry_room_state = OPEN_SPACE
```

同样，S1_BREAKOUT和S2_EXHAUSTED只改变事件及新建仓资格，不能把B1_READY或
B2_READY改写为WATCH_PULLBACK。只有INVALID等结构失效可以终止生命周期。

### 20.2 两层评分

```text
setup_quality_score = score.normalized_score

entry_quality_score = null
    when setup_stage not in {B1_READY, B2_READY, B2_CONFIRMED}

entry_quality_score = 0.00
    when data_quality == UNUSABLE
      or entry_room_state == NONE
      or S1_BREAKOUT in event_flags
      or S2_EXHAUSTED in event_flags
```

其余入场阶段从`setup_quality_score`开始，取以下可用折减因子的最小值：

```text
room_factor =
    entry_headroom_pct / entry_room.thin_headroom_max  when THIN
    1                                                  otherwise

risk_reward_factor =
    min(risk_reward_ratio / entry_room.minimum_risk_reward, 1)
    when risk_reward_ratio is available

entry_quality_score =
    quantize(setup_quality_score * min(available factors), 0.01)
```

OPEN_SPACE没有target、headroom和risk/reward，因此这些缺失因子不参与计算，也不
按零分处理。`entry_quality_score`、target、risk/reward、entry room、review group、
S1事件及对应风险解释允许随合法S1变化；同一价格序列的setup_id、setup_stage
时间线、B1/B2结构条件和`setup_quality_score`必须保持不变。

## 21. 阶段2C.1任意主板单股票评价

### 21.1 代码边界

共享解析器只接受原始六位ASCII数字字符串，禁止整数化或自动补零。允许前缀为：

- 深圳主板：000、001、002、003；
- 上海主板：600、601、603、605。

解析结果固定包含`normalized_code`、`exchange`、`baostock_code`和
`board=MAIN`。300/301、688、200、900、北交所及未知前缀在任何Provider调用前
拒绝。代码合法不等于Provider一定能在请求日期返回日线；后者是退出码1的业务或
Provider错误，不得伪装成参数错误。

该范围只解除单股票白名单。系统仍不提供证券主表、股票池、全市场扫描、排名、
报告、数据库、缓存、回测或自动交易。

### 21.2 评价模式

- `STATELESS_INSPECT`：只评价请求日，不接收`previous_signal`；不能还原B2冻结和
  确认生命周期。
- `POINT_IN_TIME_REPLAY`：从早到晚逐交易日评价，并显式传入上一交易日完整信号；
  是历史状态、冻结快照和前缀一致性验证的正式入口。

不得为了使inspect看起来与replay相同而构造虚假上一信号。

### 21.3 数据质量与上市历史

`MISSING_DAILY_FIELD`、`MISSING_LIMIT_FIELD`和`MALFORMED_DAILY_ROW`中的字段名
汇总到`missing_fields`；代码和日期不得被误识别为字段。Provider质量等级和flags
进入来源报告及相关信号，回放中的带日期日线flags只从其发生日开始生效，不得向
更早时间线回写。

资格门槛使用实际取得的有效交易日数量，不根据股票名称、当前上市日期或日历跨度
猜测。少于`universe.minimum_listing_trade_days`（当前为120）时：

```text
quality_flags includes INSUFFICIENT_TRADING_HISTORY
signal.data_quality = UNUSABLE
is_entry_candidate = false
```

该资格层只影响数据可用性及新建仓价值，不改变原有setup结构计算、B1/B2门槛、
S1、INVALID或Entry Room阈值。
