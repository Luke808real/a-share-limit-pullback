# 因子目录 FACTOR_CATALOG v1（2026-08-14）

把《涨停回调再启动》策略文档里的叙述因子形式化为可计算定义。原则：
1. 每个因子在 as_of 当天可计算（PIT，无未来数据）；
2. 优先复用冻结 artifacts（episodes 字段、b2_confirmation 特征层），
   不重复计算冻结引擎已产出的东西；
3. 现状标记：REUSE（冻结字段）/ REUSE_B2C（b2_confirmation 已有）/
   GAP（需新算）/ BLOCKED（数据不可得）。

记号：T0 = 锚点日（anchor_date）；Ti = T0 后第 i 个交易日；
vol(D) = 当日成交量；turn(D) = 当日换手；close/low/high 为原始价。

## 1. H1 所需：T0 质量类

| ID | 名称 | PIT 定义 | 数据源 | 现状 |
| --- | --- | --- | --- | --- |
| F01 | T0 位置（60 日） | (T0_close − min(low, T0−60..T0−1)) / (max(high, T0−60..T0−1) − min(low, T0−60..T0−1))，分母为 0 时置 NULL | daily_bars | GAP |
| F02 | 距 120 日高点回撤 | (max(high, T0−120..T0−1) − T0_close) / max(high, T0−120..T0−1) | daily_bars | GAP |
| F03 | T0 前连板数 | T0 之前连续涨停天数（复用冻结 anchor 语义里的 recent_limit 口径，不重算） | 冻结引擎 | REUSE（anchoring 字段已有 recent_limit_count 语义） |
| F04 | 一字板标记 | T0 开盘价 == 涨停价（历史近似：open==high==close 且涨停） | daily_bars | GAP（近似；精确封板时间需分时 → 见 F05） |
| F05 | 封板时间 | 首次封板时刻（早/中/尾盘三分档） | 分钟数据 | BLOCKED（5m 覆盖仅近 ~491 交易日，历史样本不足；近期可试点） |
| F06 | T0 换手 | turn(T0) | daily_bars | **BLOCKED**（2026-08-14 实测：canonical 与 ASL daily_bars 均无 turnover_rate 字段；需换手数据源） |
| F07 | T0 相对 20 日均量 | vol(T0) / mean(vol, T0−20..T0−1) | daily_bars | GAP |
| F08 | 板块共振 proxy | 同板块当日涨停家数占比 | ASL sector_members + limit pool | BLOCKED（SECTOR_V01 已评 LOW_CONFIDENCE_PROXY，先修数据再启用） |

## 2. H2 所需：回调时间与深度

| ID | 名称 | PIT 定义 | 数据源 | 现状 |
| --- | --- | --- | --- | --- |
| F09 | 回调深度 | (T0_close − min(close, T1..Tn)) / T0_close，n = days_since_anchor | daily_bars | GAP |
| F10 | 回调最低点日 | argmin(close, T1..Tn) 的 Ti 序号 | daily_bars | GAP |
| F11 | 回调天数 | 最低点日的 i（即 T0 后第几天见底） | daily_bars | GAP |
| F12 | 至 B2 事件天数 | B2_READY/CONFIRMED 首个事件日 − T0 的天数 | 冻结 states/episodes | REUSE（days_since_anchor + setup_stage 事件日可导出） |
| F13 | TTL 候选 | F12 的分布；研究问题：超过何阈值后第二波概率显著衰减（研究层结论，不落地生产规则） | 同上 | GAP（研究脚本计算） |

## 3. H3 所需：缩量类

| ID | 名称 | PIT 定义 | 数据源 | 现状 |
| --- | --- | --- | --- | --- |
| F14 | 回调缩量比 | min(vol, T1..Tn) / vol(T0) | daily_bars | REUSE_B2C（pullback_volume_ratio 语义近似，需核对口径） |
| F15 | 回调均量比 | mean(vol, T1..Tn) / vol(T0) | daily_bars | GAP |
| F16 | T1 量比 | vol(T1) / vol(T0) | daily_bars | GAP |
| F17 | 换手衰减速度 | (turn(T1) − min_turn(T1..Tn)) / turn(T1) | daily_bars | BLOCKED（同 F06） |

## 4. 支撑事件类（H4）

支撑必须定义为可测事件，否则「支撑有效」是事后叙事：

- E01 触及 MAx：存在 i 属于 T1..Tn 使 low(i) <= MAx(i) 且 close(i) >= MAx(i)（触及未破）
- E02 收盘跌破 MAx：存在 i 使 close(i) < MAx(i)（破位）
- E03 破位后收回：E02 后存在 j>i 使 close(j) >= MAx(j) 且 j−i <= 3
- E04 触及 T0 实体：存在 i ∈ T1..Tn 使 min(open(T0),close(T0)) <= low(i) <=
  max(open(T0),close(T0))（low 进入 T0 实体区间；跌破实体下沿不算触及）
- E05 触及平台（冻结口径）：存在 i ∈ T1..Tn 使 low(i) <= support_high 且
  high(i) >= support_low（K 线区间与冻结支撑区间相交）；support_low/high
  复用冻结 SupportSnapshot（冻结口径，不另定义新平台；缺失 → None，
  audit fix v01 恢复该定义）
- F18 支撑共振深度（F18 SUPPORT CONFLUENCE CONTRACT V01，2026-08-15）：
  对交易日 D，C(D) = 三个支撑区间（Z_MA10(D)=[MA10(D),MA10(D)]、
  Z_BODY=[min(open,close)(T0),max(open,close)(T0)]、Z_PLATFORM=
  [support_low,support_high]）中「当日激活（激活谓词逐因子复用冻结定义：
  MA=E01 low<=MA10<=close；BODY=E04 low∈实体；PLATFORM=E05 K 线区间与
  冻结区间相交）且两两存在真实公共交集」的最大子集大小（0–3）；
  F18 = max_D C(D) ∈ {0,1,2,3}，跨日不累计。三区间全 active 必须
  Z_MA10 ∩ Z_BODY ∩ Z_PLATFORM ≠ ∅ 才允许 C(D)=3。无容差（±2% 废弃，
  仅存于 h4-support-zone-v01 报告 §5 的 LEGACY CATALOG DRAFT 备注）。
  实现函数：factor_lab.support_confluence_max_count（audit fix v01 规范名）。

现状（2026-08-15，H4 SUPPORT ZONE CONTRACT V01）：
- E01-E03 → IMPLEMENTED（factor_lab.ma10_touch_hold / ma10_close_break /
  ma10_reclaim_within_3d，commit 7741ba5；与 b2_confirmation 的
  touched_below_ma5/10/18_7d 口径不同——那是「7 日内曾跌破」）
- E04 → IMPLEMENTED（factor_lab.t0_body_touch，本轮 contract v01）
- E05 → REUSE+IMPLEMENTED（factor_lab.platform_support_touch，冻结
  provenance 已确认：SupportSnapshot 由冻结引擎在 B1_READY 首日冻结、
  单调承继，随 frozen states/replay 与 episodes 的 support_low/high 列
  落盘；函数只接收冻结值，不重算平台；audit fix v01 恢复冻结相交口径
  low(D)<=support_high 且 high(D)>=support_low，missing → None）
- F18 → CONTRACT FROZEN / CLOSED（Sol audit PASS，HEAD e37c57b；修订链
  7062990 否决 → 7400dc7 主体修复 → e37c57b final semantics；
  factor_lab.support_confluence_max_count，F18 = max_D C(D) ∈ {0,1,2,3}）。
  OUTCOME VALIDATION V01（frozen episodes，N=9625 resolved，审计修正后
  primary population = F18 定义样本 9594）：H4C = REJECT——CONFLUENCE
  (F18>=2, N6634) vs NON_CONFLUENCE(F18<=1, N2960)：Δstrict_win_rate
  −0.0016、ΔP(R>0) −0.0070、Δmean_R −0.052、Δmedian_R 0.0（undefined
  F18 已按审计排除，Δswr 符号修正后为负）；深度表（0/1/2/3）无单调性
  （F18=0 层 strict_win_rate 0.312 最优，F18=3 层 mean_R −0.279 最差）；
  stage 方向 1/3、timing 方向 3/4。
  F18 PREDICTIVE VALUE = UNKNOWN；VALIDATED = NO；PROMOTED = NO（不得进入
  策略打分）。见 runs/f18-support-confluence-validation-v01/

## 5. B2 放量类（H5）

- F19 B2 放量倍数：vol(B2 事件日) / mean(vol, T1..T(n-1))（相对回调均量）
- F20 B2 放量倍数（相对 20 日均量）：vol(B2 日) / mean(vol, B2−20..B2−1)
  （F20 B2 VOLUME VS 20D MEAN CONTRACT V01，2026-08-16：factor_lab.
  b2_volume_vs_20d_mean(bars, anchor_date, b2_date) -> Decimal | None；
  **PRE20 = strictly last 20 visible trading sessions before B2**
  （仅 trade_date < b2_date 参与；future rows 内部自动排除；B2 当日
  不进入分母；anchor 位于 PRE20 内或外均不改变该定义）；
  **PRE20_N < 20 -> None**（0/1/19 个 pre-B2 session 均返回 None，
  audit fix v01）；窗口均量为 0 → None；anchor/B2 bar 缺失、重复日期、
  多 code → ValueError fail closed。**PIT：F20 内部保证 future rows 不参与（PRE20 仅取 trade_date < b2_date）；caller pre-truncation 只是上层 PIT hygiene，不是正确性依赖**。
  见 tests/test_factor_lab.py）
  **F20 != F19**：F19 = B2 / pullback mean(T+1..B2−1)（事件段长度可变）；
  F20 = B2 / fixed 20 visible sessions immediately before B2（固定 20 根）。
- 现状：**CONTRACT FROZEN / CLOSED（Sol audit PASS，fix/
  f20-contract-insufficient-history-v01）；OUTCOME VALIDATION =
  **REJECT（V01 audit-fix，2026-08-16；预注册 758768e 后正式验证 +
  prereg-compliance audit fix v01，runs/f20-outcome-validation-v01/）**：
  primary population = 全部 resolved episodes（冻结映射 anchor/b2=signal/
  as_of=signal，无 stage 预过滤；F20 自身定 defined/undefined），
  DEFINED 9508 / UNDEFINED 117（全部 INSUFFICIENT_PRE20）；
  H5A 冻结 Spearman（average-rank + Pearson，PRIMARY_RHO_UNDEFINED
  fail closed）双 gate：rho_strict=-0.1127（N=7765）AND
  rho_R_positive=-0.1182（N=7765）→ 双 gate 均非正 → **REJECT**；
  stage 三层：B1_READY -0.010/-0.010、B2_READY +0.056/+0.056（strict 编码
  与 R>0 在该两层 100% 一致，数据属性非 bug）、B2_CONFIRMED
  -0.015/-0.093（73.3% 一致）；quartile Q1-Q4 无单调；不得写 VALIDATED /
  PROMOTED；三倍量（H9）= F19/F20 的特例，作为交互项验证，不做主效应。
- v01 实证（2026-08-14，runs/h9-v01/，fail-closed 审计版）：B2 阶段
  resolved n=3,214，F19 p50=0.85 / p90=1.36 / p99=1.73 / max=3.34；
  F19≥3 仅 1 例（0.03%）→ H9 = REJECT (event-frequency level)。
  在 F19 口径下，相对 T+1..B2 前一日回调均量，B2 日成交量通常未明显
  扩张；本结果不覆盖 F20、盘中量能或换手，不得解释成「成交量对 B2
  无用」。days_since_anchor>=3 + F19>=2 = NEW / PRE-REGISTERED FORWARD
  HYPOTHESIS（新阈值假设；禁止在当前 frozen 样本重新验证）。

## 6. 失败结构类（H6）

- F21 B2 次日跌回平台：B2 事件次日 close < 平台/突破位（用冻结 support/trigger）
- F22 巨量长上影：上影线/实体 >= 阈值 且 vol 为 5 日均量 >= 1.5 倍
- F23 放量下跌：回调期存在 i 使 close(i)<close(i−1) 且 vol(i)>vol(i−1)（连续计数）
- 现状：均 GAP。

## 7. BLOCKED 清单（短期不做）

- 筹码类（获利盘/套牢盘/筹码峰/集中度）：CHIP SNAPSHOT PROBE UNAVAILABLE，
  规则禁止自研算法
- 封板时间（历史）：分钟数据覆盖不足
- 板块共振（F08）：板块 proxy 数据质量未达标
- 分时承接/VWAP（历史）：5m 覆盖不足；近期会话可试点

## 8. 下一步（步骤 2）

factor_lab 首批实现：F01、F02、F06、F07、F09、F11、F14、F16、F19、F21——
覆盖 H1-H3 与 H5/H6 的最小集，全部为 daily_bars 上的 PIT 纯函数，
附单元测试与差分校验（合成数据 + 与冻结 episodes 字段口径核对）。
