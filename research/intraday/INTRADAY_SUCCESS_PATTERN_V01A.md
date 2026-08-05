# INTRADAY SUCCESS PATTERN V01A — METRIC SEMANTIC FIX

RUN_ID: INTRADAY_SUCCESS_PATTERN_V01A
SCRIPT: research/intraday_success_pattern_v01a.py
OUTPUT: research/intraday/metrics_v01a.csv
RAW_MINUTE: data/tmp/intraday-success-pattern-v01/minute_*.parquet（与 V01 相同，未新增样本）
DATA_DATE: 2026-08-04（1m，AKSHARE/SINA）

## OLD_METRIC → NEW_METRIC

| OLD_METRIC | NEW_METRIC | WHY_CHANGED | IMPACT_ON_PREVIOUS_INTERPRETATION |
|---|---|---|---|
| minutes_to_recover_open | minutes_from_open_to_reclaim_open（保留原名语义，重命名） | 原名实为 reclaim_timestamp - 09:30，是时钟时间不是恢复时长 | 8/4 该值 43 分钟，容易误读为“恢复很慢” |
| minutes_to_recover_prev_close | minutes_from_open_to_reclaim_prev_close（重命名） | 同上 | 8/3 该值 97 分钟是时钟时间 |
| （无） | minutes_from_low_to_reclaim_open / minutes_from_low_to_reclaim_prev_close | 真正的 recovery duration = first reclaim after relevant low − relevant low 时间 | 8/4 从日内低点到收复 open 实际 13 分钟（非 43）；8/3 为 73 分钟 |
| minutes_to_reclaim_vwap | minutes_from_open_to_reclaim_vwap（重命名）+ first_vwap_reclaim_after_low / minutes_low_to_vwap_reclaim | VWAP 收复同样区分时钟时间与低点后恢复时长 | 8/3 VWAP 收复从低点起 9 分钟；8/4 从低点起 3 分钟但随后反复跌破 |
| VWAP_RECLAIM（close-weighted 代理，未标明） | VWAP_AMOUNT_BASED（cumulative amount / volume）+ VWAP_PROXY 仅作回退并显式标注 | 分钟源存在 amount 且单位有效，可计算真实累计 VWAP | time_below_vwap 变化：600756 8/3 11.76%→16.81%；8/4 59.66%→54.20%；601858 5.04%→4.62%；600468 1.68%→2.10% |
| （无） | vwap_rebreak_count_after_reclaim / pct_above_vwap_next_15m / pct_above_vwap_next_30m / hold_above_vwap_15m / hold_above_vwap_30m | 记录收复后是否真正站稳 | 8/3 与 8/4 在“是否收复 VWAP”上同为 True，但站稳质量差异巨大（见下） |
| （无） | reclaim_open_then_break_again / minutes_above_open_next_15m / minutes_above_open_next_30m / new_low_after_open_reclaim / new_low_after_vwap_reclaim / low_retest_depth_pct | 恢复后是否守住，是否再创新低 | 8/4 收复 open 后 15 分钟内 13/15 bar 在 open 上方，但仍收不回 prev close、午后转弱 |
| OPENING_SHAKEOUT（EOD close >= open 参与定义） | OPENING_DRAWDOWN_EVENT（PIT，仅用当时数据） + MORNING_RECLAIM_EVENT（截至 11:30） + EOD_SHAKEOUT_CONFIRMED（盘后标签） | 旧定义混入收盘数据，盘中不可用 | 8/4：OPENING_DRAWDOWN_EVENT=True、MORNING_RECLAIM_EVENT=True、EOD_SHAKEOUT_CONFIRMED=False——日内确实收复过 open，但收盘未确认；旧单一标签无法表达 |

说明：low_retest_depth_pct = 收复后最低价 / 收复前最低价 − 1（0/正 = 未创新低；负 = 创新低）。VWAP 为累计 amount / 累计 volume；本 4 事件均满足 amount 可用，无 VWAP_PROXY 事件。

## PER-EVENT METRICS（V01A）

| symbol | 日期 | 低点时间 | 收复 open（时钟/低点后） | 收复 prevC（时钟/低点后） | VWAP 首收（低点后） | VWAP rebreak | VWAP 上方占比 15m/30m | 收复 open 后再跌破 | below VWAP% | close_loc | 午后% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 600468 | 8/3 | 09:33 | 09:36 / 3 min | 09:34 / 1 min | N/A（未跌破 VWAP） | N/A | N/A | False | 2.10 | 1.00 | 0.00 |
| 601858 | 8/3 | 09:39 | 09:41 / 2 min | 10:01 / 22 min | 09:44 / 5 min | 0 | 100 / 100 | False | 4.62 | 1.00 | +4.02 |
| 600756 | 8/3 | 09:40 | 10:53 / 73 min | 11:07 / 87 min | 09:49 / 9 min | 4 | 25.0 / 61.3 | True（10:53 后再次跌破 open） | 16.81 | 0.88 | +2.79 |
| 600756 | 8/4 | 10:00 | 10:13 / 13 min | 未收复 | 10:03 / 3 min | 5 | 31.3 / 19.4 | True | 54.20 | 0.41 | -0.98 |

事件语义：

- OPENING_DRAWDOWN_EVENT：600468=False、601858=False、600756 两日=True。
- MORNING_RECLAIM_EVENT：600756 两日=True（均于午前收复 open）。
- EOD_SHAKEOUT_CONFIRMED：仅 600756 8/3=True；8/4=False（收盘低于 open）。
- 600468 / 601858 无 OPENING_DRAWDOWN_EVENT，无 SHAKEOUT 语义。

## 600756：8/3 vs 8/4 重点对照

### A. 从真正日内低点到重新收复 open 的分钟数

- 8/3：09:40 低 15.38 → 10:53 收复 open，73 分钟。
- 8/4：10:00 低 15.86 → 10:13 收复 open，13 分钟。

按旧字段（clock from open）分别是 83 与 43 分钟；按低点后的真正恢复时长，8/4 明显更快。

### B. 为什么 8/4 第一次恢复更快，最终却明显更弱

- 8/4 收复 open 只用了 13 分钟，但从未收复 prev close（16.59）；8/3 用了 73 分钟收复 open、87 分钟收复 prev close。
- 8/4 首次 VWAP 收复（10:03）后 rebreak 5 次，之后 30 分钟只有 19.4% 时间在 VWAP 上方；8/3 首次 VWAP 收复（09:49）后 rebreak 4 次，但之后 30 分钟有 61.3% 时间在上方，且午后继续扩张（+2.79%）并收复 prev close。
- 8/4 全天 54.2% 时间位于 VWAP 下方，收盘低于 open、close_loc 0.41、午后 -0.98%；8/3 全天仅 16.8% 时间在 VWAP 下方，收盘 close_loc 0.88。
- 8/4 收复 open 后 30 分钟内 28/30 bar 在 open 上方（表面接受不差），但结构性接受（prev close + VWAP + 午后方向）全部偏弱。

### C. 区别更接近什么

描述性判断：更接近 RECLAIM_ACCEPTANCE / VWAP_ACCEPTANCE / AFTERNOON_EXPANSION，而不是 RECLAIM_SPEED。

- 8/4 的 RECLAIM_SPEED 更快，结果更弱 → 速度不是区分变量。
- 区分特征：是否收复 prev close、VWAP 收复后 rebreak 次数与上方停留占比、是否创新低（8/4 new_low_after_vwap_reclaim=True）、午后是否扩张。

## CONCLUSION

- 未新增样本、未改案例标签、未启动 V02。
- RESULT 保持 V01 的 DATA_INSUFFICIENT（n=2 成功、无 CONTROL），V01A 只修指标语义。
- 原 V01 中“8/3 FAST_RECLAIM=False（83>60）”基于时钟时间；按低点后时长（73 分钟）结论不变，但数值含义已修正。
- 原 V01 中“8/4 不是 SHAKEOUT”受 EOD close >= open 污染；V01A 显示 8/4 存在 PIT 的 OPENING_DRAWDOWN_EVENT 与 MORNING_RECLAIM_EVENT，只是 EOD 未确认——盘中信号与盘后结论必须分离。

RESEARCH_STATUS = METRIC_FIX_ONLY
PRODUCTION_CHANGE = false
NEW_SAMPLE = false
THRESHOLD_SCAN = false

## LIMITATIONS

- 仅 4 个事件日，SUCCESS n=2；一切均为描述性。
- VWAP 使用分钟 amount / volume，单位未与交易所逐笔核对，但与价格交叉验证一致（amount/volume ≈ close）。
- hold_above_vwap_* 要求窗口内 bar 全部在上方；窗口含两端 bar（15 分钟窗口最多 16 条）。
- EOD_SHAKEOUT_CONFIRMED 为盘后标签，禁止作为盘中可执行信号。
