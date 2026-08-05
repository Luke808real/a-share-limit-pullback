# SUCCESS / CONTROL CASESET V01A — EVENT ALIGNMENT

RUN_ID: SUCCESS_CONTROL_CASESET_V01A_EVENT_ALIGNMENT
SCRIPT: research/build_success_control_caseset_v01a.py
OUTPUT: research/intraday/success_control_cases_v01a.csv（V01 CSV 未覆盖）
INPUT: corrected episodes（66d5943f…）、canonical daily bars
  snap-2026-07-31-b5f84004de8a、limit_up_pool name map
DATA_CUTOFF: 2026-07-31（frozen snapshot）

本版本保留 V01 的 8,746 case 与 outcome 不变；只做事件对齐与字段拆分。

## 1. Candidate eligibility 拆分

- PIT_CANDIDATE_ELIGIBLE：仅 D-1 可获得字段
  （setup_stage ∈ {B1_READY, B2_READY, B2_CONFIRMED}、invalid_price 有效、
  s1_price 有效、data_quality != UNUSABLE）。本集合内 8,746/8,746 = True。
- OUTCOME_EVALUABLE：future_sessions_available >= 3，独立字段；含义是
  “有足够未来 3 交易日供结果标签”，属于 censoring / label-availability
  filter，不是 live selection rule。本集合内 8,746/8,746 = True。
- 另有 164 个 PIT-eligible 但 OUTCOME_EVALUABLE=False 的 anchor（未来不足
  3 日，多为冻结截止附近），未进入主样本；已在报告中明示，未静默删除。

## 2. Outcome event date

- SUCCESS / FAILED_BREAKOUT：OUTCOME_EVENT_DATE = 未来 3 日内第一个
  S1 touch day；EVENT_SESSION_OFFSET = 1 / 2 / 3。
- STRUCTURE_FAIL：OUTCOME_EVENT_DATE = 第一个 invalid touch day。
- NO_LAUNCH / UNKNOWN：OUTCOME_EVENT_DATE = NA。
- NEXT_SESSION_DATE 显式字段与原 trade_date 分离；不得把 next_trade_date
  误称 event date。

## 3. 计数

TOTAL_CASES = 8,746
PIT_CANDIDATE_ELIGIBLE_N = 8,746
OUTCOME_EVALUABLE_N = 8,746

SUCCESS_N = 409
FAILED_BREAKOUT_N = 950
NO_LAUNCH_N = 1,730
STRUCTURE_FAIL_N = 5,415
UNKNOWN_N = 242

SUCCESS_EVENT_INTRADAY_N = 43
FAILED_BREAKOUT_EVENT_INTRADAY_N = 103

EVENT_OFFSET_D1 = 676
EVENT_OFFSET_D2 = 442
EVENT_OFFSET_D3 = 241
（SUCCESS + FAILED_BREAKOUT 合计 1,359；0 missing）

MISSING_EVENT_DATE = 0
QUALITY_FLAG_COVERAGE = 100.0%
INFERRED_LIMIT_ANCHOR 占比 = 99.62%（已保存在 CSV quality_flags 列，
不只是报告说明）

## 4. Intraday availability 口径

- EVENT_INTRADAY_AVAILABLE 按 OUTCOME_EVENT_DATE 判断（sina 1m 可用窗口
  2026-06-05 ~ 2026-08-04）；旧 next-session 口径保留为
  NEXT_SESSION_INTRADAY_AVAILABLE_ESTIMATED。
- 窗口估计，未逐 case 拉取；V02A 执行前必须逐 case 验证 1m 完整性。
- V02_EVENT_COHORT = SUCCESS/FAILED_BREAKOUT + OUTCOME_EVENT_DATE 可得 +
  EVENT_INTRADAY_AVAILABLE：共 146（SUCCESS 43、FAILED_BREAKOUT 103）。

## 5. D-1 geometry / provenance 字段

CSV 新增（均只使用 candidate_date 收盘信息）：

- candidate_close
- dist_to_s1_pct
- dist_to_invalid_pct
- quality_flags（原始列表字符串）
- data_quality

用途：下一阶段控制 D-1 geometry / quality confounding；不是新筛选规则。

## 6. V02A 研究 cohort 与 feature policy（只登记，不执行）

V02_EVENT_COHORT 回答的问题：
“已经发生 S1 攻击的事件日，盘中早期路径能否区分最终接受突破 vs 冲高失败？”

NO_LAUNCH / STRUCTURE_FAIL 不进入 V02-A cohort。

Feature policy（防未来信息泄漏）：

- 只允许 checkpoint features：09:45、10:00、10:30、11:30；
- 每个 checkpoint 只能使用该时刻及之前的分钟数据；
- 允许：OPEN_GAP、OPENING_DRAWDOWN、VWAP_STATE、VWAP_RECLAIM、
  VWAP_REBREAK、PREV_CLOSE_STATE、S1_DISTANCE、HIGH_LOW_PROGRESSION、
  RETEST、CUM_VOLUME_RELATIVE_TO_D1；
- 禁止作为 predictor：EOD close、close_location、full-day volume、
  PM_RETURN、全天 time_below_vwap、任何 checkpoint 之后的数据；
- 原因：SUCCESS 标签本身已包含 EOD close acceptance + volume expansion，
  使用 EOD 信息会直接泄漏标签。

## 7. 结论

ORIGINAL_CASESET_VALIDITY = VALID_FOR_EPISODE_OUTCOME_RESEARCH
V02_EVENT_COHORT_VALIDITY = READY

SUCCESS_EVENT_INTRADAY_N = 43（>= 20）
FAILED_BREAKOUT_EVENT_INTRADAY_N = 103（>= 20）
READY_FOR_INTRADAY_V02A = true

NO_PRODUCTION_CHANGE = true
NO_THRESHOLD_SCAN = true
NO_OUTCOME_REDEFINITION = true

NEXT = INTRADAY_SUCCESS_PATTERN_V02A（仅登记；待人工确认后执行）
