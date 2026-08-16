# TTL SETUP-LEVEL SURVIVAL CONTRACT FEASIBILITY V01 — 数据合同与可行性报告

- 状态：**FEASIBLE**（数据足以建立 setup-level survival contract；本轮只做
  contract/feasibility，未运行任何 outcome validation / 生存统计）
- 日期：2026-08-16
- 分支：`research/ttl-setup-survival-contract-v01`
- BASE_HEAD：93bbe74b19b701a14d9a2a14c5e2b7f2447e5861

---

## 0. PRE-FLIGHT

- branch 从 exact BASE_HEAD 创建；`git HEAD == 93bbe74b...`；tracked
  worktree clean（仅存在先前的 untracked `data/`、`uv.lock`）
- 未创建 worktree（单分支隔离足够）；无 PR / merge / force

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
- **关键限制（必须写进 prereg）**：episodes 文件只携带"至少出现过一个
  信号行"的 setup（17691）；**从未触发任何 stage 的 setup 不在文件中，
  无法从本输入枚举完整 anchor 人口**。因此 survival 人群 =
  snapshot 内出现 ≥1 行（anchor 已知）的 setup，属 truncated cohort；
  该限制在 v01 结论中必须声明，不得声称覆盖全部 anchor。
- `future_sessions_available` 仅作生成时刻的审计字段，不作为观测窗口。

## 6. PIT BOUNDARY

- 只用 `signal_date <= OBSERVATION_END` 的行；行内 `days_since_anchor`
  与 `anchor_date`/`signal_date` 均来自冻结 snapshot（SHA 门禁）。
- TIME_SCALE = trading sessions：以 canonical daily 的 trade_date 序列
  定义自然时间轴 T+1..T+n；`days_since_anchor` 为冻结字段直接使用，
  prereg 阶段用 daily trade_date 交叉校验其口径（calendar vs trading）。

## 7. DUPLICATE / MULTIPLE SIGNAL POLICY

- DUPLICATE_POLICY：同一 (setup, stage) 只取一行（当前数据已满足，0 重复）；
  若未来数据出现重复，取 `signal_date` 最早者并记录。
- MULTIPLE_SIGNAL_POLICY：同一 stage 的多信号（当前数据不存在）取 FIRST；
  阶段行不叠加、不求和。
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

1. **Truncated cohort**：无任何信号行的 setup 不在 episodes 中 → 右删失
   估计只能覆盖 snapshot 内出现过的 setup（见 §5）。
2. `days_since_anchor` 口径（calendar vs trading sessions）需在 prereg 用
   daily trade_date 交叉校验。
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

- **PREREGISTRATION V01**：按本 contract 冻结统计设计（SETUP_KEY、
  EVENT_READY/CONFIRMED、CENSOR_POLICY、PIT、OUTCOME_SEPARATION、
  truncated-cohort 声明、禁 TTL 阈值决策），之后才允许运行生存曲线。
- 不直接运行 survival/outcome study。
