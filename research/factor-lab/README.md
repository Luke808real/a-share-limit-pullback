# factor-lab 研究层约定

L2 研究因子层 + L3 统计验证层的落点。目标见 docs/ARCHITECTURE_GOAL.md。

## 目录

- FACTOR_CATALOG.md — 因子目录（F01-F23：PIT 定义、数据源、现状标记
  REUSE / REUSE_B2C / GAP / BLOCKED）
- *.py — 研究脚本（每个脚本 = 一个研究问题批次）
- runs/<study>/ — 输出（json 统计 + md 报告，均带输入/脚本/输出哈希）

## 铁律

1. 因子 = PIT 纯函数（src/limit_pullback/factor_lab/），只读冻结输出，
   不改 setup_stage/评分/阈值；
2. 每份报告：输入 provenance（episodes SHA、snapshot id）、脚本哈希、
   输出哈希、结论状态（REJECT / OBSERVE_ONLY / SUPPORTED）；
3. 描述性分布对比，不搜索阈值、不同样本调参+验证；
4. SUPPORTED != PROMOTED；升级需 forward 验证 + Owner 批准 + ADR；
5. forward 样本（08-03 之后）只用于复查，不得回改历史结论。

## 已完成研究

- h1h3-v01：H1 OBSERVE_ONLY(弱) / H2(F11口径) REJECT / H3(F14) OBSERVE_ONLY
- ttl-h5h6-v01：信号时点单调 4.4%→72.1%；F14 全局分离部分为阶段混合；
  F19 弱；F21 循环定义 REJECT
- ttl-survival-v01：B2 集中于 T+2/T+3；T+5 后复活 ≤1% → 研究层 TTL≈5-6 日
- h6-f23-v01：F23（回调期价跌量增）作为全局失败负向结构因子 REJECT
  （strict_win_rate delta +0.0141 与假设相反；timing 分层 4/4 负向、stage
  分层 0/3 负向 → 强 timing/stage composition 依赖）。OBSERVATION ONLY：
  F23_ANY 与较低 mean_R 存在描述性关联（胜率未同步恶化，收益分布形态可能
  不同）；未经 tail quantile/significance 专门验证，非 validated tail effect。
  不得作为 B1/B2 排除规则或 production filter。
- h4-support-zone-v01：H4 SUPPORT ZONE CONTRACT V01（contract/provenance/
  implementation only，无统计）：E04 t0_body_touch、E05
  platform_support_touch PIT 纯函数 + 合成测试；support_low/high 冻结
  provenance 确认（SupportSnapshot 冻结语义 + episodes 列 schema）；
  F18 = FEASIBLE_FOR_NEXT_ROUND_CONTRACT
- h4-closeout（2026-08-15，H4 SUPPORT ZONE CONTRACT AUDIT FIX V01 记录）：
  H4A = REJECT；H4B = REJECT（dual-metric hypothesis）；E03「跌破 MA10 后
  3 日内快速收回」= strong hit-rate OBSERVATION，NOT VALIDATED /
  NOT PROMOTED；H4B R reconciliation = CLOSED。审计修复：E05 恢复冻结
  相交口径（low<=support_high 且 high>=support_low）+ missing→None；
  F18 的 ±2% 标记为 LEGACY CATALOG DRAFT / NOT FROZEN
- f18-support-confluence-v01（2026-08-15，F18 SUPPORT CONFLUENCE CONTRACT
  V01）：F18 支撑共振 PIT 数学合同冻结 + 纯函数实现（contract/
  implementation only，无统计、无 outcome、无阈值搜索）：Z_MA10(D)=
  [MA10(D),MA10(D)]、Z_T0=[min(o,c)(T0),max(o,c)(T0)]、Z_PLATFORM=
  [support_low,support_high]；共振 = 同交易日三区间均被 K 线触及（区间
  相交）且价格真实重合（MA10(D)∈Z_T0∩Z_PLATFORM）；计数满足条件的
  D ∈ (anchor,as_of]。无容差（±2% 废弃）。missing support / MA10 不足 →
  None；非法区间/anchor/多 code/重复日期 fail closed
