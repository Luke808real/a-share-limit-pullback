# INTRADAY SUCCESS PATTERN V01B — METRIC IMPLEMENTATION FIX

RUN_ID: INTRADAY_SUCCESS_PATTERN_V01B
SCRIPT: research/intraday_success_pattern_v01b.py
OUTPUT: research/intraday/metrics_v01b.csv
RAW_MINUTE: data/tmp/intraday-success-pattern-v01/minute_*.parquet（同 V01/V01A，未新增样本）
DATA_DATE: 2026-08-04（1m，AKSHARE/SINA）

## V01A_BUG → V01B_FIX → IMPACT_ON_CONCLUSION

| V01A_BUG | V01B_FIX | IMPACT_ON_CONCLUSION |
|---|---|---|
| VWAP 接受度字段（pct_above/hold/new_low/rebreak）锚定 SESSION_FIRST_VWAP_RECLAIM（旧 rec_vwap） | 全部锚定 POST_LOW_VWAP_RECLAIM（= rec_vwap_after_low），SESSION_FIRST 与 POST_LOW 分开输出 | 600756 8/4 的 PCT_ABOVE_VWAP_NEXT_30M 由 19.35%（锚 09:39，位于日内低点 10:00 之前）修正为 73.33%（锚 10:03）。V01A 的“8/4 VWAP 短期接受差”是锚点错误造成的假象 |
| VWAP_REBREAK_COUNT_AFTER_RECLAIM 实际统计 below→above（这是 reclaim 次数） | VWAP_REBREAK = 前一根 close>=VWAP 且当前 close<VWAP（ABOVE→BELOW）；另输出 VWAP_RECLAIM_COUNT（BELOW→ABOVE），禁止混名 | 600756 8/3：V01A“rebreak 4”实为 reclaim 4，真 rebreak=3；8/4：V01A“rebreak 5”实为 reclaim 5，post-low 锚下 reclaim=2、真 rebreak=2 |
| next-15m/30m 窗口为时间窗（reclaim_tt+15/30 分钟，含锚点当根），且 open 侧用分钟计数 | next_15m = 锚点后严格 15 根 1m bar（不含锚点）；next_30m 同理；输出 bars_above 与 pct | 数值微调：600756 8/3 VWAP next15/30 25%/61.29% → 20%/60%；open 接受 14/27 → 13/26（86.7% 不变） |
| NEW_LOW_AFTER_VWAP_RECLAIM 用 session-first 锚 | NEW_LOW_AFTER_POST_LOW_RECLAIM 用 post-low 锚 | 600756 8/4 由 True 改为 False：V01A 的 True 只是把 10:00 日内低点计在 09:39 旧锚之后，不是“收复后再创新低”；post-low 锚（10:03）后未创新低 |

## PER-EVENT METRICS（V01B）

| symbol | 日期 | LOW_TIME | LOW_TO_OPEN_RECLAIM_MIN | POST_LOW_VWAP_RECLAIM_TIME | LOW_TO_POST_LOW_VWAP_RECLAIM_MIN | VWAP_RECLAIM_COUNT | VWAP_REBREAK_COUNT | BARS_ABOVE_VWAP_N15 | PCT_N15 | BARS_ABOVE_VWAP_N30 | PCT_N30 | NEW_LOW_AFTER_POST_LOW | PREV_CLOSE_RECLAIM | AFTERNOON_RETURN% | CLOSE_LOCATION |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 600468 | 8/3 | 09:33 | 3 | N/A（未跌破 VWAP） | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | True（09:34） | 0.00 | 1.000 |
| 601858 | 8/3 | 09:39 | 2 | 09:44 | 5 | 1 | 0 | 15/15 | 100 | 30/30 | 100 | False | True（10:01） | +4.02 | 1.000 |
| 600756 | 8/3 | 09:40 | 73 | 09:49 | 9 | 4 | 3 | 3/15 | 20.0 | 18/30 | 60.0 | False | True（11:07） | +2.79 | 0.883 |
| 600756 | 8/4 | 10:00 | 13 | 10:03 | 3 | 2 | 2 | 7/15 | 46.7 | 22/30 | 73.3 | False | False（全天未收复） | -0.98 | 0.405 |

补充：600756 8/3 OPEN_RECLAIM_THEN_BREAK_AGAIN=True、OPEN 后 15/30 bar 上方 86.7%/86.7%；8/4 同样 True、80%/90%。两日短期 open 接受接近，8/4 反而略高。TIME_BELOW_VWAP_PCT 全日：8/3=16.81%，8/4=54.20%。

## 600756：8/3 vs 8/4 重点比较

| 指标 | 8/3 | 8/4 |
|---|---|---|
| LOW_TIME | 09:40 | 10:00 |
| LOW_TO_OPEN_RECLAIM_MIN | 73 | 13 |
| POST_LOW_VWAP_RECLAIM_TIME | 09:49（低点后 9 min） | 10:03（低点后 3 min） |
| VWAP_REBREAK_COUNT（post-low 后） | 3 | 2 |
| VWAP_ABOVE_NEXT_15M / 30M | 20.0% / 60.0% | 46.7% / 73.3% |
| NEW_LOW_AFTER_POST_LOW_RECLAIM | False | False |
| PREV_CLOSE_RECLAIM | True（11:07） | False |
| AFTERNOON_RETURN | +2.79% | -0.98% |
| CLOSE_LOCATION | 0.883 | 0.405 |
| TIME_BELOW_VWAP（全日） | 16.81% | 54.20% |

## 重新回答：为什么 8/4 从低点恢复 open 更快，最终却更弱？

在修正锚点后，答案比 V01A 更清晰：

1. RECLAIM_SPEED：8/4 全面更快（open 13 vs 73 min；VWAP 3 vs 9 min）。速度本身不能解释弱势，反而是 8/4 占优。
2. POST_RECLAIM_ACCEPTANCE（15/30 分钟窗口）：8/4 也不弱——post-low VWAP 收复后 15/30 分钟上方占比 46.7%/73.3%，高于 8/3 的 20%/60%；open 收复后 80%/90% 与 8/3 的 86.7%/86.7% 相当。短期“站住”指标并不区分两日。
3. PREV_CLOSE_ACCEPTANCE：真正的第一个分水岭。8/3 在 11:07 收复 prev close 并保持到收盘；8/4 全天从未收复 prev close（16.59）。
4. AFTERNOON_EXPANSION：第二个分水岭。8/3 午后 +2.79% 放量扩张；8/4 午后 -0.98% 缩量走弱。
5. 全日 VWAP 接受：8/4 虽有较好的 post-low 短期接受，但全天 54.2% 时间在 VWAP 下方（8/3 仅 16.8%），说明弱势是“累计的、午后持续”的，而不是“收复后 30 分钟内失败”。

结论（描述性，不推广）：8/4 的问题不是“没有快速收复”，也不是“收复后 15-30 分钟站不住”，而是 PREV_CLOSE_ACCEPTANCE 缺失 + AFTERNOON_EXPANSION 缺失 + 全天 VWAP 下方时间过长。区分变量更接近 PREV_CLOSE_ACCEPTANCE / AFTERNOON_EXPANSION，而不是 RECLAIM_SPEED，也不是短窗口 POST_RECLAIM_ACCEPTANCE。

## CONCLUSION

- 未增加样本、未改标签、未调阈值。
- V01B 修正后，V01A 中“8/4 短期 VWAP 接受差（19%）”和“8/4 收复后创新低”两个结论被推翻（均为锚点/方向实现错误）。
- 修正后的描述性结论：短期接受度两日接近甚至 8/4 更好；真正区分的是 prev close 收复、午后方向与全天 VWAP 下方占比。
- 总体 RESULT 仍为 DATA_INSUFFICIENT（SUCCESS n=2、无 CONTROL），本版本只做指标实现修复。

RESEARCH_STATUS = METRIC_FIX_ONLY
NO_NEW_SAMPLE = true
NO_PRODUCTION_CHANGE = true
THRESHOLD_SCAN = false

## LIMITATIONS

- 仍只有 4 个事件日，SUCCESS n=2，全部为描述性。
- VWAP 基于分钟 amount/volume（与价格交叉验证一致），未与交易所逐笔核对。
- 严格窗口要求满 15/30 根 bar，否则 NA；本 4 事件窗口均完整。
- 600468 当日未跌破 VWAP，相关字段为 N/A（非 0）。
