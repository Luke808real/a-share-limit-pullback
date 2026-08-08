# SECOND_LAUNCH_FACTOR_R8A_INTRADAY_ACCEPTANCE_CONTRACT_V01

> R8A — Intraday Acceptance Contract & Data Readiness V01（contract only）
> AS_OF: 2026-08-09 · research-only · 未执行任何 R8 feature/outcome attribution

STATUS: **FROZEN（contract）；R8_DATA_STATUS=BLOCKED_BY_MINUTE_COVERAGE**

```text
BRANCH: research/second-launch-factor-r8a-intraday-acceptance-contract-v01
BASE_HEAD: fa70dd6dd8c5946544e48ad0d1e5196db8dc1bd1
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## R7_INTERPRETATION_CLARIFICATION

```text
R7B M3 解读已澄清（独立 commit）：
  M3 vs M2 Delta AUC +0.0052168 / LogLoss -0.0005773 / Brier -0.0000284 /
  AIC -5.048 / BIC +8.885；pvr/mvr corr 0.957；pvr 方向反转、mvr 保持负
  INTERPRETATION = INDIVIDUAL_ATTRIBUTION_UNSTABLE /
    JOINT_INCREMENTAL_EVIDENCE=MIXED
  （不再写 "completely absorbed" / "no joint incremental information"）
RANGE_INDEPENDENT_SUPPORTED / QUIET_INCREMENTAL_SUPPORTED / R7_STATUS=COMPLETE
  均保持；model metrics/coefficient/multicollinearity CSV 未改。
```

## CURRENT_RESEARCH_LINEAGE

```text
FEATURE_SHA a485a484… / OUTCOME_SHA 01a9f2fa… / COHORT_N 8,682 /
SOURCE_HEAD fa70dd6… —— 当前权威 lineage
```

## LEGACY_INTRADAY_LINEAGE（LEGACY_DEVELOPMENT_EVIDENCE，非权威）

```text
research/intraday/：SUCCESS_CONTROL_CASESET_V01A/B、INTRADAY_SUCCESS_PATTERN_
  V01A/B/C、V02A_MINUTE_DATA_VERIFICATION、v02a_minute_manifest.csv、
  metrics_v0*.csv
data/tmp/v02a-minute/raw_1m|raw_5m（AKShare/Sina 缓存）
research/forward/ 目录为空；forward V01/V02 仅 read-only protocol 参考，
  不得复用其 runner 作为 R8 extractor（已知 checkpoint future leakage）
旧 cohort 参考数：8746 case set / 146 event cohort / 139 5m-complete /
  40 SUCCESS / 99 FAILED —— 仅 historical reference
```

## COHORT_REBASE / EVENT_ALIGNMENT

```text
legacy V02 event cohort -> 当前 8,682 按 episode_id exact 映射：
  LEGACY_EVENT_N = 146 / MAPPED_TO_8682_N = 146 /
  NOT_IN_CURRENT_COHORT_N = 0 / LABEL_DRIFT_N = 0 /
  IDENTITY_MISMATCH_N = 0（symbol/anchor/candidate 逐行核对；
  legacy outcome == 当前 outcome_3d）
event date 来源：legacy frozen case set OUTCOME_EVENT_DATE
  （RESOLVED_CANONICAL_S1_TOUCH，first S1 touch day；当前 outcome 的
  first_event_date_10d 为"首个任意事件"，语义不同故不用）；
  禁止猜 event date / 从未来 bars 推断；不静默删除。
```

## MINUTE_SOURCE / ASL_5M_COVERAGE / BAR_TIMESTAMP_CONTRACT

```text
长期架构：ASL -> Adapter/Query -> research consumer。
R8 minute authoritative source = ASL 5m；禁止新增 AKShare/Sina/Tencent/TDX。
本地检查：无 a-share-lake checkout / 无 ASL minute 数据
  -> R8_DATA_STATUS = BLOCKED_BY_MINUTE_COVERAGE（不 fallback、不补数）
legacy AKShare/Sina 5m/1m 仅 LEGACY_PARITY_REFERENCE
  （139/146 完整、40/99；缓存仅保留 7 个 1m 完整日）。
bar 标签契约（预期 RIGHT-LABELED COMPLETED BAR，需 ASL 数据后验证）：
  09:45=3 / 10:00=6 / 10:30=12 / 11:30=24 个 completed 5m bars；
  checkpoint 只用 bar_end <= checkpoint；未来 bar 泄漏 -> BLOCKED_PIT。
当前 BAR_TIMESTAMP_SEMANTICS = VERIFICATION_PENDING（ASL 数据缺失）。
```

## R8_ONTOLOGY / ACTIVATION_CONTRACT / ACCEPTANCE_CONTRACT

```text
ACTIVATION（LAYER A）：FIRST_S1_TOUCH_5M_BAR = 首个 HIGH >= S1 的
  completed 5m bar；touch bar 只定义 activation。
ACCEPTANCE（LAYER B）：窗口从 NEXT completed bar 开始；
  分母只含 FIRST_S1_TOUCH_TIME <= checkpoint 的 episode；
  未 activation -> NOT_YET_ACTIVATED（不得当作 acceptance=0）；
  同一 bar 内不猜测 high/low/close 先后顺序。
```

## FEATURE_REGISTRY（F7 V01 冻结；registry CSV）

```text
PRIMARY：F7-1 BREAKOUT_HOLD_RATIO / F7-2 VWAP_ACCEPTANCE_RATIO /
  F7-3 RETEST_DEPTH / F7-4 FALSE_BREAK_DURATION
SECONDARY/CONTROL：S1_DISTANCE/STATE、VWAP_DISTANCE/STATE、
  PREV_CLOSE_STATE、HIGH_PROGRESSION、OPEN_GAP/OPENING_DRAWDOWN、
  CUM_VOLUME_RELATIVE_TO_D1_SAME_TIME（同 checkpoint、同 bar completion；
  禁止 full-day D1 volume）
DEFERRED：POST_BREAK_30M/60M_RETURN（无唯一 event-anchored PIT contract）
VWAP = cumulative amount / cumulative volume；amount 不可靠 -> DATA_UNAVAILABLE
  （禁止 close-weighted proxy fallback）
V01B golden：VWAP_RECLAIM = below->above；VWAP_REBREAK = above->below；
  SESSION_FIRST 与 POST_LOW 锚分开；strict next-window（anchor 排除）；
  V01B 仅 SEMANTIC_GOLDEN，非统计验证样本。
```

## CHECKPOINT_CONTRACT / PIT_GUARD

```text
全部报告 09:45 / 10:00 / 10:30 / 11:30（不得只报最好 checkpoint；
  不得看结果后选 best time —— R9 才冻结 operational checkpoint）。
LEAKAGE BAN：EOD close / close_location / full-day volume /
  afternoon_return / full-day time_below_vwap / event-day final high/low /
  checkpoint 后 bar / 最终 SUCCESS condition —— 全部禁止。
```

## DEVELOPMENT_DATA_DISCLOSURE

```text
旧 intraday evidence（S1 state / VWAP distance / high progression /
quiet volume pace / session low/range）已被开发期看过；
当前 R8 cohort = DEVELOPMENT_REANALYSIS（非 clean holdout）；
R8 最多 SUPPORTED_HYPOTHESIS；真正时间外验证在 R9。
```

## R8B_PRE_REGISTERED_EVALUATION（冻结，未执行）

```text
每 checkpoint x feature：
  Continuous：SUCCESS/FAILED N、median/mean、native AUC、
    rank-biserial 方向统计（不自动 flip）
  Binary/state：SUCCESS rate / FAILED rate / rate diff / OR+95%CI / binary AUC
禁止 threshold scan；禁止 composite score / weighted score /
  threshold voting（V01 无 Acceptance Score 复合）。
```

## COVERAGE_GATE / R8B_AUTHORIZATION

```text
当前 ASL 5m 覆盖 = 0 -> 不满足 SUCCESS>=20 / FAILED>=20
  -> R8B_RECOMMENDATION = NOT_AUTHORIZED_DATA_LIMITED
（ASL 数据落地并验证 right-label 语义后重新评估）
```

## VALIDATION

```text
compile PASS；tests/test_r8a_intraday_acceptance_contract_v01.py 20 PASS
  （cloud_ci；right-label slicing / activation HIGH>=S1 / anchor 排除 /
  NOT_YET_ACTIVATED 分母 / F7 公式 / VWAP amount-volume 语义 /
  V01B reclaim-rebreak / EOD leakage ban / 4 checkpoints / 无 composite /
  legacy->8682 exact mapping / label drift + identity mismatch fail-closed /
  coverage rows / registry deterministic）
全量回归 PASS；cloud 命令 PASS；git diff --check PASS
```

## CORRECTNESS_BLOCKER

```text
NO（contract 层面；数据层面 R8_DATA_STATUS=BLOCKED_BY_MINUTE_COVERAGE）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
ASL_ACTIVE_CHANGED=false
```
