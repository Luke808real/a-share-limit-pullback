# SECOND_LAUNCH_FACTOR_R1B2_CONTRACT_CONSISTENCY_REPORT

> R1B.2 — CA edge 语义 + 契约一致性冻结（R2 extractor 前最后一个 consistency gate）
> 只改 contract/report；未实现 extractor；未计算 8,682-row dataset；未做 outcome attribution

STATUS: **COMPLETE** — #18/#19 CA 分类修正；edge-based CA 语义冻结；缺失原因拆分；
#23 missing-policy 修正；validator 全过（25/25 FROZEN）

BRANCH: `research/second-launch-factor-contract-v01`
BASE_HEAD: `cbbd78bbd1276f9f81814a3c319e1d1f811af76e`
HEAD_AFTER: 见 GIT 段

## CA_MATRIX_FIX

```text
FACTOR_18: median_range_ratio → CA_UNSAFE_CROSS_SESSION_PRICE
FACTOR_19: range_slope → CA_UNSAFE_CROSS_SESSION_PRICE
  （range_i=(H_i-L_i)/PRECLOSE_i 依赖 PRECLOSE_i，ratio 以 #3 t0_range_pct 为基准 →
   非纯 same-session；所需 comparison edges = {T0} ∪ PULLBACK_ASOF_D + predecessor；
   CA_EVENT / CA_UNKNOWN → NULL）
PURE_SAME_SESSION_SAFE: 仅 #4 t0_close_location（V01 唯一；公式不变）
```

## CA_EDGE_SEMANTICS

```text
DEFINITION: CA_TRANSITION(s_prev -> s)（连续 canonical stock sessions）：
  NO_CA / CA_EVENT / CA_UNKNOWN（adj_factor 任一端缺失 → CA_UNKNOWN）
PREDECESSOR_POLICY: 严格对齐 canonical session predecessor；
  禁止用“上一个有 adj_factor 的日期”跨 missing session 比较
MISSING_POLICY: 任一所需 edge CA_UNKNOWN → 跨 session factor NULL（不当作 no-CA）
```

## CA_EDGE_COVERAGE

（comparison span + 紧邻 predecessor；8,682 cases 动态重算，未硬编码旧 7800/7805）

```text
#5（span T0-19..T0；coverage T0-20..T0）:
  #5_FULL: 7,766 / #5_PARTIAL: 916 / #5_NONE: 0
#7（span T0-21..T0-1；coverage T0-22..T0-1）:
  #7_FULL: 7,769 / #7_PARTIAL: 913 / #7_NONE: 0
```

PARTIAL = 窗口内部分 session 无 adj_factor 行 → 对应 case 的 #5/#7 = NULL
（CORPORATE_ACTION_UNKNOWN，fail-closed，不推断）。

## MISSING_REASON

```text
EVENT_REASON: CORPORATE_ACTION_EVENT（deterministic adj-factor transition detected）
UNKNOWN_REASON: CORPORATE_ACTION_UNKNOWN（required CA edge 因 adj_factor 缺失无法判定）
CORPORATE_ACTION_UNSAFE 仅保留为 umbrella/documentation 类别；
extractor 的 row-level missing reason 必须用具体两类
```

## PULLBACK_DURATION

```text
EMPTY_PRE_D_VALID: true（D=T+1、PRE_D 空 → peak=T0、duration=1 合法）
EMPTY_PULLBACK_REASON_REMOVED: true（#23 missing_policy 不再含 EMPTY_PULLBACK_WINDOW；
  保留 MISSING_T0_BAR / MISSING_D_BAR / CORPORATE_ACTION_EVENT /
  CORPORATE_ACTION_UNKNOWN / OTHER（D<=T0 contract violation））
```

## CONTRACT_VALIDATION

```text
FACTOR_N: 25（unique factor_name）
PRIMARY_N: 24
DERIVED_ALIAS_N: 1（#11 impulse_retrace_ratio）
BLOCKED_N: 0（contract_status 全部 FROZEN_FOR_R2）
VALIDATOR_STATUS: PASS
  （1) 除 #4 外无 factor 错误标 CA_SAFE_SAME_SESSION_GEOMETRY；
   2) #18/#19 ca_class 已更新；3) 全部 CA_UNSAFE_* missing policy 同时允许
   CORPORATE_ACTION_EVENT + CORPORATE_ACTION_UNKNOWN；4) #23 无 EMPTY_PULLBACK_WINDOW；
   5) 25 unique rows 全 FROZEN_FOR_R2；6) #11 DERIVED_ALIAS / #12 PRIMARY）
```

## R2 输入契约（冻结，写入 contract）

```text
FACTOR_CONTRACT_N = 25 / PRIMARY_N = 24 / DERIVED_ALIAS_N = 1 / BLOCKED_N = 0
结构化 NULL 允许（非数据缺陷）：insufficient history / CA event / CA unknown /
empty PRE_D（#24/#25）/ denominator / session 要求 ——
25 FROZEN ≠ 每个 case 25 个非 NULL value
```

## FILES_CHANGED

- `research/second_launch/factors_v01/DAILY_FACTOR_CONTRACT_V01.md`（M：缺失 taxonomy 拆分、
  #23 修正、§12c/§14 R2 输入契约）
- `research/second_launch/factors_v01/daily_factor_contract_v01.csv`（M：#18/#19 ca_class、
  edge 化 CA policy、missing_policy 拆分、#23 修正；25 rows 保持）
- `research/second_launch/factors_v01/CORPORATE_ACTION_CONTRACT_V01.md`（M：edge 语义、
  predecessor 覆盖、新覆盖数字、矩阵修正）
- `research/reports/SECOND_LAUNCH_FACTOR_R1B2_CONTRACT_CONSISTENCY_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: finalize factor ca edge contract
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

**R2 — DAILY FACTOR EXTRACTOR**（contract gate 已齐：25-row 合同 + edge-based CA 政策 +
immutable 输入复核后启动；extractor 须实现结构化 NULL + 具体 missing reason）。
未获授权不进入 R2。

---

## VALIDATION（本任务）

- CA edge 覆盖为有界重算（8,682 cases；动态，未硬编码旧值）
- 一次性 contract validator（不入库）6 项全过（见 CONTRACT_VALIDATION）
- `git diff --check` 通过；未实现 extractor；未计算 factor value；无 outcome 归因
