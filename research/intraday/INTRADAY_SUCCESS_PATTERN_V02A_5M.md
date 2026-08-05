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

## CHECKPOINT 主要差异（SUCCESS vs FAILED_BREAKOUT）

### 09:45

- 几乎无差异：OPEN_GAP（S +1.12% vs F +1.70%，d=0.02）、
  DRAWDOWN_FROM_OPEN（S -0.80% vs F -0.99%，d=0.03）、
  VWAP_STATE（S 60% vs F 70% 在 VWAP 上）、S1_STATE（S 35% vs F 32%）。
- S1_TOUCHED：S 47.5% vs F 58.6%（F 更早更多触 S1，rate diff -0.111）。
- 结论：09:45 无法区分两组。

### 10:00

- DIST_TO_VWAP_PCT 开始分化（S +0.82% vs F +0.40%，d=+0.31）。
- S1_STATE（收盘在 S1 上方）：S 42.5% vs F 28.3%（diff +0.142）。
- S1_TOUCHED 仍 F 更高（55% vs 68%，diff -0.127）。

### 10:30

- S1_STATE：S 55% vs F 32%（diff +0.227）；DIST_TO_S1：S +0.52% vs F -1.27%
  （d=+0.27）。
- DIST_TO_VWAP：S +1.35% vs F +0.36%（d=+0.50）。
- CURRENT_RETURN_FROM_OPEN：S +4.49% vs F +2.26%（d=+0.37）。
- S1_REBREAK_AFTER_TOUCH：S 12.5% vs F 29.3%（diff -0.168）。
- S1_REBREAK_COUNT：S 中位 0 vs F 中位 1（d=-0.32）。

### 11:30

- DIST_TO_VWAP：S +1.46% vs F +0.47%（d=+0.59）。
- CURRENT_RETURN_FROM_OPEN：S +5.77% vs F +2.76%（d=+0.50）。
- HIGH_FROM_OPEN：S +6.98% vs F +5.26%（d=+0.45）。
- DIST_TO_S1：S +0.87% vs F -1.36%（d=+0.43）；S1_STATE diff +0.166。
- VWAP_STATE：S 80% vs F 60%（diff +0.204）。
- TIME_OF_MORNING_LOW：F IQR 拉宽至 15 分钟（F 低点可晚至 09:45-09:45+），
  S 固定在 5 分钟；d=-0.28。

## A-F 回答

A. OPENING_DRAWDOWN：无稳定区别。两组开盘 30 分钟回撤几乎相同
   （d ≈ 0.02-0.04，S -0.84~-0.88% vs F -0.99~-1.15%），OPEN_GAP 无差异。

B. FAST_RECLAIM：无强区别。OPEN_RECLAIMED_NOW 早盘接近（09:45 S 82.5% vs
   F 83.8%），VWAP_FIRST_RECLAIMED 仅在 11:30 有 +0.094 的小差；
   VWAP_SECOND_RECLAIMED 无差异。

C. VWAP acceptance：有清晰描述性区别，且随时间增强（10:00 d=+0.31 →
   10:30 d=+0.50 → 11:30 d=+0.59）。SUCCESS 从 10:00 起持续更大幅度地站在
   VWAP 上方，FAILED 更接近/低于 VWAP。

D. S1 first-break acceptance：有清晰描述性区别。FAILED 触 S1 更多更早
   （所有 checkpoint -0.11~-0.15），但 10:00 起收盘站上 S1 的比例 SUCCESS 更高
   （+0.14/+0.23/+0.17），且 F 触后跌回 S1 下方比例更高（10:30 29% vs 13%）。

E. RETEST / SECOND_ACCEPTANCE vs FIRST_RECLAIM：首次收复类指标（VWAP_FIRST_
   RECLAIMED / OPEN_RECLAIMED_NOW）与二次收复计数（VWAP_SECOND_RECLAIMED /
   S1_SECOND_RECLAIMED）均无明显区别；真正有区别的是“首次触 S1 后是否跌回
   下方”（RETEST_QUALITY，10:30 起明显），即 RETEST 质量比 FIRST/ SECOND
   reclaim 计数更有区分度。

F. HIGH/LOW progression：HIGH progression 有区别（HIGH_FROM_OPEN d 0.27 →
   0.45），SUCCESS 高点持续更高；LOW progression 几乎无区别
   （LOW_FROM_OPEN d≈0.03），两组低点深度接近。

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
（HIGH_FROM_OPEN d=0.45；S1_REBREAK_AFTER_TOUCH diff -0.17@10:30；
S1_REBREAK_COUNT d=-0.32@10:30）

NO_SIGNAL_FEATURES =
OPEN_GAP_PCT（d=0.02）、DRAWDOWN_FROM_OPEN/LOW_FROM_OPEN（d<0.05）、
TIME_OF_MORNING_LOW（中位相同）、NEW_LOW_AFTER_OPEN_RECLAIM（0% 两组）、
VWAP_SECOND_RECLAIMED、S1_SECOND_RECLAIMED（计数无差异）。

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
