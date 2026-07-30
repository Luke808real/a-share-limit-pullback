# 设计决策记录

## D-001 双价格体系

**状态：已采纳**

涨停、支撑、压力、B2、失效价、成交和图表使用 raw price。均线、均线粘合和
120 日位置使用只依赖当时 `close/preclose` 的连续价格。否决“所有指标统一使用
不复权价格”，也禁止严格回测使用今天回算的历史前复权数据。

## D-002 setup 与 event 分离

**状态：已采纳**

单值 `stage` 被拆为单值 `setup_stage` 和多值 `event_flags`。S1/S2 是事件，不再
覆盖 B1/B2 setup 状态。

## D-003 B2 触发价先冻结后确认

**状态：已采纳**

确认 T 日突破所用触发价必须在 T 日之前冻结并生效。否决用确认日最高价生成
确认日触发价的循环定义。

## D-004 FULL 与 PRICE_ONLY 独立评分

**状态：已采纳**

不可获得的规则从分子和分母同时移除，并记录质量标记。否决把缺失字段按零分、
失败条件或负面理由处理。

## D-005 信号快照不可回写

**状态：已采纳**

快照模型不可变；同一 setup 的历史快照不得改写。当前版本只声明该状态不变量，
不实现仓库、数据库或版本持久化。

## D-006 失效价只能收紧

**状态：已采纳**

当前失效价不得低于初始失效价。否决随行情走弱向下放宽风险边界。

## D-007 S1 缺失不虚构目标

**状态：已采纳**

可操作 setup 缺少 S1 时进入 `OPEN_SPACE` 人工复核分组，风险收益比为空，不自动
淘汰，也不合成目标价。

## D-008 最小 Provider Protocol

**状态：已采纳**

Provider 只有日线和涨停池两个方法。当前版本不增加实现、工厂、注册、缓存、
重试、断路器、静默切换或第三方数据类型。

## D-009 Decimal 与时区

**状态：已采纳**

领域数值拒绝 float；交易日使用 `date`；运行时间使用 timezone-aware
`datetime`。

## D-010 当前交付边界

**状态：已采纳**

当前实现至阶段2B.2：阶段1.5纯策略计算、阶段2A固定真实数据适配器及单股票
`inspect`、阶段2B单股票逐日内存`replay`、风险快照时序、逐setup摘要，以及
S1压力审计和新建仓剩余空间。
DuckDB、Parquet、HTML、报告、回测、全市场扫描、盘中逻辑、自动交易和机器学习
均留在本轮范围之外。

## D-011 阶段1.5纯函数引擎

**状态：已采纳**

策略入口只接受 bars、as_of、配置、显式生成时间、可选涨停池和可选上一信号。
它不读取全局状态，不获取数据，不写文件；未来行在入口处截断。

## D-012 确定性聚类

**状态：已采纳**

价格候选先按价格和来源排序，再以簇最低价约束簇最高价。否决依赖输入顺序或
可能通过链式相邻关系产生超宽簇的实现。

## D-013 setup_id

**状态：已采纳**

有效 setup 使用 `<code>:<anchor YYYYMMDD>:<anchor price ticks>`。同一代码、锚点日、
锚点价和 tick 必然生成相同 ID；NORMAL 使用评价日和 NORMAL 后缀。

## D-014 B2纯函数推进

**状态：已采纳**

无 previous signal 时最多形成 B1_READY。只有调用者把同 setup 的 B1_READY 传入
下一交易日，才冻结 B2 触发价并进入 B2_READY；再后续交易日才能确认。

## D-015 阶段1.5.1语义加固

**状态：已采纳**

B2 使用“最高价触发 + 收盘站稳 + 其余条件多数”的三层确认。S1 突破与邻近事件
互斥；INVALID 只允许保留当日真实成立的 S2。SUPPORT_WARNING 仅表达支撑威胁，
不再表达普通健康回踩。

双形态输出唯一 `primary_pattern`，同分时
`BEARISH_PULLBACK > AIR_REFUEL`。

## D-016 新建仓候选语义

**状态：已采纳**

`is_entry_candidate` 只表达当前信号是否适合新建仓，不作为泛化的“可操作”
标记。它要求阶段为 B1_READY、B2_READY 或 B2_CONFIRMED，数据质量不是
UNUSABLE，且没有 S2_EXHAUSTED 或 S1_BREAKOUT。INVALID 无论评分多高都为
false；NEAR_S1 不直接淘汰，但必须保留风险提示。

## D-017 阶段2A固定数据职责

**状态：已采纳**

BaoStock 是原始历史日线、preclose、交易状态和历史 ST 的唯一来源；AKShare
`stock_zt_pool_em` 是封板时间、炸板次数、连板数、市值和行业的唯一来源。两个
Provider 分别暴露一个项目模型接口，不暴露 DataFrame，不设置自动回退。清洗和
缺失标记只发生在 Provider 层。

`inspect` 仅支持 002606、603123、001382 的单股票、单评价日内存计算。涨停池
不可用时显式降为 PRICE_ONLY，不伪造字段。Provider 质量和缺失说明进入结构化
输出；不写文件，也不扩展到数据库、报告、回测或市场扫描。

## D-018 阶段2B逐日状态回放

**状态：已采纳**

真实回放按交易日逐个调用同一个 `evaluate_strategy`，并把 T-1 完整信号显式
传给 T 日。日线和涨停池在每次调用前按 T 截断；预先获取数据不等于允许策略
读取未来记录。

回放只为单个代码的日线涨停候选日期请求涨停池。输出保存 Provider 版本、逐日
来源质量、实际涨停池日期、STALE_DATA、事件规则、两种形态子条件以及 B1/B2
条件。它用于验证 setup 生命周期，不计算交易、持仓、收益或绩效，因此不是回测。

SUPPORT_WARNING 的附近放量和连续测试改为双边距离判断，避免远低于支撑的价格
被单边条件误判为“附近”；其余阈值不因三只人工样本而调整。

## D-019 风险快照统一先冻结后生效

**状态：已采纳**

Support、initial/current invalid、S1 和 B2 trigger 都保存 `frozen_as_of` 与
`eligible_from`，且后者严格晚于前者。T 日只能使用从 T-1 信号沿用且已经生效的
快照判断事件和失效；T 日新冻结的快照只供下一真实交易日起使用。

`LIMIT_ANCHOR` 只冻结 anchor。support、invalid 和 S1 首次在 B1_READY 冻结；
`FAILED_SUPPORT_RECOVERY` 还要求 support 在前一交易日已经生效。支撑中心默认
不得高于冻结参考收盘价，YAML 只保留 0.2% 的极小容差，明显更高的候选转作压力。

## D-020 回放质量与 setup 摘要分层

**状态：已采纳**

`replay_data_quality` 聚合整个请求范围；每个 timeline item 只合并日线源及其所属
setup 锚点日的涨停池质量；`current_setup_data_quality` 仅聚合当前 setup。历史
旧 setup 缺池可以降低 replay 总体质量，但不得污染当前完整 setup。

`setup_summaries` 严格按 `setup_id` 分组计算 first_*、invalid 和 final stage，
`current_setup_summary` 只引用最后一个 setup，否决把不同 setup 日期混入单一
生命周期摘要。

## D-021 S1分为即时压力与目标压力

**状态：已采纳**

锚点价格属于支撑语义，只作为排除压力簇的reference。与锚点簇或冻结support
重叠、或不在B1参考收盘价上方的簇不能成为S1。候选来自左侧高点、首次上冲、
最近20/60日高点和局部摆动高点密集簇，并完整保存候选、簇、排除和选择原因。

最近有效压力保存为`immediate_resistance`。B1日最高价推导不含未来数据的预期
B2触发位；若immediate与该位重叠，则跳过该平台簇并选择上方最近簇作为
`target_s1`。否则immediate可以同时是target。后续实际B2触发位抬高时不改写旧
target，避免向历史回写。

## D-022 入场空间是独立新建仓门槛

**状态：已采纳**

entry reference按B1收盘、B2_READY的收盘与触发价较高者、B2_CONFIRMED收盘确定。
target下沿相对reference的Decimal比例分为NONE、THIN、SUFFICIENT；无可靠target
为OPEN_SPACE。THIN/SUFFICIENT边界固定在YAML的5%，本轮没有调整任何B1、B2或
失效阈值。

NONE和已确认S1_BREAKOUT禁止新建仓；THIN和NEAR_S1只形成风险提示，不单独淘汰。
OPEN_SPACE不虚构S1和risk/reward，继续进入人工复核。

## D-023 setup必须有明确终止语义

**状态：已采纳**

setup摘要用ACTIVE、INVALIDATED、SUPERSEDED_BY_NEW_ANCHOR和EXPIRED表达生命周期。
INVALID在首次失效日闭合；仍有效的旧setup在新锚点日被替代；没有新锚点且离开
回看窗口则过期。否决仅因setup最后一条记录是LIMIT_ANCHOR而永久显示为活动状态。
