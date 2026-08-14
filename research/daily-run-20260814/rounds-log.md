# 真实盘后流程执行日志（2026-08-14）

命令与证据逐轮记录。冻结边界：不改冻结规则、不跨 OOS/Forward/TradePlan、
不 commit/push/PR/合并/改生产配置。

## Round 0 — 运行前确认（11:12 CST）

- 分支 feat/agent-architecture-v01 @ 26cb139；config/strategy.yaml 干净未改
  （sha256 47a0ea2b...）；runtime.yaml 存在（84549bb8...）。
- formal pointers（ops status）：
  formal_screen_ready_pointer = [snap-2026-08-06-e798f88ff67b, cc3a163e...]；
  formal_state_pointer = stategen-2026-08-06-a846075a5ac7。
- as-of 选定：2026-08-07（08-06 之后的下一个交易日；daily 只做单会话推进，
  跳会话会被 preclose 连续性校验 fail-closed）。
- 真实输入探测（research/daily-run-20260814/probe_providers_20260807.py）：
  baostock OK（000001 08-07 close 11.1900）；tencent OK（11.1900）；
  tdx 0 行 0 failure（异常）。
- 根因定位：fetch_tdx_daily 硬编码 get_security_bars(..., 0, 5) 只取最近 5 根；
  当前 TDX 窗口 08-10..08-14，08-07 已滑出。原生 pytdx count=800 探测确认
  服务器上 08-07 数据存在（close 11.19）。
- 最小修复：tdx_daily.py 增加 TDX_LOOKBACK_BAR_COUNT=60 常量替换硬编码 5
  （窗口外的行本就按 sessions 过滤，语义不变）。
- 针对性验证：test_real_providers_offline + test_adr008_data_correctness
  33 passed；真实 TDX 复探：000001/600468 的 08-07 行可取回。
- 全量离线套件：525 passed, 25 deselected（233.6s）。
- 磁盘 173Gi 空闲；内存 16GB。

## Round 1 — ops daily-run 2026-08-07（11:20:56 CST 启动）

命令：
  .venv/bin/python -m limit_pullback.ops daily-run 2026-08-07
  （tee data/tmp/daily-run-20260807-console.log）

- 结果：立即失败，exit 0（管道 tail 掩盖），error：
  DAILY_RUN_FAILED step=daily
  AttributeError("type object 'datetime.time' has no attribute 'time'")
- 根因：ops.py 同时存在 import time 与 from datetime import time，
  后者遮蔽模块 → cmd_daily 的 time.time() 崩溃（用户未提交 WIP 中引入）。
- 最小修复：删除 datetime 导入中的 time（文件中无任何 datetime.time 用法）。
- 针对性验证：compileall OK；ops status OK；
  test_ops_daily_run + test_ops_fast_path + test_screen_cli 21 passed。

## Round 2 — ops daily-run 2026-08-07（11:2x CST 启动）

（进行中，结果见后）

进度快照（job bash-21）：
- 11:24 CST：TDX 3199 代码（约 600 代码/分钟）
- 11:25:34：TDX 5197/5198（TDX 阶段完成，1 个代码待 fetch-summary 确认）
- 11:26:51：Tencent 337/5198（~2.5-5.6 代码/秒，预计 Tencent 阶段 15-30 分钟）

## Round 2 结果（11:39 CST 完成，总 wall ~1015.96s）

命令同上（console 经 tee 捕获：data/tmp/daily-run-20260807-console-round2.log
在 harness 管道下为 0 字节——缓冲/管道捕获问题，非运行问题；同内容的结构化
证据齐全：timing.json / daily-summary.json / fetch-summary.json）。

- daily 步骤 **OK**（1015.96s）：
  - provider：5198 代码、0 重试、wall 841.2s
  - staging：confirmed 5197 / provisional 0 / **incomplete 1** / conflicted 0 /
    preclose_continuity_mismatch 0；staging_hash e9ab0427...
  - snapshot：snap-2026-08-07-586cc17164af **SCREEN_READY**（pointer 08-06 → 08-07）
  - generation：stategen-2026-08-07-a70b9b642b87 **ACTIVE**，state_n=3191，
    semantic_root fc6990b0...（pointer 08-06 → 08-07）
  - predecessor_resolution：FORMAL_STATE_POINTER → stategen-2026-08-06-a846075a5ac7
  - sentinel 4/4 match：603980 B2_CONFIRMED、002112 INVALID、000001 NORMAL、
    605198 B2_READY（fast == replay，last_processed 2026-08-07）
  - incomplete 代码 000838：staging 分类 both_providers_missing；BaoStock 独立
    复核 NON_TRADING_BAR_SKIPPED:000838:2026-08-07 → 真实停牌日，非数据缺口。
- trade-plan 步骤 **fail-closed at 冻结语义门**（0.02s）：
  StrategySemanticReviewPendingError
  (STRATEGY_SEMANTIC_REVIEW_PENDING: B2_CONFIRMED_LIFECYCLE_UNRESOLVED)
  —— 按约束不跨 TradePlan、不绕过语义门；链条在门处正确停止。
- timing.json status=FAILED，completed=[daily]；plan/brief/watchlist 均未生成
  （fail-closed 正确行为）。

观察（非缺陷）：
- fast_path_stats：fast_path_n=0，targeted_fallback_n=3191，原因统一为
  MISSING_PREFIX_HASH_V2——08-06 代 states 无 V2 前缀哈希，本次全部走
  targeted fallback（rows_scanned 1,860,488）。属一次性迁移成本；下一次推进
  （08-07 → 08-10）应恢复 fast path，届时核对 fast_path_n。

## 自评审

独立自评审 research/daily-run-20260814/self_review_20260807.py 执行结果：
**ok=true，27/27 checks 全过**（结果存 research/daily-run-20260814/self-review-result.json）。
覆盖：timing 链形状、门处停链、SCREEN_READY/ACTIVE/state_n、staging
conflicted/preclose、provider 重试、incomplete=1、sentinel 全 match、staging
hash、semantic root、formal pointer == 新 snapshot/state id、fetch sha256、
promotion 记录、门后产物缺席（fail-closed）。

## B2 语义评审与链条继续（Owner 指令 2026-08-14）

### 评审决议

- 问题：B2_CONFIRMED 单调性冲突（冻结 STATE_MACHINE：退出仅 失效/新锚点/过期；
  代码曾可降回 B2_READY，golden s2_exhausted 曾期望 B2_READY）。
- 决议（D-026）：B2_CONFIRMED 单调；engine.py 增加同 setup 保持分支；golden
  修正；新增单调性回归测试；决策门开放（allow_decision_output 默认 True；
  decision_use_status=AVAILABLE_FOR_DECISION）。详见
  research/b2-semantic-review-2026-08-14/RESOLUTION.md。
- 验证：定向 86 passed；全量 526 passed, 25 deselected。

### Round 3 — ops daily-run 2026-08-10（17:50 CST 启动，wall 841s）

- daily 步骤内部完成 promotion：snapshot snap-2026-08-10-f811c7f53089
  SCREEN_READY；generation stategen-2026-08-10-d040fc609ccc ACTIVE；
  fast_path_n=3191（V2 前缀哈希迁移完成，快路径全量生效）。
- **sentinel 失配：605198 fast=B2_READY vs replay=B2_CONFIRMED** →
  cmd_daily_run 判定 SENTINEL_CHECK_FAILED，completed=[]。
- 根因（已定位）：605198 在 08-06 代为 B2_CONFIRMED；旧引擎在 08-07 评估时
  将其降级为 B2_READY（08-07 代状态=评审前产物）；08-10 代从旧 08-07 seed
  推进，继承 B2_READY；而 fresh replay（新引擎）全程保持 B2_CONFIRMED。
- 修复（最小且不动冻结件）：对 08-10 代做**全量重建**（2024-01-01 起，
  修复后引擎，针对已提升的 08-10 快照），经正常 promotion 路径取代旧代；
  无指针回滚、无手工改状态。脚本：
  research/daily-run-20260814/rebuild_generation_20260810.py。

### 重建第一轮失败（job bash-23）

- B2ConfirmationEvaluation 校验失败：
  「normalized_score must derive from score/max」——全量重建重算历史时命中
  取整平局：strategy/b2_confirmation.py 用 ROUND_HALF_UP，而
  models/b2_confirmation.py 校验器用 quantize 默认 ROUND_HALF_EVEN，
  x.xx5 平局时差 0.01。快路径只算新 bar，未命中平局，故此前未暴露。
- 最小修复：校验器 quantize 显式 rounding=ROUND_HALF_UP（与计算层及项目
  惯例一致）。定向测试 test_b2_confirmation/test_models/test_strategy_engine
  66 passed。
- 重建重跑（job bash-24）：**成功**。新代 stategen-2026-08-10-bf507b268263
  ACTIVE，semantic_root 92ddb935...；重建自带 sentinel 4/4 match（605198
  fast=B2_CONFIRMED == replay=B2_CONFIRMED）。formal_state_pointer →
  bf507b268263（旧代 d040fc609ccc 保留为历史）。
- 链条尾部补齐（research/daily-run-20260814/complete_tail_20260810.py）：
  trade-plan 5.99s（**actionable=175 / b1_prep=0 / plans=192**，门开放后的
  首个真实决策输出，for_trade_date=null 属预期——离线快照不猜未来交易日）；
  news-brief 命中 3 只（announcement 2 + dragon_tiger 1）；
  watchlist 写出 research/daily-review/2026-08-10-HUMAN-WATCH.md；
  reconcile OK（pointer == snap-2026-08-10-f811c7f53089 /
  stategen-2026-08-10-bf507b268263）。
- 独立自评审（self_review.py 2026-08-10）：初读旧 summary 有 2 项误报，
  经即时 sentinel 复核（4/4 match）+ ops status + reconcile 修正后
  **ok=true，18/18**（amended 记录见 self-review-20260810.json）。
- 08-11 启动：ops daily-run 2026-08-11（后台 job bash-25）。

### Round 4 — ops daily-run 2026-08-11（18:20 CST 启动，wall 868.51s）

- daily OK：snap-2026-08-11-8ba1089875cb SCREEN_READY；
  stategen-2026-08-11-7447eb13d898 ACTIVE；fast_path_n=3189（快路径生效）。
- trade-plan OK：actionable=0 / plans=0 → NO_TRADE 日（合法，不为交易强制选股）。
- news-brief 跳过（无候选）；watchlist OK。
- **reconcile 步骤类型 bug**：cmd_daily_run 把 get_formal_pointer() 返回的
  [id, hash] 列表与字符串比较 → SNAPSHOT_POINTER_MISMATCH 误报（我引入的
  编排代码 bug，非流水线问题）。
- 最小修复：ops.py reconcile 取 pointer[0] 比较；测试 fixture 改为列表
  （真实形态），15 项定向测试通过。
- reconcile 复核（真实指针）：pointer=snap-2026-08-11-8ba1089875cb /
  state=stategen-2026-08-11-7447eb13d898 一致 → timing.json 修正为 OK。
- 独立自评审：**ok=true，18/18**（self-review-20260811.json）。
- 08-12 启动：ops daily-run 2026-08-12（后台 job bash-26）。

### Round 5 — ops daily-run 2026-08-12（18:47 CST 启动，wall 920.78s）

- **status=OK，五步全过**（reconcile 修复生效后首条完整干净链条）：
  daily（snap-2026-08-12-b1c93a80b1e8 / stategen-2026-08-12-651fc28e55c5）
  → trade-plan（actionable=0，NO_TRADE 日）→ news-brief 跳过 → watchlist →
  reconcile（pointer 一致，含 content hash 681e1bfe...）。
- 独立自评审：**ok=true，18/18**（self-review-20260812.json）。
- 08-13 启动：ops daily-run 2026-08-13（后台 job bash-27，fetch 阶段被 Owner
  叫停，指针仍在 08-12，状态一致；抓取缓存复用）。

## asl fast 试用、修复与集成（Owner 指令）

### 试用结论（配置 /Users/luke808/AI/asl-shared-config.toml）

- sql / screen / stats / export 四子命令全部可用：全市场涨停回踩 screen
  198ms、breadth/returns/limitup 128-137ms、特征 export 372ms。

### 修复 1 — 统计窗口 off-by-one（ASL 仓库 query/fast.py）

- 问题：_bars_cte 先按日期窗口过滤再 LAG(close)，窗口第一天 prev_close 恒
  NULL → breadth 首日 n=0、returns 丢首日。
- 修复：_bars_cte 增加 pad_start（窗口下界前移 14 个自然日），breadth/
  returns/limitup_series 传入 pad 并在最终输出裁回 trade_date >= start。
- 测试：新增 2 个回归测试（窗口自湖底之后开始），tests/unit/test_cli_fast.py
  23 passed；真实湖复核：08-07 n=7246、08-11 收益分布回归。

### 修复 2 — 复权因子新鲜度（ASL lake）

- 问题：adj_factors 停在 08-07，screen 的 hfq 回调对 08-10..08-13 回退原始价
  （adj_is_exact=false）。
- 修复：asl derive adj_factors（ASL 自身入口，env -u ALL_PROXY）→ max 追平
  2026-08-13（+70,035 行；0.8% sina 取数失败由工具如实报告）。复核：screen
  全行 adj_is_exact=true。

### 集成 — ops daily-run 新增 fast-radar 观察步骤

- 新模块 src/limit_pullback/fast_radar.py：经 asl fast（ASL_BIN/ASL_CONFIG
  环境可覆盖）跑 screen（回调 3-15% 前 30）+ breadth（1 日）+ limitup 榜，
  确定性 content_hash，fail-closed（FastRadarError）。
- daily-run 链条变为 daily → trade-plan → news-brief → **fast-radar** →
  watchlist → reconcile；雷达 markdown 段追加进 watchlist（OBSERVATION 层，
  不进入冻结策略）。--radar-top 参数（默认 30）。
- 测试：tests/test_fast_radar.py 5 项 + daily-run 编排测试更新，18 passed；
  真实湖端到端：screen 20 只、涨停榜 50、广度 1 日，hash 66873e8a...。

### 测试套件提速（Owner 指令）

- 测量：test_warehouse_probe.py::test_probe_provider_error 22.5s 等——生产
  probe 重试退避的真实 sleep 被测试继承。
- 修复：tests/conftest.py 新增 autouse no_retry_backoff_sleeps（time.sleep
  no-op，豁免唯一需要真实节拍的采样线程测试）；pytest-xdist 装入 venv 并
  加入 pyproject test extra；AGENTS.md 验证命令改为 pytest -q -n auto
  （串行/集成用 -n 0）。
- 结果：串行 234s → 73s；并行 **234s → 25.8s（约 9 倍）**，531 passed。
- 08-13 重启：ops daily-run 2026-08-13（后台 job bash-31）。

### Round 6 — ops daily-run 2026-08-13（19:36 CST 重启）

- **status=OK，六步全过（首个含 fast-radar 的完整链条）**：
  daily 207.9s（fetch 缓存复用，snap-2026-08-13-bed1fd379696 /
  stategen-2026-08-13-7fb1e965cdc7）→ trade-plan（actionable=0，NO_TRADE）
  → news-brief 跳过 → **fast-radar 3.27s（screen 30 只 + 涨停榜 50）** →
  watchlist → reconcile（pointer 一致）。
- 独立自评审：**ok=true，18/18**（self-review-20260813.json）。
- 至此链条 08-10/11/12/13 全部推进完成，formal pointer 停在 08-13。

### daily-run 耗时优化（Owner 指令「继续优化速度」）

- 测量：provider 抓取占 daily wall 的 85-90%（752-841s），其中 TDX ~4 分钟、
  Tencent ~10 分钟，且两者**串行**；计算部分（staging/promotion/state gen/
  sentinel/plan/radar）仅 2-3 分钟。
- 优化 1：daily_catchup.py 把 TDX 与 Tencent 改为**并发执行**
  （ThreadPoolExecutor(2)，各自独立缓存目录；线程异常经 f.result() 传播 →
  fail-closed 不变）。summary 增加 tdx_wall_seconds / tencent_wall_seconds。
- 优化 2：config/runtime.yaml tencent_workers 16 → 32（Tencent 经代理
  延迟敏感，翻倍并发）。
- 边界修复：_sha256_file 对空抓取（无行→无文件）返回空流哈希，summary 保持
  确定性。
- 测试：新增 tests/test_daily_catchup.py 4 项（并发重叠证明/缓存复用/失败
  记录/异常传播）；全量 535 passed / 29.4s（-n auto）。
- 基准验证：08-14 冷抓取 benchmark（仅写 data/tmp/bench-*，不动仓库，
  后台 job bash-32）；预期 provider wall 从 ~841s 降至 ~max(TDX, Tencent/2)
  ≈ 5-6 分钟量级。

### 策略重算（全量重建）优化（Owner 指令「减少 ~8 分钟」）

- 测量：重建耗时 92% 在 calculate_indicators（纯 Python Decimal，每代码
  全历史窗口均值/位置，O(n·W·w)）。
- 实验 1（滚动窗口重写）：**失败**。真实数据上 473/593 个点与原始实现
  分歧——Decimal 加减在 28 位上下文精度下**会舍入**，滚动累加的舍入序列
  与逐窗求和不同，窗口越大漂移越多；黄金锚 92ddb935 失配 → 已回退。
  教训：合成 2 位小数数据测不出舍入分歧，差分测试必须用满精度数据。
- 实验 2（指标缓存，bit-identical by construction）：**已实现**。
  src/limit_pullback/screen/indicator_cache.py（v1；JSON 存 Decimal 字符串，
  精确回环）；screen_code 命中则跳过 calculate_indicators，未命中计算并写
  缓存；key = (snapshot_id, config_hash[:16], code)，经 run_screen /
  build_state_generation 在 rebuild 模式自动启用（cache dir:
  data/screen/indicator_cache/...）。读失败一律 MISS，缓存永远不是正确性
  依赖。测试 tests/test_indicator_cache.py 3 项；全量 538 passed / 25s。
- 验证中：golden round1（后台 bash-35）灌缓存并验语义根==92ddb935；
  round2 热缓存重跑测速（预期 ~1-2 分钟，vs 原 ~8 分钟）。
- **修正**：equiv 脚本经 resolve_formal_screen_ready_snapshot 取的是当前
  formal 指针——链条已推进到 08-13，脚本实际重建的是 08-13 快照，语义根
  6ac756a0 ≠ 92ddb935 是**脚本 bug**（比错对象），非缓存/回退问题。已改用
  equiv_check_v2_20260810.py：显式 pin snap-2026-08-10-f811c7f53089 +
  run_screen 直跑（无指针检查、不 promotion、dry-run）。滚动实验的结论不受
  影响（其分歧由真实 bars 逐点对比独立证明，593 个点中 473 个分歧）。
  v2 round1（后台 bash-36）灌 08-10 缓存并验根；round2 热缓存测速。

### 重建耗时实测与结论

- **修正脚本后（显式 pin 08-10 快照）GOLDEN_MATCH=True**：缓存+回退在锚点
  commit（_git_head=26cb139...）下逐位复现 92ddb935（v2 round1，wall 230.3s）。
- 热缓存 round（0.1s）实为 run_screen **运行级结果缓存**命中（run_id 相同）；
  用新 commit 强制绕过后的真热缓存测量：**231.6s ≈ 冷跑 230.3s**——指标计算
  不是全量重建的主导成本。
- 单票拆分实测：canonical 加载 ~4ms/票；screen_code 冷/热均 ~60ms/票——
  主导是**冻结引擎的逐会话求值**，指标缓存只省 ~15-30s（保留：bit-identical、
  有测试、未来数学层变重时收益变大）。
- 并行度：wire 了 runtime.screen_process_workers（此前是死配置，run_screen
  硬编码 4）→ run_screen/build_state_generation/ops 全链路；8 workers 实测
  213.2s（vs 230.3s，~8%）、峰值 RSS 5.9GB（安全）。runtime.yaml 已设 8。
- **诚实结论**：策略修改后的全量重建 ≈ 3.5 分钟纯计算（4w=230s/8w=213s）
  + promotion/verification 开销；此前「7.3-8 分钟」含旧管线与全流程。剩余
  时间由 3191 票 × 冻结逐会话求值构成，软件层无可进一步压榨的空间（除非动
  冻结语义或用更多核）。运行级缓存使完全相同的重建免费（0.1s）。

（round 结束后执行 research/daily-run-20260814/self_review_20260807.py）
