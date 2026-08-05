# V02A MINUTE DATA VERIFICATION

RUN_ID: VERIFY_V02A_MINUTE_DATA
SCRIPT: research/verify_v02a_minute_data.py
MANIFEST: research/intraday/v02a_minute_manifest.csv
CACHE: data/tmp/v02a-minute/raw_1m/、data/tmp/v02a-minute/raw_5m/
INPUT: success_control_cases_v01b.csv（V02_EVENT_COHORT=true）
DATA_SOURCE: AKSHARE/SINA 1m（主验证）+ 5m（fallback 证据）

所有计数由最终 manifest CSV 动态读取。

## 1. INPUT

TOTAL_EVENT_CASES = 146
SUCCESS = 43
FAILED_BREAKOUT = 103

事件日范围：2026-06-05 ~ 2026-07-30（6 月 110 / 7 月 36）。

## 2. FETCH / CACHE

- 唯一 symbol = 141，全部抓取成功：1m_OK=141、1m_ERROR=0；5m_OK=141、5m_ERROR=0。
- 原始数据缓存：data/tmp/v02a-minute/raw_1m/{symbol}.parquet、
  data/tmp/v02a-minute/raw_5m/{symbol}.parquet；未覆盖 V01 原始数据。

## 3. 1m SESSION COMPLETENESS（按 OUTCOME_EVENT_DATE）

关键事实：新浪 1m 只返回约 1,970 根 bar（≈最近 8 个交易日，约 7/23 起），
因此 146 个事件日中只有 7 个事件日有 1m 数据。

- 有 1m 数据的事件日：7（全部 2026-07-28 ~ 2026-07-30）
  - SUCCESS：2（002642 07-28、603988 07-30）
  - FAILED_BREAKOUT：5（601369 07-28、000892 07-29、002292 07-29、
    603955 07-30、603630 07-30）
- 7 个事件全部通过结构校验：timestamp 单调、无重复、OHLC 合法、
  volume/amount >= 0；bar_count 237-238（1m 口径正常范围）。
- 7 个事件全部具备 09:45 / 10:00 / 10:30 / 11:30 checkpoint 与完整收盘 session。

## 4. CHECKPOINT READINESS（1m）

各 checkpoint 可用数相同（数据完整时四者同真）：

| checkpoint | SUCCESS_READY | FAILED_READY |
|---|---|---|
| 09:45 | 2 | 5 |
| 10:00 | 2 | 5 |
| 10:30 | 2 | 5 |
| 11:30 | 2 | 5 |

COMMON_SUCCESS_N = 2
COMMON_FAILED_BREAKOUT_N = 5

## 5. MISSINGNESS AUDIT

| checkpoint | success available_n / missing_n / rate | failed available_n / missing_n / rate |
|---|---|---|
| 09:45 | 2 / 41 / 4.65% | 5 / 98 / 4.85% |
| 10:00 | 2 / 41 / 4.65% | 5 / 98 / 4.85% |
| 10:30 | 2 / 41 / 4.65% | 5 / 98 / 4.85% |
| 11:30 | 2 / 41 / 4.65% | 5 / 98 / 4.85% |

按 EVENT_SESSION_OFFSET（1m 可用 7 个）：D1 = 3、D2 = 4、D3 = 0。

MISSINGNESS_IMBALANCE = false

解释：缺失不是按 outcome 差异（两组可用率几乎相同），而是系统性时间窗口
限制——新浪 1m 不提供 7/23 之前的历史；未自行补样本。

## 6. EXACT EVENT VALIDATION

- canonical daily high >= s1_price：146/146 成立（cohort 定义自洽）。
- 可用 7 个事件日：分钟 1m high 均 >= s1；分钟 close 与 canonical daily close
  差异 <= 0.5%。
- DAILY_INTRADAY_MISMATCH_N = 0；无 mismatch case。

## 7. 5m FALLBACK EVIDENCE（不作为 1m gate）

- 5m 数据覆盖事件日：146/146 有 session 数据。
- 完整 session（5m 口径）：139/146（SUCCESS 40、FAILED_BREAKOUT 99）。
- 7 个不完整事件全部为 2026-06-05（新浪 5m 窗口当日仅 2 根 bar）。
- 若未来 V02A 允许 5m fallback，结构上 SUCCESS 40 / FAILED 99 均 >= 20；
  该决策留待人工，本轮不计入 1m gate。

## 8. READY GATE

SUCCESS_READY_0945/1000/1030/1130 = 2
FAILED_READY_0945/1000/1030/1130 = 5

COMMON_SUCCESS_N = 2（< 20）
COMMON_FAILED_BREAKOUT_N = 5（< 20）

MINUTE_DATA_VERIFIED = false
READY_FOR_INTRADAY_V02A = false

## 9. 结论

- 新浪 1m 无法覆盖 V02A cohort 主体（146 事件中仅 7 个可用），且两组均远低于
  20；数据 gate 未通过。
- 缺失为时间性系统缺失而非 outcome 偏差（MISSINGNESS_IMBALANCE=false）。
- 5m fallback 可覆盖 139/146（SUCCESS 40 / FAILED 99），已缓存并记录；
  是否切换 granularity 由人工决定。

NEXT = 未登记 INTRADAY_SUCCESS_PATTERN_V02A（ready=false）
可选下一步（人工决策）：VERIFY_V02A_5M_FALLBACK 或补充其他 1m 历史源

NO_PRODUCTION_CHANGE = true
NO_THRESHOLD_SCAN = true
