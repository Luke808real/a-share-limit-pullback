# SUCCESS / CONTROL CASESET V01B — CONSISTENCY FIX

RUN_ID: SUCCESS_CONTROL_CASESET_V01B_CONSISTENCY_FIX
SCRIPT: research/build_success_control_caseset_v01b.py
OUTPUT: research/intraday/success_control_cases_v01b.csv
（V01 / V01A 文件未覆盖）

以下计数由最终 CSV（success_control_cases_v01b.csv）动态读取，非手工硬编码。

## OUTCOME IMMUTABILITY

- outcome 以 V01（success_control_cases_v01.csv）为唯一真源，按 episode_id 对齐。
- V01A 中 76 个 V01=STRUCTURE_FAIL / V01A=UNKNOWN 的行已恢复为 STRUCTURE_FAIL；
  事件日期缺失不再导致 outcome 变更。
- 硬断言全部通过：
  - total rows == 8746
  - duplicate episode_id == 0
  - V01 ↔ V01B merge：missing episode == 0、extra episode == 0、
    outcome mismatch == 0
  - 固定 outcome 计数与预期一致（见下）；如任一不一致则 FAIL / STOP，不生成 READY。

## 报告计数（来自最终 CSV）

OUTCOME_PARITY_WITH_V01 = true
OUTCOME_MISMATCH_N = 0
TOTAL_CASES = 8746

SUCCESS_N = 409
FAILED_BREAKOUT_N = 950
NO_LAUNCH_N = 1730
STRUCTURE_FAIL_N = 5415
UNKNOWN_N = 242

EVENT_OFFSET_D1 = 676
EVENT_OFFSET_D2 = 442
EVENT_OFFSET_D3 = 241
（SUCCESS + FAILED_BREAKOUT 共 1,359；OUTCOME_EVENT_DATE missing = 0）

MISSING_EVENT_DATE（SUCCESS/FAILED_BREAKOUT 内）= 0
QUALITY_FLAG_COVERAGE = 100.0%（INFERRED_LIMIT_ANCHOR 99.62%，保存在
quality_flags 列）

## EVENT DATE 与 OUTCOME 分离

| EVENT_DATE_STATUS | n | 说明 |
|---|---|---|
| RESOLVED_CANONICAL | 5,339 | STRUCTURE_FAIL 且 canonical bars 找到 first invalid touch day |
| RESOLVED_CANONICAL_S1_TOUCH | 1,359 | SUCCESS 409 + FAILED_BREAKOUT 950，first S1 touch day |
| PATTERN_ONLY_EVENT_UNRESOLVED | 76 | STRUCTURE_FAIL（pattern=INVALID_BEFORE_S1）但 canonical bars 无法重建触及日；outcome 保持 STRUCTURE_FAIL，OUTCOME_EVENT_DATE=NA、OFFSET=NA |
| N/A | 1,972 | NO_LAUNCH 1,730 + UNKNOWN 242 |

## V02 EVENT COHORT

- V02_EVENT_COHORT = 146，仅 SUCCESS / FAILED_BREAKOUT 且
  OUTCOME_EVENT_DATE resolved 且 EVENT_INTRADAY_AVAILABLE（窗口估计）。
- SUCCESS_EVENT_INTRADAY_N = 43
- FAILED_BREAKOUT_EVENT_INTRADAY_N = 103

## 下一步分钟数据 gate

EVENT_COHORT_STRUCTURALLY_READY = true
MINUTE_DATA_VERIFIED = false（146 个事件日尚未逐 case 验证 1m 数据）
READY_FOR_INTRADAY_V02A = false

NEXT = VERIFY_V02A_MINUTE_DATA

## 结论

NO_OUTCOME_REDEFINITION = true
NO_PRODUCTION_CHANGE = true
NO_THRESHOLD_SCAN = true
