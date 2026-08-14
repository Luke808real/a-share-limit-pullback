# research-strategy 只读审计报告（四 Agent 架构开篇 · Phase 5 预研）

## 资产盘点
- episode 数据集：31,422 条 corrected episodes，路径 data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet，SHA-256 66d5943f...（已冻结，禁删）。
- execution_reality 执行模型：src/limit_pullback/execution_reality.py，T+1 daily-bar，成交日目标不可退出、T1 阻塞止损开盘退出，strict/conservative 双口径；入口命令 limit_pullback execution-reality（cli.py L345-357）。
- outcome CLI：src/limit_pullback/outcome.py，入口 outcome-study（L272-301）+ outcome-relabel（L325-343），支持 snapshot-id/start/end/workers。
- replay 机制：src/limit_pullback/replay.py + inspect.py，入口 replay/inspect/screen/diagnosis（L102-132, 224-250, 303-323）。
- 稳健性/尾部校验：robustness.py、tail_gap_check.py、trade_plan.py 已产出 robustness.json、tail_gap_check.json。
- 研究脚本库：research/ 含 execution_risk_v01.py、forward_paper_test_human_watch_v1.py、run_forward_bpoint_v01.py 等，daily-review/、intraday/ 子目录为主。

## 历史结论状态（Phase 2D / 2D.1A）
- REJECT：WEEKLY_CONTEXT_V01、PRICE_VOLUME_CONTEXT_V01、JOINT_CONTEXT_V01（均 REJECT_FOR_PROMOTION）；SUPPORT_BREAK_V01（RESEARCH_INVALID_FOR_PROMOTION）。
- OBSERVE_ONLY：WASHOUT_POSSIBLE、SECTOR_V01（LOW_CONFIDENCE_PROXY）、RAW_WEEKLY_FEATURES（UNDECIDED）、H1 NEUTRAL/UNFAVORABLE cohort、BREAKOUT_GAP_FILL（年度方向不稳定）。
- RETAIN：PRICE_VOLUME_FACTS、WEEKLY_CONTEXT（RETAIN_FOR_RESEARCH）、CONTEXT_ENTRY_SEPARATION、PIT_SUPPORT_FIX。

## 缺口
- 执行真实性未闭合：price-limit execution 标记 NOT_MODELED，daily OHLC ambiguity 仍存。
- 最小 Forward Paper Validation / Daily Runner 未设计：CURRENT_PHASE 明确「下一步仅等待人工设计」，当前无脚本骨架落地。
- research/runs/ 仅 ANALOG_V03_OOS_CALIBRATION/ 的 metrics 产物，无现成 paper 回测 runner 骨架；reports/ 三份均为审计/readiness 报告。

## 最小研究范围建议（Phase 5 预研 · 不新增指标/阈值）
- 固定输入：episodes.parquet（SHA 66d5943f...）+ snap-2026-07-31-b5f84004de8a，evaluate_strategy_calls=0，不重跑全市场/不回放。
- 执行模型：复用 execution_reality 的 T+1 daily-bar strict/conservative 双口径，仅按预批 quality/Entry Room/D+N 分组，不搜索新阈值。
- 结论状态：仅产出 REJECT/OBSERVE_ONLY/SUPPORTED，SUPPORTED != PROMOTED，禁止同样本调参。
- 输入 hash 校验：--expected-sha256 66d5943f...（diagnosis/relabel/execution-reality 均已内置），另记录 snapshot-id、strategy.yaml/trade_plan.yaml SHA、脚本与输出结论状态。
- 范围边界：最小 paper 验证 = 固定样本 + 固定执行模型 + 描述性 E[R] 分组结论；不建新指标、不引入 5m 数据、不接 ashare-lake（仍 NOT_INTEGRATED）。

VERDICT: READY — 冻结资产与 CLI 入口齐备、可零改动搭最小 paper 回测，唯一阻塞是需人工拍板「最小 Forward Paper Validation」的固定输入与结论契约后即可落地 Phase 5。
