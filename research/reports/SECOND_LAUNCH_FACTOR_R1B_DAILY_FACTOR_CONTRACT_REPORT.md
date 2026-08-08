# SECOND_LAUNCH_FACTOR_R1B_DAILY_FACTOR_CONTRACT_REPORT

> R1B — DAILY FACTOR CONTRACT V01（25 个 factor 的公式预注册，纯文档契约）
> 未写 factor extractor、未计算全量 factor、未做任何 outcome 归因

STATUS: **COMPLETE** — 25 个 factor 合同冻结（22 FROZEN / 1 DECISION_REQUIRED / 2 BLOCKED）；
golden sanity 通过（窗口/off-by-one/无自引用验证）；未进入 R2

BRANCH: `research/second-launch-factor-contract-v01`
BASE_HEAD: `49a29c5ac49c5309e2efb2f41969a5f4475a7c4c`
HEAD_AFTER: 见 GIT 段

## INPUT_VERIFY

```text
ARTIFACT_ID: SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE
ROW_N: 8,682
IMMUTABLE_VERIFY: PASS（verify_interim_manifest_artifacts 全项通过）
COHORT_PROVENANCE: PARTIAL / ALLOWED_USE: EXPLORATORY_FACTOR_RESEARCH_ONLY
```

## GLOBAL_CONTRACT

```text
T0: case.anchor_date（offset 0）
D:  case.candidate_date（feature as-of；PIT cutoff = D 收盘）
PIT_CUTOFF: data_date <= D；outcome/event 字段禁止入 formula
PRE_T0_n: T0 之前的 n 个该股 session（不含 T0）
PULLBACK_PRE_D: T0 < date < D
PULLBACK_ASOF_D: T0 < date <= D（含 D；F2/F3/F5 默认窗口；T0 永不入 PB）
SESSION_SEMANTICS: 该股实际存在的 canonical bar 行；missing session != zero-volume session
PRICE_POLICY: RAW_WITH_CA_EXCLUSION（CA session 检测 = preclose_s vs close_{s-1} divergence；
  命中 → NULL CORPORATE_ACTION_UNSAFE）；长窗口 #5/#7 → BLOCKED_PENDING_CA_POLICY
SUSPENSION_POLICY: 停牌日不计 session、不算 quiet、不伪造 volume=0
MISSING_POLICY: NULL + MISSING_REASON（11 类 taxonomy）；禁止 0/inf/epsilon/winsorize/clip/impute
```

## FACTOR_CONTRACT

25 行完整合同见：

- [DAILY_FACTOR_CONTRACT_V01.md](/Users/luke808/AI/V flash-r1b-contract/research/second_launch/factors_v01/DAILY_FACTOR_CONTRACT_V01.md)
- [daily_factor_contract_v01.csv](/Users/luke808/AI/V flash-r1b-contract/research/second_launch/factors_v01/daily_factor_contract_v01.csv)
  （严格 25 rows，22 列：factor_name/family/research_intent/formula_symbolic/anchor/window/
  candidate_day_used/required_columns/price_basis/volume_basis/min_required_sessions/
  missing_policy/zero_denominator_policy/suspension_policy/corporate_action_policy/pit_safe/
  unit/higher_means/lower_means/known_collinearity/contract_status/notes）

家族分布：F1 ATTACK/PRE/VOLUME 1–8 / F2 HOLD 9–14 / F3 CONTRACTION 15–20 /
F5 TIME 21–23 / F6 ACTIVATION 24–25。第 26–30 位备选（breakout_strength 等）未纳入。

## CONTRACT_COLLISIONS

```text
EXACT_COLLINEAR:
  #11 impulse_retrace_ratio 与 #12 t0_gain_retention：
    t0_gain_retention == 1 − impulse_retrace_ratio（同一 min_pullback_close + 同一分母；
    golden sanity 验证 retention+impulse=1.0 精确恒等）
    → 保留两个条目（不删除），attribution 时仅一个独立维度，留给 Thinker 决策

NEAR_STRUCTURAL:
  #15/#16/#17（同一 PB 窗口 + V0 分母，median/min/slope 同一序列）
  #18/#19（同一 range_i 定义 + t0_range_pct 基准）
  #24/#25（同一 reference，仅 H_D vs C_D）
  #21/#22/#23（结构性依赖；#23 候选 B/C 与 #21/#22 完全重复 → 拒绝）
  #3/#18（共享 range 定义，窗口不同，非 exact）
```

## CORPORATE_ACTION

```text
AVAILABLE_DATA: raw tushare adjustment_factor（35 files，2024-01-02~2026-07-31）存在但
  未验证为 PIT 连续价 helper（本轮不使用）；仓库无已验证 continuous-price research helper；
  reconciliation 有 CORPORATE_ACTION_PRECLOSE_DIVERGENCE 标记机制
POLICY: RAW_WITH_CA_EXCLUSION（preclose divergence 检测 → NULL CORPORATE_ACTION_UNSAFE；
  不构造 adjusted series，不做数据修复）
AFFECTED_FACTORS: 全部 price factor（窗口内 CA 检测）；#1/#2/#3/#4/#11/#12 额外受 T0 日 CA 影响
BLOCKED_FACTORS: #5 t0_position_20d、#7 pre_t0_return_20d（BLOCKED_PENDING_CA_POLICY，
  待 R1B.1 冻结 CA 排除/连续价政策）
```

## DAILY_ORDER_SAFETY

```text
#10 max_drawdown_from_post_t0_high：previous-session running peak 定义
  prior_peak_j = max(T0_high, highs of PB sessions strictly before j)
  dd_j = low_j / prior_peak_j − 1；factor = min(dd_j)
  → 无同日 high-before-low 假设；T0_high 作为初始峰值（已冻结）
其余 factor 只使用 daily close/high/low 各自序列（唯一同日组合 t0_close_location 的
(H0,L0) 语义为振幅内位置，不涉顺序）
```

## GOLDEN_SANITY

（17 个 golden cases：002606/002498/600468/600756/601858；仅公式/窗口/off-by-one 验证，
无 outcome 对照）

```text
✓ t0_return ≈ +0.10（涨停日口径一致）
✓ days_since_t0 = T0→D session 数（T0=0，首 post-T0 session=1；范围 1..13）
✓ days_to_pullback_low ∈ 1..8（PB 排除 T0 后 first-min-LOW offset；含 D 时以 D 为界）
✓ F6 reference 不含 D：7 例无 PRE_D bar → high_vs_pullback_high/close_vs_pullback_high = NULL
  （EMPTY_PULLBACK_WINDOW），无 self-reference
✓ volume_slope / range_slope：PB sessions < 2 → NULL（INSUFFICIENT_PULLBACK_SESSIONS）
✓ retention + impulse = 1.0 恒等（EXACT_COLLINEAR 实证）
✓ pullback_depth_close / max_drawdown ≤ 0 语义正确（除 min-close==C0 时为 0 的边界）
✓ 关键窗口修正：PB 必须排除 T0（初版含 T0 导致 days_to_pullback_low 全 0 —— 已按契约修正）
```

## DECISION_REQUIRED

```text
1. PULLBACK 窗口是否含 D → 推荐：含 D（PULLBACK_ASOF_D，D 收盘 PIT 可得）；已按推荐冻结
2. raw price 跨 CA 如何 fail closed → preclose divergence 检测 → NULL；长窗口 BLOCKED_PENDING_CA_POLICY
3. max_drawdown 避免同日顺序假设 → previous-session running peak（含 T0_high）→ 已冻结
4. days_above_t0_mid close vs low → 推荐 close-based → 已冻结
5. pullback_duration 定义 → 无既有可信定义；候选 A（自最近 post-T0 新高以来的 session 数）
   唯一独立；候选 B/C 与 #21/#22 完全重复（拒绝）→ **#23 DECISION_REQUIRED，推荐 A**
6. quiet_days_n <1/<1 → 推荐接受（固定结构定义，非阈值扫描）→ 已冻结
```

## FROZEN_FOR_R2

```text
N: 22（#1-4,6,8-22,24,25）
list: t0_return, t0_gap, t0_range_pct, t0_close_location, pre_t0_return_5d,
      t0_volume_ratio_5d, pullback_depth_close, max_drawdown_from_post_t0_high,
      impulse_retrace_ratio, t0_gain_retention, low_vs_t0_mid, days_above_t0_mid,
      pullback_volume_ratio, min_volume_ratio, volume_slope, median_range_ratio,
      range_slope, quiet_days_n, days_since_t0, days_to_pullback_low,
      high_vs_pullback_high, close_vs_pullback_high
```

## BLOCKED_OR_PENDING

```text
N: 3（#5, #7 BLOCKED_PENDING_CA_POLICY；#23 DECISION_REQUIRED）
list: t0_position_20d, pre_t0_return_20d, pullback_duration
```

## FILES_CHANGED

- `research/second_launch/factors_v01/DAILY_FACTOR_CONTRACT_V01.md`（新增）
- `research/second_launch/factors_v01/daily_factor_contract_v01.csv`（新增，25 行）
- `research/reports/SECOND_LAUNCH_FACTOR_R1B_DAILY_FACTOR_CONTRACT_REPORT.md`（本报告）
- 未提交任何代码/extractor/数据集；golden sanity 为一次性验证脚本（未入库）

## GIT

```text
COMMIT: research: define daily factor contract v01
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

**R1B review / R1B.1 decision freeze**（人工评审 6 项 DECISION_REQUIRED 与
EXACT_COLLINEAR 处置；冻结 CA 排除/连续价政策解除 #5/#7；确认 #23 候选 A；
之后 R2 才可提取 22+ 个 FROZEN factor）。未获授权不进入 R2。

---

## VALIDATION（本任务）

- immutable verifier PASS（输入冻结复核）
- golden sanity：17 cases 有界计算（一次性脚本，未入库、未看 outcome）
- `git diff --check` 通过（见 GIT 前执行）
- 未运行 full-market、未计算全量 factor、未做统计归因
- 结论状态：OBSERVE_ONLY（纯契约；无 edge 结论）
