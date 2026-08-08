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

---

# R5A_AUDIT_PATCH

> 2026-08-08 · contract cleanup（独立审查收尾）· 未运行任何 benchmark outcome

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r5a-benchmark-contract-v01
BASE_HEAD: 123f6f2a37571c3479a3a1ad41250ae11274ad31
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## DEFINITION_SOURCE_FIXED

```text
按 frozen source contract 修正语义：
  PROJECT_DOCUMENTED = 已有明确机械规则但未冻结
  UNDERDEFINED       = 必须主观猜测关键规则
B1/B2/B3 仅有 benchmark 名称、无机械规则：
  definition_source = UNDERDEFINED（原 PROJECT_DOCUMENTED 已修正）
  保留说明：benchmark name/listing source = project research plan（§3/§8）
未给 B1/B2/B3 新增任何机械定义。
```

## B7_HISTORY_SEMANTICS

```text
bounded inspect 现有 frozen helper：
  src/limit_pullback/strategy/structure.py generate_resistance_candidates
  PRE_ANCHOR_LEFT_HIGH = pre_anchor[-resistance.left_high_lookback_days:]
结论（Option A：frozen implementation 语义唯一明确）：
  - reference = 最后 min(60, available) 个 pre-T0 会话（无最小历史门槛）
  - 20~59 会话允许；missing bars 即不在 reference
  - CA semantics：无（helper 不做 CA 过滤）
  - equality：严格大于（close_D == reference high 不是信号）
  - max(high)，平局 (high, trade_date) 取最新（不影响条件值）
  - reference 不含 T0/D；无 pre-T0 会话 -> NO_REFERENCE，episode 排除
早稿中“<20 会话排除 / CA 排除”条款不属于 frozen helper，已移除（复用-only）。
B7 保持 READY（POST_LIMIT_NEW_HIGH_PROXY，MECHANICAL_PROXY）。
```

## BLIND_INPUT_GATE

```text
新增可复现 outcome-blind gate：r5a_benchmark_contract_v01.blind_input_gate()
  - FEATURE SHA == a485a484…；OUTCOME SHA == 01a9f2fa…
  - row N 8,682/8,682；episode_id unique + exact 1:1
  - anchor/candidate/symbol identity binding
  - feature_snapshot_id binding == snap-2026-07-31-b5f84004de8a
  - canonical daily snapshot SHA == e7243dee…（READY benchmark 数据源）
  - outcome CSV 仅以 identity columns 读取：
    episode_id / anchor_date / candidate_date / symbol / feature_snapshot_id
  - MUST NOT load outcome_3d/outcome_5d/SUCCESS/FAILED_BREAKOUT/
    NO_LAUNCH/STRUCTURE_FAIL/MFE/MAE/days_to_launch（usecols guard）
  - 任一失败 fail closed
```

## OUTCOME_BLINDNESS_CONFIRM

```text
本 patch 全程未查看 outcome class 分布 / SUCCESS rate / OR / AUC /
MFE/MAE；registry 与 B7 语义仅由 frozen 定义/实现决定。
```

## REGISTRY_DIFF（仅允许范围）

```text
B1/B2/B3: definition_source PROJECT_DOCUMENTED -> UNDERDEFINED
B7: exact_rule / input_window / required_fields / missing_semantics /
  known_limitation 更新为 frozen helper 复用语义（status READY 不变，
  definition_source MECHANICAL_PROXY 不变）
B4/B5/B6/B8: 规则 / status / threshold 字节不变
未新增 benchmark
```

## VALIDATION

```text
1. compile: PASS
2. targeted R5A tests: tests/test_r5a_benchmark_contract_v01.py 20 PASS
   （新增：definition_source 语义回归、B7 frozen-history 语义、
     blind gate 正向 + feature/outcome SHA 错、episode 集不匹配、
     identity 绑定错、snapshot 绑定错、canonical SHA 错、usecols guard）
3. blind input gate positive/negative: PASS
4. registry deterministic rerun: PASS（两次生成哈希一致）
5. git diff --check: PASS
未运行 benchmark outcome / R5B / R6 / full-market / ML / production / forward。
```

## CORRECTNESS_BLOCKER

```text
NO
```

## READY_BENCHMARKS

```text
B4 FIXED_PULLBACK_TIME / B5 FIXED_PULLBACK_DEPTH /
B6 FIXED_VOLUME_CONTRACTION / B7 POST_LIMIT_NEW_HIGH_PROXY
```

## R5B_RECOMMENDATION

```text
AUTHORIZED（B7 语义唯一冻结、blind gate PASS、>=1 个 READY benchmark、
无 correctness blocker；本任务未开始 R5B）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## GIT（audit patch）

```text
COMMIT: research: r5a contract audit cleanup - source semantics and blind gate
PUSH: origin/research/second-launch-factor-r5a-benchmark-contract-v01
```
