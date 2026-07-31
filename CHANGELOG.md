# Changelog

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
