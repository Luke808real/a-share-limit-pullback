# SECOND_LAUNCH_FACTOR_R2A_EXTRACTOR_IMPLEMENTATION_REPORT

> R2A — 25-factor extractor 实现（formula + structured missing + CA edge guard）
> 未生成/未提交 8,682-row dataset；未做任何 outcome 归因

STATUS: **COMPLETE** — extractor 实现并 33/33 tests 通过；bounded golden 17 cases 验证；
full extraction 未运行

BRANCH: `research/second-launch-factor-extractor-v01`
BASE_HEAD: `1e2179025cecba567e768eeb0aeade0a8d8f8b39`
HEAD_AFTER: 见 GIT 段

## INPUT_GATE

```text
CONTRACT_SHA256: a67e7e2adab07f87227e467cfdb8234b56a5068fd8b739ac91e77bf2623606c9（pin；运行时校验）
FACTOR_N: 25 / PRIMARY_N: 24 / DERIVED_ALIAS_N: 1 / BLOCKED_N: 0
IMMUTABLE_INPUT_VERIFY: PASS（verify_interim_manifest_artifacts；8,682 行）
FEATURE_SNAPSHOT_VERIFY: PASS（e7243dee… pin）
```

## IMPLEMENTATION

```text
FILES:
  research/second_launch/factors_v01/extract_daily_factors_v01.py（~760 行，单模块）
  tests/test_daily_factor_extractor_v01.py
  tests/test_daily_factor_ca_v01.py
REGISTRY_N: 25
REGISTRY_CONTRACT_MATCH: true（双向精确相等；validate_registry_against_contract 强制，
  缺实现/多实现/重复 → FAIL CLOSED）
```

## PIT

```text
CASE_USECOLS: 11 列白名单（episode_id/symbol/name/anchor_date/candidate_date/
  s1_price/invalid_price/data_quality/quality_flags/candidate_reconciliation_status/
  feature_3d_has_provisional/label_5d_has_provisional）
OUTCOME_COLUMNS_LOADED: false（白名单 ∩ 禁止列 = ∅ 静态断言；FactorCaseContext 无 outcome 字段）
FUTURE_BAR_READ: false（仅 feature snapshot snap-2026-07-31-b5f84004de8a；
  label snapshot 不参与任何 factor 计算）
PIT_TEST_STATUS: PASS（mutating outcome_3d/outcome_5d/time_to_*/first_event_* 后提取结果
  完全一致 —— assert_frame_equal 验证）
```

## CA

```text
ADJ_SOURCE: data/raw/tushare/adjustment_factor/*.parquet（bounded loader：code/date filter）
DUP_IDENTICAL: deterministic dedupe（值一致）
DUP_CONFLICT: FAIL CLOSED（RuntimeError；禁止 keep-last）
EDGE_SEMANTICS: CA_TRANSITION(s_prev -> s) 严格 canonical predecessor；
  单观测/缺失任一端 → CA_UNKNOWN；禁止跨 missing session 比较；
  优先级 CA_EVENT > CA_UNKNOWN（冻结）
EVENT_REASON: CORPORATE_ACTION_EVENT
UNKNOWN_REASON: CORPORATE_ACTION_UNKNOWN（row-level 分开；无 CORPORATE_ACTION_UNSAFE 输出）
左边界：所有 CA_UNSAFE factor 覆盖 span + 紧邻 predecessor
  （#5 obs T0-20..T0；#7 obs T0-22..T0-1；T0 在 index 0 时 predecessor 缺 → UNKNOWN）
CA_SAFE：#21 不因 CA NULL；#4 无 CA guard（same-session geometry）
```

## TESTS

```text
TOTAL: 33 passed（~0.6s）
FORMULA_TESTS: 20（registry/contract sha/feature sha/PIT/mutation/off-by-one/suspension/
  #5 20-session/#6 5-interval/#7 20-interval/#8 T0 excluded/#10 running peak/
  #11+#12 identity/#14 close-based/#17 min sessions/#20 <1/<1/#22 first min/
  #23 四示例/#24/#25 reference+empty PRE_D/#4 zero denominator/result invariant）
CA_TESTS: 8（identical dup/conflict block/EVENT vs UNKNOWN distinct/
  EVENT priority/left-edge UNKNOWN/#18/#19 event null/#24/#25 D event null/
  #4 on CA day computable + #1 on CA day NULL）
PIT_TESTS: 5（outcome not loaded/mutation/off-by-one/suspension/no future bars）
```

## BOUNDED_GOLDEN

```text
CASE_N: 17（002606/002498/600468/600756/601858）
PER_FACTOR_NON_NULL:
  t0_return 16 / t0_gap 16 / t0_range_pct 16 / t0_close_location 17 /
  t0_position_20d 14 / pre_t0_return_5d 15 / pre_t0_return_20d 14 /
  t0_volume_ratio_5d 15 / pullback_depth_close 16 / max_drawdown 16 /
  impulse 16 / retention 16 / low_vs_t0_mid 16 / days_above_t0_mid 16 /
  pullback_volume_ratio 16 / min_volume_ratio 16 / volume_slope 10 /
  median_range_ratio 16 / range_slope 10 / quiet_days_n 16 /
  days_since_t0 17 / days_to_pullback_low 16 / pullback_duration 16 /
  high_vs_pullback_high 10 / close_vs_pullback_high 10
MISSING_REASON_COUNTS:
  CORPORATE_ACTION_UNKNOWN 22 / EMPTY_PULLBACK_WINDOW 14 /
  INSUFFICIENT_PULLBACK_SESSIONS 13 / CORPORATE_ACTION_EVENT 4
ALIAS_IDENTITY_MAX_ERROR: 1.11e-16（impulse + retention ≈ 1 精确）
NOTES:
  #21 ∈ 1..13 plausible；#23 ∈ 1,2,3,10 plausible；
  #24/#25 7/17 NULL（无 PRE_D bar，无自引用）；
  输出写 research/second_launch/factors_v01/bounded/（未 commit）
```

## CODE_REVIEW_TARGETS

```text
- load_cases()（extract_daily_factors_v01.py:214）— usecols 白名单 + bool 解析 + PIT 静态断言
- build_factor_contexts() / find_session_index()（:390/:300）— session 索引与窗口切片
- ca_edges_status() / ca_guard()（:336/:368）— edge 语义、EVENT>UNKNOWN、左边界
- FACTOR_REGISTRY / validate_registry_against_contract()（:740/:793）— 25 公式注册表
- f_max_drawdown()（:541）— daily-order-safe running peak（禁 cummax 含当日）
- f_volume_slope() / f_range_slope()（:620/:664）— OLS float64 + 会话要求
- f_pullback_duration()（:696）— PEAK_REFERENCE {T0}∪PRE_D + LAST tie
- _f6_reference()（:712）— PRE_D reference 排除 D + D 自身 CA edge
```

## FILES_CHANGED

- `research/second_launch/factors_v01/extract_daily_factors_v01.py`（新增）
- `tests/test_daily_factor_extractor_v01.py`（新增，25 tests）
- `tests/test_daily_factor_ca_v01.py`（新增，8 tests）
- `research/reports/SECOND_LAUNCH_FACTOR_R2A_EXTRACTOR_IMPLEMENTATION_REPORT.md`（本报告）
- 未提交：`research/second_launch/factors_v01/bounded/golden_v01.csv`（验证 scratch）

## GIT

```text
COMMIT: research: implement daily factor extractor v01
PUSH: origin/research/second-launch-factor-extractor-v01
```

## CONFIRM

```text
FULL_8682_EXTRACTION=false（CLI full mode 需 --allow-full，本轮未使用）
FACTOR_DATASET_PUBLISHED=false
OUTCOME_ANALYSIS_STARTED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
```

## NEXT_RECOMMENDED_ACTION

**ChatGPT code review → R2B full extraction**（仅批准后：8,682 行 bounded-mode 移除、
--allow-full 提取、R2B 再 join labels 做 attribution input）。未获授权不进入 R2B。

---

## VALIDATION（本任务）

- 33/33 targeted pytest；`git diff --check` 通过；未跑 full-market pipeline
- bounded golden：17 cases 有界提取（输入 gate 全过；无 outcome 读取）
- 数值政策：Decimal ratios / int counts / float64 slopes；无 round/winsorize/clip/impute
- 结论状态：OBSERVE_ONLY（纯实现；无 edge 结论）
