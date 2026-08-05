# ChatGPT 项目审查背景备份（2026-08-06）

- 标题：GPT-5.6 Thinking 介绍
- 来源：https://chatgpt.com/share/6a735e9c-d628-83e8-8aa4-28b41e92ccb1
- 抓取日期：2026-08-06（Asia/Shanghai）
- 消息数：5（ChatGPT 3，用户 2）
- 状态：HUMAN_PROVIDED_UNREVIEWED_BACKGROUND
- 用途：为 a-share-limit-pullback 项目审查提供背景，并保留分享页正文备份。

## 权威性边界

本文件由用户明确提供的 ChatGPT 分享页整理而来。它是背景材料与会话备份，不是冻结策略、正式 ADR、生产配置或已验证研究结论，不能覆盖 `STRATEGY_MASTER.md`、`RULE_CATALOG.md`、`BASELINE_MANIFEST.yaml`、知识库当前阶段指针或仓库中的已审核实现。涉及日期、规则、统计结果、外部政策和数据源能力的陈述，必须在正式项目审查中逐项核验。

本文件不自动进入 Full/Delta Context Pack；若需提升为正式知识库内容，应先生成并人工审核 Digest 或项目审查报告。

## 背景摘要

- 2026-08-03 至 2026-08-05 的 staged daily canonical 已按 TDX 主源、Tencent 确认完成对账，并发布新的 immutable production snapshot；旧 2026-07-31 snapshot 必须保持不变。
- Forward V02 的 reference/protocol/manifest 已在首次 observation 前冻结，但 Forward Day 1 尚未发生，ledger 仍为 0。
- 当前工程阻塞被归纳为 limit-up pool：核心涨停事实可考虑从 CONFIRMED raw daily canonical 与确定性涨跌停规则派生，外部接口只承担首封时间、炸板次数等 enrichment。
- 研究层的暂定框架是 `Quiet → Activate → Accept → Expand`；Mechanical B1/B2 尚未证明稳定正期望，Quiet Compression 仍处于 Forward 验证前。
- 会话指出本地研究状态、GitHub 文档与冻结知识库之间可能存在 Truth Drift，建议先完成 Truth Source、策略语义、研究证据、数据血缘、Forward 完整性和技术债审计。
- 会话建议最终形成 `PROJECT_AUDIT_2026-08.md`，但该建议本身尚未构成获批实施任务。

## 完整正文

以下正文按分享页渲染出的消息角色与顺序保存；仅移除了“复制”“编辑”“思考了…”等界面标签，没有把其中陈述提升为项目事实。

## 消息 1 — ChatGPT

这次可以正式授权 Codex 接通 production 数据发布链路。重点是：旧 7/31 snapshot 永远不改，8/3–8/5 staged 数据生成一个新的 immutable canonical snapshot，然后再用现有策略语义推进 screen。

直接给 Codex：


执行：

ADR008_PRODUCTION_CANONICAL_PUBLISH_AND_SCREEN_CATCHUP_V01

当前状态：

FORWARD_PAPER_D0_BPOINT_V02 = APPROVED
FORWARD_REFERENCE_COMPATIBILITY = PASS_TDX_V02

DAILY_PRIMARY = TDX
DAILY_CONFIRM = TENCENT
DAILY_AUDIT = BAOSTOCK

INTRADAY_PRIMARY = TDX_5M

当前 staged catch-up：

2026-08-03 CONFIRMED = 5195
2026-08-04 CONFIRMED = 5194
2026-08-05 CONFIRMED = 5196

PROVISIONAL_TOTAL = 11
CONFLICTED_TOTAL = 0
QUARANTINED_TOTAL = 0
INCOMPLETE_TOTAL = 307

当前正式 production：

LATEST_CANONICAL_DATE = 2026-07-31
LATEST_SCREEN_DATE = 2026-07-31

本任务目标：

将已经通过 ADR-008 reconciliation 的 staged canonical 数据，以正式、可审计、不可变 snapshot 方式发布到 production canonical；随后使用现有 frozen strategy semantics 推进 production screen。

允许修改：

DATA INGESTION / RECONCILIATION / CANONICAL PUBLISH PIPELINE
SCREEN DATA-LOADING INTEGRATION
research runner integration
tests

禁止修改：

strategy.yaml
strategy thresholds
B1/B2 semantics
support / invalid / S1 semantics
STRATEGY_MASTER
Quiet Score V02
V02 reference CDF
Forward protocol

要求：

STRATEGY_CHANGED = false
1. 首先审计现有 production canonical 发布机制

不要直接复制 staged parquet 到：

data/canonical/

先定位现有：

canonical snapshot builder
snapshot manifest
warehouse metadata
reconciliation status loader
production screen canonical reader

明确现有 snapshot 的：

schema
partitioning
snapshot_id generation
manifest format
hash calculation
as_of semantics
atomic publish semantics

必须复用现有架构。

如果现有功能缺少 ADR-008 provider 接入：

允许实现最小 production data-layer integration。

2. 旧 frozen snapshot 永远不可修改

当前历史 snapshot：

snap-2026-07-31-b5f84004de8a

必须：

IMMUTABLE = true

禁止：

append into old parquet
overwrite old snapshot
change old manifest
change old hash

先重新计算并记录旧 snapshot hash / manifest hash。

任务结束必须仍一致。

输出：

OLD_SNAPSHOT_UNCHANGED = true
3. 创建新的 production canonical snapshot

使用 copy-on-write / immutable snapshot semantics。

新 snapshot 应包含：

旧 snapshot 中截至 2026-07-31 的正式 canonical rows
+
2026-08-03 ~ 2026-08-05 新增 CONFIRMED rows

不要加入：

PROVISIONAL
INCOMPLETE
CONFLICTED
QUARANTINED

新 snapshot：

AS_OF = 2026-08-05
PRICE_DOMAIN = RAW_UNADJUSTED

生成新的：

SNAPSHOT_ID
SNAPSHOT_HASH
MANIFEST_HASH

不得人工指定成旧 ID。

4. Canonical row provenance

每个新增 row 必须完整保留：

code
trade_date
open
high
low
close
volume
amount

selected_provider = TDX
confirmation_provider = TENCENT

reconciliation_status = CONFIRMED

provider
provider_version / adapter_version
fetched_at
ingest_run_id

source_row_hash
confirmation_row_hash

source_unit
normalized_unit

price_domain = RAW
corporate_action_affected

如果现有 canonical schema 无个别 audit 字段：

使用 manifest / warehouse metadata 保存，

不要为了字段齐全破坏已有 reader schema。

5. 不允许字段拼接

继续硬性：

NO_FIELD_LEVEL_PROVIDER_MERGE = true

Canonical OHLCV 整行来自：

TDX

Tencent 只用于 confirmation。

禁止：

TDX close + Tencent volume
6. 发布前重复 reconciliation verification

不要完全信 staged 文件。

发布前重新验证 staged manifest：

trade_date
code uniqueness
OHLC validity
volume units
selected_provider
reconciliation_status
row_hash

要求：

DUPLICATE_CODE_DATE = 0
CONFLICTED_PUBLISHED = 0
PROVISIONAL_PUBLISHED = 0
7. 股票无 bar ≠ 自动数据错误

对 staged 中的 INCOMPLETE / 两源缺失股票：

先区分：

A. legitimate suspension / no trading bar
B. provider data missing
C. security not in active production universe

禁止：

forward-fill previous close
fabricate zero-volume bar
copy previous session

保留显式：

DATA_UNAVAILABLE
SUSPENDED_IF_VERIFIABLE

语义。

不要为了达到 100% coverage 造 bar。

8. 发布原子性

生产 canonical 发布必须：

build temp snapshot
validate
hash
write manifest
atomic promote

如果任一 validation 失败：

PUBLISH_STATUS = ABORTED

正式 canonical pointer / latest manifest 不得改变。

禁止半发布状态。

9. Snapshot QA

发布后：

LATEST_CANONICAL_DATE = 2026-08-05

但要实际从新 snapshot 读取验证，不能只看文件名。

输出：

TOTAL_ROW_N

20260803_ROW_N
20260804_ROW_N
20260805_ROW_N

CONFIRMED_ROW_N
DUPLICATE_ROW_N

MAX_TRADE_DATE

并抽样至少：

600756
603980
000001
600000

核对 staged → production：

OHLCV exact match
10. 新 snapshot 与旧历史区间 parity

对：

<= 2026-07-31

比较：

OLD_SNAPSHOT
NEW_SNAPSHOT

要求：

HISTORICAL_ROW_COUNT_DIFF = 0
HISTORICAL_OHLCV_DIFF_N = 0

这是非常重要的 invariant。

新 snapshot 发布不能重写历史。

11. Production screen catch-up

Canonical publish PASS 后，

使用：

NEW CANONICAL SNAPSHOT

运行现有 production screen incremental engine。

从：

last_processed_date <= 2026-07-31

推进：

2026-08-03
2026-08-04
2026-08-05

注意：

使用现有 frozen strategy evaluator。

要求记录：

EVALUATE_STRATEGY_CALLS

这里允许 production screen 正常调用 evaluator。

但是：

STRATEGY_CONFIG_HASH
FROZEN_STRATEGY_VERSION

必须保持原值。

12. 不改变股票策略状态机

不得为了 catch-up 修改：

B1_READY
B2_READY
B2_CONFIRMED
WAIT
REJECT
INVALID

等状态语义。

数据源变化不等于 strategy transition 变化。

13. 对缺失/停牌股票的 screen 处理

必须沿用现有 production semantics。

禁止自动把 stale state 当成 8/5 已处理。

每只 state 必须明确：

last_processed_date
data_status

如果无法合法处理到 8/5：

保持 stale / unavailable 状态。

不得：

last_processed_date = 2026-08-05

但实际没有对应数据。

14. Screen readiness 不得静默丢股票

最终报告：

STATE_FILE_COUNT

READY_20260805_N
STALE_N
DATA_UNAVAILABLE_N
ERROR_N

并列出 stale 原因分布。

尤其区分：

NO_CONFIRMED_BAR
SUSPENSION
SCREEN_PROCESSING_ERROR
SCHEMA_ERROR

不要只给一个 stale 总数。

15. Candidate freeze eligibility

Forward V02 candidate universe 只能来自：

PRODUCTION_SCREEN_STATES

并且 case 必须：

last_processed_date == TARGET_D1

以及满足原 production candidate semantics。

禁止将 stale state：

carry forward

成为当日 candidate。

即：

STALE_STATE_NOT_FORWARD_ELIGIBLE = true
16. 如果部分 universe stale，不自动阻塞整个 screen

这里做语义审计：

如果现有 production screen 本身允许：

individual unavailable stocks excluded
while valid stocks proceed

则保持这一语义。

不要要求：

3191/3191 都必须 ready

才算 screen ready。

但必须完整披露：

eligible universe
excluded stale universe
exclusion reasons

如果现有 frozen screen 明确定义为：

全 universe 必须同步成功

则不要擅自改；

报告：

GLOBAL_SCREEN_ATOMICITY_REQUIRED = true

并 STOP 交给 Architect。

不要自己决定新的 screen readiness 语义。

17. Screen regression

选取旧 snapshot：

2026-07-31

重新运行相同 screen engine 到 7/31，

与既有：

data/screen/states/*.json

做 regression。

要求关键字段：

setup_stage
support
invalid
s1
scores
candidate flags

与原结果一致。

允许 provenance / runtime timestamp 差异，

不允许策略输出变化。

报告：

SCREEN_REGRESSION_DIFF_N

目标：

0
18. Catch-up screen 完成后 freeze dry-run

若：

LATEST_SCREEN_DATE = 2026-08-05

且当前 TARGET_FORWARD_SESSION 尚未开盘：

执行无写入：

V02 candidate freeze dry-run

candidate source：

PRODUCTION_SCREEN_STATES

输出：

CANDIDATE_DRY_RUN_N
CANDIDATE_DRY_RUN_HASH

仍然：

FORWARD_LEDGER_ROWS_WRITTEN = 0
19. 获取 candidate D1 TDX 5m

candidate universe 确认之后，

获取：

TARGET_D1 TDX 5m

只针对合法 candidate universe。

计算：

D1_CUM_VOLUME_0945
D1_CUM_VOLUME_1000

报告 coverage：

D1_5M_0945_COMPLETE_N
D1_5M_1000_COMPLETE_N
D1_5M_MISSING_N

禁止 provider fallback。

20. Corporate action

当前：

corporate_action_affected

还只是 reserved/default false，

因此不得把：

CORPORATE_ACTION_AFFECTED_N = 0

误报成真实检测 0。

本轮改成：

CORPORATE_ACTION_DETECTION_STATUS =
NOT_IMPLEMENTED

除非项目已有可信 corporate-action source。

在未实现正式检测前：

Forward report 必须显式 caveat。

不要伪称已经检测全部股票。

21. Forward start date

运行到这一阶段时重新读取真实墙钟。

若原候选：

2026-08-06

已经开盘：

永久：

NOT_STARTED_DATA_DEPENDENCY

选择下一个合法未来交易日。

定义：

ACTUAL_FORWARD_START_DATE =
first future session where:
  D1 canonical ready
  D1 screen ready
  candidate freeze can complete before 09:30
  D1 TDX5m denominator available

不回填错过日期。

22. 生产代码修改边界

这轮明确授权：

production DATA-LAYER code changes = allowed
production canonical publisher changes = allowed
production provider adapter integration = allowed
screen canonical loader integration = allowed

但是：

strategy logic changes = forbidden
strategy config changes = forbidden

最终用：

git diff

分类 changed files：

DATA_LAYER_FILES_CHANGED
SCREEN_INFRA_FILES_CHANGED
STRATEGY_FILES_CHANGED

要求：

STRATEGY_FILES_CHANGED = 0
23. Tests

至少新增/补齐：

test_old_snapshot_immutable

test_new_snapshot_contains_old_history_exactly

test_publish_confirmed_only

test_no_provisional_publish

test_no_field_level_merge

test_atomic_snapshot_publish

test_snapshot_manifest_hash

test_staged_to_production_exact_match

test_screen_reads_new_snapshot

test_screen_0731_regression

test_stale_state_not_forward_eligible

test_no_forward_fill_missing_bar

test_v02_candidate_source_production_only

执行：

python -m compileall -q src research
git diff --check

以及完整相关 tests。

24. 完成本任务后不要自动开始 Forward

即使所有 gate 通过：

不要真正写：

forward_candidates.parquet
forward_checkpoints.parquet
forward_outcomes.parquet

保持：

FORWARD_LEDGER_ROWS_WRITTEN = 0

真实 candidate freeze 下一步单独执行。

25. 最终只返回
ADR008_PRODUCTION_PUBLISH_READY_REPORT

包含：

OLD_SNAPSHOT_ID
OLD_SNAPSHOT_HASH
OLD_SNAPSHOT_UNCHANGED

NEW_SNAPSHOT_ID
NEW_SNAPSHOT_HASH
NEW_MANIFEST_HASH

NEW_SNAPSHOT_AS_OF

HISTORICAL_ROW_COUNT_DIFF
HISTORICAL_OHLCV_DIFF_N

NEW_20260803_ROW_N
NEW_20260804_ROW_N
NEW_20260805_ROW_N

PROVISIONAL_PUBLISHED_N
CONFLICTED_PUBLISHED_N
DUPLICATE_PUBLISHED_N

LATEST_CANONICAL_DATE

SCREEN_REGRESSION_DIFF_N

STATE_FILE_COUNT
READY_20260805_N
STALE_N
DATA_UNAVAILABLE_N
ERROR_N
STALE_REASON_COUNTS

GLOBAL_SCREEN_ATOMICITY_REQUIRED

LATEST_SCREEN_DATE

TARGET_FORWARD_SESSION
TARGET_D1

CANDIDATE_DRY_RUN_N
CANDIDATE_DRY_RUN_HASH

D1_TDX_5M_0945_COMPLETE_N
D1_TDX_5M_1000_COMPLETE_N
D1_TDX_5M_MISSING_N

CORPORATE_ACTION_DETECTION_STATUS

PROTOCOL_V02_HASH_MATCH
REFERENCE_V02_HASH_MATCH
EPOCH_V02_MANIFEST_HASH_MATCH

FORWARD_LEDGER_ROWS_WRITTEN

DATA_LAYER_FILES_CHANGED
SCREEN_INFRA_FILES_CHANGED
STRATEGY_FILES_CHANGED

FUTURE_LEAKAGE

ACTUAL_FORWARD_START_DATE

STATUS

硬要求：

OLD_SNAPSHOT_UNCHANGED = true

HISTORICAL_ROW_COUNT_DIFF = 0
HISTORICAL_OHLCV_DIFF_N = 0

PROVISIONAL_PUBLISHED_N = 0
CONFLICTED_PUBLISHED_N = 0

SCREEN_REGRESSION_DIFF_N = 0

STRATEGY_FILES_CHANGED = 0

FORWARD_LEDGER_ROWS_WRITTEN = 0
FUTURE_LEAKAGE = 0

允许状态：

READY_FOR_FORWARD_EPOCH_1_V02_FREEZE

BLOCKED_CANONICAL_PUBLISH

BLOCKED_SCREEN_REGRESSION

BLOCKED_SCREEN_READINESS_SEMANTICS

BLOCKED_D1_TDX_5M

BLOCKED_DATA_PIPELINE_INTEGRATION

完成后停止。

不要执行真实 Forward freeze。
不要执行 09:45 / 10:00。

这一步跑通之后，我们的数据链路就算真正从 Tushare/Eastmoney 依赖迁成了 TDX + 腾讯 production 架构，后面就可以回到策略本身，不需要再围着数据源打转。

---

## 消息 2 — 用户

# ADR008_PRODUCTION_PUBLISH_READY_REPORT

OLD_SNAPSHOT_ID = snap-2026-07-31-b5f84004de8a
OLD_SNAPSHOT_HASH = e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514（daily；pool 45faa1a2…；manifest eb1f601f…）
OLD_SNAPSHOT_UNCHANGED = true（发布前后 hash 一致）

NEW_SNAPSHOT_ID = snap-2026-08-05-d9e93fccc966
NEW_SNAPSHOT_HASH = ce9b489292b79d5a482bfc7f2aa027326587cf1687cea13e532ed1a30b405b16
NEW_MANIFEST_HASH = 92cd5fd2d469ae13c766298f247819f8919e418b8f08875166288adbe9858037
NEW_SNAPSHOT_AS_OF = 2026-08-05（PRICE_DOMAIN=RAW_UNADJUSTED）

HISTORICAL_ROW_COUNT_DIFF = 0
HISTORICAL_OHLCV_DIFF_N = 0（≤7/31 新旧快照逐行一致）

NEW_20260803_ROW_N = 5,174
NEW_20260804_ROW_N = 5,173
NEW_20260805_ROW_N = 5,175
（staged CONFIRMED 原为 5,195/5,194/5,196；每交易日剔除 21 行缺 preclose 的新上市/无前收行，共发布 15,522 行 CONFIRMED）

PROVISIONAL_PUBLISHED_N = 0
CONFLICTED_PUBLISHED_N = 0
DUPLICATE_PUBLISHED_N = 0

LATEST_CANONICAL_DATE = 2026-08-05（从新 snapshot 实际读取验证：max_trade_date=2026-08-05；抽样 600756/603980/000001/600000 staged→production OHLCV 全等）

SCREEN_REGRESSION_DIFF_N = 0（旧 snapshot 重跑 7/31 full-market rebuild：universe 3,191、rows 1,844,543、output_hash = 9abb16e4…，与 frozen FULL_MARKET_HASH 完全一致；引擎未变。注：原始 state 文件已被 catch-up 覆盖，未做 state-level 文件 diff，采用 output_hash 全量回归）

STATE_FILE_COUNT = 5,197
READY_20260805_N = 5,175
STALE_N = 22
DATA_UNAVAILABLE_N = 22
ERROR_N = 0
STALE_REASON_COUNTS = {NO_CONFIRMED_BAR/DATA_UNAVAILABLE: 22（last_processed 2026-07-30×19、2026-07-31×2、2026-07-08×1）}

GLOBAL_SCREEN_ATOMICITY_REQUIRED = false（现有 production 语义允许可用股票推进、不可用个股保持 stale；已按此执行，未自定义 readiness 语义）

LATEST_SCREEN_DATE = 2026-08-05

TARGET_FORWARD_SESSION = 2026-08-06
TARGET_D1 = 2026-08-05

CANDIDATE_DRY_RUN_N = 0
CANDIDATE_DRY_RUN_HASH = N/A
（原因：8/3-8/5 limit-up pool 数据不可用——ADR-008 尚未接入 pool 源；screen 处理 8/3-8/5 后全部 B1/B2 状态被引擎置为 NORMAL/无效，D1 无 forward-eligible 候选。STALE_STATE_NOT_FORWARD_ELIGIBLE 语义保持，未 carry forward）

D1_TDX_5M_0945_COMPLETE_N = N/A（0 candidates）
D1_TDX_5M_1000_COMPLETE_N = N/A
D1_TDX_5M_MISSING_N = N/A

CORPORATE_ACTION_DETECTION_STATUS = NOT_IMPLEMENTED（未接入可信除权除息源；不伪称检测）

PROTOCOL_V02_HASH_MATCH = true（aaca250e…）
REFERENCE_V02_HASH_MATCH = true（dd307825…）
EPOCH_V02_MANIFEST_HASH_MATCH = true（0540ff9b…）

FORWARD_LEDGER_ROWS_WRITTEN = 0
FUTURE_LEAKAGE = 0（MAX_DATA_DATE_USED = 2026-08-05）

DATA_LAYER_FILES_CHANGED = research/publish_adr008_canonical_v01.py、research/tdx_tencent_catchup_v02.py、staged/canonical data artifacts（src production data-layer 未改；复用现有 create_snapshot）
SCREEN_INFRA_FILES_CHANGED = 0（现有 screen engine 原样调用）
STRATEGY_FILES_CHANGED = 0（strategy.yaml、thresholds、B1/B2/S1/invalid、Quiet Score V02、V02 reference/protocol 均未动）

ACTUAL_FORWARD_START_DATE = DEFERRED（8/6 因候选为 0 无法 freeze；8/6 与已错过日期永久 NOT_STARTED_DATA_DEPENDENCY）

STATUS = BLOCKED_DATA_PIPELINE_INTEGRATION

## 阻塞说明

- 唯一主阻塞：ADR-008 日线链路（TDX+Tencent CONFIRMED）与 production screen 已就绪并验证（发布、历史 parity、screen regression、states 推进 8/5 全部通过），但 limit-up pool 的 8/3-8/5 数据源未接入（Eastmoney 禁用、TDX/Tencent 无 pool 接口）→ 新快照 pool 仅含 ≤7/31 行 → screen 在 catch-up 日期无法维持/生成 B1/B2 状态 → D1 candidate universe = 0。
- 需 Architect/人工决策：为 ADR-008 增加合法 limit-up pool 源（例如可用的公开涨停池接口 + 每日归档），或明确 catch-up 期间 pool 缺失的 screen 语义。
- 次要未实现：corporate-action 检测（NOT_IMPLEMENTED，已在报告中显式 caveat）。
- 未执行真实 Forward freeze；09:45/10:00 未执行；ledger 保持 0。

---

## 消息 3 — ChatGPT

这次我建议把“涨停池”拆成两层：

核心 LIMIT_UP_EVENT_POOL 自己算；首封时间、炸板次数等 LIMIT_UP_ENRICHMENT 才依赖外部接口。

这是可行的，因为交易所涨停规则本身是确定的。2026 年 7 月 6 日起，沪深主板包括风险警示股票都是 10%；创业板和科创板是 20%；北交所是 30%。沪深新股上市前 5 个交易日不设涨跌幅，北交所上市首日不设涨跌幅。
BSE
+3
上海电气
+3
深圳证券交易所
+3

而且除权日绝不能简单拿“昨天 raw close”算涨停价。上交所现行规则明确，除权除息日以除权除息参考价作为涨跌幅基准，所以我们应该优先使用 canonical 中当天的 preclose/reference_price。
上海电气

直接给 Codex：


执行：

DERIVED_LIMIT_UP_EVENT_POOL_V01
Architect Decision

停止让外部“涨停池 API”成为 production screen 的 mandatory dependency。

新的架构：

CONFIRMED DAILY CANONICAL
        │
        ↓
PRICE-LIMIT RULE ENGINE
        │
        ↓
DERIVED LIMIT_UP_EVENT_POOL
        │
        ↓
PRODUCTION SCREEN / ANCHOR DETECTION

外部涨停池以后仅作为：

LIMIT_UP_ENRICHMENT

例如：

first_limit_time
last_limit_time
break_count
seal_amount
limit_reason
industry

这些增强字段缺失不得阻塞：

limit-up anchor
production screen
Forward Epoch
1. 核心目标

使用已经发布的：

snap-2026-08-05-d9e93fccc966

中的 CONFIRMED raw-unadjusted daily bars，

为：

2026-08-03
2026-08-04
2026-08-05

派生正式：

LIMIT_UP_EVENT_POOL

然后重新推进 production screen。

不得使用 Eastmoney 涨停池。

不得重新抓 Tushare。

不得根据股票后来走势判断是否属于涨停。

2. 先审计 production screen 实际消费哪些 pool 字段

在写代码前查清：

screen engine
strategy evaluator
anchor detector
limit_up_pool loader

实际读取字段。

输出：

LIMIT_POOL_FIELDS_CONSUMED_BY_PRODUCTION

明确区分：

REQUIRED CORE

真正影响：

anchor detection
B1/B2 state
support
invalid
S1

的字段。

OPTIONAL ENRICHMENT

仅展示/研究使用的字段。

禁止因为旧 Eastmoney pool 有很多列，就伪造这些列。

若 production 实际只使用：

code
trade_date
is_limit_up

或类似 membership，

derived pool 就只保证这些核心语义。

3. 定义 LIMIT_UP_EVENT

正式 production anchor 的核心定义：

PRICE_LIMIT_APPLIES = true
AND
close == upper_limit_price

比较必须使用：

price tick / Decimal exact semantics

不得使用：

pct_change >= 9.8
pct_change > 9.9
round(return, 2) == 10

这种模糊判断。

4. 区分“封死涨停”和“盘中摸板”

增加：

LIMIT_UP_CLOSE

定义：

close == upper_limit_price

另可计算：

LIMIT_UP_TOUCH

定义：

high == upper_limit_price
AND
close < upper_limit_price

但：

LIMIT_UP_TOUCH

不能自动进入原 frozen：

涨停锚点

除非当前 production 旧语义本来就是“盘中触板也算 anchor”。

必须通过旧 pool regression 判断。

不得自行改变 anchor 语义。

5. reference price

计算涨停价时，优先使用 canonical 当天：

preclose

或现有 schema 中语义等价的：

price_limit_reference
previous_close_reference

不要使用：

previous trading day's raw close

作为默认替代。

原因：

除权
除息
送转
配股

日的涨跌幅基准可能不同于上一交易日 raw close。

正式字段：

LIMIT_REFERENCE_PRICE_SOURCE

记录：

CANONICAL_PRECLOSE
6. preclose 缺失 policy

如果：

preclose missing

不得：

use yesterday close silently
forward fill
infer from pct_change

标记：

LIMIT_RULE_STATUS =
REFERENCE_PRICE_MISSING

该股票：

LIMIT_UP_EVENT = UNKNOWN

不得进入 derived pool。

7. price-limit rule table 必须 date-aware

建立正式：

PRICE_LIMIT_RULE_TABLE

不要把：

10%
20%
30%

散落硬编码在多个函数。

至少包含：

effective_from
effective_to
exchange
board
security_type
risk_warning_status
limit_ratio
no_limit_rule
tick_size
rule_source
8. 2026-08 当前规则

针对当前 catch-up 日期：

SSE MAIN BOARD
limit_ratio = 10%

包括 2026-07-06 起主板风险警示股票：

10%
SZSE MAIN BOARD
limit_ratio = 10%

包括 2026-07-06 起主板风险警示股票：

10%
STAR
limit_ratio = 20%
CHINEXT
limit_ratio = 20%
BSE
limit_ratio = 30%

规则必须可追溯到交易所规则文档。

不要只写：

if code.startswith(...)
9. 历史规则不要被当前规则覆盖

即使当前 catch-up 是 2026-08，

rule engine 必须支持 effective date。

例如：

MAIN_BOARD_ST
before 2026-07-06:
5%

from 2026-07-06:
10%

不要用 2026 当前规则反算 2024/2025。

但本任务：

DO_NOT_REGENERATE_OLD_FROZEN_POOL

≤ 2026-07-31 的正式历史 pool 保持 immutable。

10. board / exchange metadata

优先使用项目已有：

security master
exchange metadata
board classification

得到：

SSE_MAIN
STAR
SZSE_MAIN
CHINEXT
BSE

不要仅依赖代码前缀。

如果没有可靠 metadata，

允许建立统一：

SECURITY_MARKET_CLASSIFIER

但必须：

explicit
tested
auditable

code prefix 只能是经过测试的 fallback。

11. 新股 / 无涨跌幅日

必须识别：

NO_PRICE_LIMIT_SESSION
SSE / SZSE

IPO 上市后的：

前 5 个交易日

不实行普通价格涨跌幅限制。

BSE

IPO：

上市首日

无涨跌幅限制。

同时处理现行规则中的：

relisting first day
delisting-period first day
other exchange-defined no-limit sessions

这些日：

PRICE_LIMIT_APPLIES = false
LIMIT_UP_EVENT = false

不能因为涨了 10% / 20% / 30% 就叫涨停。

12. listing age metadata

优先读取可信：

listing_date

然后用交易日历计算：

listing_session_number

不能用：

calendar days since listing

如果 listing date 无法确定，而股票可能处于 no-limit window：

LIMIT_RULE_STATUS =
LISTING_AGE_UNKNOWN

不得猜。

13. 涨停价格计算

使用：

upper_limit_unrounded =
reference_price * (1 + limit_ratio)

再按交易所 price tick 规则得到：

upper_limit_price

A 股正常价格 tick：

0.01 RMB

使用 Decimal。

禁止 Python binary float round() 直接承担交易所价格舍入语义。

建立统一：

round_to_price_tick()

使用明确的：

ROUND_HALF_UP

或项目已有且与交易所一致的实现。

14. 输出 derived pool 核心字段

至少：

trade_date
code
name

exchange
board

reference_price
reference_price_source

price_limit_ratio
upper_limit_price

open
high
low
close
volume
amount

price_limit_applies

limit_up_touch
limit_up_close

limit_rule_status

pool_source =
DERIVED_FROM_CONFIRMED_CANONICAL

canonical_snapshot_id

source_row_hash
rule_version
derived_at
15. 不伪造 Eastmoney enrichment

以下字段如果没有合法数据：

first_limit_time
last_limit_time
break_count
seal_amount

必须：

NA

或不存在。

禁止根据 daily bar 编造：

first_limit_time = 09:30
break_count = 0
16. 首先做 frozen-pool overlap regression

这是正式发布前最重要的 gate。

使用已经存在：

<= 2026-07-31

的旧 canonical + legacy limit-up pool。

不要重写这些历史文件。

选择规则已经稳定的重叠区间，优先：

2026-07-06
→
2026-07-31

用新 derived engine 计算一份：

DERIVED_POOL_AUDIT_ONLY

然后与 frozen legacy pool 比较。

输出：

LEGACY_POOL_N
DERIVED_POOL_N

MEMBERSHIP_MATCH_N

LEGACY_ONLY_N
DERIVED_ONLY_N

以及：

LIMIT_POOL_MEMBERSHIP_DIFF_N
17. 每个 mismatch 必须解释

输出：

limit_pool_mismatch_audit.csv

包含：

trade_date
code
name

legacy_member
derived_member

board
reference_price
limit_ratio
calculated_upper_limit
daily_high
daily_close

listing_age
risk_warning_status

mismatch_reason

原因分类至少：

ROUNDING
NO_LIMIT_SESSION
REFERENCE_PRICE
BOARD_CLASSIFICATION
RISK_WARNING_RULE
LEGACY_POOL_DATA_QUALITY
UNKNOWN
18. Regression gate

如果：

LIMIT_POOL_MEMBERSHIP_DIFF_N = 0

直接：

DERIVED_POOL_COMPATIBILITY = PASS

如果不为 0：

不要直接 FAIL。

先判断所有差异是否有明确合法解释。

例如 legacy pool 本身：

missing row
incorrect old provider row

必须有独立证据才能标：

LEGACY_POOL_DATA_QUALITY

禁止为了让 regression 通过而事后改规则。

存在：

UNKNOWN

或策略语义差异：

DERIVED_POOL_COMPATIBILITY = FAIL
STOP
19. 特别检查旧 production 到底是 CLOSE_LIMIT 还是 TOUCH_LIMIT

使用 overlap audit 确认：

legacy pool membership

到底对应：

close == upper_limit

还是允许：

high == upper_limit && close < upper_limit

根据实际 legacy pool 语义锁定：

FROZEN_ANCHOR_LIMIT_SEMANTIC

不得凭经验决定。

如果旧 pool = 收盘封板：

保持：

ANCHOR = LIMIT_UP_CLOSE

如果不是：

STOP 交回 Architect。

20. 发布 8/3-8/5 derived pool

只有：

DERIVED_POOL_COMPATIBILITY = PASS

才生成：

2026-08-03
2026-08-04
2026-08-05

正式 derived limit-up pool。

新 pool snapshot：

legacy frozen pool <= 2026-07-31
+
derived pool >= 2026-08-03

旧历史 pool 永远不修改。

生成新的：

POOL_SNAPSHOT_ID
POOL_HASH
POOL_MANIFEST_HASH
21. 不修改 daily canonical snapshot

当前：

snap-2026-08-05-d9e93fccc966

保持不变。

本任务只新增/发布：

limit_up_event pool layer

不要因为 pool 问题重做 daily snapshot。

22. screen regression 再检查一次

在接入新 derived pool 后：

重新对：

2026-07-31 frozen baseline

跑 screen regression。

要求：

SCREEN_0731_OUTPUT_HASH

仍等于 frozen：

9abb16e4...

目标：

SCREEN_REGRESSION_DIFF_N = 0
23. 重跑 8/3 → 8/5 screen catch-up

用：

new daily canonical snapshot
+
new limit-up pool snapshot

重新推进 screen：

2026-08-03
2026-08-04
2026-08-05

注意：

之前因 pool 缺失生成的：

NORMAL / invalid states

属于数据输入不完整产物。

允许从：

2026-07-31 frozen state

重新 deterministically rebuild 到 8/5。

不要把错误 catch-up state 当新的冻结历史。

24. 重建方式必须可审计

推荐：

BASE_STATE_DATE = 2026-07-31
REBUILD_SESSIONS =
2026-08-03
2026-08-04
2026-08-05

不要人工 patch 个股 state。

全量/确定性重放。

输出：

SCREEN_REBUILD_OUTPUT_HASH
25. 重新 candidate dry-run

完成 screen rebuild 后针对：

TARGET_FORWARD_SESSION

执行 V02 candidate freeze dry-run。

要求：

candidate source =
PRODUCTION_SCREEN_STATES

输出：

CANDIDATE_DRY_RUN_N
CANDIDATE_DRY_RUN_HASH

SETUP_STAGE_COUNTS

B1_READY_N
B2_READY_N
B2_CONFIRMED_N

如果：

CANDIDATE_DRY_RUN_N = 0

不要立刻判错误。

报告：

ZERO_CANDIDATE_REASON =
VALID_STRATEGY_OUTPUT
or
DATA_PIPELINE_ERROR
26. D1 TDX 5m

只有 candidate > 0 后：

获取：

TARGET_D1 TDX 5m

计算：

D1_CUM_VOLUME_0945
D1_CUM_VOLUME_1000

报告 coverage。

27. 外部 enrichment 后续单独做

不要因为核心 pool 已解决，就马上重新接：

Eastmoney pool

以后可另开：

LIMIT_UP_ENRICHMENT_V01

研究：

first seal time
last seal time
break count
seal strength

这些不是当前 Forward 启动的前置条件。

28. Corporate action 与 limit-up rule 的关系

本任务至少解决：

涨停价 reference price

必须用 canonical 当日 preclose。

如果该字段已反映交易所除权参考价：

记录：

CORPORATE_ACTION_LIMIT_REFERENCE_HANDLED = true

但这不等于：

完整 corporate action detector 已实现

Forward Quiet Score 的：

CORPORATE_ACTION_DETECTION_STATUS

仍可继续：

NOT_IMPLEMENTED

两者不要混淆。

29. Tests

至少新增：

test_limit_ratio_rule_table_date_aware

test_main_board_202608_limit_10pct
test_star_limit_20pct
test_chinext_limit_20pct
test_bse_limit_30pct

test_mainboard_st_pre_20260706_5pct
test_mainboard_st_from_20260706_10pct

test_no_limit_first_five_sessions_sse
test_no_limit_first_five_sessions_szse
test_bse_no_limit_first_session

test_uses_canonical_preclose_not_previous_raw_close

test_decimal_tick_rounding

test_limit_touch_vs_close

test_missing_preclose_not_in_pool

test_no_fake_enrichment

test_frozen_pool_overlap_regression

test_old_pool_immutable

test_screen_0731_regression

test_screen_rebuild_with_derived_pool

运行：

python -m compileall -q src research
git diff --check

以及相关全量测试。

30. 最终输出

只返回：

DERIVED_LIMIT_UP_EVENT_POOL_V01_REPORT

包含：

LIMIT_POOL_FIELDS_CONSUMED_BY_PRODUCTION

FROZEN_ANCHOR_LIMIT_SEMANTIC

PRICE_LIMIT_REFERENCE_FIELD

PRICE_LIMIT_RULE_VERSION

OVERLAP_AUDIT_FROM
OVERLAP_AUDIT_TO

LEGACY_POOL_N
DERIVED_POOL_N

LEGACY_ONLY_N
DERIVED_ONLY_N

LIMIT_POOL_MEMBERSHIP_DIFF_N
UNKNOWN_MISMATCH_N

DERIVED_POOL_COMPATIBILITY

DERIVED_20260803_N
DERIVED_20260804_N
DERIVED_20260805_N

POOL_SNAPSHOT_ID
POOL_HASH
POOL_MANIFEST_HASH

OLD_POOL_UNCHANGED

SCREEN_0731_REGRESSION_DIFF_N

SCREEN_REBUILD_TO

READY_20260805_N
STALE_N
ERROR_N

CANDIDATE_DRY_RUN_N
CANDIDATE_DRY_RUN_HASH

B1_READY_N
B2_READY_N
B2_CONFIRMED_N

D1_TDX_5M_0945_COMPLETE_N
D1_TDX_5M_1000_COMPLETE_N
D1_TDX_5M_MISSING_N

CORPORATE_ACTION_LIMIT_REFERENCE_HANDLED
CORPORATE_ACTION_DETECTION_STATUS

STRATEGY_FILES_CHANGED
FORWARD_LEDGER_ROWS_WRITTEN
FUTURE_LEAKAGE

STATUS

硬要求：

OLD_POOL_UNCHANGED = true

SCREEN_0731_REGRESSION_DIFF_N = 0

STRATEGY_FILES_CHANGED = 0

FORWARD_LEDGER_ROWS_WRITTEN = 0

FUTURE_LEAKAGE = 0

允许状态：

DERIVED_POOL_READY_FOR_FORWARD

BLOCKED_LIMIT_RULE_REGRESSION

BLOCKED_LIMIT_REFERENCE_DATA

BLOCKED_SECURITY_METADATA

BLOCKED_SCREEN_REBUILD

完成后停止。

不要真实 freeze。
不要执行 09:45 / 10:00。

我更倾向这个方向，而不是继续寻找新的“免费涨停池 API”，因为涨停本身是交易规则 + 真实行情的确定性事实，本来就应该属于我们自己的 canonical derived layer。

外部网站真正有额外价值的是“09:37 首封、炸板 2 次”这种日 K 无法知道的信息，而不是告诉我们“今天到底有没有收在涨停价”。这样系统的数据依赖会再少一个单点故障。
上海电气
+2
深证所文档
+2

---

## 消息 4 — 用户

把这个对话和之前那个已经 崩溃的对话总结，我准备做一次项目审查，包括我们聊的，还有GitHub上的策略

---

## 消息 5 — ChatGPT

可以。这次我建议把它当成一次真正的 Strategy + Research + Data + Engineering 四层项目审查，而不是只检查“选股公式准不准”。

我把当前对话、之前崩掉的长对话、以及现在 GitHub 两个仓库里的状态合在一起，得到下面这份审查底稿。

A股「首板回踩再启动」项目审查摘要

审查时间基准：2026-08-05 20:45 CST 左右

当前项目已经从最初的“看图总结涨停回调规律”，发展成了一个有：

冻结策略 → PIT 数据 → 状态机 → 历史 episode → execution reality → research overlay → intraday research → Forward Paper → canonical warehouse → 数据源对账 → immutable snapshot

的完整研究系统。

但目前有一个非常重要的现状：

研究基础设施已经相当成熟，但策略本身还没有被证明具有稳定、可执行的正期望。

这是这次项目审查最应该守住的结论。

一、项目最初要解决的问题

策略最早来自我们反复复盘的这种走势：

低位/中低位第一次强势资金表态 → 涨停或强攻击 → 回调/横盘换手 → 结构不坏 → 支撑企稳 → 二次启动。

后来正式命名：

「首板回踩再启动策略 / Second Launch Radar」

“三倍量”只是最早观察到的一种资金表态形式，并不是策略本体。

B 点也逐渐被拆开：

概念	当前理解
First Attack	第一次资金明显表态
B1	回调后的低风险结构确认，更偏赔率
B2	再攻击/突破确认，更偏确定性
Support	结构承接参考
Invalid	结构真正失效的位置
S1	第一目标/压力观察位
Second Launch	第二次攻击真正成立
Post-B	主启动段已兑现，进入持仓/NO CHASE

GitHub 的通俗策略说明已经明确：系统真正解决的是注意力分配，不是预测哪只股票一定涨停，也不是机械找最低点。

二、GitHub 当前正式冻结策略

知识库：

Luke808real/a-share-strategy-brain

代码库：

Luke808real/a-share-limit-pullback

GitHub 知识库当前仍把：

phase-2d0

作为冻结策略版本，冻结 commit：

e865de484e40e45b1d2044ee1c58247c76f3a758

并明确 human-approved merge 才能改变 production truth。

Production 的真正机器状态机仍然是：

NORMAL → LIMIT_ANCHOR → WATCH_PULLBACK → B1_READY → B2_READY → B2_CONFIRMED

以及终态 INVALID。

Support、Invalid、S1、B2 Trigger 都具有 frozen_as_of / eligible_from，当天算出的东西不能反过来影响当天判断，这是整个系统防未来函数的核心之一。

三、当前 frozen strategy 的关键参数

GitHub strategy.yaml 当前还是非常明确的一套规则：

模块	当前 frozen 规则
Universe	沪深主板
上市时间	≥120 交易日
ST	排除
Anchor	涨停收盘
近期涨停	7日内 1–2 次
连板	要求非连续
首板	require_first_board=true
首封	FULL 数据下 ≤14:30
B1 窗口	锚点后 1–7 日
B1 optimal	2–5 日
B1 相对 Anchor	0.96–1.08
B1 当前量/Anchor	≤0.85
B1 condition ratio	≥60%
B2 当日涨幅	2%–7%
B2 收盘位置	≥0.65
B2 放量	1.10–1.80
B2 condition ratio	≥60%
最低 risk/reward	1.5

这里有个审查时一定要注意的问题：

这些是 Production Truth，不等于我们聊天里后来讨论的所有新想法。

例如 Quiet Compression、VWAP acceptance、筹码分布、板块、周线环境、开盘修复、三倍量，都没有因此自动变成 production rule。

四、项目从 2B 到 2D 做了什么

早期 Phase 2B 最大的价值并不是找到了赚钱公式，而是把策略语义清理干净。

特别是 2B.2 → 2B.3 后确定：

结构成立 ≠ 值得现在买。

所以：

setup_stage

和：

Entry Room / S1 / risk-reward / entry_quality

被正式解耦。

例如：

一只股票完全可以是：

B1_READY

但因为离 S1 太近：

Entry Room = NONE

结果是：

结构仍然成立，但不适合新开仓。

不能因为赔率不好就把结构历史改写成 WATCH。

这个设计后来成为整个系统非常重要的基础。GitHub STRATEGY_MASTER 仍明确要求 B1/B2 不允许被 S1、risk/reward、Entry Room 反向改写。

五、双价格体系：这里需要纠正我们聊天里的一个简化说法

之前你问我前复权时，我用比较容易理解的方式说过：

“交易看不复权，趋势看前复权。”

概念方向没问题，但项目 production 的严格实现不是直接使用供应商 qfq。

GitHub frozen strategy 实际是：

RAW price

用于：

涨停、Support、Invalid、S1、B2 trigger、成交、K线。

而趋势/均线使用：

point-in-time continuous price

它由当时已知的：

close / preclose

链式构造。

并且明确禁止：

用今天重新计算出来的历史前复权数据做严格历史评价。

所以这次审查应该把这一条重新写清楚：

Production = RAW + PIT Continuous

而不是：

RAW + vendor qfq

这是一个很重要的语义保护。

六、Phase 2C：数据系统开始真正成型

到了 2C，项目从“单股票策略函数”进入真实全市场数据工程。

最终形成：

canonical snapshot

→ 全市场 PIT replay

→ production screen

→ immutable hash

经典冻结 snapshot：

snap-2026-07-31-b5f84004de8a

覆盖：

3191 只沪深主板股票。

GitHub baseline 记录 2C.2C actionable 数为 78。

同时明确：

canonical row 必须来自单个 selected provider；

禁止字段级拼接；

snapshot immutable；

screen 只消费正式 canonical；

historical replay 必须 point-in-time。

这一步实际上比任何一个技术指标都重要。

七、Phase 2D.0：第一次大规模历史评价

这是项目一个非常重要的转折点。

Phase 2D.0：

3191 stocks

589 sessions

31,422 episodes

结果并不好。

原始 actionable expectancy：

Stage	Strict R
B1_READY	-0.1580
B2_READY	-0.0979
B2_CONFIRMED	-0.0599

也就是说：

原始机械 B1/B2 并没有证明稳定赚钱。

但某些高质量子集出现了正方向，例如 entry_quality >= 80 的 descriptive expectancy 一度较好。由于当时仍存在 FINAL_VINTAGE、执行与日 K 路径歧义等问题，所以没有因此优化 production。

这是项目审查必须保留的“反直觉事实”。

不能因为后面研究越来越复杂，就忘了：

底层 mechanical entry edge 尚未被证明。

八、B2 outcome correction

后来我们发现 B2 历史结果评价存在执行语义问题。

最终 corrected episodes hash：

66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093

31,422 episode 中：

6,686 个 derived outcome 被修正。

修正之后：

B2_READY strict expectancy

从：

-0.0979

变成：

-0.0079

但 conservative：

-0.1216

而且仍存在 OHLC 路径模糊。

所以它不是“B2 已经证明有效”，而是：

原来对 B2 的评价方式有明显误差，修正后更接近中性，但仍没有足够证据证明 edge。

九、Phase 2D.1A：把 A 股 T+1 真正加进来

之后做了 execution reality。

这一步把：

T+1

gap stop

fill

日 K 内路径歧义

真正引入。

结果非常值得重视。

GitHub baseline 当前记录：

Cohort	strict	conservative
B1 all	+0.0049	-0.2230
B1 setup quality ≥80	+0.1707	-0.0204
B1 entry quality ≥80	+0.3954	+0.1121
B2 gap	-0.0642	-0.0642

这说明一个目前仍很值得继续验证的方向是：

不是“所有 B1”，而可能是“高质量 + 好 Entry Room 的 B1”。

但它仍然只是历史证据，不允许在同一数据里继续搜阈值。

十、Context / Sector / Weekly / Chip 研究

之前崩掉的长对话里，我们做过大量“能不能改善选股”的上下文研究。

最终并没有胡乱留下很多规则。

相反，大部分被拒绝了。

GitHub baseline 已经记录：

Weekly favorable：REJECT

joint context：REJECT

washout：OBSERVE ONLY

price-volume context：REJECT_FOR_PROMOTION

sector：LOW_CONFIDENCE_PROXY

chip snapshot：PROBE_FAILED

而且已经明确：

no_further_in_sample_threshold_tuning = true

这一点项目做得是好的：

研究失败被保留下来，而不是删除。

十一、Forward Epoch 0

在此前那段对话里，还做过一个人工观察型：

FORWARD_EPOCH_0

2026-08-03 final watch：

核心 B1：

600227 / 000659 / 600578

Pullback Wait：

600844 / 002534

关键 B2 trigger observation：

002242

并且冻结后禁止 retroactive modification。

但这个 Epoch 更接近：

Human Watch / Context Forward

而不是我们现在做的：

Quiet Score formal statistical Forward Paper。

审查时两者不要混在一起。

十二、成功/失败统一 Case Set

之后研究路线发生了一次明显升级：

不再继续挑几只“漂亮案例”讲故事，而是建立统一 SUCCESS/CONTROL cohort。

最终 PIT cases：

8,746

其中：

Label	N
SUCCESS	409
FAILED_BREAKOUT	950
NO_LAUNCH	1,730
STRUCTURE_FAIL	5,415
UNKNOWN	242

这一批样本是后面几乎所有 morphology / intraday 研究的共同基础。

GitHub research 目录当前也已经正式包含 V01/V01A/V01B case builder 和这些 8,746 case 数据。

十三、最早的“开盘洗盘 → 快速收回”假设

最早我们的直觉是：

SUCCESS 可能更常出现“早盘快速下杀 → 快速收回 → 二次起飞”。

最初少数案例完全不能支持这一点。

之后 GitHub PR23/24 把研究扩展到了正式 SUCCESS / FAILED_BREAKOUT 对照。

最新 GitHub V02A 5m：

SUCCESS = 40

FAILED = 99

最后结论非常明确：

“开盘恐慌下杀 → 快速收回 → 逐步走强”整体 NOT_SUPPORTED。

真正的区分开始出现在：

10:00–10:30以后。

SUCCESS 更倾向于：

站在 S1 上方；

离 VWAP 正偏离扩大；

继续刷新高点；

触及 S1 后不容易重新掉下来。

而不是：

“早盘洗得更狠”。

GitHub 把目前最强 descriptive pattern 总结成：

S1_POSITION_PLUS_VWAP_STRENGTH_BY_1030

但仍然：

OBSERVE_ONLY / no production change。

十四、我们当前对话新做的 B 点 Morphology

随后我们的研究问题稍微改变了：

不是：

“已经发动的股票盘中长什么样？”

而是：

“在准备 B 点时，什么结构更可能最终 SUCCESS，而不是 FAILED？”

于是出现：

B_POINT_ENTRY_MORPHOLOGY_V01

最初日线研究曾看到：

HIGH_LEVEL_CONSOLIDATION

shallow pullback

probe count

price recovery

D0 support test

volume dry-up

等特征。

但后面发现：

rank-biserial tie handling 有问题。

修正之后：

很多最早看起来很强的效应接近消失。

这是一个非常重要的研究质量事件。

我们没有隐藏它，而是把早期结论降级。

十五、真正留下来的 Intraday B-point 信号

随后严格改成 checkpoint-causal intraday validation。

这里出现了一个目前非常有价值、但仍未被 Forward 验证的方向：

Quiet Compression

SUCCESS 相比 FAILED_BREAKOUT / STRUCTURE_FAIL：

早盘反而更倾向：

成交量消耗更低

最大回撤更浅

区间更窄

即：

好的 B 点不一定“看起来更强”，反而可能更加安静。

最重要的两个历史特征：

CUM_VOLUME_VS_D1_SAME_TIME

SESSION_LOW_VS_PREV_CLOSE

次级：

SESSION_RANGE_PCT

而：

VWAP strength

fast recovery

support reclaim

probe

更像：

Activation

而不是：

Quality

所以我们开始明确拆成：

QUALITY GATE

vs

ACTIVATION TRIGGER

这个思想是当前研究线里最值得 Forward 验证的东西。

十六、但 GitHub 的 V02A 与 Quiet Compression 并不矛盾

这次审查需要特别检查这一点。

GitHub V02A 在研究的是：

S1 attack / outcome event 当天

它发现：

10:00以后 SUCCESS 要更强地站住 S1/VWAP。

而 Quiet Compression 研究的是：

更早的 B-point candidate checkpoint

它发现：

真正发动之前，更好的候选可能更安静。

所以理论上完全可能出现：

启动前：quiet compression

然后：

activation 后：S1/VWAP acceptance expansion

其实这恰好可能拼成一条完整路径：

Quiet → Activate → Accept → Expand

这应该成为项目审查后的一个重要研究框架。

十七、Forward Paper V01 为什么被废弃

我们本来准备正式开始：

FORWARD_EPOCH_1

但在启动前发现了两个 reference artifact 缺陷：

第一：

批准的 volume pace 已经是：

F = D0累计量 / D-1同时刻累计量

但是 V01 reference 实际还按：

A = D0累计量 / D-1全天量

生成。

第二：

quiet_score_reference_v01.json

没有真正保存三个 component CDF。

因此 runner 无法严格复现冻结 Quiet Score。

所以：

V01 = SUPERSEDED_PRESTART_REFERENCE_DEFECT

不是：

strategy failed。

而且这个问题发现时：

Forward ledger rows = 0

没有污染真正的 Forward 数据。

这次处理是正确的。

十八、Forward V02 已经修好

现在真正冻结的本地 V02：

REFERENCE_ELIGIBLE_N = 195

原 206 中排除 11 个：

全部因为：

2026-06-05 D1 same-time 5m incomplete

而不是根据 outcome 删除。

Builder：

REFERENCE_OUTCOME_FIELDS_READ = 0

V02 使用：

EMPIRICAL_MIDRANK_ECDF_V1

Quiet Score：

1/3 × inverse(volume pace percentile)

1/3 × inverse(abs(drawdown) percentile)

1/3 × inverse(range percentile)

TDX 与 frozen minute data compatibility：

volume pace 09:45 ≈ 0.9999

10:00 ≈ 1.0000

price parity exact

score median diff 0.000855

P95 0.004274

rank correlation 0.9999

quartile agreement 100%

所以：

PASS_TDX_V02

V02 hashes：

PROTOCOL
aaca250e9bea16ca8f8ef4b09597670a2fbbc75dac968dc8a80cb65f00bbc131

REFERENCE
dd307825740e89367f76ba36fdb5ba632950b4c30e2b406894b1f45d3bf89cea

MANIFEST
0540ff9bd68bc6c06a3643f2942c09c55bbf6a43a02f5f5411ce093901ab2cb9

但：

真正的 Forward Day 1 仍然没有发生。

这是审查时一定不能搞错的。

十九、数据源架构已经发生重大迁移

原 GitHub ADR-006 仍写的是：

Tushare primary + AKShare confirmation + BaoStock audit。

但现实环境已经证明：

Tushare：

TOKEN INVALID

Eastmoney：

Proxy / endpoint unstable

所以当前本地已经迁移成：

Daily

TDX PRIMARY

Tencent CONFIRM

BaoStock AUDIT

5m

TDX PRIMARY

Sina AUDIT

TDX + Tencent 的 historical parity 非常干净。

并且新的 production canonical snapshot 已经在本地成功产生：

snap-2026-08-05-d9e93fccc966

旧：

snap-2026-07-31-b5f84004de8a

保持 immutable。

二十、当前真正的项目阻塞点

已经不是：

Tushare。

不是：

Eastmoney。

不是：

Quiet Score。

不是：

TDX。

而是：

Limit-up Pool

因为 production screen 原先依赖外部涨停池。

8/3–8/5 没有对应 pool 后：

B1/B2 lifecycle 无法正确延续。

最终 candidate dry-run：

0

因此当前最后一个核心架构任务已经转成：

从 CONFIRMED raw daily canonical + price-limit rule 自己派生 LIMIT_UP_EVENT_POOL。

外部 API 以后只提供：

首封时间、炸板次数、封单等 enrichment。

而：

“今天是不是涨停收盘”

应该成为我们自己的 derived canonical fact。

这是目前项目实际停止的位置。

二十一、GitHub 与本地现在存在明显 Truth Drift

这是这次项目审查我最建议优先解决的问题。

GitHub STRATEGY_MASTER 目前仍然描述 ADR-006：

Tushare + AKShare。

GitHub 03_Decisions 目前也只公开到：

ADR-006。

而本地已经存在：

ADR-007

ADR-008 TDX-centric architecture

Forward V02

Reference Repair

8/5 canonical snapshot

derived limit-up pool plan

也就是说现在存在：

Local Truth > GitHub Knowledge Truth

的问题。

这不是研究错误，但已经是项目治理风险。

二十二、GitHub code main 和 Production Truth 也需要重新对齐一次

GitHub 当前 Strategy Master 说：

production strategy = phase-2d0。

代码仓库 main 后来又合并了：

execution reality

performance optimization

research framework

PR23 intraday

PR24 V02A 5m

但这些理论上都不应改变 frozen strategy。

项目 operating model 本身也规定了四层 Truth：

Production Truth

Frozen Historical Evidence

Forward Observation

Research Overlay

并明确：

SUPPORTED != PROMOTED。

这次审查需要重新验证：

main 上所有 phase-2d0 之后的变更，到底哪些是 production infrastructure，哪些是 research，哪些真正碰了 strategy semantics。

二十三、一个需要重点防止的语义混乱

GitHub 现在同时出现两套语言。

Production：

B1_READY / B2_READY / B2_CONFIRMED

人类通俗文档：

PREPOSITION / LAUNCH_READY / SECOND_LAUNCH / POST_B

本身没有错。

但建议审查时明确建立：

Human Concept → Production State

mapping。

否则以后很容易出现：

“Second Launch”

到底表示：

B2_CONFIRMED？

outcome SUCCESS？

S1 breakout？

盘中二次起飞？

不同研究使用不同定义的问题。

二十四、当前研究结论应该分成四类
分类	当前代表
Production Frozen	B1/B2 lifecycle、Support/Invalid/S1、snapshot timing、Entry Room
Historical evidence	phase-2d0 / 2D1A / corrected episodes
Research promising	Quiet Compression、Activation/Quality decomposition
Rejected / No Edge	opening shakeout、weekly context、joint context、多数 fast-reclaim 直觉

特别要保持：

“描述性支持” ≠ “可以交易”。

二十五、我认为这次项目审查最重要的 10 个问题

Production Truth 到底以哪个 commit/tag/hash 为唯一基线？

GitHub 与本地 ADR-007/008/V02 是否完整同步？

phase-2d0 后 main 的代码改动有没有任何 strategy semantic drift？

Limit-up anchor 能否完全从 canonical data deterministic reconstruction？

旧 external limit-up pool 与 derived pool membership 是否完全兼容？

RAW + PIT Continuous 是否在所有模块严格统一，彻底禁止 vendor qfq 混入 historical PIT？

SUCCESS/FAILED/NO_LAUNCH/STRUCTURE_FAIL label 有没有剩余 outcome leakage？

Quiet Compression 与 GitHub V02A S1/VWAP strength 是否属于不同阶段，而不是重复/冲突指标？

Forward V02 是否真正做到首次 observation 前完全冻结？

最终研究目标到底是“改善 PREPOSITION ranking”，还是直接构造机械 entry system？

我目前更倾向：

近期不要继续增加指标。

先把：

Truth Layers → GitHub同步 → derived limit-up pool → production screen → Forward V02 Day 1

全部闭环。

二十六、现在这个项目真正可以用一句话描述

目前它已经不是：

“一个涨停回调选股公式”。

而是：

一个以涨停后结构生命周期为核心，用机器筛选 Second Launch 候选、用 PIT 数据研究 B 点质量，并通过冻结 Forward observation 验证“Quiet → Activate → Accept → Expand”路径是否真实存在的 A 股研究系统。

但目前最重要的科学结论仍然是：

Mechanical B1/B2 尚未证明稳定正期望；Quiet Compression 仍处于 Forward 验证前；任何新规则都不应在第一批 Forward 数据出现前继续优化。

我建议这次项目审查的最终产物

最好最后形成一份唯一的：

PROJECT_AUDIT_2026-08.md

里面固定六张表：

Truth Source Audit

Strategy Semantic Audit

Research Evidence Matrix

Data Lineage Audit

Forward Integrity Audit

Open Technical Debt / Next Actions

然后所有“聊天里说过但没进入 GitHub”“GitHub 已过时”“本地有 artifact 但没 commit”“研究结论和 production rule 混用”的地方一次性清掉。

这会比继续马上做下一轮策略研究更有价值。
