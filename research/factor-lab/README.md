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
  V01；CONTRACT = FROZEN / CLOSED，HEAD e37c57b，Sol audit PASS；
  修订链 7062990 否决 → 7400dc7 主体修复 → e37c57b final semantics）：
  F18 = max_D C(D) ∈ {0,1,2,3}，C(D)=当日激活支撑区间中两两真实公共交集
  的最大子集大小；激活谓词逐因子复用冻结定义（MA=E01 low<=MA10<=close；
  BODY=E04 low∈实体；PLATFORM=E05 区间相交）；跨日不累计；三区间全
  active 必须 Z_MA10∩Z_BODY∩Z_PLATFORM≠∅ 才允许 C=3。实现函数：
  factor_lab.support_confluence_max_count（17 个 F18 测试）。无容差
  （±2% 废弃）。missing support / MA10 不足 → None；结构坏 bar/anchor
  缺失优先于 missing 短路 fail closed；非法区间/多 code/重复日期
  fail closed
- f18-support-confluence-validation-v01（2026-08-15，OUTCOME VALIDATION
  V01；F18 CONTRACT = FROZEN / CLOSED，HEAD e37c57b）：预注册 outcome
  验证（frozen episodes SHA 门禁通过，EPISODES_TOTAL=31422，
  RESOLVED_N=9625，F18_DEFINED_N=9594，UNDEFINED=31 全为 NO_DEFINED_MA10，
  OTHER_ERROR=0；undefined 按审计排除出 primary population）：
  primary contrast F18>=2(N6634) vs F18<=1(N2960)，
  Δstrict_win_rate=−0.0016、ΔP(R>0)=−0.0070 → **H4C = REJECT**；深度表无
  单调性；robust R 显示双方尾部均极端（max_R 69/109，top1pct 贡献为负）。
  **F18 OUTCOME VALIDATION V01 = REJECT；PREDICTIVE_VALUE: global main
  effect not supported；VALIDATED = NO；PROMOTED = NO**（2026-08-16
  hardening v01 收口：accounting invariants + frozen materialization locks
  fail closed、artifact accounting 字段、undefined isolation / wrong-SHA /
  no-bypass 回归测试）。timing 分层观察仅作 OBSERVATION / NEW HYPOTHESIS，
  不升级为规则。预注册纪律：未做 outcome-aware 调参、未搜索阈值、合同未改。
  产物：runs/f18-support-confluence-validation-v01/f18-validation-v01.json
  + f18-validation-report-v01.md + research/f18_validation_v01.py
- f20-b2-volume-20d-contract-v01（2026-08-16，F20 B2 VOLUME VS 20D MEAN
  CONTRACT V01；CONTRACT = FROZEN / CLOSED，HEAD 见本分支）：F20 =
  vol(B2 日) / mean(vol, B2−20..B2−1)，窗口为 B2 之前最近 20 个可见交易
  日（B2 当日不进入分母）。实现：factor_lab.b2_volume_vs_20d_mean
  （含 7 个测试：精确值、恰好最后 20 根、窗口不足、零均量、B2/anchor
  缺失 fail closed、PIT 未来不泄漏）。无 outcome、无阈值、无合同外语义。
  待 outcome validation
