# H4 SUPPORT ZONE CONTRACT V01 — Contract / Provenance / Feasibility

研究层报告。本轮只做 contract / provenance / implementation，不做任何
outcome 统计、不搜索阈值、不修改 strategy / score / setup_stage、不触碰
production / forward / TradePlan。代码基线：1a62c7b（H4B dual-metric final
QC，独立复核 PASS）。

## 1. 本轮范围

| 项 | 内容 | 状态 |
| --- | --- | --- |
| E04 | T0 涨停实体支撑触及：PIT 纯函数 + 合成测试 | IMPLEMENTED |
| E05 | 冻结平台支撑触及：先确认 support_low/high frozen provenance，再 PIT 纯函数 + 合成测试 | IMPLEMENTED（provenance 确认） |
| F18 | 支撑共振可行性：仅判断是否具备下一轮正式冻结 contract 的条件 | FEASIBLE（不计算） |

## 2. support_low/high 冻结 provenance 确认

证据链（代码级，逐环核对）：

1. **冻结引擎计算**：strategy/structure.py `generate_support_candidates`
   以 ANCHOR_PRICE / PLATFORM_HIGH_20（anchor 前 20 个可见 session 的最高
   high）/ MA5-250 为候选源，聚类后 `select_support_cluster` 选出支撑簇。
2. **冻结时点物化**：strategy/engine.py（≈L934-959）在首次 B1_READY 当日
   把选中支撑簇固化为 `SupportSnapshot(support_low, support_high,
   support_center, sources, frozen_as_of, eligible_from, reference_close,
   max_above_reference_close, reference_low)`，其后逐日单调承继
   （`frozen_support = prior_support`），不随行情重算。
3. **冻结模型语义**：models/signal.py `SupportSnapshot(FrozenDomainModel)`
   带 frozen_as_of / eligible_from 约束（eligible_from > frozen_as_of；
   center 相对 reference_close 上限 0.5%）。
4. **冻结落盘**：
   - 冻结 states / replay 记录携带 `support_snapshot`
     （models/replay.py，quality.py L129 由 signal.support 构造）；
   - 冻结 outcome-study episodes 携带 `support_low / support_high /
     support_center` 列（outcome.py `_FrozenEvent` L251-253 与
     `_event_payload` L287-289）；
   - b2_confirmation 层 `rank_b1_setup` 的 B1SetupRankRow 同样投影
     `b1_zone_low/high` 与 `support_low/high`，来源为
     `support = signal.support`（b2_confirmation.py L742-759）——三个
     存储层均指向同一个冻结 SupportSnapshot，无独立重算路径。
5. **冻结版本锚点**：策略版本 phase-2d0，内容提交 e865de4（CURRENT_PHASE.md）。

**VERDICT = PROVENANCE_CONFIRMED** → E05 不 BLOCKED，按 REUSE 路径实现。

物理列级复核（2026-08-15，V flash/data/outcome-study/outcome-snap-
2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/
corrected-b2-trigger-outcome/episodes.parquet）：

- SHA256 = 66d5943f...b84b093（与 h4-ma10-report-v01 记录的输入哈希一致）
- 总行数 31,422；support_low / support_high / support_center 三列均存在
- **列类型为 string（十进制文本，outcome.py _event_payload 的
  str(decimal) 序列化）**：消费方必须 Decimal() 解析后使用；实测 31,414
  个非空值 0 解析失败
- SUPPORT_DEFINED_N = 31,414 / SUPPORT_MISSING_N = 8；8 个缺失行全部为
  WATCH_PULLBACK 且 is_entry_candidate=False（支撑尚未到冻结时点），与
  冻结语义一致（支撑在首次 B1_READY 才冻结）
- Decimal 解析后不变式 low <= center <= high 违反数 = 0（31,414/31,414
  满足）——注意：若直接对 string 列做数值比较会因字典序出错，F18 运行
  脚本必须显式 Decimal 解析

## 3. E04 contract v01（T0 涨停实体支撑）

- 函数：factor_lab.`t0_body_touch(bars, anchor_date, as_of)`
- 谓词：存在 D ∈ (anchor_date, as_of] 使
  `min(open(T0), close(T0)) <= low(D) <= max(open(T0), close(T0))`
  （T0 实体区间取闭合区间；low 进入实体算触及，跌破实体下沿算破体不算
  触及，low 全程在实体上方算未接触）
- 退化实体（open == close，如一字板）：区间退化为单点，要求 low 精确相等
- PIT：只读 (anchor_date, as_of]；anchor 缺失 / 多 code / 重复日期 →
  ValueError fail closed；as_of 无 T0 后 bar → None
- 测试：tests/test_factor_lab.py 新增 7 例（进实体 True / 破体 False /
  上方无接触 False / 退化实体精确命中 / PIT 截止 / 无 T0 后 bar None /
  fail closed）

## 4. E05 contract v01（冻结平台支撑触及）

- 函数：factor_lab.`platform_support_touch(bars, anchor_date, as_of,
  support_low, support_high)`
- 输入契约：support_low/high 必须是冻结 SupportSnapshot 的冻结值
  （frozen states / episodes 列），函数内**不重算任何平台**
- 谓词（冻结口径，audit fix v01 恢复）：存在 D ∈ (anchor_date, as_of] 使
  `low(D) <= support_high 且 high(D) >= support_low`（K 线区间与冻结区间
  相交即触及；low 低于 support_low 但 high 进入区间仍算触及）
- 退化区间（support_low == support_high）：K 线区间覆盖该单点价格
- missing 语义（audit fix v01）：support_low/high 任一为 None（冻结样本
  中支撑未到冻结时点的缺失行）→ 返回 None，不抛 TypeError
- fail closed：support_low/high 非正或倒挂 → ValueError
- PIT：同 E04；anchor 缺失 / 多 code / 重复日期 → ValueError；
  as_of 无 T0 后 bar → None
- 测试：tests/test_factor_lab.py E05 共 10 例（区内 True / 相交 True（low
  低于下沿） / 整根在区间下方 False / 上方 False / 退化区间覆盖单点
  True 与未覆盖 False / missing→None×3 / PIT 截止 / 无 T0 后 bar None /
  倒挂与零价 fail closed / anchor 缺失 fail closed）

## 5. F18 可行性评估（不计算）

F18 := E01/E04/E05 在相近价位同时成立的数量。
（注：此前的 ±2% 表述为 LEGACY CATALOG DRAFT，NOT FROZEN；下一轮冻结
contract 须显式定义价格代表与相近判定基准，见下方契约点 1。）

- 输入可得性：E01 需要 MA10 序列（canonical daily bars，已有实现）；
  E04 需要 T0 实体（bars 可得）；E05 需要冻结 support_low/high
  （episodes 列已确认，物理列级复核为下一轮 gate）→ 全部可得。
- 待下一轮冻结的契约点：
  1. 每个事件的价格代表（E01 用事件日 MA10 值 / E04 用 T0 实体区间
     中心或上下沿 / E05 用冻结区间中心或上下沿）与"相近"的基准语义
     （相对哪个参考价、区间与区间之间如何判定相近；±2% 仅属 legacy
     draft，未冻结）；
  2. 同时性窗口（同一天成立 vs 在 (T0, as_of] 内各自成立即计数）；
  3. 计数语义（最大同时数 vs 成对计数）与分层/verdict 协议、MIN_N；
  4. episodes 物理列级 provenance gate（见 §2 caveat）。
- **VERDICT = FEASIBLE**：具备下一轮正式冻结 F18 contract 的条件；
  本轮不产出任何统计结论。

## 6. 结论状态

| 项 | 结论 |
| --- | --- |
| E04 | IMPLEMENTED（PIT 纯函数 + 合成测试，contract v01 冻结） |
| E05 | IMPLEMENTED（frozen provenance 确认 + PIT 纯函数 + 合成测试；audit fix v01 恢复冻结相交口径与 missing→None） |
| F18 | FEASIBLE_FOR_NEXT_ROUND_CONTRACT（本轮不计算；±2% 标记为 LEGACY CATALOG DRAFT / NOT FROZEN） |
| production / forward / TradePlan | 未改动 |
| strategy / score / setup_stage | 未改动 |

## 7. AUDIT FIX V01（2026-08-15，CHANGES_REQUIRED 修复）

Sol 审计（HEAD 7e70957）CHANGES_REQUIRED 的修复记录，见分支
fix/h4-support-zone-contract-audit-v01：

- **BLOCKER 1 修复**：E05 恢复冻结合同谓词
  `low(D) <= support_high 且 high(D) >= support_low`（K 线区间相交），
  替换此前被擅自改写的 low-only 语义；FACTOR_CATALOG.md E05 定义同步恢复。
- **BLOCKER 2 修复**：missing support（support_low/high 为 None）→ 返回
  None（冻结样本中确有 8 行缺失，语义为支撑未到冻结时点、无触碰答案），
  不再抛 TypeError。
- **BLOCKER 3 修复**：factor-lab README 补记 H4 closeout：
  H4A = REJECT；H4B = REJECT（dual-metric hypothesis）；E03 quick reclaim =
  strong hit-rate OBSERVATION（NOT VALIDATED / NOT PROMOTED）；
  H4B reconciliation = CLOSED。
- **F18 wording 修复**：±2% 标记为 LEGACY CATALOG DRAFT / NOT FROZEN，
  下一轮冻结 contract 需显式定义价格代表与相近判定基准。
- 测试：E05 用例从 8 例扩展为 10 例（含相交语义与 missing→None×3）；
  E04 与其余合同未动。
