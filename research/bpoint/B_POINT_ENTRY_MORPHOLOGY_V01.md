# B_POINT_ENTRY_MORPHOLOGY_V01

RUN_ID: B_POINT_ENTRY_MORPHOLOGY_V01
ROLE: Execution Engineer（Strategy/Research Architect: ChatGPT）
STATUS: OBSERVE_ONLY / SUPPORTED_DESCRIPTIVE / CANDIDATE_FOR_INTRADAY_VALIDATION
（无 PROMOTED / ACCEPTED_RULE / FROZEN / PRODUCTION）

## DATA_SOURCE / SNAPSHOT / CASESET

- Daily bars：data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet
  （frozen snapshot，as_of 2026-07-31）
- Corrected episodes：outcome-study …/25903057f106/episodes.parquet
  （snapshot snap-2026-07-31-b5f84004de8a；corrected episodes hash
  66d5943f…；frozen_event_hash 每行保留）
- Caseset：research/intraday/success_control_cases_v01b.csv（8,746，PIT
  候选 = 每 anchor 最早 candidate；outcome 与 V01 逐 episode 一致）
- Intraday local cache（仅登记，未混用）：raw_5m 141 文件、raw_1m 141 文件；
  unfrozen 8/3-8/4 数据仅登记，未参与。
- 脚本：research/bpoint_entry_morphology_v01.py +
  research/bpoint_morphology_lib.py
- 输出：research/bpoint/features_v01.parquet、feature_summary_v01.csv、
  archetype_summary_v01.csv、example_cases_v01.csv、analogs_v01.csv、
  summary_v01.json

SUCCESS_N = 409
CONTROL_N = 8,095（FAILED_BREAKOUT 950 / NO_LAUNCH 1,730 / STRUCTURE_FAIL 5,415）
UNKNOWN 242 排除于比较，但保留于 features 文件。

## 方法边界

- D0 = candidate_date；特征只用 anchor～D0 close 及之前数据；
  outcome 仅作分析后 label。
- 无 threshold scan：damage / probe / archetype 均为预注册的固定描述性定义。
- 统计：median / p25 / p75、median diff、rank-biserial（r）、bootstrap 95% CI
  （500 次）、archetype risk ratio / odds ratio + bootstrap CI。
- 符号约定：r > 0 表示 SUCCESS 数值低于 CONTROL；r < 0 表示 SUCCESS 更高。

## 主要结果

### 连续特征（与三个 control 方向一致且 |r| ≥ 0.15）

| 特征 | 方向（S vs C） | r vs FAILED / NO_LAUNCH / STRUCTURE_FAIL | 说明 |
|---|---|---|---|
| low_position_enc | S 最低点更多出现在 D0 | -0.42 / -0.32 / -0.33 | 入口日下探型 |
| probe_count_3d | S 更多试盘 | -0.27 / -0.30 / -0.22 | D-3~D0 触碰 S1 后回落 |
| price_recovery_pct | S 恢复更强 | -0.46 / -0.27 / -0.28 | 大阴后至 D0 的恢复（缺失 46.6%） |
| probe_count_since_anchor | S 更多试盘 | -0.27 / -0.27 / -0.19 | 自 anchor 起 |
| d1_upper_shadow_pct | S D-1 上影更多 | -0.28 / -0.27 / -0.23 | D-1 试压 |
| closest_high_to_s1_pct | S 更贴近 S1 | -0.04 / -0.20 / -0.24 | 与 FAILED 无差异 |
| dist_to_s1_pct | S 更贴近 S1 | +0.06 / -0.45 / -0.39 | 主要区分不发动组 |
| pullback_min_vol_ratio | S 回调更缩量 | +0.18 / +0.06 / +0.19 | 与 NO_LAUNCH 弱 |
| d0_vol_anchor_ratio | S D0 量相对 anchor 更低 | +0.18 / +0.05 / +0.19 | 同上 |
| d0_vol_d1_vol_ratio | S D0 量相对 D-1 更低 | +0.19 / +0.07 / +0.18 | “再放量”无证据 |
| days_since_anchor | S 比 FAILED 更晚 | -0.27 / -0.08 / -0.21 | FAILED 更早发动 |
| reward_room | S 空间更小（更贴 S1） | -0.05 / +0.11 / +0.51 | 主要 vs STRUCTURE_FAIL |

### Archetype 命中率（vs 各组 OR）

| Archetype | S rate | vs FAILED | vs NO_LAUNCH | vs STRUCTURE_FAIL | vs ALL |
|---|---|---|---|---|---|
| HIGH_LEVEL_CONSOLIDATION | 22.5% | 1.39 (1.06-1.83) | 1.37 (1.06-1.76) | 1.80 (1.39-2.26) | 1.64 (1.27-2.06) |
| MULTI_PROBE_BREAKOUT_PREP | 5.1% | 0.99 (0.56-1.67) | 1.51 (0.84-2.43) | 1.50 (0.83-2.22) | 1.42 (0.83-2.12) |
| SHALLOW_PULLBACK_HIGHER_LOW | 73.6% | 0.94 (0.73-1.23) | 1.37 (1.08-1.78) | 1.44 (1.15-1.84) | 1.36 (1.09-1.74) |
| SUPPORT_SHAKEOUT_RECLAIM | 16.6% | 1.12 (0.83-1.52) | 1.75 (1.31-2.29) | 1.25 (0.96-1.62) | 1.32 (1.00-1.70) |
| STRUCTURE_DECAY | 13.7% | 1.48 (1.05-2.08) | 0.65 (0.47-0.85) | 0.72 (0.54-0.95) | 0.75 (0.57-0.98) |
| DAMAGE_FAST_REPAIR | 0.2% | 0.14 | 0.32 | 0.19 | 0.20 |
| VOLUME_DRY_UP_REEXPANSION | 0.0% | — | — | — | — |

注意：STRUCTURE_DECAY 在 SUCCESS 中比 FAILED_BREAKOUT 更常见
（OR 1.48）——因为 SUCCESS 的 D0 常表现为“日线看像破坏”的下探日
（low 在 D0、收阴/放量），随后才是启动；这是 D0 支撑测试的另一面，
不能机械把 D0 下探判死。

### 低点/重心 base type

- LOWER_LOW（D0 低 < D-1 低）：S 47.7% vs C 43.0%（OR 1.21，CI 0.98-1.49）——
  略多，与“D0 下探”一致。
- HIGHER_LOW：OR 0.95（无区别）；HIGHER_LOW_HIGHER_CLOSE：OR 0.81
  （CI 0.62-1.01，vs FAILED 0.65 / vs STRUCTURE_FAIL 0.77）——简单
  “重心上移”并不构成 SUCCESS 优势。

## 真实案例（example_cases_v01.csv，41 行）

- HIGH_LEVEL_CONSOLIDATION SUCCESS 示例（8）：605117 德业股份
  （2024-07-11→07-16）、605133 嵘泰股份（2025-04-23→04-25）、
  002965（2026-06-11→06-15）等；CONTROL lookalike 8 只。
- MULTI_PROBE_BREAKOUT_PREP SUCCESS 示例（8）+ CONTROL lookalike（8）。
- DAMAGE_FAST_REPAIR 仅 1 个 SUCCESS 示例（002208 合肥城建 2026-06-10→06-15），
  该形态在 SUCCESS 中极稀有。
- 每只均含 anchor/candidate、outcome、days_since_anchor、关键 morphology
  数值，供人工打开复盘。

## Similarity Search（analogs_v01.csv，97 行）

- 原型：HUMAN_600468（7/23→7/31）、HUMAN_600756（7/28→7/31）、
  DB 自动 SUCCESS 原型 3 个（600095:20250924、600186:20260423、
  600992:20241010）；601858 / 002606 无可靠 frozen 时间轴 → 未作为原型
  （HUMAN_REFERENCE_UNAVAILABLE）。
- Top-20 最近邻的 outcome 分布：97 个 analog 中 SUCCESS 仅 2 个（2.1%），
  低于全样本 SUCCESS 率 4.7%；HUMAN_600468 邻域 0 SUCCESS / 18 STRUCTURE_FAIL。
- 结论：当前 morphology 向量的最近邻并未富集 SUCCESS——相似形态本身不是
  强选择器，只能作 descriptive case retrieval。

## 10 个问题的回答

1. SUCCESS 二次启动前最常见的进入形态：高位窄幅换手（HIGH_LEVEL_
   CONSOLIDATION，OR 1.64）、浅回调+重心偏上（SHALLOW_PULLBACK，OR 1.36，
   但与 FAILED 无差异）、多次试盘+低位抬高（MULTI_PROBE，OR 1.42，CI 宽）、
   支撑下探后收复（SUPPORT_SHAKEOUT，OR 1.32）；连续层面还有“D0 最低点 +
   D-3~D0 多次试 S1”。
2. 与 FAILED 同样常见、无辨识度：贴近 S1（dist_to_s1 与 FAILED r≈0）、
   reward_room、浅回调+重心上移（OR 0.94）、多试盘组合（OR 0.99）、
   MA 修复状态（中位数 5/5）。
3. 最能区分 SUCCESS vs STRUCTURE_FAIL：HIGH_LEVEL_CONSOLIDATION
   （OR 1.80）、贴近 S1（r=-0.39）、reward_room（r=+0.51，S 更贴 S1）、
   D0 range 更小（r=+0.25）、盘中最大回撤更小（r=+0.21）、更远离 invalid
   （r=-0.36）、回调缩量（r=+0.19）。
4. “缩量回调→再放量”：缩量回调有部分证据（vs FAILED/STRUCTURE_FAIL
   r≈0.18-0.19，vs NO_LAUNCH 弱）；D0 再放量无证据（S D0 量比 D-1 更低；
   ARCH_VOLUME_DRY_UP_REEXPANSION 在 SUCCESS 命中 0）。结论：
   PARTIAL / NO_CLEAR_EDGE（再放量部分）。
5. “大阴/急杀→快速修复”：D-3~D0 窗口内 DAMAGE_FAST_REPAIR 极稀有且
   SUCCESS 命中率更低（OR 0.20）；修复时间类特征 97-99% 缺失（多数在 D0
   尚未修复，修复发生在事件日之后）。结论：REJECT（快速修复不是 D0 前置
   特征）；大阴后至 D0 的恢复幅度（price_recovery_pct）方向为正，OBSERVE。
6. HIGHER LOW：单独使用无价值（OR 0.95；HIGHER_LOW_HIGHER_CLOSE 反而
   OR 0.81，且 vs FAILED/SF 均为负）；有价值的是“贴近 S1 + D0 下探不破”
   的组合描述，而非简单 higher low。
7. 多次试盘：正面但弱——probe_count 与三组方向一致（r≈-0.22~-0.30），
   但 MULTI_PROBE 组合 vs FAILED 无差异；试盘是“准备”信号，
   “试盘即成功”不成立（FAILED 同样试盘）。
8. 进入准备区的时间：SUCCESS D0 中位数 = anchor+2 交易日；FAILED 更早
   （中位 anchor+1，r=-0.27）；与 NO_LAUNCH 无差异。即 SUCCESS 比
   FAILED 多等约 1 日（弱，OBSERVE）。
9. 最有价值的 B 点前置状态（描述性组合，非已验证 composite）：
   “高位窄幅换手/浅回调 + D0 下探不破 + D-3~D0 多次试 S1 + 贴近 S1 +
   回调缩量”的 D0 状态。
10. 下一步分钟级研究只研究 5 个变量：DIST_TO_S1、PROBE_COUNT_3D、
    D0_SUPPORT_TEST（D0 最低点/是否收复）、DAMAGE_RECOVERY_PCT、
    PULLBACK_VOLUME_DRY_UP（+D1_UPPER_SHADOW 作第 6 观察项）。

## INTRADAY_B_POINT_CANDIDATE_FEATURES

通过 5 项门槛（≥2 control 方向一致、效应可见、样本足、无泄漏、可解释）：

1. S1_DISTANCE_AT_D0（candidate = CANDIDATE_FOR_INTRADAY_VALIDATION；
   注意 vs FAILED 无差异）
2. PRE_BREAKOUT_PROBE_COUNT（3d 与 since-anchor，三组一致）
3. D0_SUPPORT_TEST（lowest-low-since-anchor 出现在 D0；三组一致）
4. DAMAGE_RECOVERY_PCT（三组一致；缺失 46.6%，需分钟数据补）
5. PULLBACK_VOLUME_DRY_UP（vs FAILED/STRUCTURE_FAIL 一致，vs NO_LAUNCH 弱）
6. （OBSERVE）D1_UPPER_SHADOW_PROBE

已剔除：D0 再放量（无证据）、DAMAGE_FAST_REPAIR（稀有/负向）、
HIGHER_LOW_HIGHER_CLOSE（负向）、MA 修复状态（无差异）、
dist_to_trigger（B1 候选 99.9% 缺失）。

## 结论等级

| 发现 | 等级 |
|---|---|
| HIGH_LEVEL_CONSOLIDATION | SUPPORTED_DESCRIPTIVE（OR 1.64，CI 不含 1；三组一致） |
| D0 最低点/支撑测试 | SUPPORTED_DESCRIPTIVE |
| 多次试盘（连续 probe_count） | SUPPORTED_DESCRIPTIVE（弱） |
| 贴近 S1（vs 不发动组） | SUPPORTED_DESCRIPTIVE |
| 回调缩量 | OBSERVE（vs NO_LAUNCH 弱） |
| 大阴后恢复幅度 | OBSERVE（缺失率高） |
| 浅回调+重心上移、SUPPORT_SHAKEOUT | OBSERVE |
| HIGHER_LOW / HIGHER_LOW_HIGHER_CLOSE | REJECT / NO_CLEAR_EDGE |
| DAMAGE_FAST_REPAIR | REJECT（D0 窗口） |
| D0 再放量 | REJECT / NO_CLEAR_EDGE |
| MA 修复状态 | NO_CLEAR_EDGE |
| Morphology nearest-neighbor 富集 SUCCESS | REJECT（analog 邻域 SUCCESS 2.1% < 4.7%） |

全部为 research 标签；无 PROMOTED / ACCEPTED_RULE / FROZEN / PRODUCTION。

## QA

PIT_VIOLATIONS = 0（特征仅使用 anchor～D0）
DUPLICATES = 0（episode_id 唯一，8,746/8,746）
MISSING_BARS = 0
OUTCOME_COUNTS = SUCCESS 409 / FAILED_BREAKOUT 950 / NO_LAUNCH 1,730 /
STRUCTURE_FAIL 5,415 / UNKNOWN 242
FEATURE_MISSINGNESS：dist_to_trigger_pct 99.9%（B1 无 trigger）；
days_to_recover_* 97-99%（多数在 D0 尚未修复）；largest_down_day/
price_recovery 46.6%（window 无下杀日或仅 1 日）
EVALUATE_STRATEGY_CALLS = 0
PRODUCTION_FILES_CHANGED = false

## DATA_QUALITY_CAVEATS

- 99.6% 候选带 INFERRED_LIMIT_ANCHOR（frozen 产物既有属性）。
- name 覆盖 27.2%（limit_up_pool 名称映射）。
- 修复时间/大阴特征缺失率高；trigger 几何对 B1 不可用。
- 效应量整体温和（|r| ≤ 0.5，多为 0.2-0.4）；analog 邻域无 outcome 富集。
- 未做 D/V 切分与显著性检验（按任务约束为描述性）。

## NEXT_RECOMMENDED_EXPERIMENT

INTRADAY_B_POINT_VALIDATION_V01：
对 INTRADAY_B_POINT_CANDIDATE_FEATURES（5+1 项）在 D0 盘中
（09:45/10:00/10:30/11:30 checkpoint）计算 PIT 版本，观察
“D0 下探不破 + 贴近 S1 + 多次试盘”在分钟级是否提前可辨；
仅登记，不自动执行。
