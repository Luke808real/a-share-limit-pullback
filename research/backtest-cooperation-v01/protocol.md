# Backtest Cooperation Study v01 — 协议（2026-08-14）

Owner: research-strategy agent（设计）; data-processing（输入校验）;
news-analysis（观察标签）; performance（内存/耗时/确定性）; MAIN（归档）。
本研究**不是策略优化、不是组合回测**（not_strategy_optimization /
not_portfolio_backtest = true），只做冻结样本 + 冻结执行模型下的描述性复核
与四 Agent 协作链路验证。

## 固定输入（冻结，不可改）

- 快照：snap-2026-07-31-b5f84004de8a（phase-2d0 冻结）。
- corrected episodes：
  data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet
  31,422 条 / 2,773 只；SHA-256
  66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093。
- 执行模型：Phase 2D.1A 冻结的 T+1 daily-bar 模型（max_holding_sessions=10，
  friction_bps=[0,10,20,30]，price_limit_execution=NOT_MODELED，
  evaluate_strategy_calls=0）。strict/conservative 双口径以 frozen
  execution-reality 输出为准。

## 研究问题（本次协作新增，不调任何参数）

- H1（data-processing）：冻结输入 provenance 完整、哈希可复现 → SUPPORTED/REJECT。
- H2（performance）：同一输入重算与冻结输出语义一致、耗时/内存受控 → SUPPORTED/REJECT。
- H3（news-analysis）：ASL 新闻/公告/龙虎榜可给历史 episode 打观察标签 → SUPPORTED/OBSERVE_ONLY/REJECT。
- H4（research-strategy）：冻结 cohort E[R] 结论与 Phase 2D.1A 记录一致、且无新策略规则被引入 → SUPPORTED/REJECT。

## 协作分工与产物

| Agent | 动作 | 产物 |
| --- | --- | --- |
| data-processing | SHA/行数/快照校验 | inputs-verified.json |
| news-analysis | 覆盖率计算（只读） | news-tag-coverage.json（research/news-observation-v01/） |
| performance | 全量重算 + 语义对比 + 耗时 | runs/execution-reality-recheck/ |
| research-strategy | 结论分类 | conclusions.md |
| MAIN | 归档与 provenance | provenance.json |

## 边界

- 禁止同样本调参；禁止用本研究的数字反向改阈值或评分。
- 任何 SUPPORTED 都不等于 PROMOTED；升级需 Owner 单独批准并走 ADR。
- 08-03 之后的会话一律视为 forward 观察，不进入本研究的结论统计。
