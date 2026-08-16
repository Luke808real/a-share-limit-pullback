# TTL SETUP-LEVEL SURVIVAL CONTRACT FEASIBILITY V01 — 数据合同与可行性报告

- 状态：**BLOCKED_FOR_T0_SURVIVAL**（CASE B：无冻结 authority 枚举完整 T0
  setup universe；本轮只做 provenance audit / contract，未运行任何
  outcome validation / 生存统计）
- 日期：2026-08-16
- 分支：`research/ttl-setup-survival-contract-v01`（fix/ttl-setup-survival-contract-v01 审计后更新）
- BASE_HEAD：10c2012cd971116ff8e0938d69a26f55df74c4fb

---

## 0. PRE-FLIGHT

- branch 从 exact BASE_HEAD 创建；`git HEAD == 10c2012cd...`；tracked
  worktree clean（仅存在先前的 untracked `data/`、`uv.lock`）
- 无 PR / merge / force

## 0b. 审计后更新（Sol review @10c2012，fix/ttl-setup-survival-contract-v01）

本轮 provenance audit 结论：

1. **T0 population completeness = NOT ESTABLISHED（CASE B）**
   - 沿冻结 lineage 向上追溯（outcome.py `_replay_code` / `run_outcome_study`、
     summary.json audit、diagnosis、warehouse、screen runs/states、b1-lifecycle
     audit、context-historical）**未找到**任何冻结 artifact 能枚举全部 T0
     anchor（包括从未出现 B1_READY/B2_READY/B2_CONFIRMED 的 setup）。
   - episodes.parquet 只携带"至少出现过 1 个 target-label 事件"的 setup
     （17,691 个 setup；TARGET_LABELS = B1_PREP/B1_READY/B2_READY/B2_CONFIRMED）。
   - summary.json audit 显示 replay 对 3191 codes × 589 dates 做了
     1,844,543 次 evaluate_strategy 调用，但仅持久化了 31,422 个
     target-label 事件行；**未触发任何 stage 的 anchor 不落盘**。
   - 因此现有数据**不能**估计 `P(B2 by T+k | all T0 setups)`；
     只能支持 `CONDITIONAL_ON_OBSERVED_SIGNAL_COHORT` 研究。
   - 任何 T0 分母估计都会引入 ascertainment truncation（向上选择偏差）。

2. **TIMEBASE 审计 = MISMATCH（不能直接冻结 days_since_anchor）**
   - ROWS_CHECKED = 31,422（全部合法 stage 行）
   - MATCH_N = 31,044；MISMATCH_N = **378**；MISSING_ANCHOR_DATE_N = 0；
     MISSING_SIGNAL_DATE_N = 0；MAX_ABS_DIFF = **18**
   - 378 条 mismatch 中 100% 为 `days_since_anchor < trading-session
     distance`（dsa 偏小；如 000008:20260330 → 2026-04-10，dsa=3 但
     session distance=8）。
   - **结论：不得把 `days_since_anchor` 冻结为 EVENT_TIME。**
     EVENT_TIME 必须改为 canonical trading-session index distance
     （用 frozen daily trade_date 逐 code 排序索引差），并记录 mismatch。

3. **DUPLICATE / STAGE ORDER = 干净，policy 收紧为 fail closed**
   - STAGE_ORDER_VIOLATION_N = 0（B1_READY <= B2_READY；B2_READY <=
     B2_CONFIRMED 双向均 0 violation）
   - SAME_SETUP_STAGE_DUPLICATE_N = 0；exact physical duplicate rows = 0
   - 因无任何重复证据，且无 frozen semantics 证明重复 stage signal 合法：
     **DUPLICATE_POLICY = FAIL CLOSED**（identical physical duplicate 仅在
     deterministic equality 被证明时可 dedupe + 显式 accounting；conflicting
     same-(setup,stage) → FAIL CLOSED；禁止无条件 take FIRST）。

---

## 1. INPUT AUTHORITIES

| 输入 | 路径 | SHA256 | 用途 |
| --- | --- | --- | --- |
| episodes | data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet | 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093 | setup 身份 / 阶段 / 时间轴 |
| daily | data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet | e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514 | 交易日历（TIME_SCALE 校验用） |

- 复用研究代码：research/factor-lab/ttl_survival_v01.py（v01 近似删失版本，
  已在 runs/ttl-survival-v01/ 留档）；本轮 contract 修正其删失近似为
  snapshot 边界右删失 + 明确 PIT 边界。
- 复用 frozen state/episode semantics：F20/F22 validation runner 的
  `signal_date = b2_date = as_of` 冻结映射约定。

## 2. AVAILABLE FIELDS（episodes，31422 rows / 17691 setups）

- `setup_id`：`{code}:{anchor_date}:{seq}` 格式（示例 `000001:20240221:1080`）
- `code`、`anchor_date`、`signal_date`、`setup_stage`、`days_since_anchor`
- `outcome`（WIN_S1 / LOSS_INVALID / CANCEL_GAP_INVALID / NO_FILL /
  TIMEOUT / AMBIGUOUS_INTRADAY / CENSORED）、`execution_label`
- `future_sessions_available`（snapshot 生成时的元数据，仅作审计线索，
  **不得作为 observation end**）

## 3. SETUP KEY（唯一识别）

- **SETUP_KEY = `setup_id`**（= `code:anchor_date:seq`）
- 已验证唯一性约束：
  - 17691 个 distinct setup_id；**0 个 setup 对应 >1 个 code**
  - **0 个 setup 对应 >1 个 anchor_date**（anchor 恒为 setup 常量）
- 时间原点 **TIME_ORIGIN = T0 = anchor_date**（setup 常量，可直接解析）

## 4. EVENT DEFINITIONS

| 事件 | 定义 | 时间 |
| --- | --- | --- |
| EVENT_READY | 该 setup **首个** `setup_stage == B2_READY` 的行 | 该行 `signal_date`（= days_since_anchor 语义） |
| EVENT_CONFIRMED | 该 setup **首个** `setup_stage == B2_CONFIRMED` 的行 | 该行 `signal_date` |

- **每个 setup 最多贡献一次 EVENT_READY / EVENT_CONFIRMED**
  （survival trajectory 每 setup 仅一条）
- 已验证阶段结构（结构性计数，非 outcome 统计）：
  - setups with B1_READY：17689；B2_READY：10952；B2_CONFIRMED：2773
  - rows/setup ∈ {1,2,3}（6735 / 8181 / 2775）
  - **0 个 setup 在同一 stage 有 >1 行**（同一阶段最多一行）
  - **0 个 violation：B2_READY 晚于 B1_READY；0 个 violation：
    B2_CONFIRMED 早于 B2_READY**（阶段时序单调）
- WATCH_PULLBACK（8 行，execution_label B1_PREP）为阶段前记录；
  其中 2 个 setup 无 B1_READY 行——仍以 anchor_date 入列，不阻断。

## 5. CENSOR POLICY（右删失）

- **OBSERVATION_END = snapshot 边界 2026-07-31**
  （episodes 与 daily 的最大 trade_date 均为 2026-07-31；无未来数据）
- setup 在 OBSERVATION_END 前未出现 EVENT_READY（或 EVENT_CONFIRMED）
  → 在该时点**右删失**（right-censored）
- **BLOCKER（CASE B）**：episodes 文件只携带"至少出现过一个 target-label
  事件"的 setup（17691）；**从未触发任何 stage 的 setup 不在文件中，
  无法从本输入枚举完整 anchor 人口**。因此生存人群 =
  snapshot 内出现 ≥1 target-label 事件的 setup，属 truncated cohort；
  **不能估计 P(B2 by T+k | all T0 setups)**。
- `future_sessions_available` 仅作生成时刻的审计字段，不作为观测窗口。

## 6. PIT BOUNDARY

- 只用 `signal_date <= OBSERVATION_END` 的行；行内 `anchor_date`/
  `signal_date` 均来自冻结 snapshot（SHA 门禁）。
- **EVENT_TIME（冻结决定）**：TIME_SCALE = trading sessions，且
  EVENT_TIME = **canonical trading-session index distance**（用 frozen
  daily trade_date 逐 code 排序后的索引差：index(signal_date) −
  index(anchor_date)）。**不得使用 `days_since_anchor`**：timebase audit
  显示 31,422 行中 378 行 mismatch（MAX_ABS_DIFF=18），该字段不可靠。

## 7. DUPLICATE / MULTIPLE SIGNAL POLICY（fail closed）

- STAGE_ORDER_VIOLATION_N = 0（B1_READY <= B2_READY <= B2_CONFIRMED，
  双向检查均 0 violation）
- SAME_SETUP_STAGE_DUPLICATE_N = 0；exact physical duplicate rows = 0
- **DUPLICATE_POLICY = FAIL CLOSED**：
  - identical physical duplicate（逐字段相等）→ 仅当 deterministic
    equality 被证明时才允许 canonical dedupe + 显式 accounting；
  - conflicting same-(setup, stage)（内容冲突）→ FAIL CLOSED；
  - **禁止无条件 take FIRST**（当前数据 0 重复，无 frozen semantics
    证明重复 stage signal 合法）。
- MULTIPLE_SIGNAL_POLICY：同一 stage 的多信号（当前数据不存在）——
  与 duplicate 同样 FAIL CLOSED，不得静默取 FIRST。
- 禁止把 episodes 多行直接当成独立 setup 样本
  （17,691 是 setup 数；31,422 是 stage 行数，二者不可混用）。

## 8. OUTCOME SEPARATION（本轮冻结）

- **A. state-transition survival**：T0 → EVENT_READY / EVENT_CONFIRMED
  （本 contract 的事件；只关心"是否发生、何时发生"）
- **B. trading outcome**：WIN_S1 / LOSS_INVALID / CANCEL_GAP_INVALID /
  NO_FILL（+ TIMEOUT / AMBIGUOUS_INTRADAY / CENSORED）
- **二者严格分离**：CANCEL / LOSS / NO_FILL 不属于 survival event；
  state-transition 的事件定义只看 stage 行的存在，不看该行 outcome。
- P(success | event at T+k) 属 **future prereg candidate**，本轮不计算。

## 9. KNOWN LIMITATIONS

1. **BLOCKER — T0 universe 不可枚举（CASE B）**：无任何冻结 authority 记录
   全部 T0 anchor（含从未触发 stage 的 setup）；episodes 仅为
   CONDITIONAL_ON_OBSERVED_SIGNAL cohort → 不得估计 T0 全体的 survival。
2. `days_since_anchor` 字段与 canonical trading-session distance 不一致
   （31,422 行中 378 行 mismatch，MAX_ABS_DIFF=18）→ 不得直接使用该字段；
   EVENT_TIME 必须用 daily trade_date 重算。
3. OBSERVATION_END 为 snapshot 边界：2026-07-31 之后的事件不可见，
   靠近边界的 setup 删失率高（v01 已有 83 个删失近似）。
4. 阶段行是"曾达到"记录，非每日 lineage——无法回答
   "T+k 当天 setup 是否仍 alive"的逐日状态（v01 已注明
   "NOT a daily tracked lineage"）；contract 只承诺事件发生时间，
   不承诺逐日存活状态。
5. NO_FILL 语义：存在信号但未成交——属于 trading outcome 层，与
   state-transition 事件定义无关（不影响 EVENT 判定）。

## 10. FORBIDDEN ANALYSES（冻结）

- 禁止 outcome-conditioned threshold search / cutoff 选择（T+5/T+6 等
  不得按 outcome 选）
- 禁止 subgroup rescue、F22 rescue、significance test 后补
- 禁止修改 strategy / production / forward / TradePlan /
  F18/F19/F20/F22 verdict / frozen artifacts
- 禁止重跑 F22、禁止 full-market regeneration、禁止 ML
- 本轮禁止运行任何 survival/outcome 统计；只做 contract

## 11. NEXT RECOMMENDED ACTION

- **BLOCKED_FOR_T0_SURVIVAL**：在找到能枚举完整 T0 anchor universe 的
  冻结 authority（或新冻结的 setup 注册表）之前，**不推荐**
  PREREGISTRATION V01，不得运行 T0→B2 survival。
- 可记录的独立未来研究问题（本轮不自动改变目标、不运行）：
  - `B1_READY → B2_READY / B2_CONFIRMED`（observed-signal cohort 内的
    state-transition survival，声明 truncated cohort）
  - 若未来存在完整 anchor/setup 注册 authority：`T0 → B2_READY /
    B2_CONFIRMED`（需先冻结人口定义）。
