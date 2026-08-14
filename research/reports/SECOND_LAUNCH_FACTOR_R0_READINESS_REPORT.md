# SECOND_LAUNCH_FACTOR_R0_READINESS_REPORT

> R0 — CONTRACT & DATA READINESS（只读审计，未实现任何因子代码）
> AS_OF: 2026-08-08 · 研究依据：a-share-strategy-brain `04_Research/Second-Launch-Factor-Research-V01.md`
> 约束遵守：未修改策略规则 / B1-B2 状态机 / snapshot 语义；未创建或 promote generation；未跑 full-market pipeline；未抓新数据；未扫描整个仓库。

STATUS: COMPLETE — contract & data readiness audit（只读；输出仅本报告文件）
BRANCH: `stabilize/pr-e-atomic-state-generation`
HEAD: `0f08348fd1fa7e04bdf468acc5516d6001e169b9`
WORKTREE: 有先前已存在的用户改动（未修改 / 未暂存 / 未清理）：

- `M` AGENTS.md, pyproject.toml, `src/limit_pullback/models/*`（5 文件）,
  `src/limit_pullback/screen/*`（6 文件）, `src/limit_pullback/strategy/*`（2 文件）
- `??` config/runtime.yaml, docs/A_SHARE_STRATEGY_FULL_SWE_AUDIT_REPORT_2026-08-06.md,
  docs/HANDOFF_2026-08-05.md, ops/, research/ 下大量既有研究脚本与产物

本任务唯一新增文件：`research/reports/SECOND_LAUNCH_FACTOR_R0_READINESS_REPORT.md`（本文件）。

---

## CASESET

CASESET_ID/PATH:

- 正式 case set：`SUCCESS_CONTROL_CASESET_V01B`
  `research/intraday/success_control_cases_v01b.csv`（SHA256 `b22eae1dd438ed1b4053ce2cfce7ce668010518462261cb724f149615894f4e6`）
- outcome 唯一真源：`research/intraday/success_control_cases_v01.csv`
  （SHA256 `20d1973b280b67f27b573e302e7915d04131b9bac6d568bb9c2e79416cf52fc3`）
- 冻结 episode 源：`data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet`
  SHA256 `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093`（与已冻结研究哈希一致）
- 构建脚本：`research/build_success_control_caseset_v01.py` / `_v01a.py` / `_v01b.py`
- 交叉引用：`docs/background/chatgpt-project-audit-context-2026-08-06.md`（§十二 统一 Case Set）、
  `research/bpoint/summary_v01.json`、`research/intraday/SUCCESS_CONTROL_CASESET_V01*.md`

OUTCOME_COUNTS（活数据动态读取，8,746 行 / 无重复 episode_id）：

| outcome | n |
|---|---:|
| SUCCESS | 409 |
| FAILED_BREAKOUT | 950 |
| NO_LAUNCH | 1,730 |
| STRUCTURE_FAIL | 5,415 |
| UNKNOWN | 242（AMBIGUOUS 212 + 日K缺失/标签缺失 30） |
| TOTAL | 8,746 |

与目标计数完全一致（409 / 950 / 1,730 / 5,415 / 242）。关键词检索未发现被后来正式研究替代的版本；
V01B 为当前经过验证的一致修复版（outcome 与 V01 完全对齐，mismatch=0），即当前正式版本。

outcome 定义（固定 3 个交易日前瞻；冻结 pattern_3d 顺序 + 日K细化）：

- SUCCESS：S1_BEFORE_INVALID，且首个 S1 触及日 close >= S1（ACCEPTANCE/HOLD）且当日 volume >= candidate 日 volume（EXPANSION）
- FAILED_BREAKOUT：S1_BEFORE_INVALID 但接受失败（close < S1）或量能未扩张
- NO_LAUNCH：NEITHER（3 日内 S1/invalid 均未触及，结构仍在、未发动）
- STRUCTURE_FAIL：INVALID_BEFORE_S1（3 日内 invalid 先于 S1）
- UNKNOWN：pattern_3d AMBIGUOUS（同日 S1/invalid 顺序不明）或日K缺失；不参与比较

manifest / generation：case set 不是 screen generation（`data/screen/generations/stategen-*` 与它无关），
是研究产物 CSV；episode 源自带 provenance（snapshot_id `snap-2026-07-31-b5f84004de8a`、
strategy_commit `315fbe0d6a41cbcbb17166c03c134e010f163084`、哈希 66d5943f…）。

feature-as-of / label-as-of 语义：

- 候选入口 = 冻结 lifecycle 候选（setup_stage ∈ {B1_READY, B2_READY, B2_CONFIRMED}），
  只使用 D-1 收盘可得信息（signal_date 的 invalid / S1 / trigger / score）
- FEATURE_AS_OF = D = candidate_date（candidate_date 范围 2024-07-03 ~ 2026-07-28）
- outcome 仅在候选集生成后读取未来数据，前瞻固定 3 个交易日；OUTCOME_EVENT_DATE /
  EVENT_SESSION_OFFSET 已落 CSV（SUCCESS+FAILED_BREAKOUT 1,359 全部解析）
- 同一 anchor 的后续候选日（B2 等）不作为独立 case；sibling 数记录在 same_anchor_sibling_count
- 注：episodes.parquet 共 31,422 行（全部执行级候选，distinct setup_id 17,691），
  其 outcome 列是执行 outcome（WIN_S1/LOSS_INVALID/NO_FILL 等），不是 case set 的 5 分类；
  case set 8,746 = 每 setup_id 最早候选日去重后的子集，计数与定义见上

inferred anchor / quality flags：

- 8,713/8,746（99.62%）候选带 `INFERRED_LIMIT_ANCHOR` flag（冻结 episodes 自身 provenance）；
  锚点日期取 episode 的 anchor_date，不重新推断
- data_quality：PARTIAL 8,713 / OK 33（V01B 已排除 UNUSABLE）
- 76 个 STRUCTURE_FAIL 事件日无法从 canonical 重建（PATTERN_ONLY_EVENT_UNRESOLVED，outcome 不变）；
  1,972 个 NO_LAUNCH+UNKNOWN 无事件日（N/A）

CASESET_STATUS: **FROZEN (VERIFIED)** — 计数、哈希、去重、PIT 声明全部通过活数据复核；
未发现替代版本；无需 BLOCKED，无需重建。

---

## PIT

PIT_STATUS: **PASS**

EVIDENCE:

- `SUCCESS_CONTROL_CASESET_V01.md`：PIT_VIOLATIONS=0；候选选择字段全部来自冻结 D-1 episode，
  outcome 仅在候选集生成后读取未来数据；DUPLICATES=0（8,746/8,746）
- CSV 列 `pit_valid` + `PIT_CANDIDATE_ELIGIBLE` 逐行标记
- episode 源按单一 snapshot_id（`snap-2026-07-31-b5f84004de8a`）作用域读取，无 today-adjusted 历史数据
- canonical 读取路径为 snapshot 作用域：`src/limit_pullback/warehouse/snapshot.py`
  `read_snapshot_daily` / `read_snapshot_daily_table` / `read_snapshot_pool`；
  snapshot manifest（`data/manifests/snap-2026-07-31-b5f84004de8a.json`）含 canonical/source 文件哈希
- 未来数据仅用于 labeling：OUTCOME_EVENT_DATE 由 case 生成后回读 canonical bars 得出
- 残余 caveat（非违规，需在 R1 显式成约）：价格未复权（见 DATA）；停牌日不落行
  （trade_status 全 True）；99.6% anchor 为推断；data_quality 多为 PARTIAL

---

## DATA

DAILY_STATUS: **READY**

- 来源：canonical daily bars `data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet`
  （ASL/canonical 查询层，snapshot 作用域）
- 覆盖：3,282,707 行 / 5,634 codes / 2024-01-02 ~ 2026-07-31
- 字段：open/high/low/close、preclose（0 null）、volume、amount（0 null）、pct_change、
  turnover_rate（96.6% null，见下）、trade_status、is_st、selected_provider
  （TUSHARE 3,171,813 / AKSHARE 110,894）、reconciliation_status（CONFIRMED 1,844,543 / PROVISIONAL 1,438,164）
- preclose 可用；停牌语义 = 当日不落行（trade_status 全部为 True），需以交易日历成约
- 价格合约 = 原始价（未复权；代码内无复权逻辑；raw tushare adjustment_factor 存在但未使用）——
  除权除息跨日连续性需在 R1 显式定义

TURNOVER_STATUS: **PARTIAL**

- canonical `turnover_rate` 仅 AKSHARE 行有值（110,894 行 = 3.4%），TUSHARE 行全部为 null
  （3,171,813），不满足 PIT 读取；禁止使用默认值 / UNKNOWN=0 / 近似
- raw tushare `daily_basic`（35 文件，3,415,290 行，2024-01-02 ~ 2026-07-31）含
  turnover_rate + circ_mv + volume_ratio，带 lineage（provider/provider_version/ingest_run_id/row_hash），
  但未 promote 进 canonical 查询层 → 需要 R1 数据合约决策（本任务不授权）
- 结论：turnover 因子（t0_turnover / price_damage_per_turnover / max_drawdown_per_cumulative_turnover）
  在 promote 前一律排除，不进入 V01

INTRADAY_STATUS: **READY_LATER**

- 仓库无分钟数据层；只有临时缓存：
  - `data/tmp/v02a-minute/raw_1m/` + `raw_5m/`：141 只 / 事件日 2026-06-05 ~ 2026-07-30
    （`research/intraday/v02a_minute_manifest.csv` + `V02A_MINUTE_DATA_VERIFICATION.md`）
  - 1m gate 未通过：146 事件仅 7 个完整可用（SUCCESS 2 / FAILED 5，均 < 20）→ 1m 不可研究
  - 5m fallback：139/146 完整 session（SUCCESS 40 / FAILED 99，均 >= 20），已缓存；
    是否采用 5m 为人工决策，尚未登记 V02A
  - `data/tmp/intraday-success-pattern-v01/`：600468/600756/601858 的 1m 缓存（2026-07-23 ~ 08-04）
- 5m bar 生成确定性、时间戳语义、历史覆盖均未形成仓库契约 → 只能 READY_LATER，
  6 个分钟因子（breakout_hold_ratio / vwap_acceptance_ratio / retest_depth /
  false_break_duration / post_break_30m_return / post_break_60m_return）本阶段不实现

CONTEXT_STATUS: **BLOCKED**

- 仓库内不存在可靠、历史 point-in-time 的 industry/concept mapping / sector 日度成员 / 板块宽度：
  - `data/canonical/limit_up_pool/snap-2026-07-31-b5f84004de8a.parquet` 仅 901 行 / 601 codes /
    2026-07-13 ~ 2026-07-31（历史涨停池不在仓库；08-05/08-06 快照同样从 2026-07-13 起）
  - 板块代理仅存在于 forward-paper 手工审计：`data/forward-paper/manual-first-plan-overlay-audit/sector_data_audit.json`
    明确 `LOW_CONFIDENCE_PROXY`、`LIMIT_UP_POOL_SECTOR_PROXY`、SELECTION_BIAS_PRESENT、64/78 覆盖
  - 禁止用“今天的板块成员”反推历史 → 5 个 sector 因子全部 BLOCKED
- 市场宽度（market_up_down_breadth / market_limitup_downlimit_n）可由 canonical 日线全市场
  （5,634 codes）以 pct_change 近似计算，但涨停判定需价格限制合约（raw tushare `price_limits`
  3 文件存在、未 promote）→ 标 V01_OPTIONAL（近似 + 需合约）

---

## GOLDEN_CASE_READINESS

（bounded 读取：canonical daily bars snap b5f84004de8a + raw tushare daily_basic + 分钟缓存文件名）

| code | name | daily_available | turnover_available | minute_available | sector_available |
|---|---|---|---|---|---|
| 002606 | 大连电瓷 | YES（621 行，2024-01-02~2026-07-31） | PARTIAL（canonical 5.6%；raw daily_basic 624/624） | NO（无缓存） | NO |
| 002498 | 汉缆股份 | YES（621 行） | PARTIAL（5.6%；raw 624/624） | NO（无缓存） | NO |
| 600468 | 百利电气 | YES（622 行） | PARTIAL（5.5%；raw 624/624） | PARTIAL（1m 缓存 2026-07-23~08-04） | NO |
| 600756 | 浪潮软件 | YES（623 行） | PARTIAL（5.6%；raw 624/624） | PARTIAL（1m 缓存 2026-07-23~08-04，9 日） | NO |
| 601858 | 中国科传 | YES（621 行） | PARTIAL（5.5%；raw 624/624） | PARTIAL（1m 缓存 2026-07-23~08-04，9 日） | NO |

case set 内成员（V01B 活数据）：002606 3 例（STRUCTURE_FAIL 2 / NO_LAUNCH 1）；002498 3 例
（FAILED_BREAKOUT 2 / STRUCTURE_FAIL 1）；600468 2 例（STRUCTURE_FAIL 2）；600756 7 例
（FAILED_BREAKOUT 1 / NO_LAUNCH 1 / STRUCTURE_FAIL 3 / SUCCESS 1 / UNKNOWN 1）；
601858 2 例（NO_LAUNCH 2）。
注：`SUCCESS_CONTROL_CASESET_V01.md` 映射表写 600756 STRUCTURE_FAIL=4，活数据为 3（文档计数笔误，以 CSV 为准）。

---

## FACTOR_FEASIBILITY

分级：V01_GO（可立即实现）/ V01_OPTIONAL（需先成约或近似，可延后）/ LATER（数据未过 gate）/ BLOCKED（排除）。

| FACTOR | FAMILY | REQUIRED_DATA | COVERAGE | PIT_SAFE | IMPLEMENTABLE_NOW | BLOCKER | NOTES |
|---|---|---|---|---|---|---|---|
| t0_return | F1 ATTACK | daily | 100% | YES | YES | — | 原始价跨除权需 R1 合约 |
| t0_gap | F1 ATTACK | daily | 100% | YES | YES | — | 需 preclose（可用） |
| t0_range_pct | F1 ATTACK | daily | 100% | YES | YES | — | — |
| t0_close_location | F1 ATTACK | daily | 100% | YES | YES | — | — |
| t0_position_20d | F1 ATTACK | daily | 100% | YES | YES | — | — |
| pre_t0_return_5d | F1 PRE | daily | 100% | YES | YES | — | — |
| pre_t0_return_20d | F1 PRE | daily | 100% | YES | YES | — | — |
| t0_volume_ratio_5d | F1 VOLUME | daily | 100% | YES | YES | — | volume 无缺失 |
| pullback_depth_close | F2 HOLD | daily | 100% | YES | YES | — | — |
| max_drawdown_from_post_t0_high | F2 HOLD | daily | 100% | YES | YES | — | — |
| impulse_retrace_ratio | F2 HOLD | daily | 100% | YES | YES | — | — |
| t0_gain_retention | F2 HOLD | daily | 100% | YES | YES | — | 高共线，与 drawdown 同族标注 |
| low_vs_t0_mid | F2 HOLD | daily | 100% | YES | YES | — | — |
| days_above_t0_mid | F2 HOLD | daily | 100% | YES | YES | — | — |
| pullback_volume_ratio | F3 CONTRACTION | daily | 100% | YES | YES | — | — |
| min_volume_ratio | F3 CONTRACTION | daily | 100% | YES | YES | — | — |
| volume_slope | F3 CONTRACTION | daily | 100% | YES | YES | — | 与 min/pullback ratio 共线，同族标注 |
| median_range_ratio | F3 CONTRACTION | daily | 100% | YES | YES | — | — |
| range_slope | F3 CONTRACTION | daily | 100% | YES | YES | — | — |
| quiet_days_n | F3 CONTRACTION | daily | 100% | YES | YES | — | — |
| days_since_t0 | F5 TIME | daily | 100% | YES | YES | — | — |
| days_to_pullback_low | F5 TIME | daily | 100% | YES | YES | — | — |
| pullback_duration | F5 TIME | daily | 100% | YES | YES | — | 与 days_to_pullback_low 高度共线 |
| high_vs_pullback_high | F6 BREAKOUT | daily | 100% | YES | YES | — | — |
| close_vs_pullback_high | F6 BREAKOUT | daily | 100% | YES | YES | — | — |
| breakout_strength | F6 BREAKOUT | daily | 100% | YES | YES | — | 与 high/close_vs_pullback_high 共线，同族 |
| relative_volume | F6 BREAKOUT | daily | 100% | YES | YES | — | — |
| t0_position_60d | F1 ATTACK | daily | 100% | YES | YES | — | 需 60 日历史（2024-01 起点前少数样本不足） |
| t0_volume_ratio_20d | F1 VOLUME | daily | 100% | YES | YES | — | 与 5d 版本共线 |
| low_vs_t0_open | F2 HOLD | daily | 100% | YES | YES | — | 与 low_vs_t0_mid 高度共线 |
| market_up_down_breadth | F8 CONTEXT | daily | 100%（全市场） | YES | PARTIAL | 需涨跌家数口径合约 | 可由 canonical pct_change 近似 |
| market_limitup_downlimit_n | F8 CONTEXT | daily + 价格限制 | 100% | YES | NO | 涨停判定需 price_limits promote + 合约 | raw tushare price_limits 存在未 promote |
| t0_turnover | F4 ABSORPTION | turnover | canonical 3.4% / raw 100% | RAW-YES | NO | canonical 未 promote；禁止近似 | 排除出 V01 |
| price_damage_per_turnover | F4 ABSORPTION | turnover | 同上 | RAW-YES | NO | 同上 | 排除出 V01 |
| max_drawdown_per_cumulative_turnover | F4 ABSORPTION | turnover | 同上 | RAW-YES | NO | 同上 | 排除出 V01 |
| breakout_hold_ratio | F7 ACCEPTANCE | 5m | 139/146（fallback） | 待定 | NO | 1m gate 失败；5m 待人工决策 | LATER |
| vwap_acceptance_ratio | F7 ACCEPTANCE | 5m + amount | 待验证 | 待定 | NO | 同上 + minute amount 覆盖未验 | LATER |
| retest_depth | F7 ACCEPTANCE | 5m | 139/146 | 待定 | NO | 同上 | LATER |
| false_break_duration | F7 ACCEPTANCE | 5m | 139/146 | 待定 | NO | 同上 | LATER |
| post_break_30m_return | F7 ACCEPTANCE | 5m | 139/146 | 待定 | NO | 同上 | LATER |
| post_break_60m_return | F7 ACCEPTANCE | 5m | 139/146 | 待定 | NO | 同上 | LATER |
| sector_limitup_n | F8 CONTEXT | sector 日度 | 无历史 | NO | NO | 无历史 PIT sector 数据 | BLOCKED |
| sector_up_ratio | F8 CONTEXT | sector 日度 | 无历史 | NO | NO | 同上 | BLOCKED |
| sector_median_return | F8 CONTEXT | sector 日度 | 无历史 | NO | NO | 同上 | BLOCKED |
| sector_relative_strength | F8 CONTEXT | sector 日度 | 无历史 | NO | NO | 同上 | BLOCKED |
| sector_reactivation_n | F8 CONTEXT | sector 日度 | 无历史 | NO | NO | 同上 | BLOCKED |

覆盖口径：daily = canonical snap b5f84004de8a（2024-01-02 ~ 2026-07-31，5,634 codes）；
case set 候选日期范围 2024-07-03 ~ 2026-07-28，日线覆盖完整（前 60/20 日窗口对 2024-07 之前
少数样本会有 warm-up 截断，属正常，建议标注）。

---

## V01_RECOMMENDED_FACTORS

第一版只实现以下 **25 个 DAILY factors**（全部 V01_GO；优先 OHLCV；不掺 turnover/sector/minute；
高共线因子保留用于第一轮 attribution，family 已标注）：

1. t0_return（F1 ATTACK）
2. t0_gap（F1 ATTACK）
3. t0_range_pct（F1 ATTACK）
4. t0_close_location（F1 ATTACK）
5. t0_position_20d（F1 ATTACK）
6. pre_t0_return_5d（F1 PRE）
7. pre_t0_return_20d（F1 PRE）
8. t0_volume_ratio_5d（F1 VOLUME）
9. pullback_depth_close（F2 HOLD）
10. max_drawdown_from_post_t0_high（F2 HOLD）
11. impulse_retrace_ratio（F2 HOLD）
12. t0_gain_retention（F2 HOLD）
13. low_vs_t0_mid（F2 HOLD）
14. days_above_t0_mid（F2 HOLD）
15. pullback_volume_ratio（F3 CONTRACTION）
16. min_volume_ratio（F3 CONTRACTION）
17. volume_slope（F3 CONTRACTION）
18. median_range_ratio（F3 CONTRACTION）
19. range_slope（F3 CONTRACTION）
20. quiet_days_n（F3 CONTRACTION）
21. days_since_t0（F5 TIME）
22. days_to_pullback_low（F5 TIME）
23. pullback_duration（F5 TIME）
24. high_vs_pullback_high（F6 BREAKOUT）
25. close_vs_pullback_high（F6 BREAKOUT）

（候选集第 26-30 位：breakout_strength、relative_volume、t0_position_60d、
t0_volume_ratio_20d、low_vs_t0_open —— 与上表同源共线，可在第一轮 attribution 中作为
同族对照加入，但计入 25 个上限内时优先以上 25 个。）

---

## BLOCKERS

1. **Turnover 未过 canonical gate**：canonical turnover_rate 96.6% null（仅 AKSHARE 行）；
   raw tushare daily_basic 全周期可用但未 promote。需 R1 数据合约决策（promotion 属数据开发，
   本任务未授权）。3 个 turnover 因子因此排除出 V01。
2. **分钟数据 gate 未过**：1m 仅 7/146 可用；5m fallback 139/146（SUCCESS 40 / FAILED 99）
   待人工决策；无仓库级分钟层。
3. **Sector/context 无历史 PIT 数据**：limit_up_pool（含 industry）仅 2026-07-13 ~ 07-31；
   无 industry/concept 映射；禁止用今日成员反推历史 → 5 个 sector 因子 BLOCKED。
4. **价格合约未复权**：canonical 为原始价，跨除权除息连续性未成约
   （raw tushare adjustment_factor 存在未使用）。
5. **停牌语义未成约**：trade_status 全 True、停牌日不落行；raw tushare suspension 仅到
   2026-04-30（2026-05~07 缺失）。
6. **Anchor 置信度**：99.62% INFERRED_LIMIT_ANCHOR + data_quality PARTIAL 8,713/8,746；
   必须保留 quality_flags 维度，不做静默替代。
7. **UNKNOWN 242 例**（AMBIGUOUS 212 / 缺K 30）不参与比较——V01 分析需明确排除口径。

## DO_NOT_IMPLEMENT_YET

- 全部 6 个分钟因子（breakout_hold_ratio / vwap_acceptance_ratio / retest_depth /
  false_break_duration / post_break_30m_return / post_break_60m_return）
- 全部 5 个 sector 因子（sector_limitup_n / sector_up_ratio / sector_median_return /
  sector_relative_strength / sector_reactivation_n）
- 全部 3 个 turnover 因子（t0_turnover / price_damage_per_turnover /
  max_drawdown_per_cumulative_turnover），直到 promote 门通过
- 任何 factor extractor 代码、模型、full-market 重算、generation 创建/promotion、阈值扫描

## NEXT_RECOMMENDED_ACTION

1. 人工评审本报告（R0 结论）。
2. R1 数据合约（human decision）：(a) turnover promote（raw daily_basic → canonical，
   snapshot 作用域 + 哈希校验）；(b) 日线因子提取合约：原始价除权处理、停牌/交易日历语义、
   t0=episode anchor_date（inferred 标记保留）、FEATURE_AS_OF=candidate_date；
   (c) 5m fallback 是否采纳。
3. 合约通过后：R2 在冻结 8,746 case set 上经 `read_snapshot_daily`（snap b5f84004de8a）
   以内存有界流式方式提取 25 个日线因子，输出 factors_v01 可实现性矩阵 → GO/BLOCK 逐因子落地。
4. 本报告仅登记；R1/R2 未获授权前不开始。

---

## VALIDATION（本任务）

- 未运行 full-market 重算；仅 targeted file/schema 检查 + 少量有界 sample query
  （episodes 31,422 行、daily bars 3,282,707 行聚合、raw daily_basic 3,415,290 行聚合、golden 5 codes 行级读取）
- 5 个 golden cases 为 bounded 数据读取，未做策略复盘
- 未安装依赖、未修改任何现有文件、未提交任何内容
- 输入 provenance：episodes parquet SHA256 66d5943f…（与冻结哈希一致）；
  canonical manifest `data/manifests/snap-2026-07-31-b5f84004de8a.json`
  （daily_bars hash e7243dee…、limit_up_pool hash 45faa1a2…）
- 结论状态：OBSERVE_ONLY（数据就绪度审计；不构成任何 edge 结论，SUPPORTED != PROMOTED）
