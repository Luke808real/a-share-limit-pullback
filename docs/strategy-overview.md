# 策略概览 — 首板回踩再启动 / Second Launch Radar

> 通俗版说明。研究性系统，不承诺稳定盈利，不自动下单。

## 1. Strategy philosophy

核心哲学：**注意力分配优先于精确买点**。

全市场 3000+ 股票中，绝大多数不值得人工逐一看。系统的任务是把范围缩到
“结构上可能二次发动”的少量候选，再由人工在盘中判断是否参与。

系统目标不是自动预测涨停，也不是机械寻找最低价。

## 2. Lifecycle states

| 状态 | 含义 |
|---|---|
| FIRST_ATTACK | 第一次资金明显表态（涨停或放量攻击） |
| STRUCTURE_ALIVE | 表态后的回调/换手没有破坏底部或平台结构 |
| RECLAIM | 价格重新站回短均线等关键位置 |
| PREPOSITION | 结构健康、修复中，值得继续观察 |
| LAUNCH_READY | 次日值得重点盯盘的转强候选 |
| SECOND_LAUNCH | 第二次攻击确认（新高 / 接近 S1 / 明显扩张） |
| POST_B | 目标达成或已走完，只观察不追 |

状态使用客观描述（资金表态、结构保持、换手/分歧、重新转强），
不把“主力洗盘 / 吸筹”写成事实。

## 3. PREPOSITION vs LAUNCH_READY

- **PREPOSITION**：结构完整、修复进行中，属于“继续观察池”。
- **LAUNCH_READY**：已经进入可操作的转强窗口，属于“重点盯盘池”。

两者都是 research 语义，不等于自动买入信号。

## 4. Human Watch architecture

- 机器扫描并给出候选、参考位（支撑 / invalid / S1 / G）与历史证据。
- 人工负责盘口承接、板块环境、是否追高、是否交易。
- 数据受限（DATA_LIMITED / PROVISIONAL / unmapped）的标的单独进入
  MANUAL_REVIEW，不混入自动排序。
- 每日允许 **NO_TRADE_DAY**：没有合适标的时间可以全部不交易。

## 5. B condition

B 不是单一价格，而是：

`PRICE ZONE + BEHAVIOR CONFIRMATION + INVALIDATION`

即价格进入计划区域、盘中表现符合预期、风险失效位置明确。

## 6. Support / invalid / S1 的作用

- **support**：潜在承接/参考区（MA、平台、突破位都只是代理）。
- **invalid**：结构失效位，跌破视为放弃。
- **S1**：第一目标/观察位；S2 在冻结系统中没有价格目标，仅作事件语义。

这些是参考，不是保证。

## 7. Forward observation

每个 forward 候选会记录未来 1d / 3d / 5d 的 MFE、MAE、S1/invalid 触达、
是否 SECOND_LAUNCH、TIME_TO_SECOND_LAUNCH。只追加 observation，
不回写历史、不因单日结果调整模型。

## 8. Human heuristics vs validated evidence

来自人工复盘的经验（如 FAST_RECLAIM、TIGHT_CONSOLIDATION、
PREPLANNED_B_CONDITION）标注为 **HUMAN_HEURISTIC**。

研究结论标注为 **RESEARCH_OVERLAY_ONLY**。

两者都不等于 production fact；只有经过冻结流程的规则才属于 production。

## 9. Current limitations

- 机械 B1 entry 尚未证明稳定正期望。
- “越便宜越好”未获支持；强势候选往往更靠近近期高点。
- G Geometry 是 radar 排序，不是自动买入信号。
- Analog Engine 仅做描述性案例检索，不预测 S1/S2。
- 技术指标只是辅助特征。

## 10. Future directions

以下仅记录方向，**当前不执行**：

- intraday recovery quality（5m/15m：recovery speed、time below support、
  VWAP/MA reclaim、intraday low-to-close recovery）
- sector / relative strength
- better PREPOSITION ranking
- continued forward sample accumulation
