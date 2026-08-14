# SECOND_LAUNCH_FACTOR_R1A_OUTCOME_CONTRACT_REPORT

> R1A — OUTCOME CONTRACT REVIEW（research-only / read-only；未修改任何 frozen case set / outcome builder / 策略）
> AS_OF: 2026-08-08 · 依据：`SUCCESS_CONTROL_CASESET_V01B`（R0 已验证）+
> `research/build_success_control_caseset_v01*.py` + `src/limit_pullback/outcome.py` + 冻结 episodes / canonical snapshots

STATUS: COMPLETE — 语义 / 时间窗口 / censoring 审计完成；未生成 V02、未实现任何 factor
BRANCH: `stabilize/pr-e-atomic-state-generation`
HEAD: `0f08348fd1fa7e04bdf468acc5516d6001e169b9`
WORKTREE: 有先前已存在的用户改动（未修改 / 未暂存 / 未清理）；本任务唯一新增文件为本报告。

---

## CURRENT_3D_CONTRACT

（完整来自 V01/V01B 构建代码，逐条引用，不重新解释）

```text
CURRENT_OUTCOME_CONTRACT = V01B（outcome 与 V01 完全对齐，mismatch=0）

FEATURE_AS_OF: D = candidate_date（signal_date）；只用 D-1 冻结 episode 字段
  （invalid_price / s1_price / trigger / scores；episodes.parquet，snapshot_id snap-2026-07-31-b5f84004de8a）
LABEL_START: D 之后该股自身的下一根 bar（严格 > D）
LABEL_HORIZON: 固定 3 个交易会话 = 该股 bar 序列中严格 > D 的前 3 行（head(3)）；
  停牌/无数据日不落行即不计入；不是日历日
S1_SOURCE: episodes.parquet `s1_price`（冻结，D-1 可得）
INVALID_SOURCE: episodes.parquet `invalid_price`（冻结，D-1 可得）
VOLUME_CONFIRMATION: 首个 S1 触及日 volume >= 候选日（signal day）volume（固定预注册，无调参）
ACCEPTANCE_RULE: 首个 S1 触及日日线 close >= s1（日线级接受，不看日内）

SUCCESS:        pattern_3d = S1_BEFORE_INVALID 且首个 S1 触及日 close >= s1 且 volume >= 候选日 volume
FAILED_BREAKOUT: pattern_3d = S1_BEFORE_INVALID 但 close < s1（FAILED_ACCEPTANCE）
                或 volume < 候选日 volume（FAILED_EXPANSION）；两原因由 outcome_reason 区分
NO_LAUNCH:      pattern_3d = NEITHER（3 会话内 S1 与 invalid 均未触及）
STRUCTURE_FAIL: pattern_3d = INVALID_BEFORE_S1（3 会话内 invalid 先于 S1）
UNKNOWN:        pattern_3d 缺失 / AMBIGUOUS（同日同根K触 S1+invalid）/
                日K或 signal 日 volume 缺失 / “S1_BEFORE_INVALID 但找不到 S1 触及 bar”
```

关键机制（代码事实）：

- 3 个交易日计数：`horizon = bars[bars.trade_date > signal_date].head(3)`（每只股票自身 bar 行）
- `event_session_offset`：事件行在 head(3) 中的 1-based 位置（idx+1；取值 1..3）
- 同日 S1 / invalid ambiguous：`_pattern_result`（outcome.py）逐根K判定：
  同根K `high>=s1 且 low<=invalid` → `AMBIGUOUS` → UNKNOWN；不按日内顺序拆分
- pattern_3d 另含 `CENSORED`（窗口不足 3 根），但 case set 构造门槛
  `future_sessions_available >= 3` 使 3D 无 CENSORED
- 去重：每 setup_id（= code:anchor_date）只取**最早 signal_date** 的候选日
  （sort by signal_date + drop_duplicates(keep=first)）；sibling 数记录在 same_anchor_sibling_count
- 候选门槛：setup_stage ∈ {B1_READY, B2_READY, B2_CONFIRMED}；invalid 与 s1 均有效；
  future_sessions_available >= 3；data_quality != UNUSABLE
- 事件日判定：首个 `high >= s1` 的 bar 为 S1 触及日；其日线 close/volume 做接受/扩张判定；
  invalid 触及日 = 首个 `low <= invalid` 的 bar

## WHAT_3D_ACTUALLY_MEASURES

**判定：B — SHORT_HORIZON_3D continuation（3 会话内的“激活 → 接受 → 扩张”快速确认基准）**，
兼有 C 的少量成分，不是 A。

理由（代码/定义事实）：

- 标签只在候选日之后 3 个会话内看 S1/invalid 触序 + 首个 S1 触及日的接受/扩张；
  不测量持续趋势、二次趋势扩张、更长持有验证 → 不是完整 SECOND_LAUNCH outcome（A）
- 候选入口是 lifecycle 状态（8,736 B1_READY / 9 B2_READY / 1 B2_CONFIRMED 的最早候选日），
  不是“B2 触发后”专属 → 与 C（B2 后快速确认）仅部分重叠
- 它回答的问题：“该 setup 在候选日之后 3 个交易日内，结构是否先守后攻（S1 先于 invalid），
  且首触当日是否被收盘接受并放量”

**NO_LAUNCH 语义（关键）**：代码原语是
`"no S1 and no invalid touch within 3 sessions"`（pattern=NEITHER）——
**只表示未来 3 个交易日内未发动，不表示永远没有第二波**。

量化证据（8,746 case，冻结 bars + validated 08-06 snap 仅做标签扩展）：

- 10D 内首次事件分布：INVALID 6,183 / S1 1,881 / 无事件 470 / AMBIG 212
- 首次 S1 触及 offset（1..10）：1:683, 2:448, 3:250, 4:159, 5:117, 6:66, 7:61, 8:39, 9:29, 10:29
  → 3D 窗口捕获 73.4% 的 10D 内首触（1,381/1,881），**约 1/4 的启动发生在第 4-10 会话**
- 3D NO_LAUNCH 1,730 例中：262 例（15.1%）在 5D 内触 S1；478 例（27.6%）在 10D 内触 S1；
  131 例（7.6%）10D 内达到完整 SUCCESS 标准
- 3D FAILED_BREAKOUT 950 例 → 10D SUCCESS = 0（首个 S1 触及日固定，接受/扩张失败不可被更长窗口“赎回”）
- 3D SUCCESS 409 → 5D SUCCESS 402 + 5D 截尾 7（= 88 截尾中的 7 例，晚近候选），无不一致

结论：3D 是 **short-horizon 快速确认基准**；对“SECOND_LAUNCH 完整结局”它同时有
**HORIZON_TOO_SHORT 漏检**（迟发启动）与 **FAILED_BREAKOUT 不可赎回** 两种偏置，不能当作完整 ground truth。

## GOLDEN_CASE_AUDIT

（bounded 读取：v01b CSV 行 + 冻结 bars + 08-06 snap 标签扩展；未做策略复盘）

| code | setup_id | anchor_date | candidate_date | current_3d_outcome | event_date | event_session_offset | s1 | invalid | reason_for_current_label | 人工价值 vs 3D 标签差异原因 |
|---|---|---|---|---|---|---|---|---|---|---|
| 002606 | 002606:20260119:1084 | 2026-01-19 | 2026-01-22 | STRUCTURE_FAIL | 2026-01-23 | 1 | 11.80 | 10.63 | invalid first within 3 sessions | INVALID_FIRST（5D/10D 均 STRUCTURE_FAIL，非漏检） |
| 002606 | 002606:20260408:1190 | 2026-04-08 | 2026-04-09 | NO_LAUNCH | — | — | 14.44 | 11.10 | no S1/invalid within 3 sessions | OTHER（10D 内仍无任何触及，确属未发动；人工研究价值来自后续新 setup） |
| 002606 | 002606:20260522:1645 | 2026-05-22 | 2026-05-25 | STRUCTURE_FAIL | 2026-05-26 | 1 | 18.13 | 16.37 | invalid first within 3 sessions | INVALID_FIRST |
| 002498 | 002498:20260324:880 | 2026-03-24 | 2026-03-26 | STRUCTURE_FAIL | 2026-03-27 | 1 | 9.38 | 8.53 | invalid first within 3 sessions | INVALID_FIRST |
| 002498 | 002498:20260415:850 | 2026-04-15 | 2026-04-16 | FAILED_BREAKOUT | 2026-04-20 | 2 | 9.38 | 8.46 | S1 close accepted but volume < signal-day volume | FAILED_EXPANSION（5D/10D 首触日固定，不可赎回） |
| 002498 | 002498:20260429:902 | 2026-04-29 | 2026-05-06 | FAILED_BREAKOUT | 2026-05-07 | 1 | 9.32 | 8.97 | S1 touched but close 9.29 < S1 9.32 | FAILED_ACCEPTANCE |
| 600468 | 600468:20251219:714 | 2025-12-19 | 2025-12-23 | STRUCTURE_FAIL | 2025-12-24 | 1 | 7.44 | 6.88 | invalid first within 3 sessions | INVALID_FIRST |
| 600468 | 600468:20260629:584 | 2026-06-29 | 2026-06-30 | STRUCTURE_FAIL | 2026-07-02 | 2 | 6.66 | 5.81 | invalid first within 3 sessions | INVALID_FIRST + SNAPSHOT_RIGHT_CENSORING（人工 2026-08-03 SECOND_LAUNCH 观察在 cutoff 2026-07-31 之后，属新 setup，不在 case set） |
| 600756 | 600756:20240702:1115 | 2024-07-02 | 2024-07-04 | FAILED_BREAKOUT | 2024-07-05 | 1 | 11.35 | 10.56 | S1 touched but close 11.00 < S1 11.35 | FAILED_ACCEPTANCE |
| 600756 | 600756:20240926:1214 | 2024-09-26 | 2024-10-11 | NO_LAUNCH | — | — | 15.81 | 12.78 | no S1/invalid within 3 sessions | HORIZON_TOO_SHORT（10D 内 S1 触及于 offset 9 → 10D FAILED_BREAKOUT） |
| 600756 | 600756:20241028:1845 | 2024-10-28 | 2024-10-30 | STRUCTURE_FAIL | 2024-10-31 | 1 | 19.80 | 16.82 | invalid first within 3 sessions | INVALID_FIRST |
| 600756 | 600756:20250207:1701 | 2025-02-07 | 2025-02-10 | STRUCTURE_FAIL | 2025-02-11 | 1 | 18.90 | 16.92 | invalid first within 3 sessions | INVALID_FIRST |
| 600756 | 600756:20250526:1538 | 2025-05-26 | 2025-05-27 | STRUCTURE_FAIL | 2025-05-28 | 1 | 16.50 | 15.42 | invalid first within 3 sessions | INVALID_FIRST |
| 600756 | 600756:20260313:1763 | 2026-03-13 | 2026-03-16 | SUCCESS | 2026-03-17 | 1 | 18.11 | 16.64 | S1 first + close>=S1 + volume>=signal-day volume | —（本身就是 SUCCESS，无需解释） |
| 600756 | 600756:20260708:1323 | 2026-07-08 | 2026-07-27 | UNKNOWN | — | — | 14.95 | 13.83 | pattern_3d AMBIGUOUS (same-day S1/invalid) | OTHER（同日同根K触 S1+invalid，3D 无法定序；10D 内首事件即 AMBIG） |
| 601858 | 601858:20260112:2147 | 2026-01-12 | 2026-01-19 | NO_LAUNCH | — | — | 24.98 | 19.25 | no S1/invalid within 3 sessions | OTHER（10D 内无任何触及，确属未发动） |
| 601858 | 601858:20260311:2167 | 2026-03-11 | 2026-03-13 | NO_LAUNCH | — | — | 24.98 | 21.75 | no S1/invalid within 3 sessions | HORIZON_TOO_SHORT（S1 触及于 offset 4 → 5D/10D FAILED_BREAKOUT） |

人工“有第二波研究价值”但 3D 非 SUCCESS 的原因分布（本 5 股 17 setups）：
INVALID_FIRST 9 / HORIZON_TOO_SHORT 2 / FAILED_ACCEPTANCE 2 / FAILED_EXPANSION 1 /
SNAPSHOT_RIGHT_CENSORING（+INVALID_FIRST）1 / OTHER 2（1 例 AMBIGUOUS、1 例另属新 setup 无相关 case）。
**未修改任何标签**；2 例 HORIZON_TOO_SHORT 是 3D 契约漏检迟发启动的直接个案证据。

## LABEL_DATA_AVAILABILITY

```text
AVAILABLE_LABEL_DATA_END: 2026-08-06
SOURCE_SNAPSHOT: snap-2026-08-06-e798f88ff67b（SCREEN_READY + validation PASS，as_of 2026-08-06）
  （另可用：snap-2026-08-05-49a843e6d7aa，SCREEN_READY + PASS，as_of 2026-08-05；
   不可用：snap-2026-08-05-d9e93fccc966，QUARANTINED）
STATUS: READY（仅用于 outcome label 扩展；feature 一律保持冻结 snap-2026-07-31-b5f84004de8a）
```

## CENSORING

（feature 保持 candidate_date 当时 PIT；更晚 snapshot 仅用于标签；未回灌任何 feature 字段）

| horizon | 冻结 snap-07-31 | validated snap-08-06 扩展后 | 说明 |
|---|---:|---:|---|
| 3D | EVALUABLE 8,746 / CENSORED 0 | 8,746 / 0 | 构造门槛 future_sessions_available>=3 已保证；UNKNOWN 242（AMBIG 212 + 缺K/缺标签 30）属歧义/缺失，非截尾 |
| 5D | 8,658 / 88 | **8,746 / 0** | 88 例晚近候选可用 08-06 标签补齐；补齐后 outcome5：SF 50 / NL 20 / FB 9 / SUCCESS 7 / AMBIG 2 |
| 10D | 8,658 / 88 | 8,658 / 88 | 需要标签数据到 ~2026-08-11；当前 validated 最新仅 08-06 → 尾部 88 例 **BLOCKED_BY_LABEL_DATA** |

provenance 注意：episodes.parquet 的 `pattern_5d/pattern_10d` 与冻结 snap 重算存在
183 行不一致（多为 2026-07 下旬候选：episodes 侧有值而冻结 bars 重算为 CENSORED/NEITHER 等），
疑似 episodes 构建时使用了更晚的 bar 缓存 → **多 horizon 标签必须从 validated snapshot 重算，
不要直接读取 episodes 的 pattern_5d/10d 列**。

## OUTCOME_DESIGN_OPTIONS

- **A. Binary horizons（SUCCESS_3D/5D/10D）**：优点——完全复用冻结 3D 判定语义逐 horizon 复制，
  标签互操作简单（SUCCESS_3D ⊆ SUCCESS_5D 单调，仅截尾差异），attribution 可直接分 horizon 对比；
  缺点——失败类不可赎回（FAILED_BREAKOUT 首触日固定），3D/5D/10D 是同一事件在不同截断下的快照，
  信息冗余高；censoring 逐 horizon 需管理。
- **B. Time-to-event（time_to_s1 / time_to_invalid / time_to_second_launch）**：优点——不丢事件时间信息，
  直接支持生存分析，无 horizon 截断浪费；缺点——`second_launch` 需要独立定义（S1 触及只是其中一环，
  目前无定义，OPEN_RESEARCH_QUESTION）；censoring 基础设施（右截尾 + 竞争风险：S1 vs invalid 互斥首事件）
  复杂度高。
- **C. Hierarchical（SURVIVE → LAUNCH → ACCEPT → EXPAND）**：优点——失败原因天然分层，attribution 可直接
  定位在哪一层流失；与当前五分类可一一映射（见 FAILURE_DECOMPOSITION）；缺点——层级顺序假设
  （invalid 先于 S1 才叫 survival failure）是 3D 触序的固有语义，换 horizon 后层级计数会漂移；
  AMBIGUOUS/UNKNOWN 仍无法归层。

三者不互斥：A 提供可解释基准，C 提供分解，B 作为补充事件时间（time_to_s1/time_to_invalid 可从现有数据免费得到）。

## PROPOSED_SECOND_LAUNCH_OUTCOME_V02

（只提案，不实现；最大化复用 V01B：S1 / invalid / acceptance / expansion / candidate / setup_id 全部不变）

每 case 建议输出字段：

```text
outcome_3d            # 冻结 V01B 原值，零改动（唯一真源）
outcome_5d            # 同一判定语义，horizon=5，标签扩展自 validated snap（08-06）
outcome_10d           # 同上 horizon=10；尾部 88 例标注 right_censored=true
time_to_launch        # 首次 S1 触及 offset（1..10；未触及=NA）
time_to_invalid       # 首次 invalid 触及 offset（1..10；未触及=NA）
launch_event_date     # 首次 S1 触及日
event_session_offset  # 沿用 V01B 定义（1-based，首个事件行位置）
right_censored        # 标签窗口不足对应 horizon 时为 true
outcome_reason        # 沿用 V01B 原 reason；SUCCESS/FAILED_BREAKOUT 拆 acceptance/expansion 两原因
```

**SUCCESS 判定是否保持 S1_BEFORE_INVALID + close>=S1 + volume expansion：保持（推荐）。**

任何变更都标为 `OPEN_RESEARCH_QUESTION`，本任务不修改：

- OQ1: volume expansion 基准是否从“候选日 volume”改为“候选日前 20 日均量 / 5 日均量”
  （3D 契约使用候选日 volume，对放量日当天相对口径可能失真）
- OQ2: 接受规则是否允许“首触日后 N 会话内任意日收盘站上 S1”而非仅首触当日
  （当前首触日固定 → FAILED_BREAKOUT 不可赎回，见 3D→10D SUCCESS=0）
- OQ3: `second_launch`（完整第二波）是否需要“突破后 N 日不回撤/再创新高”等持续条件
  （超出当前触序+接受+扩张的定义域）

## FAILURE_DECOMPOSITION

代码事实支持以下映射（按 3D 触序语义）：

```text
STRUCTURE_FAIL = survival failure（invalid 先于 S1 → 结构在启动前被破坏）
NO_LAUNCH      = activation failure within horizon（3 会话内无 S1 也无 invalid 触及）
FAILED_BREAKOUT= acceptance failure（close < S1）或 expansion failure（volume < 候选日 volume）——两因可拆
SUCCESS        = survival + activation + acceptance + expansion 全通过
```

不支持强行套用的点（明确说明）：

- 映射严格 **horizon-scoped**：NO_LAUNCH 不是永久不发动（1,730 中 478 例 10D 内仍触 S1）；
  STRUCTURE_FAIL 也只是“3 会话内 invalid 先触”，不排除更长窗口修复后形成新 setup
- FAILED_BREAKOUT 混合两种失败，必须保留 outcome_reason 拆分（代码已区分，CSV 有列）
- AMBIGUOUS / UNKNOWN（242）无法归入任何一层（同日同根K触序不可判定）
- “S1_BEFORE_INVALID 但找不到触及 bar”（数据不一致）归 UNKNOWN 而非失败——是数据事实，不是策略语义

## QUALITY_STRATIFICATION

后续 attribution 至少保留以下维度（本任务只设计，不过滤样本）：

```text
anchor_quality        # INFERRED_LIMIT_ANCHOR（8,713/8,746，99.62%）vs 直接锚点 → 0/1 列
data_quality          # PARTIAL 8,713 / OK 33（沿用 V01B 列）
quality_flags         # 原始 JSON 列表完整保留（含 MISSING_SCORE_FIELD:*）
score_missing_flags   # 从 quality_flags 解析出的缺失字段名列表（amplitude_contraction / b2_quality / position_120）
setup_quality_score   # 沿用
entry_quality_score   # 沿用
same_anchor_sibling_count  # 沿用（sibling 去重影响）
outcome_reason        # 保留（acceptance vs expansion vs no-launch 拆层用）
snapshot_id           # 冻结标签来源（b5f84004de8a）+ 扩展标签来源（e798f88ff67b）双列
```

## BLOCKERS

1. **10D 标签尾部截尾**：88 例需到 ~2026-08-11 的 validated 数据；当前最新 validated snap 为
   `snap-2026-08-06-e798f88ff67b` → 10D 全 cohort 不可得（BLOCKED_BY_LABEL_DATA）。
2. **episodes pattern_5d/10d provenance 不一致**（183 行与冻结 snap 重算不符）→ 多 horizon 标签
   不得直接读 episodes 列，必须从 validated snapshot 重算（需要重算脚本，属 R1B 输入，非本任务）。
3. 3D 契约的固有语义限制：FAILED_BREAKOUT 首触日固定不可赎回；NO_LAUNCH 是 horizon-scoped；
   SUCCESS 不度量持续/第二波本身 → 3D 不能充当完整 SECOND_LAUNCH ground truth。

## DECISION_REQUIRED

1. 是否批准用 validated `snap-2026-08-06-e798f88ff67b` 做 **label-only** 5D 扩展（feature 仍冻结 07-31）；
2. 10D 尾部 88 例：等待后续 validated snapshot，还是 V02 以 `right_censored=true` 纳入并显式标注；
3. V02 契约中 3 个 OPEN_RESEARCH_QUESTION（volume 基准 / 接受窗口 / second_launch 持续定义）
   是否列入 R1B 之后的研究议程（不改动当前 SUCCESS 定义）；
4. episodes pattern_5d/10d 与冻结 snap 的不一致是否需登记为 provenance 缺陷（研究者决定）。

## R1B_RECOMMENDATION

**明确推荐：R1B 使用 `outcome_3d`（主 target，冻结零改动）+ `outcome_5d`（次级 target，
label-only 扩展自 validated 08-06 snap，0 截尾）+ 事件时间字段（time_to_launch / time_to_invalid，10D 内免费）。
10D 不作为 R1B 的 target（BLOCKED_BY_LABEL_DATA 尾部 88 例），以 right_censored 字段预留；
不推荐“先完成 V02 全量标签再继续”（会无谓阻塞 3D/5D 已可得的完整样本）。**

即：选项 (b) 的务实版本——outcome_3d + outcome_5d + time-to-event 辅助字段；10D 明确延后。

## NEXT_RECOMMENDED_ACTION

1. 人工评审本报告与 3 个 DECISION_REQUIRED 项。
2. 批准后 R1B 输入包：冻结 8,746 case（V01B）+ outcome_3d（原列）+
   outcome_5d（08-06 标签扩展，0 截尾）+ time_to_launch/time_to_invalid（10D 内）+
   质量分层字段（见 QUALITY_STRATIFICATION）。
3. R1B 内部不得修改 V01B / outcome builder / 策略；5D 标签重算脚本作为 R1B 前置产物需先登记。
4. 本报告仅登记；未获授权前不进入 R1B、不实现 V02、不提取任何 factor。

---

## VALIDATION（本任务）

- 只读审计：targeted code inspection（build_success_control_caseset_v01*.py、outcome.py `_pattern_result`）、
  冻结 CSV/parquet bounded read、5 股 golden bounded read、validated snapshot 元数据（duckdb governance/validation 表）
- 小型统计：8,746 case 多 horizon 标签重算（冻结 bars + 08-06 snap），全部有界（<5s 完成）
- 输入 provenance：episodes SHA256 66d5943f…（与 R0 一致）；快照状态来自
  `warehouse.duckdb`（dataset_snapshots / snapshot_validation_records / canonical_publications / snapshot_governance_records）
- 未修改任何文件（仅新增本报告）；未运行 full-market 重算；未抓新数据
- 结论状态：OBSERVE_ONLY（契约审计；不构成 edge 结论）
