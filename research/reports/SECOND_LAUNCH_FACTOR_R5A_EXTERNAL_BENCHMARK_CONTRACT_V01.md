# SECOND_LAUNCH_FACTOR_R5A_EXTERNAL_BENCHMARK_CONTRACT_V01

> R5A — External Benchmark V01 contract + availability（先冻结，后执行）
> AS_OF: 2026-08-08 · research-only · BASE_HEAD `ae36f79074a33279900d87b1ec0f9fa2a2d3fd51`

STATUS: **FROZEN（pre-registered；未执行任何 benchmark outcome）**

## INPUT_GATE（outcome-blind）

```text
FEATURE_SHA: a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8
OUTCOME_SHA: 01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d
EPISODE_N: 8,682 / episode_id 1:1 / anchor/candidate/symbol binding PASS
snapshot binding: snap-2026-07-31-b5f84004de8a PASS
outcome 仅做 SHA/schema/join-key gate；未读取 outcome class 分布
```

## OUTCOME_BLINDNESS_CONFIRM

```text
本任务全程未 inspect：SUCCESS rate / OR / AUC / MFE/MAE / subgroup result。
benchmark 定义、阈值、registry 全部在读取任何 outcome 之前冻结。
```

## BENCHMARK_UNIVERSE（冻结，共 8 个，不新增）

```text
B1 N_PATTERN                传统 N 字 / N-pattern 类规则
B2 DRAGON_RETURN_2N         龙回头 / 2+N 类规则
B3 SINGLE_YANG_HOLD         单阳不破类规则
B4 FIXED_PULLBACK_TIME      固定回调/session 长度基线
B5 FIXED_PULLBACK_DEPTH     固定回撤深度基线
B6 FIXED_VOLUME_CONTRACTION 固定缩量条件基线
B7 POST_LIMIT_NEW_HIGH      涨停后重新突破前高/创新高 activation 基线
B8 HOT_SECTOR_FILTER        热点/板块过滤基线
```

来源：项目冻结研究计划 `04_Research/Second-Launch-Factor-Research-V01.md`
§8 外部 Benchmark 计划（PROJECT_DOCUMENTED 名录）。该计划未列入
“三倍量战法” -> 三倍量保持排除（不自动加入）。
“涨停双响炮”未列入 B1-B8 -> 不新增。

## DEFINITION_SOURCES（每个 benchmark 强制标记）

```text
PROJECT_FROZEN   = 项目内已有明确、冻结、可机械执行定义
PROJECT_DOCUMENTED = 项目文档已有明确规则但未冻结（原样转写候选）
MECHANICAL_PROXY = 名称结构清楚、缺部分非结果驱动细节（命名 <NAME>_PROXY）
UNDERDEFINED     = 必须主观猜测关键阈值/形态才能实现
```

## BENCHMARK_DEFINITIONS（冻结；全部 PIT as-of D）

### B1 N_PATTERN — UNDERDEFINED

```text
项目文档（§3/§8）仅列出名称“N字战法”，无任何机械定义；
实现需主观猜测形态关键（第一腿定义、回调深度/时长、确认规则）-> 保持
UNDERDEFINED。禁止为 READY 自行发明规则。
```

### B2 DRAGON_RETURN_2N — UNDERDEFINED

```text
同上：仅名称“龙回头 / 2+N”；无机械定义（“回头”深度/时长/确认未定义）。
```

### B3 SINGLE_YANG_HOLD — UNDERDEFINED

```text
同上：仅名称“单阳不破”；无机械定义（阳线尺度、不破基准、时长未定义）。
```

### B4 FIXED_PULLBACK_TIME — READY（PROJECT_FROZEN）

```text
exact_rule: 2 <= days_since_t0 <= 5
  （config/strategy.yaml b1.optimal_days_min=2 / optimal_days_max=5，
  冻结生产配置；非 outcome 驱动）
input_window: T0（offset 0）.. D；days_since_t0 为 frozen feature 列
latest_allowed_date: D（candidate_date）
required_fields: days_since_t0（feature CSV）
data_source: second_launch_factors_v01b_reproducible.csv
artifact_sha: a485a484…
missing_semantics: days_since_t0 缺失（MISSING_D_BAR）-> episode 不计入
known_limitation: 阈值来自项目自身冻结策略配置（自基准，非社区标准）
```

### B5 FIXED_PULLBACK_DEPTH — READY（PROJECT_FROZEN）

```text
exact_rule: close_D / close_T0 - 1 >= -0.04
  （config/strategy.yaml b1.close_to_anchor_min=0.96，冻结生产配置）
input_window: {T0, D}（D-close vs T0-close）
latest_allowed_date: D
required_fields: close_D, close_T0（frozen canonical bars）
data_source: canonical daily_bars snap-2026-07-31-b5f84004de8a
artifact_sha: e7243dee…
missing_semantics: T0 或 D 为 CA 日（preclose divergence > 0.5%，
  R1B 契约）或缺失 bar -> episode 不计入（fail closed）
known_limitation: 同 B4（自基准）；使用 D-close 深度（非 min-pullback-close）
```

### B6 FIXED_VOLUME_CONTRACTION — READY（PROJECT_FROZEN）

```text
exact_rule: volume_D / volume_T0 <= 0.85
  （config/strategy.yaml b1.volume_to_anchor_max=0.85，冻结生产配置）
input_window: {T0, D}
latest_allowed_date: D
required_fields: volume_D, volume_T0（frozen canonical bars）
data_source: canonical daily_bars snap-2026-07-31-b5f84004de8a
artifact_sha: e7243dee…
missing_semantics: 同 B5（CA/缺失 bar -> 不计入）；volume<=0 -> 不计入
known_limitation: 同 B4（自基准）；使用 D 当日 volume（非 PB median）
```

### B7 POST_LIMIT_NEW_HIGH — READY（POST_LIMIT_NEW_HIGH_PROXY，MECHANICAL_PROXY）

```text
exact_rule: close_D > max(high over sessions [T0-60 .. T0-1])
  - 比较对象：pre-T0 60-session 前高（reference 不含 T0、不含 D）
  - 使用 D 收盘 close（收盘突破），非 intraday high 突破
  - D 不允许等于 reference high（严格大于）
  - 窗口长度：config/strategy.yaml resistance.left_high_lookback_days=60
    （冻结生产配置）
  - reference 内 CA 事件（preclose divergence > 0.5%）-> episode 不计入
  - reference 有效前会话 < 20 -> episode 不计入（INSUFFICIENT_HISTORY）
input_window: [T0-60 .. T0-1]（high）+ D（close）
latest_allowed_date: D
required_fields: high（60 个 pre-T0 会话）, close_D, preclose（CA 检测）
data_source: canonical daily_bars snap-2026-07-31-b5f84004de8a
artifact_sha: e7243dee…
missing_semantics: CA / insufficient history -> 不计入（fail closed）
known_limitation: 代理为机械规则（名称结构 + 冻结窗口组装）；
  “突破 T0 自身高点”变体已考虑但未选择（单规则，无 grid，无 outcome 输入）
```

### B8 HOT_SECTOR_FILTER — DATA_UNAVAILABLE

```text
可用性 gate：
  无 PIT-safe sector membership artifact（canonical/raw 无行业数据；
  limit_up_pool.industry 仅覆盖 2026-07-13..31 且无历史期）；
  无 contemporaneous sector-strength artifact（sector_limitup_n 等
  F8 CONTEXT 因子仍为未来设计，未冻结）；
  未来回填行业分类 / 当前板块标签均被禁止
-> HOT_SECTOR_FILTER = DATA_UNAVAILABLE（禁止临时抓取）
```

## PIT_CONTRACT（所有 READY benchmark）

```text
AS_OF = candidate_date D
只使用：T0 及以前必要历史；T0 < session <= D；D 当日收盘可得信息
禁止：D+1+；outcome window；SECOND_LAUNCH 未来结果；future high/low；
  未来板块标签；回看未来确认形态
每个 READY benchmark 的 INPUT_WINDOW / LATEST_ALLOWED_DATE /
  REQUIRED_FIELDS / MISSING_SEMANTICS / PIT_PROOF 见 registry CSV
```

## DATA_AVAILABILITY

```text
feature CSV（a485a484…）：B4 所需 days_since_t0
frozen canonical daily_bars（e7243dee…）：B5/B6/B7 所需 close/volume/high/preclose
  （全部 PIT as-of D；hash-pin 门禁复用 R4 语义）
limit_up_pool（45faa1a2…，15 日）：仅 B8 评估用，不足 -> DATA_UNAVAILABLE
```

## BENCHMARK_REGISTRY

```text
research/second_launch/factors_v01/r5a_benchmark_registry_v01.csv
（由 r5a_benchmark_contract_v01.py 确定性生成；status 枚举
  READY / UNDERDEFINED / DATA_UNAVAILABLE / BLOCKED）
```

## EVALUATION_CONTRACT（冻结，R5B 执行；本轮不执行）

```text
PRIMARY: outcome_3d；SENSITIVITY: outcome_5d；UNKNOWN: exclude
每个 READY benchmark 至少报告：
  eligible_n / signal_n / SUCCESS_n / SUCCESS_rate
  FAILED_BREAKOUT_rate / NO_LAUNCH_rate / STRUCTURE_FAIL_rate
  Odds Ratio / 95% CI / binary AUC
  MFE / MAE / days_to_launch
  （MFE/MAE/days_to_launch 需 R5B 先冻结 companion outcome artifact，
  当前 frozen outcome 无 MFE/MAE —— 沿用 R3B.1 记录）
binary rule 不得为提高 AUC 调阈值
```

## FAIR_COMPARISON_CONTRACT

```text
R5 目标 = 建立传统/simple benchmark 自身表现。
禁止 benchmark+F3 / benchmark+F6 / baseline+project factors（属 R6）。
不同 benchmark eligible sample 不同时：同时报告 OWN_ELIGIBLE_SAMPLE 与
COMMON_COMPARABLE_SAMPLE；不得只报告更好看的一个。
```

## UNDERDEFINED / DATA_UNAVAILABLE / UNRESOLVED

```text
UNDERDEFINED: B1 N_PATTERN / B2 DRAGON_RETURN_2N / B3 SINGLE_YANG_HOLD
  （需人工冻结机械定义后转 READY；禁止自行发明）
DATA_UNAVAILABLE: B8 HOT_SECTOR_FILTER（缺 PIT-safe sector artifact）
UNRESOLVED: 三倍量战法（研究计划未列入 R5，保持排除）；
  MFE/MAE/days_to_launch 评估所需 companion outcome artifact
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R5B_RECOMMENDATION

```text
至少一个可信 READY benchmark（B4/B5/B6/B7）且无 correctness blocker
-> R5B_RECOMMENDATION = AUTHORIZED（本任务未开始 R5B）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```
