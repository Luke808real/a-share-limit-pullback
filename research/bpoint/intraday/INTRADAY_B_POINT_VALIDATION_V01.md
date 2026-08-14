# INTRADAY_B_POINT_VALIDATION_V01

RUN_ID: INTRADAY_B_POINT_VALIDATION_V01
SCRIPT: research/intraday_b_point_validation_v01.py
OUTPUTS: research/bpoint/intraday/availability_v01.csv、
checkpoint_features_v01.parquet、checkpoint_feature_summary_v01.csv、
checkpoint_effect_matrix_v01.csv、stratified_robustness_v01.csv、
example_intraday_cases_v01.csv、summary_v01.json
STATUS: OBSERVE_ONLY / SUPPORTED_DESCRIPTIVE / CANDIDATE_FOR_FORWARD_PAPER
（无 BUY_RULE / PROMOTED / FROZEN / PRODUCTION）

## DATA_AVAILABILITY

- 扫描 8,746 cases 的 candidate_date=D0 分钟行情：
  - 1m COMPLETE = 0（新浪 1m 仅覆盖 ~7/23 起，D0 窗口不满足）
  - 5m COMPLETE = 206；PARTIAL = 2；MISSING = 8,538
  - 本轮主粒度 = 5m（1m 全部不可用；明确记录，不混合频率）
- 完整性检查：09:35-15:00 连续、bar≥46、无重复时间戳、无异常 gap、
  OHLC/volume/amount 合法。

## COHORT_COUNTS

SUCCESS_N = 40
FAILED_BREAKOUT_N = 97
NO_LAUNCH_N = 12（样本小，结论带 caveat）
STRUCTURE_FAIL_N = 51
UNKNOWN_N = 6

SUCCESS ≥ 20 → 允许正式比较。

## 重要统计修正（贯穿本报告）

V01 使用的 rank-biserial 未处理并列排名，离散特征（low_position_enc、
probe_count_3d、price_recovery_pct、d1_upper_shadow_pct 等）效应被夸大。
本轮 lib 已修正（平均秩 + 零方差保护），并重算了 V01 关键离散特征：

| V01 特征 | V01 旧 rb（F/NL/SF） | 修正 rb（F/NL/SF） | 结论 |
|---|---|---|---|
| low_position_enc | -0.42/-0.32/-0.33 | +0.02/+0.02/-0.01 | 伪效应（中位数全部 0） |
| probe_count_3d | -0.27/-0.30/-0.22 | -0.07/-0.12/-0.10 | 显著减弱，弱 |
| d1_upper_shadow_pct | -0.28/-0.27/-0.23 | -0.04/-0.04/-0.04 | 全样本伪效应（见下） |
| price_recovery_pct | -0.46/-0.27/-0.28 | +0.01/-0.05/0.00 | 伪效应 |
| pullback_min_vol_ratio | +0.18/+0.06/+0.19 | +0.18/+0.06/+0.19 | 连续变量，稳健 |
| dist_to_s1_pct | +0.06/-0.45/-0.39 | 不变 | 连续变量，稳健 |

结论：V01 的“D0 最低点 / 多次试盘 / 快速修复”类结论主要来自并列排名伪效应，
须以本报告修正口径为准。

## V01 五个候选的实时验证

1. S1_DISTANCE(t)：SUCCESS 比 STRUCTURE_FAIL 更贴近 S1（rb -0.26~-0.42，
   全部 D-1 距离 quartile 稳健），但与 FAILED_BREAKOUT 无差异（rb ≈ 0~0.14）。
   → ACTIVATION_FEATURE_ONLY（风险排除变量，不是 SUCCESS vs FAILED 的 B 点变量）。
2. PRE_BREAKOUT_PROBE_COUNT → PROBE_STATE(t)：D0 是启动前日，S1 盘中几乎不被
   触及（所有组 s1_touched=0）；修正后 V01 rb 仅 -0.07~-0.12。
   → NO_CLEAR_EDGE（实时版）。
3. D0_SUPPORT_TEST → SUPPORT_TEST_RECLAIM(t)：支撑触及/收复率 S 60%/57.5% vs
   F 66%/57.7% vs SF 70.6%/56.9%（几乎相同），仅 vs NO_LAUNCH（25%/25%）有区别；
   quartile 内不稳定。→ ACTIVATION_FEATURE_ONLY（vs NO_LAUNCH），
   不是 S vs F 的区分项。
4. DAMAGE_RECOVERY_PCT → SESSION_LOW_RECOVERY(t)：恢复幅度/时间无区分
   （recovery_from_session_low S 反而更低 2.37 vs F 3.33；minutes_low_to_open
   rb≈±0.09）；真正的实时信号是 D0 回踩更浅
   （session_low_vs_prev_close S -1.80 vs F -2.37 / SF -2.45）。
   → “急杀后恢复”REJECT；替换为“D0 浅回踩”SUPPORTED_DESCRIPTIVE。
5. PULLBACK_VOLUME_DRY_UP（pre-D0）→ 实时版不一致（vs F +0.10，vs SF -0.08；
   quartile 正负混杂）→ REJECT。但 D0 盘中相对量能是真实信号：
   cum_volume/D1_volume、cum_volume/anchor_volume 在 SUCCESS 全天更低
   （rb +0.21~+0.42），即“D0 安静日”而非“再放量”。

附加：D1_UPPER_SHADOW 在 206 例 cohort 中 S 中位 1.68 vs F/SF 0.0
（rb -0.32/-0.31，全部 quartile 稳健，CI 不含 0，preopen 已知）；
但全样本修正 rb ≈ -0.04（稀疏）→ 该效应可能为 cohort/时期限定，标 OBSERVE。

## TOP_SUCCESS_VS_FAILED_FEATURES（D0 实时）

| 特征 | 方向 | rb@09:45→11:30 | CI@11:30 | 说明 |
|---|---|---|---|
| cum_volume_vs_D1_ratio | S 更低 | +0.23→+0.31 | (-0.30,-0.01) 不含 0 | D0 相对 D-1 更缩量 |
| cum_volume_vs_anchor_ratio | S 更低 | +0.21→+0.30 | (-0.30,0.06) 宽 | 同上族 |
| session_low_pct_vs_prev_close | S 更浅 | -0.31→-0.27 | (0.02,1.96)@09:45 不含 0 | D0 回踩浅 |
| session_range_pct | S 更小 | +0.21→+0.27 | 宽 | D0 窄幅 |
| D1_upper_shadow_pct | S 更高 | -0.32（preopen） | 不含 0 | D-1 试盘（cohort 限定） |

## TOP_SUCCESS_VS_STRUCTURE_FAIL_FEATURES

同一批变量方向一致且更强：cum_volume ratios（+0.29~+0.42）、
session_range（+0.35~+0.48）、session_low 更浅（-0.31~-0.36）、
price_to_s1 更近（-0.26~-0.42）、D1 upper shadow（-0.31）、
high_progression（+0.12~+0.23）。

## ACTIVATION_ONLY_FEATURES

仅区分 SUCCESS vs NO_LAUNCH、不能区分 vs FAILED：support_touched/reclaimed
（NL 25%）、price_to_s1（NL 更远）、probe（弱）。NO_LAUNCH n=12 为 caveat。

## EARLIEST_STABLE_CHECKPOINT

- D1_UPPER_SHADOW：preopen（D-1 收盘即可知）。
- CUM_VOLUME_VS_D1、SESSION_LOW_VS_PREV_CLOSE、SESSION_RANGE：
  09:45 即出现稳定方向，持续到 14:30（非 10:17 类单点最优）。
- 结论：最早稳定辨识时刻 = 09:45（盘前为 D1 shadow）。

## STRATIFIED_ROBUSTNESS（D-1 dist_to_s1 quartile 内，1130）

| 特征 | S vs F | S vs SF |
|---|---|---|
| cum_volume_vs_D1_ratio | 4/4 quartile 同向 | 3/4（Q2 弱） |
| session_low_vs_prev_close | 3/4（Q2 翻转） | 4/4 |
| session_range_pct | 3/4 | 3/4 |
| D1_upper_shadow | 4/4 | 4/4 |
| price_to_s1 | 混合 | 4/4 |

即：量能/回踩深度/窄幅信号不是“因为 SUCCESS 本来在 D-1 更贴 S1”造成的。

## 12 个问题

1. V01 哪些日 K 结论在分钟级仍成立：D0 窄幅（session_range）、D0 回踩浅
   （vs prev close）、D0 相对量能低（quiet day）、贴近 S1 的“风险排除”角色。
2. S1 distance：更接近 ACTIVATION/风险排除变量；对 SUCCESS vs FAILED 无区分
   （FAILED 同样贴 S1 并发动）。
3. probe 多：修正后弱（V01 伪效应）；D0 盘中 S1 几乎不触；不是正面也不是
   负面主导变量 → NO_CLEAR_EDGE。
4. 支撑下探后 reclaim：S vs F/SF 收复率几乎相同（~58%），只在 vs NO_LAUNCH
   有区分 → 不是“成功 B 点”优势，是“会发动”特征。
5. session low 后 recovery：恢复幅度/时间无优势；真正优势是“低点本身不深”。
6. VWAP acceptance（D0）：FAILED 反而更常站在 VWAP 上（他们在进攻）；
   SUCCESS 无优势 → NO_CLEAR_EDGE（与事件日 V02A 结论相反，阶段不同）。
7. pullback volume dry-up：pre-D0 定义不一致；D0 盘中相对量能低是稳健增量。
8. D1 upper shadow：在本 cohort 方向为“正面试盘”（S 更高），全样本稀疏；
   标 OBSERVE，不能判为压力拒绝。
9. SUCCESS vs FAILED 最有价值实时差异：D0 相对量能低 + 回踩浅 + 窄幅
   （三者均 09:45 起稳定；FAILED 是更活跃、更接近 S1、波动更大的那一天）。
10. 最早稳定 checkpoint：09:45（盘前为 D1 upper shadow）。
11. 只能预测 NO_LAUNCH 的变量：support test/reclaim、price_to_s1（对 NL）、
    probe（弱）→ ACTIVATION_FEATURE_ONLY。
12. 应 REJECT：probe（D0 实时）、DAMAGE_FAST_REPAIR 类恢复速度、
    VWAP acceptance（D0）、pre-D0 dry-up 原定义、d0_new_low（实时最低点）、
    close_location（方向混杂）、return_from_prev_close（弱且衰减）。

## 状态

| 变量 | 状态 |
|---|---|
| CUM_VOLUME_VS_D1_RATIO（D0 相对量能） | CANDIDATE_FOR_FORWARD_PAPER |
| SESSION_LOW_VS_PREV_CLOSE（D0 回踩深度） | CANDIDATE_FOR_FORWARD_PAPER |
| SESSION_RANGE_PCT | OBSERVE（vs F CI 宽） |
| D1_UPPER_SHADOW | OBSERVE（cohort 限定） |
| PRICE_TO_S1（vs SF） | SUPPORTED_DESCRIPTIVE（风险排除） |
| SUPPORT_TEST/RECLAIM | ACTIVATION_FEATURE_ONLY |
| PROBE / RECOVERY / VWAP(D0) / PRE_D0_DRYUP / D0_NEW_LOW | REJECT / NO_CLEAR_EDGE |

## QA

PIT_VIOLATIONS = 0
CHECKPOINT_FUTURE_LEAKAGE = 0
DUPLICATES = 0
MISSING_MINUTE_CASES = 8,538
PARTIAL_MINUTE_CASES = 2
SUCCESS_N = 40 / FAILED_BREAKOUT_N = 97 / NO_LAUNCH_N = 12 / STRUCTURE_FAIL_N = 51
EVALUATE_STRATEGY_CALLS = 0
PRODUCTION_FILES_CHANGED = false

## DATA_QUALITY_CAVEATS

- 主粒度 5m（1m 完整 = 0）；D0 是启动前日，S1 盘中触及天然稀少。
- cohort 受 5m 缓存窗口（2026-06-05~08-04）与 V02A symbol 集限制，
  与全样本组成不同；NO_LAUNCH n=12。
- V01 离散特征效应因 tie bug 被夸大；本报告已用修正口径重述。
- D1 upper shadow 效应为 cohort 限定；support 字段来自 episodes
  （support_center/low），个别 case 可能缺失。

## NEXT_RECOMMENDED_EXPERIMENT

FORWARD_PAPER_D0_BPOINT：
预注册 09:45/10:00 两个 checkpoint 的
“D0 相对量能低 + 回踩浅 + 窄幅”状态，
仅做 forward paper observation，不形成交易规则。
