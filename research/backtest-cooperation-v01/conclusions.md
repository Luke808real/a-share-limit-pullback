# Backtest Cooperation Study v01 — 结论（2026-08-14）

输入：protocol.md 固定输入（episodes SHA
66d5943f...、snap-2026-07-31-b5f84004de8a、Phase 2D.1A T+1 模型）。
结论分类只允许 REJECT / OBSERVE_ONLY / SUPPORTED；SUPPORTED != PROMOTED。

## 假设结论

- H1 冻结输入 provenance 完整可复现 → **SUPPORTED**
  （episodes SHA 与冻结值逐字节一致；快照 id 一致；31,422 条 / 2,773 只与
  Phase 2D.1A 记录一致）。
- H2 重算确定性与资源受控 → **SUPPORTED**
  （重算 21.5s、evaluate_strategy_calls=0、derived_rows=31,422；剥离
  analysis_seconds 后与冻结 summary 语义完全相等；内存峰值未超 4096MB gate）。
- H3 历史 episode 新闻标签 → **REJECT_FOR_THIS_STUDY**
  （episodes 锚日区间 2024-01-03 .. 2026-07-30，ASL 新闻/公告表覆盖
  2026-08-10 .. 2026-08-13，重叠 0 天；历史标签不可行）。
  新闻面标签自今日起 forward-only：经 ops daily-run 的 news-brief 按日累积，
  目前定位 **OBSERVE_ONLY**（机制已落地、证据为零）。
- H4 冻结 cohort 结论无漂移、无新规则引入 → **SUPPORTED**
  （重算 cohort 与 Phase 2D.1A 记录一致，例：B1_READY_ALL 10bp E[R]
  -0.1730；B1_READY_ENTRY_GE_80 10bp +0.2605 仍为观察值，不提升；
  本研究未改任何阈值/评分/规则）。

## 描述性复核（摘自 inputs-verified.json，仅重申，非新结论）

| Cohort | 10bp E[R] | 20bp E[R] | resolved |
| --- | --- | --- | --- |
| B1_READY_ALL | -0.1730 | -0.3622 | 747 |
| B1_READY_SETUP_GE_80 | +0.0204 | -0.1277 | 151 |
| B1_READY_ENTRY_GE_80 | +0.2605 | +0.1280 | 130 |
| B2_READY_ALL | -0.1107 | -0.1273 | 1627 |
| B2_CONFIRMED_ALL | -0.1272 | -0.1451 | 637 |

注：price_limit_execution=NOT_MODELED、日线 OHLC ambiguity 未消除；上述数字
不得用于调参或选股规则升级。

## 与每日流程的衔接

本研究同时确认了「最小 Forward Paper Validation / Daily Runner」的落地形态：
ops daily-run DATE（daily → trade-plan → news-brief → 人工 watchlist，
fail-closed + 对账 receipt）即日起承担每日 forward 证据累积；该证据按
research/daily-review/<date>-HUMAN-WATCH.md 留存，供 Owner 后续决定是否
进入更正式的 forward validation。
