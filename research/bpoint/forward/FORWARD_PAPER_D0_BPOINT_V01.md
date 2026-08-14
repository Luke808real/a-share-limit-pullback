# FORWARD PAPER D0 BPOINT V01 — Protocol

STATUS: RESEARCH_ONLY / FORWARD_ONLY（NO_PRODUCTION_CHANGE /
NO_THRESHOLD_OPTIMIZATION / NO_LIVE_TRADING）
PROTOCOL_HASH: 4125a4496540b572391512ea32ed8b485553cad886a26ba2d70e2a0dd74398c9
REFERENCE_DISTRIBUTION_HASH: 9b8863a7dc71caf7c59e601871104bb7147db204ac7a96ad4eada1fd2aba4c72

## 预注册假设（方向冻结，禁止翻转）

- H1: 更低 VOLUME_PACE → 更好 outcome
- H2: 更浅 SESSION_LOW_VS_PREV_CLOSE → 更好 outcome
- H3: 更小 SESSION_RANGE → 更好 outcome

## 分层架构（QUALITY ≠ ACTIVATION）

- LAYER A B_POINT_QUALITY：
  - VOLUME_PACE_PRIMARY = CUM_VOLUME_VS_D1_SAME_TIME（approved）
  - MAX_DRAWDOWN_FROM_PREV_CLOSE（= session_low_vs_prev_close_pct）
  - SESSION_RANGE_PCT
- LAYER B ACTIVATION_STATE（只记录，不参与质量分）：
  - support touch / reclaim、distance to S1、S1 touch、probe
- 四象限可区分：HIGH_QUALITY_NOT_ACTIVATED / HIGH_QUALITY_ACTIVATED /
  LOW_QUALITY_ACTIVATED / LOW_QUALITY_NOT_ACTIVATED。

## Quiet Compression Score（等权、连续、非优化）

QUIET_COMPRESSION_SCORE =
mean(
  inverse_percentile(VOLUME_PACE_PRIMARY),
  inverse_percentile(abs(SESSION_LOW_VS_PREV_CLOSE)),
  inverse_percentile(SESSION_RANGE_PCT)
)

- percentile 使用 development 206 cases 冻结参考分布
  （quiet_score_reference_v01.json，hash 9b8863…）；
  09:45 与 10:00 各一套参考。
- Q1（最不安静）~ Q4（最安静）按冻结分布四分位；
  Q4 = quietest / shallowest / narrowest。
- Forward 开始后不得重拟合 percentile；不得改 quartile 边界。

## Checkpoints

- PRIMARY（决定当天 paper）：09:45、10:00（最后一根完整 5m bar close 为 entry ref）
- OBSERVATION ONLY：10:30 / 11:30 / 13:30 / 14:00 / 14:30（不修改当天 decision）

## Forward Universe / Freeze Rule

- 盘前冻结 D-1 的 frozen production / research-approved daily screen 输出；
  保存 RUN_DATE、CANDIDATE_LIST_HASH、SOURCE_SNAPSHOT、CODE、SETUP_ID、
  ANCHOR_DATE、SETUP_STAGE、SUPPORT、INVALID、S1、D1_CLOSE、D1_VOLUME。
- 09:30 后当天列表禁止修改；新出现股票 NOT_ELIGIBLE_FOR_TODAY。

## Paper Entry / Outcome

- PAPER_ENTRY_0945 / PAPER_ENTRY_1000 = 对应 checkpoint 最后一根完整 5m close；
  禁止 next-low / VWAP / intraday-low 理想成交。
- OUTCOME = 固定 3 会话结构 outcome（SUCCESS / FAILED_BREAKOUT / NO_LAUNCH /
  STRUCTURE_FAIL / UNKNOWN，caseset V01B 冻结定义）。
- 主比较：QUIET Q4 vs Q1 + Q1→Q4 单调性；
  重点比率 SUCCESS / (SUCCESS + FAILED_BREAKOUT)。

## Execution layer

T_PLUS_1_EXECUTION_RULE = EXECUTION_LAYER_PENDING
（复用 Phase 2D.1A execution-reality 语义，但需 forward 兼容 resolver 批准；
当前只做结构 outcome；不新造止损逻辑。）

## Gates

- INTERIM：SUCCESS ≥ 10 且 FAILED_BREAKOUT ≥ 20 → 仅允许描述
- DECISION：SUCCESS ≥ 30 且 FAILED_BREAKOUT ≥ 30 且 ≥ 20 trading sessions
  → 才允许正式审核

## 禁止重调

VWAP_ACCEPTANCE、DAMAGE_RECOVERY、FAST_RECLAIM、D0_PROBE_COUNT、
D0_NEW_LOW、CLOSE_LOCATION、RETURN_FROM_PREV_CLOSE、MA_RECLAIM、
MORPHOLOGY_NEAREST_NEIGHBOR。

## Context observation only

- D1_UPPER_SHADOW（记录方向/median，不进 score）
- VWAP（VWAP_NOT_ENTRY_FEATURE = true；除非全新 forward evidence）

## Ledger

research/bpoint/forward/：
forward_candidates.parquet、forward_checkpoints.parquet、
forward_outcomes.parquet（append-only）；forward_summary.csv；
FORWARD_PAPER_PROTOCOL_V01.json（protocol hash 4125a4…）。

协议不可静默修改；如需修改 → V02，不覆盖 V01。

FORWARD_START_DATE = PENDING_HUMAN_APPROVAL
PRODUCTION_FILES_CHANGED = false
