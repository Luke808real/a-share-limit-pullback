# SUCCESS / CONTROL CASESET V01

RUN_ID: BUILD_SUCCESS_AND_CONTROL_CASESET_V01
SCRIPT: research/build_success_control_caseset_v01.py
OUTPUT: research/intraday/success_control_cases_v01.csv
INPUT: corrected episodes（outcome-study execution-reality，episodes.parquet，
冻结 hash 66d5943f…）、canonical daily bars snap-2026-07-31-b5f84004de8a、
limit_up_pool name map
DATA_CUTOFF: 2026-07-31（frozen snapshot）

## 候选入口（PIT，D-1 收盘可得）

- 统一入口 = 冻结 lifecycle 候选：setup_stage ∈ {B1_READY, B2_READY,
  B2_CONFIRMED}（项目 frozen 语义中 STRUCTURE_ALIVE / PREPOSITION /
  LAUNCH_READY 的等价物）。
- 仅使用 D-1 及之前信息：signal_date（candidate_date）收盘可得的
  invalid / S1 / trigger / score；未来数据未参与选择。
- 硬门槛：invalid_price 与 s1_price 均有效；future_sessions_available >= 3；
  data_quality != UNUSABLE。
- 去重：每个启动 episode（setup_id = code:anchor_date）只取最早的候选日
  （min signal_date），同一启动不重复进入多个 case。
- 样本量：8,746 个 case（8,736 B1_READY / 9 B2_READY / 1 B2_CONFIRMED
  作为最早候选）。

## Outcome 规则（候选集生成后使用未来数据，仅作结果标签）

固定前瞻 3 个交易日；基准顺序用冻结 pattern_3d，接受/扩张用日K细化：

- SUCCESS：S1_BEFORE_INVALID，且首个 S1 触及日 close >= S1（ACCEPTANCE/HOLD）
  且当日 volume >= candidate 日 volume（EXPANSION）。
- FAILED_BREAKOUT：S1_BEFORE_INVALID 但接受失败（close < S1）或量能未扩张
  （close >= S1 但 volume < candidate 日 volume）。
- NO_LAUNCH：NEITHER（3 日内 S1/invalid 均未触及，结构仍在、未发动）。
- STRUCTURE_FAIL：INVALID_BEFORE_S1（3 日内 invalid 先于 S1）。
- UNKNOWN：pattern_3d AMBIGUOUS（同日 S1/invalid 顺序不明）或日K缺失；不参与比较。

规则为预注册固定定义，无 threshold scan、无事后调整。

## 计数

| outcome | n |
|---|---|
| SUCCESS | 409 |
| FAILED_BREAKOUT | 950 |
| NO_LAUNCH | 1,730 |
| STRUCTURE_FAIL | 5,415 |
| UNKNOWN | 242（AMBIGUOUS 212 + 日K缺失/标签缺失 30） |
| TOTAL | 8,746 |

SUCCESS_N = 409（>= 20）
CONTROL_N = 8,095（FAILED_BREAKOUT + NO_LAUNCH + STRUCTURE_FAIL，>= 20）

## PIT 与去重审计

- PIT_VIOLATIONS = 0：候选选择字段全部来自冻结 D-1 episode；outcome 仅在候选集
  生成后读取未来数据。
- DUPLICATES = 0：episode_id（setup_id）唯一，8,746/8,746。
- 同一 anchor 的后续候选日（B2 等）未作为独立 case；sibling 数量记录在
  same_anchor_sibling_count 供追溯。

## 时间分散

- 年份：2024 = 2,128（24.3%）；2025 = 4,027（46.0%）；2026 = 2,591（29.6%）。
- 月份最高：2026-06 = 746（8.5%）。
- 单日最高：2024-10-09 = 84（0.96%）。
- SAMPLE_CONCENTRATION = false（max year 46% < 50%，max month 8.5% < 30%，
  max date 0.96% < 5%）。

## 已知质量 caveat

- 8,713 / 8,746（99.6%）候选带 INFERRED_LIMIT_ANCHOR quality flag（frozen
  episodes 自身 provenance），data_quality 多为 PARTIAL；这是冻结研究产物的
  既有属性，不构成 PIT 违规，但属于置信度限制，V02 分析时需保留
  data_quality / quality_flags 维度。
- name 覆盖 27.2%（来自 limit_up_pool 快照，仅涨停日有名称）；未覆盖者为空。
- intraday_data_available 为窗口估计（sina 1m 可用窗口
  2026-06-05 ~ 2026-08-04），未逐 case 拉取；V02 执行前需逐 case 验证。

## 已有案例的统一规则映射

已有 KB/人工案例未自动进入 SUCCESS；按统一规则落入：

| code | 统一规则下的 case | outcome |
|---|---|---|
| 600468 | 2（2025-12-23、2026-06-30） | STRUCTURE_FAIL ×2 |
| 601858 | 2（2026-01-19、2026-03-13） | NO_LAUNCH ×2 |
| 600756 | 7 | FAILED_BREAKOUT 1 / NO_LAUNCH 1 / STRUCTURE_FAIL 4 / SUCCESS 1（2026-03-16）/ UNKNOWN 1 |
| 002606 | 3 | STRUCTURE_FAIL 2 / NO_LAUNCH 1 |
| 603980 | 3 | STRUCTURE_FAIL ×3 |

600756 保留 HUMAN_EXECUTION / OBSERVATION 身份；其 2026-08-03/04 人工观察日
不在本 case set（超出 frozen cutoff 2026-07-31）。2026-08 人工 SECOND_LAUNCH
案例（600468 8/3 等）同理不在本集合，不影响统一规则公平性。

## Intraday 可用子集

- SUCCESS：42（>= 20）
- CONTROL：909（FAILED_BREAKOUT 99 + NO_LAUNCH 145 + STRUCTURE_FAIL 665）
- 即使只使用 intraday 可用子集，V02 也可运行；但 42 个 SUCCESS 中仍有质量
  caveat 与窗口限制，V02 前逐 case 验证 1m 完整性。

## 结论

CASESET_READY = true
SUCCESS_N = 409
CONTROL_N = 8,095
PIT_VALID = true
READY_FOR_INTRADAY_V02 = true

NO_PRODUCTION_CHANGE = true

NEXT = INTRADAY_SUCCESS_PATTERN_V02（仅登记；需人工确认本 case set 后才执行）
