# INTRADAY SUCCESS PATTERN V02A_5M

RUN_ID: INTRADAY_SUCCESS_PATTERN_V02A_5M
SCRIPT: research/intraday_v02a_5m.py
OUTPUT: research/intraday/metrics_v02a_5m.csv、metrics_v02a_5m.json
INPUT: success_control_cases_v01b.csv + v02a_minute_manifest.csv +
  data/tmp/v02a-minute/raw_5m（AKSHARE/SINA 5m，未提交）
DATA_GATE: 5m full-session、OHLC 与 canonical 日线对齐、S1 touch 一致性
CONCLUSION_STATUS: OBSERVE_ONLY（描述性；SUPPORTED != PROMOTED）

HYPOTHESIS: “成功案例常见开盘恐慌下杀 → 快速收回 → 日内逐步走强”

## FINAL COHORT

FINAL_COHORT_SUCCESS_N = 40
FINAL_COHORT_FAILED_N = 99
（139 = 146 − 7 个不完整 5m session，动态读取）

全部事件日为 2026-06-05 ~ 2026-07-30；无 DISCOVERY/VALIDATION 切分可能
（5m 源窗口只覆盖 2026），时间集中度由数据源决定。

## DATA GATE

DATA_GATE_STATUS = PASS

| 字段 | MAX_ABS_DIFF | MEDIAN_ABS_DIFF |
|---|---|---|
| 5M_OPEN_DIFF_PCT | 0.2967% | 0.00% |
| 5M_HIGH_DIFF_PCT | 0.00% | 0.00% |
| 5M_LOW_DIFF_PCT | 0.1833% | 0.00% |
| 5M_CLOSE_DIFF_PCT | 0.0831% | 0.00% |

S1_TOUCH_MISMATCH_N = 0；OHLC_INVALID_N = 0；CHECKPOINT_MISSING_N = 0。

## PR24 METRIC SEMANTIC FIX

1. EVENT_PREV_CLOSE：改为 canonical daily bars 中 OUTCOME_EVENT_DATE 前一交易日
   真实 close；OPEN_GAP / DRAWDOWN_FROM_PREV_CLOSE / CURRENT_RETURN_FROM_PREV_CLOSE /
   PREV_CLOSE_STATE / DIST_TO_PREV_CLOSE 全部改用该值。审计：EVENT_SESSION_OFFSET=1
   的 76 例中 candidate_close 与 EVENT_PREV_CLOSE 全部精确一致（max diff = 0）；
   D2/D3 不再使用 candidate_close 冒充事件日前收。
2. RECLAIM 第一根 bar：VWAP/OPEN lost-state 检测允许 index 0 参与；
   “第一根 below → 第二根 above”现可识别为 reclaim。
3. NEW_LOW_AFTER_OPEN_RECLAIM：改为 PRE_RECLAIM_LOW（reclaim bar 及之前最低）
   vs POST_RECLAIM_LOW（reclaim 后最低）。
4. HIGH/LOW PROGRESSION：严格相邻 checkpoint（10:00 vs 09:45、10:30 vs 10:00、
   11:30 vs 10:30）；09:45 = NA。
5. S1 RETEST 拆分：新增 S1_TOUCH_REJECTED_IMMEDIATELY（首触 bar close<S1）、
   S1_ACCEPTED_CLOSE_OCCURRED（曾 close>=S1）、S1_ACCEPTED_THEN_REBREAK
   （接受后再跌破）；保留 CURRENT S1_STATE。S1_ACCEPTED_THEN_REBREAK 不再混称
   “所有触 S1 后跌回”。

## CHECKPOINT 主要差异（SUCCESS vs FAILED_BREAKOUT）

### 09:45

- 几乎无差异：OPEN_GAP 中位数均为 0（修正事件日前收后 d=-0.28，均值方向 F 略高开）、
  DRAWDOWN_FROM_OPEN（S -0.80% vs F -0.99%，d=0.03）、
  VWAP_STATE（S 60% vs F 70% 在 VWAP 上）、S1_STATE（S 35% vs F 32%）。
- S1_TOUCHED：S 47.5% vs F 58.6%（F 更早更多触 S1，rate diff -0.111）。
- S1_TOUCH_REJECTED_IMMEDIATELY：S 17.5% vs F 28.3%（diff -0.108）。
- 结论：09:45 无法区分两组。

### 10:00

- DIST_TO_VWAP_PCT 开始分化（S +0.82% vs F +0.40%，d=+0.31）。
- S1_STATE（收盘在 S1 上方）：S 42.5% vs F 28.3%（diff +0.142）。
- S1_TOUCHED 仍 F 更高（55% vs 68%，diff -0.127）。
- S1_TOUCH_REJECTED_IMMEDIATELY：S 22.5% vs F 35.3%（diff -0.129）；
  S1_ACCEPTED_THEN_REBREAK：S 12.5% vs F 22.2%（diff -0.097）。

### 10:30

- S1_STATE：S 55% vs F 32%（diff +0.227）；DIST_TO_S1：S +0.52% vs F -1.27%
  （d=+0.27）。
- DIST_TO_VWAP：S +1.35% vs F +0.36%（d=+0.50）。
- CURRENT_RETURN_FROM_OPEN：S +4.49% vs F +2.26%（d=+0.37）。
- S1_REBREAK_AFTER_TOUCH：S 12.5% vs F 29.3%（diff -0.168）。
- S1_REBREAK_COUNT：S 中位 0 vs F 中位 1（d=-0.32）。
- 拆分后：S1_TOUCH_REJECTED_IMMEDIATELY S 25% vs F 40.4%（diff -0.154）；
  S1_ACCEPTED_CLOSE_OCCURRED S 60% vs F 54.5%；S1_ACCEPTED_THEN_REBREAK
  S 12.5% vs F 29.3%。
- HIGH_PROGRESSION（vs 10:00）：S +0.11% vs F 0.0%（d=+0.30）。

### 11:30

- DIST_TO_VWAP：S +1.46% vs F +0.47%（d=+0.59）。
- CURRENT_RETURN_FROM_OPEN：S +5.77% vs F +2.76%（d=+0.50）。
- HIGH_FROM_OPEN：S +6.98% vs F +5.26%（d=+0.45）。
- DIST_TO_S1：S +0.87% vs F -1.36%（d=+0.43）；S1_STATE diff +0.166。
- VWAP_STATE：S 80% vs F 60%（diff +0.204）。
- TIME_OF_MORNING_LOW：F IQR 拉宽至 15 分钟（F 低点可晚至 09:45-09:45+），
  S 固定在 5 分钟；d=-0.28。
- S1_TOUCH_REJECTED_IMMEDIATELY：S 30% vs F 45.5%（diff -0.154）；
  S1_ACCEPTED_CLOSE_OCCURRED：S 70% vs F 61.6%；S1_ACCEPTED_THEN_REBREAK：
  S 25% vs F 36.4%。
- VWAP_FIRST_RECLAIMED（首根 bar 参与）：S 75% vs F 59.6%（diff +0.154）。
- HIGH_PROGRESSION（vs 10:30）：S 更高（d=+0.38）。
- NEW_LOW_AFTER_OPEN_RECLAIM（修正后）：S 5% vs F 11.1%（diff -0.061）。

## A-F 回答

A. OPENING_DRAWDOWN：无稳定区别。两组开盘 30 分钟回撤几乎相同
   （d ≈ 0.02-0.04，S -0.84~-0.88% vs F -0.99~-1.15%），OPEN_GAP 无差异。

B. FAST_RECLAIM：修正后可见区别。允许首根 bar 参与后，VWAP_FIRST_RECLAIMED
   09:45 为 S 27.5% vs F 23.2%，10:30 起拉开（+0.100），11:30 S 75% vs F 59.6%
   （diff +0.154）；OPEN_RECLAIMED_NOW 早盘仍接近，VWAP_SECOND_RECLAIMED 无差异。

C. VWAP acceptance：有清晰描述性区别，且随时间增强（10:00 d=+0.31 →
   10:30 d=+0.50 → 11:30 d=+0.59）。SUCCESS 从 10:00 起持续更大幅度地站在
   VWAP 上方，FAILED 更接近/低于 VWAP。

D. S1 first-break acceptance：有清晰描述性区别。FAILED 触 S1 更多更早
   （所有 checkpoint -0.11~-0.15），但 10:00 起收盘站上 S1 的比例 SUCCESS 更高
   （+0.14/+0.23/+0.17），且 F 触后跌回 S1 下方比例更高（10:30 29% vs 13%）。

E. RETEST / SECOND_ACCEPTANCE vs FIRST_RECLAIM：修正后首次收复（VWAP_FIRST_
   RECLAIMED）10:30 起有可见区别（+0.100/+0.154），二次收复计数仍无区别；
   S1 侧真正的区分拆成两支：首触即被拒绝（S1_TOUCH_REJECTED_IMMEDIATELY，
   09:45 起 -0.11，11:30 -0.15）与接受后再跌破（S1_ACCEPTED_THEN_REBREAK，
   10:00 起 -0.10，10:30 -0.17）。RETEST_QUALITY 仍是主要区分，
   但“触 S1 后跌回”必须按立即拒绝/接受后回落分开报告。

F. HIGH/LOW progression：相邻 checkpoint 口径下，HIGH_PROGRESSION 更清晰
   （10:30 d=+0.30、11:30 d=+0.38），SUCCESS 在每段 checkpoint 间继续刷新
   高点；LOW_PROGRESSION 无明显区别（d≈-0.24@10:00 后趋近 0），
   低点推进两组接近。

## HYPOTHESIS RESULT

RESULT = NOT_SUPPORTED

“开盘恐慌下杀 → 快速收回 → 逐步走强”这一特定路径未获支持：两组的开盘回撤与
早期收复行为几乎相同；成功案例的区分出现在 10:00-10:30 之后的价格位置
（站在 S1/VWAP 上方并保持），而不是更深的洗盘或更快的收复。

## TOP / SECONDARY / NO SIGNAL

TOP_DESCRIPTIVE_SIGNAL = S1_AND_VWAP_HOLD_BY_1030
（10:30-11:30 收盘位于 S1 上方 + 正偏离 VWAP 扩大 + 累计收益更强；
DIST_TO_VWAP d=0.50/0.59，DIST_TO_S1 d=0.27/0.43，S1_STATE rate diff
+0.23/+0.17）

SECONDARY_SIGNAL = HIGH_PROGRESSION_AND_RETEST_QUALITY
（HIGH_PROGRESSION 相邻 checkpoint d=0.30/0.38；S1_TOUCH_REJECTED_IMMEDIATELY
diff -0.15@10:30/11:30；S1_ACCEPTED_THEN_REBREAK diff -0.17@10:30）

NO_SIGNAL_FEATURES =
OPEN_GAP_PCT（修正后中位数均为 0；仅均值方向差异）、DRAWDOWN_FROM_OPEN/
LOW_FROM_OPEN（d<0.05）、
TIME_OF_MORNING_LOW（中位相同）、NEW_LOW_AFTER_OPEN_RECLAIM（0% 两组）、
VWAP_SECOND_RECLAIMED、S1_SECOND_RECLAIMED（计数无差异）、LOW_PROGRESSION。

（NEW_LOW_AFTER_OPEN_RECLAIM 修正后为 5% vs 11.1% @11:30，方向 F 更多，
但绝对差异小，仍列弱信号。）

CONFOUNDED_NOT_COUNTED = CUM_VOLUME（SUCCESS 明显更高，但 outcome 标签本身
包含 volume expansion，且未做候选日 PIT 归一化；不作为独立信号）。

## WHAT_THIS_MEANS_FOR_HUMAN_EXECUTION

仅 HUMAN_HEURISTIC_CANDIDATE（不构成自动 BUY signal，不改 B1/B2/G）：

- 09:45 之前的信息（下杀幅度、早盘收复）不足以区分当天能否站稳 S1。
- 10:00-10:30 起更值得盯的是“首次触 S1 后是否跌回 S1 下方”和“能否持续站在
  VWAP 上方并扩大正偏离”，而不是“今天有没有洗盘”。
- 若 10:30 前已触 S1 却跌回下方（S1_REBREAK），历史方向上更接近失败路径，
  宜等二次确认；若触 S1 后保持上方且距 VWAP 正偏离扩大，是更接近成功路径的
  观察特征。
- 全部为描述性单期观察（2026-06~07，n=40/99），必须 forward 验证后才能
  进入人工 heuristics 正式清单。

## LIMITATIONS

- 5m（非 1m）粒度；checkpoint 为 5m bar 对齐。
- 样本仅 2026-06-05~07-30，无 DISCOVERY/VALIDATION 切分，时间高度集中。
- outcome 标签含 EOD acceptance + volume expansion；早盘价格位置与标签
  天然相关，方向性解读需谨慎（本报告只做描述）。
- CUM_VOLUME 与标签定义混淆，未计为信号。
- standardized difference 为描述性效应量（|d|≥0.3 视为“可见差异”的固定
  报告参考，非优化阈值）。

NO_PRODUCTION_CHANGE = true
NO_THRESHOLD_SCAN = true
NO_OUTCOME_REDEFINITION = true

## OLD_RESULT vs CORRECTED_RESULT

| 项目 | OLD_RESULT | CORRECTED_RESULT | CHANGED |
|---|---|---|---|
| HYPOTHESIS | NOT_SUPPORTED | NOT_SUPPORTED（OPENING_DRAWDOWN 仍无差异 d≈0.03） | 不变 |
| TOP_SIGNAL | S1_AND_VWAP_HOLD_BY_1030 | 不变（DIST_TO_VWAP d=0.50/0.59、S1_STATE diff +0.23/+0.17） | 不变 |
| B FAST_RECLAIM | 无强区别 | VWAP_FIRST_RECLAIMED 10:30/11:30 可见（+0.100/+0.154）；首根 bar 参与后成立 | CHANGED |
| F HIGH_PROGRESSION | HIGH_FROM_OPEN d=0.45 | 相邻 checkpoint HIGH_PROGRESSION d=0.30/0.38 | CHANGED（口径 + 更清晰） |
| PREV_CLOSE 相关 | 使用 candidate_close | 使用事件日前收；D1 76 例完全一致，D2/D3 修正；CURRENT_RETURN_FROM_PREV_CLOSE @11:30 d 0.42→0.28，OPEN_GAP 中位数 1.12/1.70→0/0 | CHANGED（数值与叙述） |
| S1 RETEST | “触 S1 后跌回”单一字段 | 拆为 S1_TOUCH_REJECTED_IMMEDIATELY / S1_ACCEPTED_CLOSE_OCCURRED / S1_ACCEPTED_THEN_REBREAK | CHANGED（语义拆分） |
| NEW_LOW_AFTER_OPEN_RECLAIM | 0% / 0% | 5% vs 11.1% @11:30（F 更多，弱） | CHANGED（口径修正） |

WHICH_CONCLUSIONS_CHANGED：
FAST_RECLAIM（由“无区别”改为“10:30 后 VWAP 首次收复率有可见区别”）；
HIGH_PROGRESSION（改为相邻 checkpoint 口径后成为更清晰次级信号）；
PREV_CLOSE 相对指标（D2/D3 数值修正，OPEN_GAP 中位数归零，prev-close 收益差减弱）；
S1 retest 结论拆分为“首触即拒”与“接受后回落”两支；
NEW_LOW_AFTER_OPEN_RECLAIM 由全 0 变为非零弱差异。

未改变结论：HYPOTHESIS=NOT_SUPPORTED、TOP_SIGNAL=S1_AND_VWAP_HOLD_BY_1030、
OPENING_DRAWDOWN 无差异、SECOND_RECLAIM 计数无差异、VWAP_ACCEPTANCE 方向。
