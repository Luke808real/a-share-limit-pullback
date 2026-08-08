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

# R8A_ASL5M_READINESS_UNBLOCK（2026-08-09 只读发现；未改 R8 contract）

## LOCAL_ASL_DISCOVERY

```text
检查位置（bounded，/Users/luke808/AI maxdepth 3 + /tmp + env + worktrees）：
  A_SHARE_DATA_ROOT = UNSET
  /Users/luke808/AI 下无 ashare-lake / a-share-lake checkout
  /tmp/asl_phase1a_lake、/tmp/asl_phase1b_lake = 仅日线 staging spike
    （staging/daily_bars + trading_calendar；meta/state 有 minute 锁文件
    但无任何 minute 数据表/parquet）
  ASL adapter（asl_adapter.py）仅支持 daily curated，无 minute/5m 接口
结论：ASL_LOCAL_REPO = 仅日线 spike lakes；ASL_MINUTE_PRESENT = False
  -> R8_DATA_STATUS = BLOCKED_BY_MINUTE_COVERAGE（不 fallback、不补数）
```

## S1_PROVENANCE（冻结）

```text
S1 来源 = 当前 frozen outcome artifact（s1_price 列，SHA 01a9f2fa…）：
  8,682 全部 finite 且 > 0（min 1.13）
146 mapped event episodes：s1 finite 146/146、>0 146/146、
  event date 非空 146/146、identity mismatch 0、
  current outcome ∈ {SUCCESS, FAILED_BREAKOUT} 146/146
event date 来源 = legacy frozen case set OUTCOME_EVENT_DATE
  （SHA b22eae1d…；first S1 touch day）
manifest 新增：s1_price / s1_source / s1_source_sha /
  event_date_source / event_date_source_sha
provenance artifact：r8a_asl5m_provenance_v01.csv
```

## COVERAGE_RECOMPUTE（ASL 5m = 0）

```text
TOTAL_EVENT_COHORT = 146（SUCCESS 43 / FAILED_BREAKOUT 103）
ASL_EVENT_DAY_FOUND_N = 0
ASL_MORNING_COMPLETE_N = 0
SUCCESS_MORNING_COMPLETE_N = 0
FAILED_BREAKOUT_MORNING_COMPLETE_N = 0
FULL_DAY_COMPLETE_N = 0
MISSING_EVENT_DAY_N = 146（0 + 146 == 146 reconciliation）
VWAP_READY_N = 0 / D1_CONTROL_READY_N = 0
VWAP_STATUS = DATA_UNAVAILABLE（无数据；无 proxy）
BAR_SEMANTICS = VERIFICATION_PENDING_NO_ASL_DATA
```

## R8B_READINESS_GATE（重新评估）

```text
S1 provenance PASS；bar semantics 无法验证（无 ASL 数据）；
SUCCESS_MORNING_COMPLETE_N = 0 < 20；FAILED_MORNING_COMPLETE_N = 0 < 20
-> R8B_RECOMMENDATION = NOT_AUTHORIZED_DATA_LIMITED
exact gap：146 个 event day 全部缺 ASL 5m morning-complete 数据
（ASL minute 数据落地并验证 right-label 语义后重新评估）
```

## VALIDATION（readiness）

```text
compile PASS；tests/test_r8a_asl5m_readiness_v01.py 7 PASS
  （6 cloud_ci：S1 146/146 finite+positive、identity binding、source pins、
    S1 missing fail-closed、coverage reconciliation、provenance deterministic；
    1 local_data：本机 ASL discovery 无分钟数据）
全量回归 PASS；deterministic rerun PASS；git diff --check PASS
```

# R8_ASL5M_SEED_FREEZE（2026-08-09 · bounded seed；DATA_FREEZE=true）

## PROVENANCE_HYGIENE

```text
VFLASH_ASL_INTEGRATION_HEAD = 097fcb7（V Flash integration provenance，
  不是 upstream ASL code SHA）
R8_ASL_CANDIDATE_SHA = 04bd94936587b35cae55c833627260866d025184
  （rootSunc/ashare-lake，detached exact SHA；不是 ASL_ACTIVE）
```

## ISOLATED_CHECKOUT / RESEARCH_LAKE

```text
ASL_REPO_PATH = /Users/luke808/AI/ashare-lake-r8-candidate
  （clone @ 04bd949…，rev-parse 验证，worktree clean，未 pull/升级）
R8_ASL_DATA_ROOT = /Users/luke808/AI/asl-r8-5m-lake（RESEARCH_ONLY；
  NOT ASL_ACTIVE；NOT PRODUCTION）
旧 /tmp/asl_phase1a|phase1b_lake 未动
```

## BOOTSTRAP / BACKFILL（有界）

```text
最小 bootstrap：init_phases = ["phase1_reference"]
  （仅 instruments 7,399 + trading_calendar；无 daily backfill）
请求集：r8a_asl5m_provenance_v01.csv -> 146 events（SUCCESS 43 /
  FAILED_BREAKOUT 103）；UNIQUE_SYMBOL_N = 141（67 SH / 79 SZ，无 BJ）
BACKFILL_START = 2026-06-04（MIN_EVENT_DATE 前一交易日）
BACKFILL_END = 2026-07-30
命令：asl backfill minute_bars_5m --start 2026-06-04 --end 2026-07-30
  --symbols <141>（5m only；首 run 部分截断后重跑补齐；DATA_FREEZE=false 阶段）
TDX 5m 视野（~491 交易日）覆盖本窗口。
```

## ASL_5M_SCHEMA / BAR_SEMANTICS / UNITS（真实数据验证）

```text
schema：symbol / trade_date / bar_time / frequency / open / high / low /
  close / volume / amount / source / data_version / fetched_at
  frequency = 5m；source = tdx_protocol；data_version = v1
BAR_LABEL = RIGHT_LABELED_COMPLETED（真实数据验证）：
  09:35..11:30 上午 24 bars；13:05..15:00 下午 24 bars；48 bars/全日
  09:45 = 3 / 10:00 = 6 / 10:30 = 12 / 11:30 = 24（PASS）
  unique(symbol, trade_date, bar_time) = 0 dup；时间严格递增；
  无 13:00 phantom；无 off-session bars
UNITS：volume = shares；amount = RMB（实测 5m 汇总 / canonical 日线
  volume = 1.000、amount = 1.000；per-bar amount/volume 落在 [low, high]
  价格区间内）-> VWAP_STATUS = READY
```

## DATASET_LOCK / COVERAGE

```text
dataset_lock_sha = 3914887a81908dfc6745c412a3f0406c3ba6a7ddc7e7e2902b0af0fb730add9a
（40 partitions x 6,750 rows；total 270,000；partition 行数+sha256 全记录于
  r8_asl5m_dataset_lock_v01.csv；raw bars 不提交 GitHub）
COVERAGE（真实 frozen lake）：
  TOTAL_EVENT_COHORT = 146；ASL_EVENT_DAY_FOUND_N = 146；
  ASL_MORNING_COMPLETE_N = 146；SUCCESS_MORNING_COMPLETE_N = 43；
  FAILED_BREAKOUT_MORNING_COMPLETE_N = 103；FULL_DAY_COMPLETE_N = 146；
  MISSING = 0；INCOMPLETE_MORNING = 0；VWAP_READY_N = 146；
  D1_CONTROL_READY_N = 141（2026-06-04 全 symbols；15 个缺失 symbol-day
  为停牌，与 canonical 日线一致）
```

## HARD_R8B_GATE

```text
S1_PROVENANCE = PASS
BAR_SEMANTICS = RIGHT_LABELED_VERIFIED
SUCCESS_MORNING_COMPLETE_N = 43 >= 20；FAILED = 103 >= 20
无重复 bars；无 checkpoint leakage；dataset frozen
-> R8_CORE_DATA_STATUS = READY（VWAP 单独 READY；未执行任何 R8 attribution）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
ASL_ACTIVE_CHANGED=false
```
