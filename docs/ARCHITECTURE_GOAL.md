# 架构目标 v2 — 三层解耦的形态策略研究系统（2026-08-14 重写）

> 依据 2026-08-14 与 Owner 的策略讨论重写。旧目标（四 Agent 架构 + 每日
> 链条）已完成部分保留，本文定义后续演进方向。

## 目标（一句话）

让「形态假设 → 因子化 → PIT 统计验证 → 缩小候选范围」成为一条可复用、
带 provenance 的流水线：研究者只定义因子与假设，不关心数据管道怎么运行；
数据准确由既有冻结链路保证，速度由「数据库内筛选 + 状态机验证」两层分工
保证。

## 三层架构

### L1 数据链与冻结语义层（既有，不动）

- V flash 仓库（formal snapshot/state 指针链）+ ASL 湖（只读）
- 冻结 setup_stage 生命周期（LIMIT_ANCHOR/WATCH_PULLBACK/B1/B2/INVALID）、
  阈值、评分、S1/S2、Entry Room 语义
- PIT replay、episodes（31422 条 corrected）、execution_reality（T+1
  strict/conservative）
- 职责：数据准确（provenance/hash/对账）、每日推进（ops daily-run）

### L2 研究因子层（新增，快速迭代）

- 把策略文档里的叙述性因子写成 **PIT 纯函数/派生标签**，附着在 episodes
  上：T0 质量、回调深度与天数、缩量比、支撑事件、B2 放量倍数、TTL、
  SECOND_LAUNCH/FAILED 事件标签
- 落点：src/limit_pullback/factor_lab/（正式模块 + 单元测试，替代临时
  研究脚本的重复计算部分）
- 铁律：**只读冻结引擎输出，绝不改写 setup_stage/评分/阈值**；
  SECOND_LAUNCH/FAILED 是研究层事件标签（像 S2_EXHAUSTED 那样），
  不是新 setup_stage

### L3 统计验证层（cohort 对比）

- 假设注册表（H1-H10，见下）+ 固定样本（frozen snap-2026-07-31
  in-sample；08-03 之后 forward-only）
- 结论分类 REJECT / OBSERVE_ONLY / SUPPORTED；SUPPORTED != PROMOTED
- 每个研究记录：输入 hash、脚本、输出、结论状态

## 假设待办（按验证优先级）

| # | 假设 | 优先级 |
| --- | --- | --- |
| H1 | T0 质量（位置+换手+封板形态+连板数）显著分层「是否存在第二波」 | P0 |
| H2 | 回调天数与第二波概率非单调：存在最优窗口，之后衰减（TTL 依据） | P0 |
| H3 | 回调最低量/T0 量（缩量深度）区分 SUCCESS/FAILED | P0 |
| H4 | 支撑共振数量 > 单一支撑类型（B1 有效性） | P1 |
| H5 | B2 重新放量倍数（vs 回调均量）区分真突破与诱多 | P1 |
| H6 | B2 后早期失败信号（次日跌回平台、巨量长上影）有增量预测力 | P1 |
| H7 | 板块共振提升成功率（先修板块 proxy 数据质量） | P2 |
| H8 | 高换手是强/弱信号取决于位置与结构（交互项） | P2 |
| H9 | 三倍量单独无区分度，仅与 B2 结构条件组合有增量 | P2 |
| H10 | quality>=80 cohort 正效应在形态细分后仍稳健 | P2 |

## 分步计划

1. 因子目录 FACTOR_CATALOG.md：每个因子 = 精确定义（as_of PIT）+ 数据源 +
   现状（复用冻结字段 / 复用 b2_confirmation 字段 / 需新算 / BLOCKED）
2. factor_lab 模块骨架 + 首批因子（H1-H3 所需）+ 单元测试
3. H1-H3 cohort 验证脚本（frozen episodes）+ 报告
4. TTL 研究（H2 结论 → 研究层结论，不落地生产规则，除非 Owner 单独批准）
5. 架构收口：研究脚本按主题归档、目录治理、docs 更新
6. WIP 与全部改动一起 commit（不 push/不 PR）

## 边界（继承项目铁律）

- 冻结语义不可动；PIT；幸存者偏差防护（delisting 重建）；禁止同样本调参+验证；
- 数据准确 = provenance 完整（hash/对账/fail-closed）；
- 速度 = 数据库内做筛选（asl fast 类 SQL），状态机做验证——两层分工，
  不混用；
- 筹码类因子短期 BLOCKED（CHIP SNAPSHOT PROBE UNAVAILABLE，禁止自研）。

## 成功标准

- factor_lab 至少 6 个 PIT 因子 + 单元测试全绿
- H1-H3 各有 cohort 报告（样本数、分布、结论状态）
- 新研究不再新增乱放脚本；一律走 factor_lab + 验证层模板
- 全量测试绿 + WIP 已 commit
