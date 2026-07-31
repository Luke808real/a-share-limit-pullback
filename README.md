# A-share Limit Pullback

纯盘后、单股票的A股涨停回调策略检查器。当前Phase 2C.1支持任意合法沪深主板
六位代码，但不提供全市场扫描、数据库、报告、回测、盘中监控或自动交易。

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
