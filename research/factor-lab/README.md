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
  CONTRACT V01；CONTRACT = FROZEN / IMPLEMENTED，审计后状态见下方
  insufficient-history audit fix 条目）：F20 = vol(B2 日) / mean(vol,
  B2−20..B2−1)，窗口为 B2 之前最近 20 个可见交易日（B2 当日不进入分母）。
  实现：factor_lab.b2_volume_vs_20d_mean。无 outcome、无阈值、无合同外语义。
  待 outcome validation
- fix/f20-contract-insufficient-history-v01（2026-08-16，F20 CONTRACT
  INSUFFICIENT-HISTORY AUDIT FIX V01；audit CHANGES_REQUIRED 修复）：
  **PRE20 = strictly last 20 visible trading sessions before B2**（仅
  trade_date < b2_date 参与；future rows 内部自动排除——PIT 正确性由
  函数内部保证，caller pre-truncation 只是上层 PIT hygiene）；**PRE20_N < 20
  -> None**（0/1/19 个 pre-B2 session 均返回 None，短窗口不再求均值）；
  F20 其余语义不变（B2 不进分母、恰好 20 根、21 根取最后 20、零均量
  -> None、missing B2/anchor/duplicate/multi-code -> ValueError）。
  测试拆出独立 future-leak 测试（B2 后巨大 volume bar 不影响 F20）。
  F20 CONTRACT = **NOT CLOSED，pending audit fix 独立审计**；
  不写 SUPPORTED / VALIDATED / PROMOTED。无 outcome、无阈值、F19 未改
- research/f20-outcome-prereg-v01（2026-08-16，F20 OUTCOME VALIDATION
  PREREGISTRATION V01；**F20 CONTRACT = CLOSED**，Sol audit PASS 于
  ff4ea77）：只冻结统计设计，未读取 outcome、未运行正式验证。
  设计：H5A 连续 Spearman 双 gate（rho_strict > 0 AND rho_R_positive >
  0 → SUPPORTED_DIRECTIONALLY 否则 REJECT）；undefined F20 仅 accounting
  不进 primary；quartile Q1-Q4 仅描述；stage/timing composition 只报告
  方向、N<20 SMALL_CELL；禁止 threshold mining（1.2/1.5/2/3/top decile）。
  产物：runs/f20-outcome-prereg-v01/f20-outcome-prereg-v01.md。
  OUTCOME VALIDATION = **PREREGISTERED / NOT RUN**；不得写 SUPPORTED /
  REJECT / VALIDATED
- research/f20-outcome-validation-v01（2026-08-16，F20 OUTCOME VALIDATION
  V01；预注册 758768e 后正式验证 + prereg-compliance audit fix v01
  （Sol review @648aa06 修复：去掉 stage 预过滤、冻结 Spearman 实现、
  PRIMARY_RHO_UNDEFINED fail closed、undefined reason 拆分、补独立测试））：
  primary population = 全部 resolved（冻结映射，F20 自身定 defined），
  DEFINED 9508 / UNDEFINED 117（INSUFFICIENT_PRE20，无 ZERO_DENOMINATOR/
  OTHER_ERROR）；H5A 双 gate：rho_strict = -0.1127（N=7765）AND
  rho_R_positive = -0.1182（N=7765）→ 双 gate 均非正 → **OUTCOME
  VALIDATION = REJECT**。stage 三层：B1_READY -0.010/-0.010、B2_READY
  +0.056/+0.056（strict 编码与 R>0 在该两层 100% 一致，数据属性）、
  B2_CONFIRMED -0.015/-0.093；quartile Q1-Q4 无单调；composition 只报告
  方向。产物：runs/f20-outcome-validation-v01/f20-outcome-validation-v01.{json,md}；
  测试：tests/test_f20_validation.py（SHA 门禁、no bypass、undefined
  isolation、accounting、ties、CANCEL exclusion、numeric-R、fail closed、
  future leakage、quartile 独立性）。VALIDATED = NO；PROMOTED = NO；
  禁止 threshold mining；不得写 SUPPORTED / VALIDATED。
- research/factor-lab-phase-synthesis-v01（2026-08-16，FACTOR LAB 阶段性
  综合决策；**索引**——不改变任何 factor verdict）：CLOSED_FACTOR_N=8
  （F11/F14/H4A-H4B/E03/F18/F23/F19/F20），REJECT_N=6、OBSERVE_ONLY_N=1、
  OBSERVATION_N=1。模式：静态结构/放量正向单因子连续失败；时间/状态结构
  有信息。决策：**NEXT_FACTOR = F22（巨量长上影，失败结构/假突破方向）**；
  F21（B2 次日跌回平台）因循环定义已 REJECT（ttl-h5h6-v01）排除。
  产物：runs/factor-lab-phase-synthesis-v01/factor-lab-phase-synthesis-v01.md。
- research/f22-contract-pit-v01（2026-08-16，F22 CONTRACT/PIT；FROZEN/CLOSED，
  AUTHORITY d3325e2，K=1.0 OWNER_FROZEN）：EOD failure-risk diagnostic，
  **INTRADAY_B2_ENTRY_ELIGIBLE = NO**（上影+全天量仅收盘后确定；
  NEXT_DAY_RISK / HOLD_EXIT_DIAGNOSTIC / POST_B2_FAILURE_RESEARCH 方向）。
  契约：SHAPE_TRUE = UPPER_SHADOW>0 AND UPPER_SHADOW>=BODY（乘法式，
  BODY=0 合法非 undefined）；PRE5 = B2 前严格 5 个 visible sessions；
  VOLUME_TRUE = VOL_RATIO>=1.5；F22_TRUE = SHAPE_TRUE AND VOLUME_TRUE，
  可计算未触发 = DEFINED FALSE；undefined 仅数据不可计算类。
  产物：runs/f22-contract-pit-v01/f22-contract-pit-v01.md。
- research/f22-factor-implementation-v01（2026-08-16，F22 实现）：
  `factor_lab.b2_huge_upper_shadow_volume(bars, b2_date) -> bool | None`
  （布尔因子；None 仅 INSUFFICIENT_PRE5 / ZERO_DENOMINATOR；B2 bar missing →
  ValueError fail closed；**F22 has no anchor dependency**；future rows
  内部排除；INVALID_B2_OHLCV is rejected by canonical DailyBar validation
  upstream——F22 assumes valid DailyBar instances）。**CONTRACT FROZEN /
  IMPLEMENTATION PASS / CLOSED（AUTHORITY
  cd3d676c756a85e4c0ef2d3ffb82d2edc61ea43f）**；不得写 VALIDATED /
  SUPPORTED / PROMOTED；prereg 冻结后 F22_TRUE vs outcome 已由
  f22-outcome-validation-v01 冻结验证（REJECT）。测试：
  tests/test_factor_lab.py（F22 15 项：TRUE/FALSE/BODY=0/PRE5<5/零均量/缺失
  fail closed/future leak/no-anchor）。
- research/f22-outcome-prereg-v01（2026-08-16，F22 OUTCOME VALIDATION
  PREREGISTRATION V01；**PASS / FROZEN / CLOSED（AUTHORITY
  3d2c8a71318aa8d45fca499100c880f962ad9caf）**）：H22A——B2 日巨量长
  上影（F22_TRUE）预示 SECOND_LAUNCH 失败风险更高（EOD failure-risk
  diagnostic，负面信号）。population = resolved AND stage ∈ {B2_READY,
  B2_CONFIRMED}；strict binary（CANCEL_GAP 排除）+ R-defined；primary gate：
  DELTA_FAIL_RATE > 0 AND OR_FAILURE > 1 → SUPPORTED_DIRECTIONALLY 否则
  REJECT；N<20 → INSUFFICIENT_PRIMARY_N；PRIMARY_METRIC_UNDEFINED → FAIL
  CLOSED；禁止 threshold mining / 子组 rescue；undefined 仅 accounting。
  产物：runs/f22-outcome-prereg-v01/f22-outcome-prereg-v01.md。
- research/f22-outcome-validation-v01（2026-08-16，F22 OUTCOME VALIDATION
  V01；预注册 3d2c8a7 PASS/FROZEN/CLOSED 后正式验证）：population = resolved
  AND stage ∈ {B2_READY, B2_CONFIRMED}，POPULATION_N=3214；F22 materialize
  全部成功：DEFINED_TRUE_N=196、DEFINED_FALSE_N=3018、UNDEFINED_N=0（无
  undefined reason，守恒成立）。primary：PRIMARY_TRUE_N=176（WIN 129 /
  LOSS 47，FAIL_RATE=0.2670）、PRIMARY_FALSE_N=2722（WIN 1904 / LOSS 818，
  FAIL_RATE=0.3005）；DELTA_FAIL_RATE=-0.0335（<0，方向反转）AND
  OR_FAILURE=0.8481（<1）→ **OUTCOME VALIDATION = REJECT**（F22_TRUE 组失败
  率反而更低，H22A 不支持；方向反转按 prereg §6 记录 observation）。
  stage/timing composition 仅描述（B2_READY TRUE 0.359 vs FALSE 0.366；
  B2_CONFIRMED TRUE 0.214 vs FALSE 0.244；T1-2 TRUE 0.364 vs FALSE 0.371，
  其余 timing 层 TRUE 均更低），不改变 verdict。产物：
  runs/f22-outcome-validation-v01/f22-outcome-validation-v01.{json,md}；
  测试：tests/test_f22_validation.py（SHA 门禁、no bypass、undefined
  isolation、accounting 守恒、CANCEL 排除、numeric-R、primary metrics 手算、
  verdict 分支、PRIMARY_METRIC_UNDEFINED fail closed、small cell N<20、
  B1_READY 排除、future leakage）。VALIDATED = NO；PROMOTED = NO；
  禁止 threshold mining；不得写 SUPPORTED / VALIDATED。
