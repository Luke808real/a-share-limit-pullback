# Changelog

## Unreleased — Phase 2C.1

- 用共享解析器取代三股票白名单，支持指定的沪深主板前缀。
- 为inspect和replay分别增加`STATELESS_INSPECT`与
  `POINT_IN_TIME_REPLAY`输出。
- 加固BaoStock相同重复行去重、冲突重复检测及login/query/logout异常优先级。
- 将日线畸形字段汇总到`missing_fields`并显式传播Provider质量标记。
- 少于120根实际交易日线时标记`INSUFFICIENT_TRADING_HISTORY`并禁止新建仓。
- 夹紧仅由Decimal上下文舍入产生的簇中心越界，不改变簇成员或选择规则。
- 保持Phase 2B.3策略结构语义和`strategy.yaml`阈值不变。
