# SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_REPORT

> R5A — External Benchmark V01 contract + availability（只冻结，不执行）
> AS_OF: 2026-08-08 · research-only

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r5a-benchmark-contract-v01
BASE_HEAD: ae36f79074a33279900d87b1ec0f9fa2a2d3fd51
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## INPUT_GATE

```text
FEATURE_SHA a485a484… / OUTCOME_SHA 01a9f2fa… / 8,682 / episode 1:1 /
anchor/candidate/symbol binding / snapshot binding: PASS
```

## OUTCOME_BLINDNESS_CONFIRM

```text
本任务未 inspect 任何 outcome class 分布 / SUCCESS rate / OR / AUC /
MFE/MAE / subgroup result；benchmark 定义与阈值在看 outcome 之前冻结。
outcome artifact 仅做 SHA/schema/join-key gate。
```

## BENCHMARK_UNIVERSE（冻结 8 个，不新增）

```text
B1 N_PATTERN / B2 DRAGON_RETURN_2N / B3 SINGLE_YANG_HOLD /
B4 FIXED_PULLBACK_TIME / B5 FIXED_PULLBACK_DEPTH /
B6 FIXED_VOLUME_CONTRACTION / B7 POST_LIMIT_NEW_HIGH /
B8 HOT_SECTOR_FILTER
来源：冻结研究计划 Second-Launch-Factor-Research-V01.md §8（PROJECT_DOCUMENTED
名录）。三倍量未列入 -> 排除；涨停双响炮不在 B1-B8 -> 不新增。
```

## DEFINITION_SOURCES

```text
B4/B5/B6 = PROJECT_FROZEN（config/strategy.yaml 冻结生产阈值：
  b1.optimal_days_min/max 2..5；b1.close_to_anchor_min 0.96；
  b1.volume_to_anchor_max 0.85）
B7 = MECHANICAL_PROXY（名称结构 + 冻结 resistance.left_high_lookback_days=60）
B1/B2/B3 = PROJECT_DOCUMENTED 名录但 UNDERDEFINED（无机械定义）
B8 = PROJECT_DOCUMENTED 名录但 DATA_UNAVAILABLE（无 PIT-safe sector artifact）
```

## BENCHMARK_DEFINITIONS（冻结；全部 PIT as-of D）

```text
B4 FIXED_PULLBACK_TIME      : 2 <= days_since_t0 <= 5（feature）
B5 FIXED_PULLBACK_DEPTH     : close_D/close_T0 - 1 >= -0.04（canonical）
B6 FIXED_VOLUME_CONTRACTION : volume_D/volume_T0 <= 0.85（canonical）
B7 POST_LIMIT_NEW_HIGH_PROXY: close_D > max(high, [T0-60..T0-1])
  （收盘突破 pre-T0 60-session 前高；strict greater；reference 不含 T0/D；
  CA/不足 20 个前会话 -> 排除；"突破 T0 高点"变体已考虑未选择）
```

## PIT_CONTRACT

```text
AS_OF = candidate_date D；只使用 T0 及以前历史 + T0 < session <= D +
D 当日收盘可得信息；禁止 D+1+ / outcome window / future high/low /
未来板块标签 / 回看未来确认形态。READY 项逐条记录
INPUT_WINDOW / LATEST_ALLOWED_DATE / REQUIRED_FIELDS / MISSING_SEMANTICS /
PIT_PROOF（见 registry CSV + contract doc）。
```

## DATA_AVAILABILITY

```text
B4: feature CSV a485a484…（days_since_t0）
B5/B6/B7: frozen canonical daily_bars e7243dee…（close/volume/high/preclose，
  PIT as-of D，hash-pin 门禁复用 R4 语义）
B8: DATA_UNAVAILABLE（无 PIT-safe sector membership/strength artifact；
  limit_up_pool.industry 仅 15 日；F8 CONTEXT 因子未冻结；禁止临时抓取）
```

## BENCHMARK_REGISTRY

```text
research/second_launch/factors_v01/r5a_benchmark_registry_v01.csv
（r5a_benchmark_contract_v01.py 确定性生成，10 字段/benchmark）
B1-B3 UNDERDEFINED / B4-B7 READY / B8 DATA_UNAVAILABLE
```

## EVALUATION_CONTRACT（冻结，未执行）

```text
PRIMARY outcome_3d / SENSITIVITY outcome_5d / UNKNOWN exclude；
每个 READY benchmark 报告 eligible_n / signal_n / SUCCESS_n / rate /
FAILED_BREAKOUT_rate / NO_LAUNCH_rate / STRUCTURE_FAIL_rate / OR+95%CI /
binary AUC / MFE / MAE / days_to_launch（MFE/MAE 需 R5B 先冻结 companion
outcome artifact；沿用 R3B.1 记录）；binary rule 不得调阈值提 AUC。
```

## FAIR_COMPARISON_CONTRACT

```text
R5 目标 = benchmark 自身表现；禁止 benchmark+F3/F6/baseline+factors
（属 R6 INCREMENTAL VALUE）；eligible sample 不同时同时报告
OWN_ELIGIBLE_SAMPLE 与 COMMON_COMPARABLE_SAMPLE。
```

## UNDERDEFINED / DATA_UNAVAILABLE / UNRESOLVED

```text
UNDERDEFINED: B1/B2/B3（需人工冻结机械定义；禁止自行发明）
DATA_UNAVAILABLE: B8（缺 PIT-safe sector artifact）
UNRESOLVED: 三倍量（研究计划未列入，保持排除）；
  MFE/MAE/days_to_launch 评估所需 companion outcome artifact
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R5B_RECOMMENDATION

```text
AUTHORIZED（存在 4 个可信 READY benchmark：B4/B5/B6/B7，且无 correctness
blocker；本任务未开始 R5B）
```

## VALIDATION

```text
1. compile: PASS
2. targeted contract tests: tests/test_r5a_benchmark_contract_v01.py 10 PASS
   （universe 冻结 / status 枚举 / PIT 完整性 / B7 proxy 语义 / B8 原因 /
     validator 负向 / SHA pin / registry 确定性）
3. input SHA/binding negative tests: PASS（feature SHA == a485a484…，
   validator 对非法 status/D+1 规则 fail closed）
4. PIT boundary tests: PASS（READY 规则无 D+1/future/outcome 引用）
5. registry determinism: PASS（两次生成哈希一致）
6. git diff --check: PASS
未运行 benchmark outcome / full-market / R6 / ML / production / forward。
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

```text
research/reports/SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_V01.md（新增）
research/reports/SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_V01_REPORT.md（本报告）
research/second_launch/factors_v01/r5a_benchmark_contract_v01.py（新增 validator）
research/second_launch/factors_v01/r5a_benchmark_registry_v01.csv（新增，确定性生成）
tests/test_r5a_benchmark_contract_v01.py（新增）
```

## GIT

```text
COMMIT: research: add r5a external benchmark contract and availability
PUSH: origin/research/second-launch-factor-r5a-benchmark-contract-v01
```
