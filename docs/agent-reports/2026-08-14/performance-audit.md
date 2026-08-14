# performance 只读审计报告（四 Agent 架构开篇）

## 现状耗时表（源自 canonical-catchup-2026-08-06 各 summary，字段缺失标 UNKNOWN）
- fetch/catchup：fetch-summary.json 无 wall 字段 → UNKNOWN（tdx 5198 / tencent 5196 行，0 失败）。
- staging：staging-summary.json 无 wall → UNKNOWN（confirmed 5196 / provisional 2 / conflicted 0）。
- promotion 物化：promotion-summary.json build_wall_seconds=55.6，validation 3.2s，peak_rss 1.54GB，daily_total_n=3,301,481。
- state generation：stategen-summary.json build_wall_seconds=384.4，peak_rss 10.3GB，state_n=3191（全量增量 state 构建，不是 ASL 横截面）。
- ASL 推进筛选：asl-screen-20260813/summary.json total_wall_seconds=1.46、fast_path_n=0（读已持久化 state，非重建）。

## 热点确认
- 热点1：load_canonical_market（screen/canonical.py:163）全量物化——生产调用仅在测试/单票 replay；trade_plan.py:924-927 已显式不调用它（读 state JSON + 仅流式拉 eligible codes）。
- 热点2：ops daily 主路径走 fast_path=True 增量，但 _verified_no_trade_from_previous/_calendar_sessions/_previous_trading_session 各开独立 duckdb 连接重复扫 daily parquet（L83/162/197）。
- 热点3：cold-rebuild-profile 显示 92%（89.4s/96.7%）耗时在 strategy/math.calculate_indicators（evaluate_strategy_calls=11173，per_code 4.62s），canonical_load 仅 0.8%。

## 时间预算表（盘后 ~16:00 完成，现量级）
- catchup→staging→promotion：UNKNOWN + ~55.6s（promotion 为已知大头）→ 目标 <90s。
- state generation（增量 fast_path）：~384s（08-06 实测全量）→ 目标 <180s。
- trade-plan 横截面：~4s（读 3191 state JSON）→ 目标 <2s。
- news brief + 人工 watchlist：UNKNOWN → 目标合计 <120s，全程锚 16:00。

## 调优候选（仅列参数与方向，未改 runtime.yaml）
- canonical_reader_threads 4→8/16：外排读取提速。
- canonical_reader_memory_limit 2GB↑：减少 DuckDB 外部排序落盘。
- screen_process_workers 4↑：state 构建并发放大（受 peak_rss 10.3GB 约束）。
- daily_window_calendar_days 400↓：缩小 fast_path 增量回看重算窗口 → 直接降 state gen 耗时。

## 风险与等价校验要求
- 并发/读取路径改动：触碰策略语义（screen/canonical.py 行序/去重 DUPLICATE_CANONICAL_ROW_CONFLICT fail-closed），必须跑 .goal-task/refactor-check/equiv_0806.py 对齐 stategen-2026-08-06-a846075a5ac7。
- 复用 canonical 一次载入多处用（runner L200/L816 双 iter_canonical_code_bars 循环）：属数据加载层，不碰 setup_stage/阈值，风险低但需按语义哈希 5d0817f4… 校验。
- 数学层（math.py 92% 热点）重写风险最高：触及 PIT/指标语义，必须走完整 full↔inc↔repeat 三等价验证 + 黄金锚。

VERDICT: 真正瓶颈不是 load_canonical_market（trade-plan 已绕过），而是 state generation 的 384s 与 math 层 92% 指标计算——先降 daily_window_calendar_days 并复用 duckdb 连接、并行 screen workers，比改 canonical 读取更划算，且全部需过黄金等价校验。
