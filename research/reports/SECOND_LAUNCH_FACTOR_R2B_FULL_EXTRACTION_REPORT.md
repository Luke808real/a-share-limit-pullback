# SECOND_LAUNCH_FACTOR_R2B_FULL_EXTRACTION_REPORT

> R2B — 正式 full factor extraction（8,682 cohort）+ dataset QA + immutable feature dataset
> 未 join outcome labels；未做 attribution；未修改 strategy

STATUS: **PASS** — 8,682/8,682 提取；全项 QA 通过；immutable dataset 已发布

BRANCH: `research/second-launch-factor-r2b-full-extraction-v01`
BASE_HEAD: `5a4d7ca10a94c21125c1969dd3d070d7cbcb0bca`
HEAD_AFTER: 见 GIT 段

## INPUT_GATE

```text
COHORT_VERIFY: PASS（immutable manifest verify；cohort sha 01a9f2fa… 与冻结一致）
COHORT_N: 8,682
CONTRACT_SHA256: a67e7e2adab07f87227e467cfdb8234b56a5068fd8b739ac91e77bf2623606c9（pin 校验 PASS）
CONTRACT_VERIFY: 25 FROZEN / PRIMARY 24 / DERIVED_ALIAS 1 / BLOCKED 0
FEATURE_SNAPSHOT_VERIFY: PASS（snap-2026-07-31-b5f84004de8a，e7243dee…）
REGISTRY_N: 25 / REGISTRY_CONTRACT_MATCH: true（双向精确）
```

## EXTRACTION

```text
INPUT_CASE_N: 8,682 / OUTPUT_CASE_N: 8,682
FACTOR_N: 25 / PRIMARY_N: 24 / DERIVED_ALIAS_N: 1
OUTCOME_COLUMNS_LOADED: false（usecols 白名单；forbidden ∩ usecols = ∅）
OUTCOME_JOINED: false（输出 schema 无任何 outcome/event 列）
FUTURE_BAR_READ: false（仅 feature snapshot）
运行方式：--allow-full 官方路径，单次运行（41s）；未恢复 --skip-input-gate
```

## IDENTITY_QA

```text
MISSING_CASE_N: 0 / EXTRA_CASE_N: 0 / DUPLICATE_CASE_N: 0
IDENTITY_MATCH: true（episode_id 1:1 映射冻结 cohort）
```

## MISSING_QA

```text
PER_FACTOR_NON_NULL（摘要）：t0_close_location 8,682；days_since_t0 8,682；
  T0 日因子 8,216；#5 7,232；#6 7,689；#7 7,204；#8 7,727；PB 因子 8,029-8,030；
  volume_slope 4,330；range_slope 4,331；#23 8,122；#24/#25 4,371
PER_FACTOR_NULL = 8,682 − NON_NULL（见上）
MISSING_REASON_COUNTS:
  CORPORATE_ACTION_UNKNOWN 12,378 / EMPTY_PULLBACK_WINDOW 8,102 /
  INSUFFICIENT_PULLBACK_SESSIONS 7,750 / CORPORATE_ACTION_EVENT 3,100 /
  NONPOSITIVE_VOLUME 3
UNKNOWN_MISSING_REASON_N: 0（未注册 reason 出现 → 无）
VALUE_REASON_INCONSISTENT_N: 0（value ⟺ reason 严格互斥）
```

## CA_QA

```text
CA_GUARDED_FACTORS: 23（#4/#21 为 CA_SAFE）
逐 factor VALID/EVENT/UNKNOWN/OTHER 见附录表（全部 EVENT 与 UNKNOWN 分开；
  OTHER 仅为 INSUFFICIENT_PULLBACK_SESSIONS 等结构化 reason）
CA_EVENT_COUNTS: 合计 3,100（T0 日因子 42×3；#7 747；#5 713；#8 164；
  PB 因子 81×12；#23 64；#24/#25 31×2）
CA_UNKNOWN_COUNTS: 合计 12,378
CA_SEMANTICS_STATUS: PASS（edge-based、canonical predecessor、EVENT>UNKNOWN、
  左边界 predecessor 强制、无 silent skip、无 CA-guarded value 违反 NULL 契约）
```

## PLAUSIBILITY_QA

```text
NON_FINITE_N: 0（非空值中 inf/-inf/NaN 均无）
IMPOSSIBLE_VALUE_N: 0（days_since_t0<0 / days_to_pullback_low<1 /
  pullback_duration<1 / close_location∉[0,1] / quiet_days>days_since_t0 /
  days_above>days_since_t0 均 0）
PER_FACTOR_DISTRIBUTION_SUMMARY: 见附录表（t0_return≈+0.10 涨停口径一致；
  days_since_t0 1..23；drawdown ≤0 中位数 −0.056；slope 因子仅在 ≥2 PB sessions 填充）
备注：max_drawdown_from_post_t0_high 有 467/8,030（5.8%）正值 —— 结构合法
  （PB session 全部跳空高于 running peak 时 min(dd_j)>0，公式无上 clamp）；
  契约 #10 unit 标注 “(<=0)” 比公式更严格 —— 已记录为契约元数据待维护项，
  本轮不改冻结合同
```

## ALIAS_QA

```text
ALIAS_COMPARABLE_N: 8,030
ALIAS_MAX_ABS_ERROR: 4.44e-16
ALIAS_MISMATCH_N: 0（>1e-9 容差）
```

## REPRODUCIBILITY

```text
DATASET_ID: SECOND_LAUNCH_FACTORS_V01B_REPRODUCIBLE
DATASET_SHA256: a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8
SCHEMA_SHA256: 4d8765f44c8ac31e1aade5b03732c6e963880efb4968ba80c35d69f9025ea64f
INPUT_COHORT_SHA256: 01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d
FEATURE_SNAPSHOT: snap-2026-07-31-b5f84004de8a（e7243dee…）
EXTRACTOR_COMMIT: 5a4d7ca10a94c21125c1969dd3d070d7cbcb0bca（reviewed HEAD）
```

## PUBLICATION

```text
FEATURE_DATASET_PATH: research/second_launch/factors_v01/second_launch_factors_v01b_reproducible.csv
MANIFEST_PATH: research/second_launch/factors_v01/manifest_factors_v01b_reproducible.json
IMMUTABLE: true（manifest 记录 DATASET_SHA256/SCHEMA_SHA256/输入哈希/EXTRACTOR_COMMIT；
  与 R2A bounded 输出、冻结 cohort、既有 artifact 均不覆盖）
OUTCOME_INCLUDED: false（features only）
```

## CORRECTNESS

```text
CORRECTNESS_BLOCKER: NO
DATASET_QA: PASS
```

## CONFIRM

```text
OUTCOME_ANALYSIS_STARTED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## R3_RECOMMENDATION

```text
AUTHORIZED
```

（依据 §15 全部门条件满足：COHORT_N=8,682 / OUTPUT_CASE_N=8,682 /
MISSING=0 / EXTRA=0 / DUP=0 / REGISTRY_MATCH=true / UNKNOWN_REASON=0 /
NON_FINITE=0 / ALIAS_MISMATCH=0 / OUTCOME_JOINED=false / BLOCKER=NO / QA=PASS。
本任务未启动 R3。）

## FILES_CHANGED

- `research/second_launch/factors_v01/second_launch_factors_v01b_reproducible.csv`（新增，8,682 行）
- `research/second_launch/factors_v01/manifest_factors_v01b_reproducible.json`（新增）
- `research/reports/SECOND_LAUNCH_FACTOR_R2B_FULL_EXTRACTION_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: publish r2b full factor feature dataset
PUSH: origin/research/second-launch-factor-r2b-full-extraction-v01
```

---

## 附录 A — CA_QA 逐 factor

| factor | VALID | CA_EVENT | CA_UNKNOWN | OTHER |
|---|---:|---:|---:|---:|
| t0_return / t0_gap / t0_range_pct | 8,216 | 42 | 424 | 0 |
| t0_position_20d | 7,232 | 713 | 737 | 0 |
| pre_t0_return_5d | 7,689 | 194 | 799 | 0 |
| pre_t0_return_20d | 7,204 | 747 | 731 | 0 |
| t0_volume_ratio_5d | 7,727 | 164 | 791 | 0 |
| PB 类（#9-#16/#18/#20/#22，12 个） | 8,029-8,030 | 81 | 571 | 0-1 |
| volume_slope | 4,330 | 58 | 242 | 4,052 |
| range_slope | 4,331 | 81 | 571 | 3,699 |
| pullback_duration | 8,122 | 64 | 496 | 0 |
| high_vs/close_vs_pullback_high | 4,371 | 31 | 229 | 4,051 |

## 附录 B — 分布摘要（P01/P50/P99）

见提取时 QA 输出（已存档于本报告生成过程）；关键：
days_since_t0 ∈ 1..23；days_to_pullback_low ∈ 1..20；pullback_duration ∈ 1..19；
t0_close_location ∈ [0.923,1]；drawdown p50 −0.056；slope 仅 ≥2 sessions 填充。
