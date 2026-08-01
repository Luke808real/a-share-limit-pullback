# Changelog

## Unreleased — Phase 2C.2B

- 新增离线全市场 `screen` 命令：`screen --as-of --snapshot-id`（增量）与
  `screen --start --as-of --rebuild`（全量重建）。
- 只读取已发布 canonical 快照的 `CONFIRMED` 日线与 canonical 涨停池；
  全程禁止联网；复用 `evaluate_strategy`，不复制 B1/B2 逻辑。
- 新增逐股状态持久化（`data/screen/states/`）与运行输出
  （`data/screen/runs/`）；状态绑定 `bars_prefix_hash`，行情修订自动重算。
- 每次运行绑定 strategy commit、config hash、dataset snapshot 与
  output hash；相同输入相同输出；全量重建=逐日增量；未来快照不改历史。
- 输出 `NEW_ANCHOR / WATCH_PULLBACK / B1_READY / B2_READY / B2_CONFIRMED /
  INVALID / EXPIRED`，保存评分、Support、Invalid、B2 Trigger、S1、
  Entry Room、事件与数据质量。
- `--verify-replay` 逐代码校验“重建=增量”与“全市场=单股 replay”逐字段一致；
  既有 8 案例真实验收通过。不实现 B1_PREP、挂单、持仓、S 点卖出或回测。
- 复审修复：`NEW_ANCHOR` 严格按锚点创建日定义；历史 `as_of` 只读时点已发布
  snapshot；状态绑定 bars/pool 前缀哈希、strategy commit、config hash 与
  对账策略版本；涨停池 `PROVISIONAL` 正式门禁（D-028）；缓存未验证不得复用；
  公共质量合并提取到 `quality.py`。
- 全市场韧性：bootstrap 写入显式 heartbeat（`.bootstrap_heartbeat.json`）并
  记录限频预计恢复时间（`.rate_limit_wait.json`）；限频失败独立记录为
  `DEFERRED_RATE_LIMIT`（含 retry_at），与真实 FAILED 分开；
  AKShare 抓取可隔离到独立子进程（`--isolate-akshare`），V8 原生崩溃只影响
  该批次。
- 快照与回填：核心行情完成后可发布 `SCREEN_READY` 快照；`--aux-backfill`
  使用独立 run_id 补抓 Tushare 辅助数据集并发布 `RESEARCH_READY` 快照；
  adjustment_factor 补齐后自动重处理 `PRECLOSE_DIVERGENCE_UNCONFIRMED`
  记录并释放确认为除权的行。
- 涨停池政策：单源正式发布状态改为 `CONFIRMED_SINGLE_SOURCE`（正式 screen
  可用，不用 pool_debug）；`PROVISIONAL` 仍仅调试模式。
- 历史覆盖：stock_basic 抓取 L/D/P 三状态并携带 delist_date；universe 按
  上市/退市区间过滤，报告窗口内退市股票覆盖。

## Unreleased — Phase 2C.2A

- 新增 Tushare Pro 认证（仅环境变量）与 `provider-probe` 能力探针
  （`AVAILABLE / UNAVAILABLE_PERMISSION / UNAVAILABLE_PROVIDER /
  MALFORMED_RESPONSE`）。
- 新增 Parquet + DuckDB 本地仓库：`raw/{tushare,akshare,baostock}`、
  `canonical/`、`quarantine/`、`manifests/` 与七张元数据表
  （`provider_capabilities / ingest_runs / dataset_snapshots /
  source_files / reconciliation_results / canonical_publications /
  quarantine_records`）。
- 新增 `bootstrap`（历史回填、断点恢复、幂等）与 `update`（每日幂等增量、
  Provider 修订产生新快照）。
- 新增显式对账：`PROVISIONAL / CONFIRMED / INCOMPLETE / CONFLICTED /
  QUARANTINED`，容差内跨源一致发布 canonical，冲突隔离且不发布。
- 新增 `data-status` 与 `data-validate`（唯一性、OHLC 关系、preclose 连续性、
  Decimal 精度、日期范围、row hash、manifest 哈希、canonical 可追溯、
  禁止字段拼接）。
- 新增不可变 dataset snapshot 与 point-in-time 读取：`as_of` 只回放不晚于
  该边界的早期发布，未来修订不重写旧快照。
- 新增 `.env.example`（`TUSHARE_TOKEN=`），真实 `.env` 与 `data/` 保持
  Git 忽略。
- AKShare 日线使用 `stock_zh_a_daily`（sina）端点（东财 kline 主机在本机
  网络不可达时确定性选择），涨停池继续使用东方财富；不引入静默回退。

## Unreleased — Phase 2C.1

- 用共享解析器取代三股票白名单，支持指定的沪深主板前缀。
- 为inspect和replay分别增加`STATELESS_INSPECT`与
  `POINT_IN_TIME_REPLAY`输出。
- 加固BaoStock相同重复行去重、冲突重复检测及login/query/logout异常优先级。
- 将日线畸形字段汇总到`missing_fields`并显式传播Provider质量标记。
- 少于120根实际交易日线时标记`INSUFFICIENT_TRADING_HISTORY`并禁止新建仓。
- 夹紧仅由Decimal上下文舍入产生的簇中心越界，不改变簇成员或选择规则。
- 保持Phase 2B.3策略结构语义和`strategy.yaml`阈值不变。
