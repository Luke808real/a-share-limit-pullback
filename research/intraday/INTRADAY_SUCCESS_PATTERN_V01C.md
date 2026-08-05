# INTRADAY SUCCESS PATTERN V01C — FINAL METRIC CORRECTNESS FIX

RUN_ID: INTRADAY_SUCCESS_PATTERN_V01C
SCRIPT: research/intraday_success_pattern_v01c.py
OUTPUT: research/intraday/metrics_v01c.csv
RAW_MINUTE: data/tmp/intraday-success-pattern-v01/minute_*.parquet（同 V01-V01B，未新增样本）
DATA_DATE: 2026-08-04（1m，AKSHARE/SINA）

## V01B_REMAINING_BUGS

1. VWAP transition 计数：V01B 用 shift(1)+fillna(False) 作为 after-anchor 第一根 bar 的前一状态，导致“锚点后始终在 VWAP 上方”时第一根 bar 被误计为一次 BELOW→ABOVE。验证案例 601858：V01B 输出 VWAP_RECLAIM_COUNT=1，正确应为 0。
2. POST_LOW_VWAP 状态：V01B 直接找“low 后第一个 close>=VWAP”，未先确认 low 后存在 close<VWAP，也没有用状态机验证真实 BELOW→ABOVE transition；且用 tt>575 过滤，漏掉 09:34-09:35 的早盘跌破（600468 被误标为 N/A/未跌破，实际 09:36 有一次真实收复）。
3. PREV_CLOSE_ACCEPTANCE：V01B 只有 reclaim time + final close，并在报告里写了“8/3 11:07 收复 prev close 并保持到收盘”——1m 数据证实 11:07 只是一分钟触及，11:08 立即跌破，13:25 才第二次收复，13:28 再次回踩，13:29 第三次收复后保持。
4. AFTERNOON_RETURN 被口头当作 expansion 证据；本轮改名为 PM_RETURN，只表示午后收益，不新造 expansion threshold。

## V01C_FIXES

1. VWAP transition 状态机从锚点真实状态起步（anchor close >= VWAP）：VWAP_RECLAIM_COUNT = BELOW→ABOVE，VWAP_REBREAK_COUNT = ABOVE→BELOW；锚点后持续在上方时两计数均为 0。验证：601858 = 0 / 0。
2. POST_LOW_VWAP 状态分类：先检查 low 后是否真实存在 close<VWAP → POST_LOW_VWAP_NEVER_LOST 或 POST_LOW_VWAP_LOST_THEN_RECLAIMED / LOST_NOT_RECLAIMED；只有真实 BELOW→ABOVE 才给出 POST_LOW_VWAP_RECLAIM_TIME。
3. 新增 PREV_CLOSE_ACCEPTANCE 全套：FIRST_PREV_CLOSE_RECLAIM_TIME、PREV_CLOSE_REBREAK_COUNT、SECOND_PREV_CLOSE_RECLAIM_TIME、严格 15/30 bar 窗口（BARS/PCT）、PREV_CLOSE_HOLD_15M/30M、FINAL_CLOSE_ABOVE_PREV_CLOSE、TIME_ABOVE_PREV_CLOSE_AFTER_FIRST_RECLAIM_PCT。
4. AFTERNOON_RETURN → PM_RETURN；不定义 expansion threshold。

## PER-EVENT METRICS（V01C）

| symbol | 日期 | LOW | LOW_TO_OPEN | POST_LOW_VWAP_STATE | POST_LOW_VWAP_RECLAIM | VWAP_RECLAIM / REBREAK | PCT_ABOVE_VWAP 15/30 | NEW_LOW_AFTER_POST_LOW | FIRST_PREV_RECLAIM | PREV_REBREAK | SECOND_PREV_RECLAIM | PCT_ABOVE_PREV 15/30 | HOLD 15/30 | TIME_ABOVE_PREV% | PM_RETURN% | CLOSE_LOC |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 600468 | 8/3 | 09:33 | 3 | LOST_THEN_RECLAIMED | 09:36 | 0 / 0 | 100 / 100 | False | 09:34 | 0 | NA | 100 / 100 | T/T | 100.00 | 0.00 | 1.000 |
| 601858 | 8/3 | 09:39 | 2 | LOST_THEN_RECLAIMED | 09:44 | 0 / 0 | 100 / 100 | False | 10:01 | 2 | 10:07 | 66.7 / 80.0 | F/F | 97.12 | +4.02 | 1.000 |
| 600756 | 8/3 | 09:40 | 73 | LOST_THEN_RECLAIMED | 09:49 | 4 / 4 | 20.0 / 60.0 | False | 11:07 | 3 | 13:25 | 0.0 / 0.0 | F/F | 63.38 | +2.79 | 0.883 |
| 600756 | 8/4 | 10:00 | 13 | LOST_THEN_RECLAIMED | 10:03 | 2 / 3 | 46.7 / 73.3 | False | 无 | NA | NA | NA | NA | 0（未收复） | -0.98 | 0.405 |

## 600756_PATH_RECONSTRUCTION（8/3，1m 精确）

prev close = 16.33：

1. FIRST_PREV_CLOSE_RECLAIM = 11:07（close 16.33，high 16.34）——仅一分钟触及。
2. REBREAK = 11:08（close 16.25 < 16.33），此后 11:08-13:24 基本位于 prev close 下方（11:26 回踩 15.95，午后 13:20 低 16.00）。
3. SECOND_PREV_CLOSE_RECLAIM = 13:25（close 16.33）。
4. 再次回踩 = 13:28（close 16.24），第三次收复 = 13:29（close 16.35）。
5. 13:29 后保持在 prev close 上方并午后扩张：13:30-14:00 高 16.75，收盘 16.59（PM_RETURN +2.79%，close_loc 0.883）。

真实路径：FIRST_RECLAIM(11:07) → REBREAK(11:08) → SECOND_RECLAIM(13:25) → 回踩(13:28) → THIRD_RECLAIM(13:29) → AFTERNOON_EXPANSION。
此前 V01A/V01B“11:07 收复并保持到收盘”的表述错误，已修正。

## 600756：8/3 vs 8/4 重新比较

| 指标 | 8/3 | 8/4 |
|---|---|---|
| LOW_TO_OPEN_RECLAIM | 73 min | 13 min |
| POST_LOW_VWAP_STATE | LOST_THEN_RECLAIMED（09:49） | LOST_THEN_RECLAIMED（10:03） |
| VWAP_REBREAK（post-low 后） | 4 | 3 |
| PCT_ABOVE_VWAP 15/30 | 20.0 / 60.0 | 46.7 / 73.3 |
| FIRST_PREV_CLOSE_RECLAIM | 11:07 | 无 |
| PREV_CLOSE_REBREAK | 3 | NA |
| SECOND_PREV_CLOSE_RECLAIM | 13:25 | 无 |
| PCT_ABOVE_PREV 15/30 | 0.0 / 0.0（首次收复未接受） | NA |
| TIME_ABOVE_PREV_CLOSE（首次收复后） | 63.38% | 0% |
| PM_RETURN | +2.79% | -0.98% |
| CLOSE_LOCATION | 0.883 | 0.405 |

重点回答（描述性）：8/3 真正区别于 8/4 的，不是 FIRST_RECLAIM，也不是短窗口 VWAP 接受。

- FIRST_RECLAIM 不是区分变量：8/3 的首次 prev-close 收复（11:07）本身就是失败的（之后 15 根 bar 上方占比 0%，立即 rebreak）；8/4 则从未获得首次收复。8/4 在 open/VWAP 的首次收复上甚至更快。
- 短窗口 VWAP 接受也不是：8/4 的 15/30 分钟上方占比（46.7%/73.3%）高于 8/3（20%/60%）。
- 真正的区分链：SECOND_ACCEPTANCE（8/3 在 13:25 第二次收复 prev close 并在 13:29 第三次确认后保持；8/4 从未收复）+ AFTERNOON_EXPANSION（8/3 PM +2.79% / close_loc 0.883；8/4 PM -0.98% / close_loc 0.405）。
- 若必须排序：RETEST_AFTER_RECLAIM / SECOND_ACCEPTANCE 是分水岭时刻，AFTERNOON_EXPANSION 是确认尾部；FIRST_RECLAIM 与 RECLAIM_SPEED 均不能区分这两日。

## WHAT_WE_LEARNED

1. 首次收复 ≠ 接受：600756 8/3 的 11:07 收复是一分钟触及（后续 15 bar 0% 在上方）。
2. 速度不能预测结果：8/4 的 open/VWAP 首次收复全部更快，最终更弱。
3. 短窗口 VWAP 接受（15/30 min）也不是区分变量。
4. prev close 的二次接受（rebreak 次数、第二次/第三次收复、收复后上方时间占比）与 PM_RETURN / CLOSE_LOCATION 是这两个观察日中最像的区分特征。
5. transition 计数必须从锚点真实状态起步；锚点后持续在上方时 VWAP_RECLAIM_COUNT=0 / VWAP_REBREAK_COUNT=0（601858 验证通过）。

## WHAT_IS_STILL_UNKNOWN

- 上述特征是否在 SUCCESS vs CONTROL 上真正区分（无对照组，SUCCESS n=2）。
- SECOND_ACCEPTANCE / AFTERNOON_EXPANSION 是“当日结果描述”还是“盘中可提前识别的预测特征”（13:25 第二次收复时能否执行，未验证）。
- PM_RETURN 与“扩张”的完整关系（price expansion / high progression / volume expansion）未建立；本轮按指示不新增 threshold。
- 600468（快速封板）与 601858（爬升封板）代表的其他成功路径与 600756 路径的关系未知。

## CONCLUSION

RESULT = DATA_INSUFFICIENT
RESEARCH_STATUS = METRIC_CORRECTNESS_FINAL
NO_NEW_SAMPLE = true
NO_THRESHOLD_SCAN = true
NO_PRODUCTION_CHANGE = true

V01 系列指标修正到此结束，不再继续修改 V01 指标。
