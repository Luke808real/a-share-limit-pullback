# INTRADAY SUCCESS PATTERN V01

HYPOTHESIS:
“成功的二次启动案例是否常见：开盘先下杀/恐慌释放 → 快速收回 → 日内逐步走强”

RUN_ID: INTRADAY_SUCCESS_PATTERN_V01
SCRIPT: research/intraday_success_pattern_v01.py
OUTPUT: research/intraday/metrics.csv
RAW_MINUTE: data/tmp/intraday-success-pattern-v01/minute_*.parquet
DATA_DATE: 2026-08-04（1m 行情，AKSHARE/SINA）

## 1. CASE SET / LABEL_SOURCE

只使用知识库已有标签，未重新定义成功/失败。

| symbol | name | group | event_date | event_role | label_source |
|---|---|---|---|---|---|
| 600468 | 百利电气 | SUCCESS | 2026-08-03 | SECOND_LAUNCH_DAY（涨停 6.22 突破前高 6.18） | KB 02_Cases/Success/600468-2026-08-03.md（STRUCTURE_SUCCESS / SECOND_LAUNCH_SUCCESS） |
| 601858 | 中国科传 | SUCCESS | 2026-08-03 | SECOND_LAUNCH_DAY（涨停 21.76） | KB 04_Research/Human-Review-Heuristics-2026-08-03.md（SECOND_LAUNCH_SUCCESS / STRONG_CLOSE_CONFIRMATION；标签观察日即 8/3） |
| 600756 | 浪潮软件 | OBSERVATION | 2026-08-03 | OBSERVATION_FAST_RECLAIM | 人工交易记录 + FAST_RECLAIM observation；非模型 success ground truth |
| 600756 | 浪潮软件 | OBSERVATION | 2026-08-04 | OBSERVATION_HOLD_DAY | 人工持仓日（1200@15.494） |

CONTROL_CASES = NONE_FOUND。

- 知识库 `02_Cases/Failure/` 为空（仅 .gitkeep）；没有 FAILED / NO_LAUNCH / REJECT
  命名案例文件。
- 禁止为凑样本把未标记股票重新定义为失败 → CONTROL 组不可用，
  SUCCESS vs CONTROL 统计比较无法进行。

EXCLUDED_CASES：

- 002606 大连电瓷：MANUAL_REVIEW（README 明确仓库内无完整时间轴，不补造事实）。
- 603980 吉华集团：PENDING / OBSERVATION，未纳入 SUCCESS。
- 600756：HUMAN_EXECUTION_SUCCESS / OBSERVATION，不因交易盈利自动当模型 success。
- 002640 / 002891 / 600199：知识库 observed success，但无显式
  STRUCTURE_SUCCESS / SECOND_LAUNCH_SUCCESS 标签，不纳入 SUCCESS 组。

## 2. INTRADAY DATA

- 数据源：AKSHARE/SINA `stock_zh_a_minute`（1m，不复权）。
- INTRADAY_DATA_GRANULARITY = 1m（全部 4 个事件日可用）。
- DATA_COMPLETENESS：每事件日 238 条 1m bar（全天约 238-240 条），无缺失日。
- 所有案例均参与 intraday 统计；无 DATA_LIMITED 案例。

## 3. INTRADAY PATH METRICS

| symbol | 8/3 or 8/4 | open_gap% | 30m ret% | 30m DD vs open% | day low | recov open(min) | recov prevC(min) | recov VWAP(min) | below VWAP% | low→close% | close_loc | 午后% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 600468 | 8/3 | +1.95 | +7.99 | -0.87 | 09:33 | 6 | 4 | N/A（未跌破 VWAP） | 1.68 | +8.93 | 1.00 | 0.00 |
| 601858 | 8/3 | -2.98 | +2.29 | -0.52 | 09:39 | 11 | 31 | 14 | 5.04 | +13.99 | 1.00 | +4.02 |
| 600756 | 8/3 | -1.41 | -2.67 | -4.47 | 09:40 | 83 | 97 | 14 | 11.76 | +7.87 | 0.88 | +2.79 |
| 600756 | 8/4 | -1.45 | -1.77 | -3.00 | 10:00 | 43 | 未收复 | 10 | 59.66 | +2.02 | 0.41 | -0.98 |

描述性标签定义（固定，未扫描阈值）：

- OPENING_SHAKEOUT = 开盘 30 分钟回撤 ≤ -1.0% 且收盘回到开盘价上方且低点后重新收复 open。
- FAST_RECLAIM = OPENING_SHAKEOUT 且收复 open ≤ 60 分钟。
- VWAP_RECLAIM = 曾跌破 VWAP 后重新站回（N/A 表示从未跌破）。
- EARLY_LOW = 日内最低点在 10:30 前。

## 4. PATH CLASSIFICATION

| 事件 | OPENING_SHAKEOUT | FAST_RECLAIM | EARLY_LOW | VWAP_RECLAIM | 分类 |
|---|---|---|---|---|---|
| 600468 8/3 | False | False | True | N/A | B SHALLOW_PULLBACK_TREND_UP（09:47 前封板，首30分钟量占91.5%） |
| 601858 8/3 | False | False | True | True | B SHALLOW_PULLBACK_TREND_UP（低开小回撤→全天爬升→午后扩张封板） |
| 600756 8/3 | True | False（83min） | True | True | E OTHER（开盘下杀→午前收复 open/prevC→午后扩张；收复速度中等） |
| 600756 8/4 | False（收盘未回 open） | False | True（10:00） | True（但全天 59.7% 在 VWAP 下） | E OTHER（开盘下杀→部分修复→弱收盘） |

在现有 4 个事件日中，A 类（OPENING_SHAKEOUT_FAST_RECLAIM）出现 0 次。

## 5. SUCCESS vs CONTROL

无法进行：CONTROL_CASES = NONE_FOUND（知识库无 FAILED/NO_LAUNCH 案例文件；
禁止重新定义成功失败凑样本）。以下仅为 SUCCESS 组（n=2）的描述性观察，
不具备统计意义。

对 4 个关键问题的回答：

1. 成功案例是否更容易“先杀后拉”？—— 现有 2 个成功案例均不是“先杀后拉”：
   600468 为高开快速封板；601858 为低开浅回撤后全天爬升。样本内未观察到
   OPENING_SHAKEOUT + FAST_RECLAIM 的成功路径。
2. 还是多种路径、只是印象更深？—— 描述性支持“成功路径不唯一”（封板型 vs
   爬升型），但 n=2 无法回答该问题。
3. 真正区分的是下杀本身还是恢复速度？—— 无 CONTROL 组无法判定；600756 两日
   对照（8/3 下杀 4.5% 后收复并收强 vs 8/4 下杀 3% 后收不回 open、59.7% 时间在
   VWAP 下方）方向性指向“恢复质量”而非“下杀幅度”，仅为观察。
4. 失败案例是否也早盘急跌但收不回？—— 无 FAILED 案例数据，无法验证；
   该问题登记为 FUTURE_RESEARCH_NOTE。

## 6. 特别复盘 600756（1m 路径）

### 8/3（O16.10 L15.38 H16.75 C16.59，+1.59%）

| 时段 | O | H | L | C | 量 |
|---|---|---|---|---|---|
| 09:30-10:00 | 16.10 | 16.22 | 15.38 | 15.72 | 1732万 |
| 10:00-10:30 | 15.72 | 15.96 | 15.62 | 15.92 | 420万 |
| 10:30-11:00 | 15.92 | 16.27 | 15.64 | 16.16 | 481万 |
| 11:00-11:30 | 16.16 | 16.43 | 15.95 | 16.10 | 394万 |
| 13:00-13:30 | 16.13 | 16.42 | 16.00 | 16.35 | 229万 |
| 13:30-14:00 | 16.34 | 16.75 | 16.24 | 16.60 | 591万 |
| 14:00-14:30 | 16.61 | 16.61 | 16.35 | 16.55 | 274万 |
| 14:30-15:00 | 16.55 | 16.59 | 16.43 | 16.59 | 545万 |

1m 事实：09:40 见低 15.38（-4.47% vs open）→ 10:53 收复 open（83 分钟）→
11:07 收复 prev close（97 分钟）→ 09:54 已先站回 VWAP → 午后 13:30-14:00
放量扩张至 16.75，收 16.59。结论：属于“开盘下杀 + 中等速度收复 +
午后扩张”，不是 FAST_RECLAIM（60 分钟参考）；日K 观感“快速收回”高于
1m 实际恢复速度。

### 8/4（O16.35 L15.86 H16.65 C16.18，-2.47%）

| 时段 | O | H | L | C | 量 |
|---|---|---|---|---|---|
| 09:30-10:00 | 16.35 | 16.65 | 15.94 | 15.96 | 1346万 |
| 10:00-10:30 | 15.96 | 16.60 | 15.86 | 16.42 | 727万 |
| 10:30-11:00 | 16.42 | 16.58 | 16.29 | 16.43 | 287万 |
| 11:00-11:30 | 16.42 | 16.45 | 16.33 | 16.34 | 133万 |
| 13:00-13:30 | 16.34 | 16.42 | 16.14 | 16.27 | 274万 |
| 13:30-14:00 | 16.27 | 16.27 | 16.11 | 16.20 | 328万 |
| 14:00-14:30 | 16.20 | 16.28 | 16.10 | 16.18 | 295万 |
| 14:30-15:00 | 16.17 | 16.18 | 16.11 | 16.15 | 505万 |

1m 事实：10:00 见低 15.86 → 10:43 收复 open（43 分钟）→ 全天未收复 prev close
16.59 → 全天 59.7% 时间在 session VWAP 下方 → 收盘 16.18 低于 open、
close_loc 0.41、尾盘走弱。结论：15.86 下杀后只是“低点守住 + 部分修复”，
不是真正 FAST_RECLAIM；日K 看起来像收回，1m 显示全天弱于 VWAP。

## 7. HUMAN EXECUTION HEURISTIC

仅保留数据支持的描述性内容：

- GOOD_SHAKEOUT_CANDIDATE：当前数据不足以建立。成功案例（n=2）未出现
  OPENING_SHAKEOUT + FAST_RECLAIM；600756 8/3 具备“下杀 + 收复 + 午后扩张”，
  但收复速度中等（83/97 分钟）。保留为未来假设，不进入操作语义。
- BAD_WEAKNESS（600756 8/4 型，描述性）：开盘下杀后收不回 prev close、
  大部分时间位于 session VWAP 下方、收盘低于 open/close_loc<0.5 →
  与“日K 看似收回”形成对照，是 FAST_RECLAIM 语义的重要反例。
- 恢复质量字段（minutes_to_recover_open / minutes_to_recover_prev_close /
  time_below_vwap_pct / close_location）已可计算，纳入 INTRADAY_RECOVERY_QUALITY
  未来研究字段集，本轮不执行。

## 8. CONCLUSION

RESULT = DATA_INSUFFICIENT

- SUCCESS 组 n=2，CONTROL 组无可用案例 → “成功案例常见开盘下杀后逐步拉升”
  既未证实也未证伪。
- 描述性发现：两个成功案例的日内路径都不是“先杀后拉”；均以浅回撤/爬升或
  快速封板收场，收盘 close_loc = 1.00。
- 600756 两日对照方向性提示：恢复质量（能否收复 open/prev close、VWAP 下方
  时间占比）比“是否出现下杀”更值得研究，但样本不足，不作结论。

WHAT_MATTERS_MORE = NO_CLEAR_EDGE

（方向性候选：RECOVERY_SPEED / VWAP_ACCEPTANCE，未验证，不提升。）

CONCLUSION_STATUS = OBSERVE_ONLY（research-cycle 口径；SUPPORTED != PROMOTED）

NO_PRODUCTION_CHANGE = true

## LIMITATIONS

- 成功样本仅 2 个，且均为 2026-08-03 当日事件，日期高度集中。
- CONTROL 组缺失（知识库无 FAILED/NO_LAUNCH 案例文件）。
- 1m 数据来自新浪，未与第二来源交叉核对（Eastmoney 代理不可用）。
- OPENING_SHAKEOUT / FAST_RECLAIM 使用固定描述性参考（-1.0% / 60 分钟），
  非优化阈值；VWAP 为 close-weighted 累计代理。
- 禁止据此建立自动买点或修改生产。
