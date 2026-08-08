# SECOND_LAUNCH_FACTOR_R1B1_DECISION_FREEZE_REPORT

> R1B.1 — 决策冻结 + Corporate Action 契约（contract/data-audit；未进入 R2）
> 无 outcome-guided 决策；未实现 extractor

STATUS: **COMPLETE** — #11/#12 alias 冻结、#23 公式冻结、CA truth/政策冻结、
#5/#7 数据支持解锁（25/25 FROZEN，0 BLOCKED）

BRANCH: `research/second-launch-factor-contract-v01`
BASE_HEAD: `1c04bfd3247eb17a6c20d8cc7ec31a072d6daec4`
HEAD_AFTER: 见 GIT 段

## INPUT_VERIFY

```text
ARTIFACT_ID: SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE / ROW_N: 8,682
IMMUTABLE_VERIFY: PASS（上轮 R1B 已验；本轮输入未变）
```

## CONTRACT_FIXES

```text
IMPULSE_DIRECTION: 已修正（#11 higher_means=MORE_RETRACED / lower_means=LESS_RETRACED）
GAIN_RETENTION_ROLE: #12 t0_gain_retention = PRIMARY
IMPULSE_ROLE:       #11 impulse_retrace_ratio = DERIVED_ALIAS（保留于 25-row 供 R2 QA；
                    univariate 独立维度只算 #12；multivariate 禁止同放）
PULLBACK_DEPTH_UNIT: #9 unit → decimal fraction（PB close 全 > C0 时可 >0；不 clamp）
TIME_EXPOSURE_TAGS: #14/#20 known_collinearity += NEAR_STRUCTURAL_WITH_TIME_EXPOSURE
                    （count 受 days_since_t0 / pullback_duration 机械上界约束）
VOLUME_SLOPE_IDENTITY: #17 记录 slope(log(vol_i/V0)) == slope(log(vol_i))（log V0 常数），
                    非 V0-scale 依赖
```

CSV 新增列：`analysis_role`（PRIMARY / DERIVED_ALIAS / BLOCKED）、`ca_class`（5 类）。

## PULLBACK_DURATION

```text
FORMULA: pullback_duration = D_offset − PRE_D_PEAK_OFFSET
PEAK_REFERENCE_WINDOW = {T0} ∪ PULLBACK_PRE_D；peak_high = max(HIGH over window)
T0_INCLUDED: true（T0 可为 peak）
D_EXCLUDED_FROM_PEAK_REFERENCE: true（D 仅提供 D_offset，绝不进 peak reference）
TIE_POLICY: 最高 HIGH 多次出现 → LAST occurrence offset（PRE_D_PEAK_OFFSET）
示例: T0 peak, D=T+4 → 4；T+2 new high, D=T+5 → 3；T+3 ties, D=T+5 → 2
STATUS: FROZEN_FOR_R2（ca_class = CA_UNSAFE_LEVEL_ORDERING）
```

## CA_DATA

```text
ADJ_FACTOR_SOURCE: data/raw/tushare/adjustment_factor/*.parquet（35 files）
DATE_RANGE: 2024-01-02 .. 2026-07-31
ROW_N: 3,391,611 / CODE_N: 5,657
DUP_N: 44,658 组（全部值一致，0 冲突，确定性去重安全）
NULL_N: 0 / NONPOSITIVE_N: 0
```

## CA_CASE_COVERAGE

```text
（8,682 cases；{T0}∪{D}∪PRE_T0_21∪T0..D union）
FULL: 7,725 / PARTIAL: 957 / NONE: 0
（PRE_T0_21-only: FULL 7,805 / PARTIAL 877；#5 窗口 FULL 7,800 / PARTIAL 882；
  #7 窗口 FULL 7,805 / PARTIAL 877 —— PARTIAL = fail-closed NULL，不推断）
```

## CA_EVENT

```text
定义：CA_EVENT(s) = adj_factor(s) != adj_factor(previous stock session)（精确 decimal；
      同一 stock 首行不算 CA；missing → CA_UNKNOWN ≠ no-CA）
research-case 日期上：
ADJ_FACTOR_EVENT_N: 530 / PRECLOSE_EVENT_N: 619
BOTH: 35 / ADJ_ONLY: 495 / PRECLOSE_ONLY: 584
POLICY: CA_MASK truth = validated adj-factor event；preclose divergence =
        AUDIT/SECONDARY_CONFIRMATION（两定义一致性低，不可互换；未按 outcome 选择）
```

## CA_FACTOR_MATRIX

（25 行完整矩阵在 daily_factor_contract_v01.csv `ca_class` 列）

```text
CA_SAFE:                        #21
CA_SAFE_SAME_SESSION_GEOMETRY:  #4 #18 #19
CA_UNSAFE_CROSS_SESSION_PRICE:  #1 #2 #3 #6 #7 #9 #10 #11 #12 #13 #24 #25
CA_UNSAFE_LEVEL_ORDERING:       #5 #14 #22 #23
CA_UNSAFE_CROSS_SESSION_VOLUME: #8 #15 #16 #17 #20
```

关键修正：#22 不再默认 CA-safe（raw LOW 尺度）；#23 依赖跨日 HIGH level；
#24/#25 增加 **D 自身 CA event → NULL**（机械假突破守卫）；volume family
（#8/#15/#16/#17/#20）无法区分现金分红与股本变化 → share-scale 未证明 → fail closed。

## FACTOR_STATUS

```text
FROZEN_FOR_R2_N: 25
DERIVED_ALIAS_N: 1（#11）
BLOCKED_N: 0
```

## #5_#7

```text
T0_POSITION_20D: FROZEN_FOR_R2（解锁）
PRE_T0_RETURN_20D: FROZEN_FOR_R2（解锁）
DECISION: 四项解锁条件全满足 —— (1) adj_factor 窗口覆盖 FULL 89.8-89.9% / NONE 0；
  (2) CA deterministic identify；(3) missing fail-closed（CA_UNKNOWN → NULL）；
  (4) 无需 adjusted price series（无 CA 窗口 raw 公式直接有效）。
  覆盖 blocker 说明：882-877 例 PARTIAL 覆盖 → 这些 case 的 #5/#7 = NULL（设计内 fail-closed，
  非数据缺陷 blocker）。
```

## CONTRACT_COLLISIONS

```text
EXACT_COLLINEAR（冻结处置）:
  #11 impulse_retrace_ratio ≡ 1 − #12 t0_gain_retention → PRIMARY/DERIVED_ALIAS
NEAR_STRUCTURAL:
  #15/#16/#17（同窗口+V0）；#18/#19（同 range 定义）；#24/#25（同 reference）；
  #21/#22/#23（结构性，但 #23 公式已独立化）；#14/#20 新增 TIME_EXPOSURE 上界标注
```

## FILES_CHANGED

- `research/second_launch/factors_v01/DAILY_FACTOR_CONTRACT_V01.md`（M：R1B.1 决策、#23 冻结、状态汇总）
- `research/second_launch/factors_v01/daily_factor_contract_v01.csv`（M：+analysis_role/+ca_class、
  metadata 修正、25 rows 保持）
- `research/second_launch/factors_v01/CORPORATE_ACTION_CONTRACT_V01.md`（新增）
- `research/reports/SECOND_LAUNCH_FACTOR_R1B1_DECISION_FREEZE_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: freeze factor decisions and ca policy
PUSH: origin/research/second-launch-factor-contract-v01
```

## CONFIRM

```text
FACTOR_EXTRACTION_STARTED=false
OUTCOME_ANALYSIS_STARTED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
```

## NEXT_RECOMMENDED_ACTION

**R2 — DAILY FACTOR EXTRACTOR**（仅当 contract gate 通过：25-row 合同 + CA 政策 +
immutable 输入复核后启动）。未获授权不进入 R2。

---

## VALIDATION（本任务）

- targeted 检查：warehouse reconciliation CA 逻辑、adjustment_factor schema/重复、
  test_corporate_action_preclose.py；bounded adj coverage 查询（8,682 cases）
- 一次性 contract validator（不入库）通过：25 unique factor_name；#11/#12 identity metadata；
  #11 direction；#23 公式冻结；#24/#25 D-CA policy 显式；无 BLOCKED 误标 FROZEN；
  analysis_role ∈ {PRIMARY, DERIVED_ALIAS, BLOCKED}
- `git diff --check` 通过；未计算 factor value；无 outcome 归因
