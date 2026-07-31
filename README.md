# A-share Limit Pullback

纯盘后、单股票的A股涨停回调策略检查器。Phase 2C.1支持任意合法沪深主板六位
代码的 `inspect` / `replay`；Phase 2C.2A提供本地多数据源历史行情仓库
（Tushare 主日线 + AKShare 交叉验证/涨停池 + BaoStock 历史补录），但不提供
全市场扫描、HTML报告、回测、盘中监控或自动交易。

## CLI

安装项目依赖后，可在内存中运行：

```bash
python -m limit_pullback inspect \
  --code 603318 \
  --as-of 2026-07-30 \
  --days 400

python -m limit_pullback replay \
  --code 603318 \
  --as-of 2026-07-30 \
  --lookback-calendar-days 400
```

`inspect`是`STATELESS_INSPECT`，只解释指定交易日；它没有上一信号，不能还原
B2生命周期。`replay`是`POINT_IN_TIME_REPLAY`，会从早到晚传递上一交易日信号。
两者只向stdout输出JSON且不自动写文件。

允许深圳000/001/002/003及上海600/601/603/605前缀。代码必须保留为六位字符串；
创业板、科创板、B股、北交所及未知前缀会在Provider调用前拒绝。合法代码并不
保证请求日存在行情。

默认测试完全封禁socket：

```bash
pytest -q
```

真实Provider测试必须显式运行：

```bash
pytest -m integration -q
```

## Phase 2C.2A 本地行情仓库

仓库命令把真实数据写入默认 `data/` 目录（可用 `--data-root` 或环境变量
`LIMIT_PULLBACK_DATA_ROOT` 覆盖）；`data/` 已被 Git 忽略，真实行情永不入库。

```bash
# 探测 Tushare 各接口能力（仅从环境变量 TUSHARE_TOKEN 读取认证）
python -m limit_pullback provider-probe --provider tushare

# 历史 bootstrap：下载 → 单位标准化 → 对账 → canonical 快照
python -m limit_pullback bootstrap \
  --start 2026-06-01 --end 2026-07-30 \
  --codes 603918 603318 002640 600199 002891

# 幂等每日增量更新
python -m limit_pullback update --as-of 2026-07-31

# 仓库状态与完整性校验
python -m limit_pullback data-status
python -m limit_pullback data-validate
```

布局：

```text
data/
  raw/tushare/            daily_bars, adjustment_factor, daily_basic,
                          suspension, price_limits
  raw/akshare/            daily_bars, limit_up_pool
  raw/baostock/           daily_bars
  canonical/              daily_bars, limit_up_pool（按 snapshot 不可变发布）
  quarantine/             冲突与隔离记录
  manifests/              snapshot manifest（原子提交）
  warehouse.duckdb        运行/能力/文件/快照/对账元数据
```

对账状态：`PROVISIONAL / CONFIRMED / INCOMPLETE / CONFLICTED /
QUARANTINED`。Tushare 与 AKShare 一致时发布 `CONFIRMED`；BaoStock 明确
延迟但双源一致时仍 `CONFIRMED` 并记录 `BAOSTOCK_LAGGING`；OHLC 超容差冲突
进入 `CONFLICTED` 并隔离，绝不发布 canonical；不同来源的字段绝不拼接。
`TUSHARE_TOKEN` 只从环境变量读取，缺失时返回
`TUSHARE_TOKEN_NOT_CONFIGURED`，Token 不会出现在日志、异常、报告或 Git 中。

## Phase 2C.2B 离线全市场 setup 扫描

`screen` 完全离线运行：只读取已发布 canonical 快照中的 `CONFIRMED` 日线
（涨停池取自 canonical pool），不访问任何 Provider、不使用未来数据。

```bash
# 首次/全量重建
python -m limit_pullback screen \
  --start 2026-06-01 --as-of 2026-07-30 --rebuild \
  --snapshot-id snap-xxx --verify-replay

# 日常增量：只推进昨日活动 setup 与当日新 Anchor
python -m limit_pullback screen --as-of 2026-07-31
```

每次运行绑定 `strategy commit / config hash / dataset snapshot / output hash`；
输出（setup 快照、评分、Support、Invalid、B2 Trigger、S1、Entry Room、事件、
数据质量）写入 `data/screen/runs/`，逐股状态写入 `data/screen/states/`。
全量重建与逐日增量必须一致；未来快照不修改历史结果。不实现 B1_PREP、挂单、
持仓、S 点卖出或回测。

要点：

- 历史 `--as-of` 默认只读取该时点已发布的 snapshot；如仓库快照晚于请求日，
  必须显式传 `--snapshot-id`；
- 正式模式不把 `PROVISIONAL` 涨停池记录当作 OK 锚点（质量降 `UNUSABLE`）；
  `--pool-debug` 仅用于调试（降 `DEGRADED` 并输出警告）；
- `NEW_ANCHOR` 仅出现在 `LIMIT_ANCHOR` 且 `anchor_date == trade_date` 的当天；
- 状态绑定 bars/pool 前缀哈希、strategy commit、config hash 与对账策略版本，
  任一变化自动从安全起点重算。
