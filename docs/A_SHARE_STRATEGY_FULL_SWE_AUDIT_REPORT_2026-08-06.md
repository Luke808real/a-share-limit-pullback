# A_SHARE_STRATEGY_FULL_SWE_AUDIT_REPORT

审计日期：2026-08-06（Asia/Shanghai）

审计模式：READ_ONLY_FULL_SWE_AUDIT。除本报告外，未修改策略、配置、数据、Forward、测试或运行状态；未启动 Forward，未合并 PR，未修复任何问题。

审计对象：

| 对象 | 审计基线 | 工作区状态 |
|---|---|---|
| 代码仓库 | GitHub main = e2d5b57d10f016e94730e69df875758361055f9f；本地 HEAD = e82ccc591f4c07812fc0f0ce49dd3283203834c7 | main 比本地 HEAD 多 PR #25 的 merge commit；本地有大量未跟踪研究/迁移文件，pyproject.toml 有未提交修改 |
| 知识仓库 | main = 5085eda13458b30c3b36e28009b8382e3ab0f791 | 有未提交 CASE_INDEX、案例、ADR-007、ADR-008 和研究说明 |
| 冻结策略 | phase-2d0 内容 commit = e865de484e40e45b1d2044ee1c58247c76f3a758；tree = cb786d72f513baf67d936b61176c4c89a17acfb9 | config、SPEC、DECISIONS 与 phase-2d0 哈希一致 |
| 最后一个可限定使用的快照 | snap-2026-07-31-b5f84004de8a，status = SCREEN_READY | 仅作为回滚/复核基线；不消除本文发现的长期 B2 语义冲突 |
| 当前默认快照 | snap-2026-08-05-d9e93fccc966，status = CURRENT | 已证实 correctness failure，禁止用于正式 screen、TradePlan、研究或 Forward |

证据等级：

- DIRECT_CODE：逐行检查实现与测试。
- DIRECT_DATA：对 DuckDB、Parquet、状态文件、manifest 做只读查询或哈希验证。
- EXECUTED：本次实际执行测试、编译、CLI、依赖检查与 profile。
- REMOTE_PRIMARY：通过 GitHub CLI 读取远端仓库、PR、workflow、release 和分支保护状态。
- RECORDED：复用已冻结且哈希可核验的历史 benchmark/research artifact。

## 1. EXECUTIVE SUMMARY

| 项目 | 结论 |
|---|---|
| PROJECT_HEALTH | CORRECTNESS_BLOCKER_FOUND |
| PRODUCTION_READINESS | NO。当前默认 canonical、limit-up derived layer 和全部 screen states 不可信 |
| RESEARCH_READINESS | LIMITED。冻结历史证据可继续只读使用；任何依赖 2026-08-03 至 2026-08-05 新快照的结果必须作废并重建 |
| FORWARD_READINESS | NO。Forward 尚未开始且 ledgers 为 0 行，这是好消息；runner 本身当前不可安全运行 |
| MAINTAINABILITY | MEDIUM-LOW。领域模型和不变量较强，但生产、研究、迁移脚本、数据发布和知识治理之间边界破裂 |
| FINAL VERDICT | CORRECTNESS_BLOCKER_FOUND |

### Stop-the-line

以下五项同时构成 P0_STOP_THE_LINE：

1. 2026-08-04 与 2026-08-05 共 10,251 行 canonical daily bar 的 preclose 不是上一交易日 close。它会直接改变连续价格、涨停判定、日收益、B2 和后续所有状态。
2. 当前 5,197 个 screen state 全部引用上述坏快照；其中 2,006 个代码属于 300、301、688 前缀，超出产品定义的沪深主板范围。当前 limit-up pool 又停在 2026-07-31。
3. Forward runner 将“自午夜起分钟数”与 HHMM 整数比较，09:45 会包含整日 48 根 5m bar；V02 模式还硬编码 V01 epoch/reference。若运行，将产生确定性的未来泄漏和协议错配。
4. B2_CONFIRMED 的代码/golden 可回退到 B2_READY，而冻结人类 State Machine 规定其只因 invalid/new anchor/expiry 退出。任务规则把任何 strategy semantic drift 定义为 P0；即使它是长期冲突，也必须先决议再继续。
5. ADR-008 provider prototype 捕获任意异常后 silent continue/None，并在没有完整 failure registry/coverage gate 时进入 production publication。原始规则把 provider silent fallback 或 untraceable production result 均定义为 P0；本路径按 P0 处理。

### TOP_5_RISKS

| 排名 | 风险 | 直接后果 |
|---|---|---|
| 1 | ADR-008 catch-up 的 preclose 被固定为 2026-07-31 close | 当前 canonical 与所有衍生状态不可用于决策 |
| 2 | snapshot status、pool freshness、主板 universe 没有消费端硬门禁 | 坏数据可被“latest snapshot”静默选中 |
| 3 | Forward checkpoint 时间过滤、epoch、reference、candidate fields 错误 | 一旦启动即产生未来泄漏或不可复核记录 |
| 4 | B2_CONFIRMED lifecycle 的人类真源与代码/golden 冲突 | frozen semantic fidelity 不能证明 |
| 5 | 未审阅 publisher、非事务 snapshot/state、可覆盖 Forward ledger | Git/ADR/data truth 分叉，崩溃或并发可留下不可追溯结果 |

### TOP_5_STRENGTHS

| 排名 | 强项 | 证据 |
|---|---|---|
| 1 | 冻结策略基线可验证 | strategy.yaml、SPEC.md、DECISIONS.md 与 phase-2d0 哈希完全一致 |
| 2 | 核心模型有较强不变量 | eligible_from、INVALID、snapshot immutability、setup/entry separation 有模型和测试保护 |
| 3 | PIT 意图清晰且大量例测存在 | same-day trigger、future row、support/S1 freeze、Entry Room 不改 stage 等均有测试 |
| 4 | 性能优化有等价性证据 | one-pass artifact 记录 60.231s → 2.754s、21.87x，output/state hash 相等 |
| 5 | 研究结论总体克制 | REJECT / OBSERVE_ONLY / SUPPORTED 与 SUPPORTED != PROMOTED 已形成治理语言；Forward 实际仍为 0 行 |

### 立即使用边界

| 能否继续 | 范围 |
|---|---|
| 可以 | 只读分析 phase-2d0、7 月 31 日冻结快照、哈希匹配的 corrected episodes 与既有研究 artifact |
| 不可以 | 使用 8 月 5 日 snapshot、现有 states、8 月 3–5 日 screen 输出生成观察卡或 TradePlan |
| 不可以 | 启动 Forward V01/V02、修补后回填历史 Forward、用当前 runner 生成 checkpoint |
| 需要 Human/Architect 决定 | B2_CONFIRMED 是否单调、ADR-008 正式 promotion、V02 reference 的不可变生命周期 |

## 2. CURRENT SYSTEM MAP

~~~mermaid
flowchart TD
    subgraph Knowledge["Knowledge / Governance"]
      KB["Strategy Master / Rule Catalog / State Machine"]
      BM["Baseline Manifest / Current Phase / Context Pack"]
      ADR["ADR-006 reviewed; ADR-007/008 local-untracked"]
    end

    subgraph Data["Data Plane"]
      P["Providers: historical Tushare + AKShare + BaoStock; proposed TDX + Tencent"]
      R["Raw/Staging + normalization + reconciliation"]
      C["Canonical Parquet + DuckDB snapshot metadata"]
      LP["Derived limit-up pool"]
    end

    subgraph Production["Production Application"]
      S["Market-wide screen"]
      ST["Per-code state JSON"]
      TP["TradePlan / post-close human watch"]
      RP["Replay / inspect"]
    end

    subgraph Research["Research Plane"]
      EP["Frozen corrected episodes"]
      RS["Outcome / execution / context / intraday studies"]
      FP["Forward protocol + reference"]
      FL["Candidates / checkpoints / outcomes ledgers"]
    end

    P --> R --> C
    R --> LP
    C --> S
    LP --> S
    S --> ST --> TP
    C --> RP
    KB --> S
    BM --> RS
    C --> EP --> RS --> FP --> FL
    ADR --> R
    KB -. reviewed promotion .-> FP
~~~

### 实际边界与偏差

| 领域 | 正式实现 | 旁路/偏差 |
|---|---|---|
| Strategy core | src/limit_pullback/strategy、models、frozen YAML | outcome、trade_plan、screen 调用部分私有 helper；B2 lifecycle 与人类 state machine 冲突 |
| Warehouse | src/limit_pullback/warehouse，DuckDB 元数据，原子单文件写 | ADR-008 catch-up/publish 位于未跟踪 research 脚本，绕过 source_files/reconciliation_results |
| Screen | canonical loader、runner、state、verify、chunks | latest/status 无 gate；全 universe 未过滤主板；先写 state 后 verify |
| Research | outcome、execution_reality、diagnosis、robustness 和 research scripts | 大量一次性脚本、重复 helper、未跟踪 artifact；position sizing 先于 proven edge |
| Forward | JSON protocol/reference/manifest + 3 个 Parquet ledger | runner 名为 v01、混用 V01/V02、非原子覆盖；当前 0 行 |
| Knowledge | 独立知识仓库 + reviewed promotion | CURRENT_PHASE、agent-context、Strategy Master、ADR 与实际代码/数据不同步 |

## 3. TRUTH SOURCE AUDIT

### TRUTH_SOURCE_MATRIX

| Truth layer | 唯一应有 authoritative source | 当前实物 | 状态 | 冲突/动作门禁 |
|---|---|---|---|---|
| PRODUCTION TRUTH | GitHub main 的 reviewed code + 明确 frozen tag/config + 被验证为 SCREEN_READY 的 snapshot | code main e2d5b57；phase-2d0；snapshot b5f 可限定使用 | PARTIAL | 本地未跟踪脚本发布了新 CURRENT snapshot，不能视为 production truth |
| FROZEN HISTORICAL EVIDENCE | BASELINE_MANIFEST + 哈希固定的 episodes/outputs | corrected episodes hash 66d5943…；execution episodes 3c3cfc… | PASS_WITH_PROVENANCE_GAP | episodes 记录 strategy_commit 315fbe0，而 phase-2d0 内容 commit 是 e865de4 |
| FORWARD OBSERVATION | immutable protocol/reference/epoch manifest + append-only ledgers | V01/V02 文件存在；3 个 ledger 均 0 行 | NOT_STARTED | runner 与 durability gate 不通过；不得启动 |
| RESEARCH OVERLAY | reviewed research artifact + provenance + conclusion taxonomy | 已合并的 context/perf/intraday 研究与本地大量未跟踪研究 | MIXED | 未跟踪结果不是可 promotion truth；SUPPORTED 也不等于 PROMOTED |
| DATA TRUTH | provider raw hash → reconciliation record → canonical hash → validated publication pointer | 7/31 pipeline lineage较完整；8/5 manifest 有 canonical/source hash | FAIL_LATEST | 8/5 无 source_files/reconciliation_results，source path 为绝对临时路径，且数值错误 |
| KNOWLEDGE / ADR TRUTH | knowledge main 上 reviewed master/rules/ADR/current phase | main 5085eda；ADR-007/008 仍未跟踪 | FAIL_SYNC | ADR-008 GATE_PENDING 时 production snapshot 已发布；旧 provider policy 仍在 Master/Rule Catalog |

### Domain-specific truth resolution

| Domain | Authoritative Source | Current Version | Actual Implementation | Drift | Severity |
|---|---|---|---|---|---|
| Strategy | phase-2d0 tag + reviewed STRATEGY_MASTER/STATE_MACHINE | e865de4/tree cb786d72 | GitHub main core + current golden | B2_CONFIRMED lifecycle conflict | CRITICAL/P0 |
| Config | frozen config files + Baseline Manifest hashes | strategy hash 47a0ea2b…；trade-plan hash 06fd5dc9… | repo config + duplicated model fallback | version/default mapping gap | MEDIUM |
| Data architecture | reviewed ADR + matching main implementation | ADR-006 reviewed；ADR-008 local GATE_PENDING | old formal pipeline + local TDX/Tencent publisher | architecture/promotion split | CRITICAL |
| Research | reviewed artifact manifest/report + frozen input hashes | merged studies through PR24；local drafts beyond | package studies + many untracked scripts | local result not reviewed truth | HIGH |
| Forward protocol | approved immutable epoch manifest/protocol/reference | V02 hashes aaca…/dd30…/0540…，no start approval | V01-named runner hardcodes V01 fields | protocol/runtime mismatch | CRITICAL/P0 |
| Canonical snapshots | SCREEN_READY manifest + validation report + hashes | last usable b5f；latest d9e invalid CURRENT | loader defaults latest regardless status | bad latest selected | CRITICAL/P0 |
| Screen state | verified atomic generation bound to usable snapshot | current 5,197 files bound d9e | per-code JSON written before verify | whole state root contaminated | CRITICAL/P0 |
| Execution semantics | trade_plan config + typed execution contract；never setup truth | phase-2c2c config，B1_PREP execution-only | trade_plan/model defaults + human terms | duplicated defaults/naming | MEDIUM |
| Knowledge/ADR | knowledge main reviewed commit | 5085eda | local ADR-007/008 and dirty case files | main behind local/runtime | HIGH/CRITICAL where production |

### 单一真源决议

| 主题 | 审计后唯一真源 | 不得再当真源的材料 |
|---|---|---|
| 冻结阶段/阈值 | phase-2d0 tag + BASELINE_MANIFEST 中的哈希 + reviewed STRATEGY_MASTER | 聊天记录、README 的营销式术语、本地未提交笔记 |
| 运行代码 | GitHub main commit e2d5b57 | dirty worktree、未跟踪 research 脚本 |
| 数据架构 | reviewed ADR + Master/Rule Catalog + GitHub main 实现；只有三者一致才有效 | 本地未跟踪 ADR/script、聊天中的 provider 选择 |
| Canonical snapshot | 显式 snapshot ID 且 status=SCREEN_READY、完整 lineage、通过 continuity/universe/pool gate | latest/CURRENT 自动选择；8/5 snapshot |
| Screen state | 完成 verify 后原子 promotion、绑定 usable snapshot 的 state root hash | 当前逐文件 JSON、未完成 run、坏 snapshot state |
| Execution semantics | config/trade_plan.yaml + typed TradePlan contract；execution labels 不反写 setup | README human term、模型 fallback 默认、人工口述 |
| 历史研究样本 | corrected episodes hash 66d5943… 和 execution hash 3c3cfc… | 原始未纠正 episodes、重新生成但无 provenance 的副本 |
| Forward | 人工批准且哈希锁定的单一 epoch manifest + append-only ledger | 文件名推断、runner 默认、可覆盖 reference |
| 人工概念 | 带 namespace 的映射表 | FIRST_ATTACK、SECOND_LAUNCH、POST_B 等无 namespace 文本 |

### 已确认 truth conflicts

1. docs/agent-context.md 仍称 Phase 2C.2C、PR #7、branch feature/phase-2c2c；当前已到 phase-2d0 并合并 PR #25。
2. STRATEGY_MASTER 与 RULE_CATALOG 仍写 Tushare + AKShare active policy；本地 ADR-008 改为 TDX + Tencent，但未进入知识 main。
3. ADR-008 是 ACCEPTED (architecture) / GATE_PENDING (implementation audit)，数据层却已发布 ADR-008 CURRENT snapshot。
4. STATE_MACHINE 说 B2_CONFIRMED 只退出到 invalid/new anchor/expiry；代码可在次日降回 B2_READY。
5. V02 manifest 声明 epoch FORWARD_EPOCH_1_V02；runner 写死 FORWARD_EPOCH_1 和 quiet_score_reference_v01。
6. BASELINE_MANIFEST 记录到 Phase 2D.1A，而 CURRENT_PHASE 又记录 PR #19；知识 main 未包含 8 月 3–5 日新增研究与数据迁移事实。

## 4. REQUIREMENTS TRACEABILITY

### 产品目标与非目标

~~~text
Post-close A-share limit-up pullback system
├── Inspect one stock from canonical point-in-time data
├── Detect and advance frozen setup lifecycle
├── Screen eligible Shanghai/Shenzhen main-board stocks after close
├── Produce next-session execution observations / TradePlan
├── Build frozen research episodes and evaluate hypotheses
└── Run Forward observation only after explicit gates

Explicit non-goals
├── Intraday monitor
├── Broker client / auto-trader
├── Profit guarantee
├── General report generator
├── Portfolio backtester
├── Threshold optimizer
├── Same-sample tune-and-validate workflow
└── Position sizing before proven entry edge
~~~

### Functional requirements inventory

这里的 owner 是当前应承担最终责任的角色，不代表现有仓库已经用 CODEOWNERS 强制。

| REQ_ID | Description | Implemented | Tested | Documented | Owner |
|---|---|---|---|---|---|
| F-INGEST | provider daily/pool ingestion、retry、raw persist | YES，旧正式路径 | YES，offline + opt-in integration | PARTIAL | Market Data |
| F-RECON | normalize units、whole-row reconcile、quality status | YES for ADR-006；ADR-008 prototype only | YES old；V02 tests detached | PARTIAL/CONFLICTING | Market Data |
| F-PUBLISH | immutable canonical + manifest + metadata | YES | PARTIAL | PARTIAL | Warehouse |
| F-SCREEN | post-close main-board candidate screen | YES | YES examples | YES | Screening |
| F-STATE | incremental per-code state persist/rebuild | YES | YES examples | PARTIAL | Screening |
| F-STRATEGY | frozen setup evaluation and explainable signal | YES | STRONG | STRONG | Strategy Architect + Engine |
| F-CASE | construct frozen research episodes/case sets | YES | YES | YES in reports | Research |
| F-INTRADAY | 5m feature extraction for research | script-only | PARTIAL | YES in research reports | Research |
| F-FORWARD | candidate freeze/checkpoint/outcome observation | BROKEN prototype | INSUFFICIENT | Protocol documented | Forward Observation |
| F-EXECUTION | T+1 execution reality analysis | YES | YES | YES | Research/Execution |
| F-REPORT | produce research/audit artifacts, not a product reporting service | script/document only | reproducibility tests vary | PARTIAL | Research/Human |

### Example end-to-end trace

“当天生成的 trigger 不允许当天确认”：

STRATEGY_MASTER snapshot timing → config/frozen phase-2d0 semantics → strategy/engine.py eligible_from → models/signal.py invariant → strategy/replay tests → phase-2d0 golden artifacts。该链条为 PASS。相比之下，B2_CONFIRMED monotonicity 在 State Machine → code → golden 处断裂。

### REQUIREMENT_TRACEABILITY_MATRIX

| ID | Requirement | Authoritative source | Implementation | Tests/evidence | Status |
|---|---|---|---|---|---|
| FR-01 | 从 immutable canonical snapshot 做单股 inspect/replay | SPEC、STRATEGY_MASTER | inspect.py、replay.py、screen/canonical.py | replay、snapshot guard tests | PASS_WITH_LATEST_DATA_BLOCK |
| FR-02 | LIMIT_ANCHOR → WATCH/B1/B2/INVALID 生命周期 | STRATEGY_MASTER、STATE_MACHINE | strategy/engine.py、models/signal.py | strategy engine + golden tests | FAIL：B2_CONFIRMED 非单调冲突 |
| FR-03 | setup 与 entry/execution 分离 | AGENTS、STRATEGY_MASTER | signal models、trade_plan.py | contract/invariant tests | PASS |
| FR-04 | 主板全市场 post-close screen | README、SPEC、agent context | screen/runner.py、chunks.py | screen tests、real benchmark | FAIL：包含 300/301/688 共 2,006 states |
| FR-05 | CONFIRMED-only formal screen | ADR-006/007/008 | pool_quality、canonical query | screen gate tests | PARTIAL：latest status/pool freshness 无门禁 |
| FR-06 | 下一交易日 TradePlan | trade_plan.yaml、phase 2C.2C docs | trade_plan.py、CLI | trade_plan tests | BLOCKED_BY_STATE_DATA |
| FR-07 | 冻结 outcome/execution episodes | phase-2d0、BASELINE_MANIFEST | outcome.py、execution_reality.py | 31,422-row hash artifacts + tests | PASS_WITH_COMMIT_PROVENANCE_GAP |
| FR-08 | Research conclusion governance | AGENTS、research-cycle rules | diagnosis/robustness/scripts/reports | reviewed reports | PARTIAL：未跟踪脚本与 sizing 违规 |
| FR-09 | Forward candidate freeze/checkpoint/outcome | V02 protocol/manifest | run_forward_bpoint_v01.py | local migration tests | FAIL_IMPLEMENTATION；ledgers 尚未开始 |
| FR-10 | Provider reconcile 后整行选择、禁止 field merge | ADR-006/007/008 | warehouse/reconciliation.py；未跟踪 catch-up | reconciliation tests | OLD_PATH_PASS；ADR-008 production lineage FAIL |
| NFR-01 | Point-in-time / no future leakage | SPEC、AGENTS | as_of/eligible_from/frozen snapshots | PIT tests | CORE_PASS；Forward runner FAIL |
| NFR-02 | Reproducible by hashes | BASELINE_MANIFEST | manifests、state provenance、research artifacts | hash audit | PARTIAL |
| NFR-03 | Offline default tests | AGENTS、pytest config | integration marker | 357 passed, 16 deselected in venv | PASS_IN_FULL_ENV；base dependency UX FAIL |
| NFR-04 | Memory-bounded full market | AGENTS | streaming loader、chunk processes | full-market benchmark | PARTIAL：child peak 2.403 GB，validators materialize |
| NFR-05 | Crash-safe/atomic publication | implied production correctness | atomic single-file helpers | snapshot/resume tests | FAIL across multi-file snapshot/state/ledger |
| NFR-06 | Observable provenance | research invariants | metadata/manifests/state fields | direct DB audit | PARTIAL；8/5 bypass |
| NFR-07 | Security/privacy | Git/public-repo policy | token redaction、gitignore | tests + static scan | PARTIAL |
| NFR-08 | Reviewed production changes | AGENTS/Git rules | PR workflow | remote PR history | FAIL for local untracked production publisher |
| NFR-09 | Maintainable boundaries | engineering objective | modules/models | AST/import audit | PARTIAL：large orchestration functions and research duplication |
| NFR-10 | Release/rollback governance | phase tags/manifests | Git tags + explicit snapshot IDs | tag/hash audit | PARTIAL：no release, no protected main, no rollback runbook |

### Documentation and ownership completion

| REQ_ID | DOCUMENTED | OWNER / promotion gate |
|---|---|---|
| FR-01 | SPEC、inspect/replay docs | Screening/Replay |
| FR-02 | STRATEGY_MASTER、STATE_MACHINE，当前互相冲突 | Strategy Architect；Human decides |
| FR-03 | AGENTS、STRATEGY_MASTER | Strategy + Execution |
| FR-04 | README、SPEC | Screening |
| FR-05 | ADR-006/007/008，后两者未review | Market Data + Human promotion |
| FR-06 | trade_plan config/docs | Execution Observation |
| FR-07 | phase-2d0、Baseline Manifest | Historical Research |
| FR-08 | AGENTS/research-cycle/report headers | Research Architect + Human |
| FR-09 | V01/V02 protocol/manifest | Forward Observation + Human start gate |
| FR-10 | ADR reconciliation policies | Market Data |
| NFR-01 | SPEC、AGENTS | All domains；CI must block |
| NFR-02 | Baseline/manifests | Governance/Release |
| NFR-03 | AGENTS、pyproject pytest config | Platform/CI |
| NFR-04 | AGENTS、performance records | Screening/Performance |
| NFR-05 | implicit only；缺正式 transaction spec | Warehouse/Screen/Forward |
| NFR-06 | research invariants、manifest conventions | Governance/Data |
| NFR-07 | git/security conventions | Security/Human |
| NFR-08 | AGENTS Git rules | Human merge gate |
| NFR-09 | architecture intent only | Module owners/Architect |
| NFR-10 | tags/manifests部分记录 | Release/Human |

### Orphans and gaps

| 类型 | 发现 |
|---|---|
| Orphan requirement | Corporate-action detection and exclusion is declared by ADR-008/V02, but no authoritative detector/source is wired |
| Orphan requirement | Snapshot promotion requires readiness in practice, but no documented state transition contract CURRENT → VALIDATED → SCREEN_READY exists |
| Orphan code | Active CLI still eagerly imports Tushare warehouse modules although proposed active policy removes Tushare |
| Orphan code | Numerous untracked migration/B-point/daily-review scripts have no reviewed ownership or lifecycle |
| Orphan tests | tests/test_data_migration_v02.py reimplements constants/helpers instead of importing production scripts; it passed while real preclose bug remained |
| Untested rule | B2_CONFIRMED monotonicity、pool recency、main-board-only full screen、ADR-008 publisher 必须调用现有 preclose validator、V02 HHMM filtering |
| Dead/ambiguous config | strategy_version 0.1.0 is not mapped to phase-2d0; execution defaults are duplicated in model defaults and trade_plan fallback |
| Intentional placeholders | CLI planned commands report/run/backtest are explicit non-goals/placeholders, not production features |

## 5. STRATEGY SEMANTIC AUDIT

### STRATEGY_SEMANTIC_INVARIANTS

| INVARIANT | CODE_LOCATION | TEST | STATUS |
|---|---|---|---|
| LIMIT_ANCHOR originates from eligible limit-up event | strategy/structure.py、engine.py、pool provider | strategy/screen tests | PASS_ON_VALID_DATA；8/5 pool stale |
| Same-day trigger cannot be confirmed | engine eligible_from/frozen trigger | same-day PIT tests | PASS |
| Support/invalid/S1 snapshots cannot use future rows | engine frozen_as_of/eligible_from | future support/S1 tests | PASS |
| INVALID is terminal within same setup | engine.py lines 885–895 | invalid terminal/replay tests | PASS |
| New anchor creates a new setup | strategy engine setup selection | new-anchor tests | PASS |
| Entry Room does not rewrite setup stage | models/signal invariants、scoring | contract/strategy tests | PASS |
| Setup quality and entry quality remain distinct | models/config/signal | scoring/entry-room tests | PASS |
| B1_PREP is execution label，not setup_stage | trade_plan/models enums | trade-plan contract tests | PASS_IN_CORE；human namespace gap |
| B2_READY freezes trigger before later confirmation | engine trigger snapshot | B2 timing tests | PASS |
| B2_CONFIRMED only exits invalid/new anchor/expiry | engine.py lines 897–916 vs State Machine | golden currently expects demotion；no monotonic test | FAIL_P0 |
| S1/S2 are event/target，not setup stages | enums/models | strategy tests | PASS |
| Raw and continuous domains not silently mixed | strategy/math.py、structure.py | continuous-price tests | CODE_PASS / LATEST_DATA_FAIL |
| MAX_DATA_TIMESTAMP_USED <= decision timestamp | engine/replay as_of guards | PIT example tests | CORE_PASS / FORWARD_FAIL |
| Formal universe is沪深主板 | instruments.py / screen runner | single-code boundary tests；no full-screen contract | FAIL_FULL_SCREEN |
| Frozen thresholds unchanged | config + hash manifests | hash audit | PASS |

### B2_CONFIRMED 冲突

- 人类真源：knowledge/01_Strategy/STATE_MACHINE.md 明确 B2_CONFIRMED 的退出仅为失效、新锚点或过期。
- 代码：src/limit_pullback/strategy/engine.py lines 897–916 每日重新计算；如果当天不再满足 b2_confirmed 但 trigger 仍存在，会落回 B2_READY。
- 测试：tests/fixtures/golden_expectations.yaml 的 s2_exhausted 预期正是 B2_READY，因此现有 golden 固化了代码行为，而不是知识语义。
- 历史：该行为在 phase-2d0 已存在，属于长期 code-vs-knowledge conflict，不是本次性能改动引入的 drift。
- 严重度：P0_STOP_THE_LINE。原始审计规则明确把任何 strategy semantic drift 归为 P0；“长期存在”只说明影响面更难评估，不是降级理由。
- 决策要求：先由 Human/Architect 决定“状态单调”还是“每日条件态”为真；不得由修复 PR 自行选择，更不得顺带改阈值。

### CONCEPT_MAPPING

| 人工概念 | 推荐 namespace | 机器映射 | 风险/决议 |
|---|---|---|---|
| FIRST_ATTACK | event:FIRST_ATTACK | 最接近 LIMIT_ANCHOR，但 README 还包含“放量攻击” | 不能一对一等同；生产 anchor 只接受规则定义的有效涨停锚点 |
| STRUCTURE_ALIVE | derived:STRUCTURE_ALIVE | WATCH_PULLBACK、B1_READY、B2_READY、B2_CONFIRMED 的 active set | 作为派生布尔值，不新增 setup_stage |
| PREPOSITION | human:PREPOSITION | 人工/研究 radar | 不是 B1_READY，也不是 B1_PREP |
| B1_PREP | execution:B1_PREP | TradePlan 执行标签 | 明确禁止作为 setup_stage |
| LAUNCH_READY | human:LAUNCH_READY | 可参考 B_ACTIONABLE_WINDOW/geometry | 不等同 B2_READY；缺少冻结定义 |
| SECOND_LAUNCH | 禁止裸名 | 可能指 setup:B2_CONFIRMED、event:S1_BREAKOUT、outcome:SUCCESS 或 intraday:ACTIVATION | 必须改名或强制 namespace |
| POST_B | human:POST_B | 人工持有/退出管理语境 | 当前无生产 setup_stage；不得反向修改 lifecycle |
| SUCCESS | outcome:SUCCESS | 3-session frozen structural outcome | 不等于 B2_CONFIRMED 或 S1_BREAKOUT |
| S1_BREAKOUT | event:S1_BREAKOUT | 事件 flag | 不等于 outcome:SUCCESS |
| ACTIVATION | intraday:ACTIVATION | Forward checkpoint 派生观察 | 不得写入历史 setup stage |

## 6. DATA ARCHITECTURE AUDIT

### 数据流与 provider 角色

| 时期/政策 | Daily primary | Confirm/audit | Limit-up pool | 实际状态 |
|---|---|---|---|---|
| ADR-006 / 7月31冻结历史 | Tushare | AKShare/BaoStock | AKShare single-source enrichment | lineage 较完整；1,844,543 daily CONFIRMED |
| ADR-007（本地未跟踪） | Eastmoney | TDX；BaoStock audit | 未完整实现 | 因 Eastmoney 环境不稳定而 IMPLEMENTATION_BLOCKED |
| ADR-008（本地未跟踪） | TDX | Tencent；BaoStock audit | 应为 derived data | architecture accepted / implementation GATE_PENDING，却已发布 CURRENT snapshot |

| Provider | Proposed active role | Current formal-code role | Availability/dependency assessment |
|---|---|---|---|
| TDX / pytdx | DAILY_PRIMARY、INTRADAY_PRIMARY | 仅未跟踪 migration/Forward scripts | 无 token；协议库 pytdx 1.72 的 PyPI 最近发布为 2019-08-26，未被官方标为 archived，但维护陈旧，是高风险单点 |
| Tencent via AKShare | DAILY_CONFIRM | 未跟踪 catch-up | 可用性需重试与 coverage；不能 silent fallback |
| BaoStock | DAILY_AUDIT_BACKUP、calendar | 正式 provider +研究 calendar | PyPI 0.9.3 在 2026-07-10 发布，但 classifier 仍为 Alpha；只能 audit/non-blocking |
| Sina 5m | INTRADAY_AUDIT | research parity/cache | 非 primary；不可在缺失时替代 TDX primary |
| Tushare | INACTIVE under ADR-007/008 | 旧正式 warehouse 与 CLI 仍 active-import | 历史兼容，需明确 LEGACY_COMPAT，不可静默恢复 active |
| Eastmoney | OPTIONAL_DISABLED under ADR-008 | AKShare legacy pool/daily code仍在 | endpoint/proxy 曾不稳定；不能成为 production blocker |

依赖活跃度来源为官方 PyPI：[pytdx](https://pypi.org/project/pytdx/)、[baostock](https://pypi.org/project/baostock/)、[AKShare](https://pypi.org/project/akshare/)、[Tushare](https://pypi.org/project/tushare/)。AKShare 1.18.81（2026-07-29）和 Tushare 1.4.29（2026-03-25）仍有近期发布；这不证明其上游数据 endpoint 稳定。

### 数据合同审计

| Contract | 关键字段 | 正面 | 缺口 |
|---|---|---|---|
| CanonicalDailyBar | code/date/OHLC/preclose/volume/amount/turnover/pct/status/ST/selected_provider/reconciliation/source hash/snapshot | 类型明确、整行选择、snapshot id | 发布 schema 丢失 confirmation_provider、confirmation_row_hash、price_domain、source/normalized units、corporate_action_affected |
| CanonicalLimitUpRecord | date/code/name/limit price/seal/open count/caps/industry/reconciliation | enrichment 与 anchor 分层 | 8/5 仍复用截止 7/31 的 901 行；无 recency/coverage gate |
| SnapshotRecord | ID/as_of/provider/source/canonical hashes/policy/status/manifest | 可显式定位与哈希 | status 没有强制状态机；多文件+DB非事务；绝对路径进入 manifest |
| ReconciliationRecord | code/date/providers/status/selected/notes/snapshot | 7/31 有 5.48m 记录 | 8/5 snapshot 为 0；不能追 confirmation row 或字段单位 |
| ScreenState | code/date/signal/snapshot/prefix hashes/commit/config/policy | 有 provenance 与 incremental hash | 写在 verify 之前；全部状态可被坏 snapshot 批量覆盖 |
| ResearchEpisode | setup/outcome/snapshot/commit/config | 31,422 行哈希冻结 | strategy_commit 与 phase-2d0 内容 commit 不一致，需 provenance explanation |
| Forward ledgers | candidate/checkpoint/outcome columns | 物理分层 | 0-row 文件均是 Arrow null schema；非 append-only、无锁、无 journal |

### Entity contract detail

| Entity | Required fields | Primary key | Unique enforcement | Nullable fields | Unit / price domain | Time semantics | Provenance / quality | Audit |
|---|---|---|---|---|---|---|---|---|
| DailyBar | code/date/OHLC/preclose/volume/amount/source/fetched_at | code + trade_date | validator/provider tests；Parquet无storage constraint | turnover、pct、ST | shares、CNY、RAW input；continuous另算 | exchange date；fetched_at UTC | source/fetched_at；quality外置 | Core typed；canonical lineage不足 |
| MinuteBar | 应有code/bar_end/OHLC/volume/amount/provider | code + bar_end_time | NONE；无共享contract | provider gap须显式status，不能隐式空 | shares、CNY、RAW | Asia/Shanghai BAR_END_TIME；09:35首根 | raw hash/complete-bar/quality | FAIL：仅research DataFrame |
| LimitUpRecord | code/date/limit_price/source | code + trade_date | provider/validator层检查；Parquet无constraint | seal/open/cap/industry enrichment | RAW CNY、turnover %、caps CNY | trade_date；seal time Asia/Shanghai | reconciliation status/source | Core typed；membership外部依赖 |
| CanonicalRow | DailyBar fields + snapshot/selected provider/status/source hash | snapshot_id + code + trade_date | data_validate检查duplicate；无storage constraint | approved enrichment only | 必须显式unit/domain | daily date；fetched_at UTC | selected+confirmation provider/hash/status | FAIL：发布丢字段 |
| ScreenState | code/last date/signal/snapshot/prefix/config/commit/policy | generation + code，当前实际仅code path | 文件路径只允许一个active code；无generation transaction | setup_id可随NORMAL为空 | signal price应标RAW-equivalent | processed_at UTC；decision exchange date | prefix hashes/policy/snapshot | 无schema_version/atomic root |
| Episode | episode_id/setup/snapshot/config/commit/outcome | episode_id | 研究QA断言0 duplicates；Parquet无constraint | feature-specific | artifact schema定义percent/price | candidate/event/resolution dates | frozen event/input/output hashes | Stronger，commit mapping gap |
| ForwardCandidate | epoch/run date/code/setup/source fields/D1 | epoch + run_date + code | NONE in Parquet；date duplicate check不等于constraint | D1/source hash不应空 | support/invalid/S1/close RAW；volume shares | freeze timestamp + D-1 date | snapshot/config/strategy/candidate hash | FAIL：runner写null |
| ForwardCheckpoint | candidate ref/checkpoint/price/volume/features/status | epoch + run_date + code + checkpoint | NONE | feature NA only by frozen missing policy | RAW/shares/ratios/% | completed Asia/Shanghai BAR_END_TIME | candidate event/minute source hash | FAIL：null schema |
| ForwardOutcome | candidate ref/code/outcome/reason/horizon | epoch + run_date + code | NONE | UNKNOWN允许；code不可空 | outcome enum | after frozen 3-session horizon | candidate/checkpoint refs/correction event | FAIL：无referential constraint |

禁止把 Parquet 的“列存在”当作合同完整：nullable、单位、timezone、primary key、quality status 和 schema_version 都必须 machine-checkable。

### PRICE_DOMAIN_MATRIX

| 数据/计算 | 应用 price domain | 实现 | 结论 |
|---|---|---|---|
| Canonical OHLC/preclose | RAW_UNADJUSTED | 旧 schema 无显式 price_domain；ADR-008 临时表有字段但发布时丢失 | PARTIAL |
| 涨停价/limit close | RAW_UNADJUSTED + 当日制度 | structure + raw preclose | CODE PASS；8/4–8/5 DATA FAIL |
| K线形态 | RAW candle geometry | strategy patterns | PASS |
| 跨除权连续收益/均线结构 | PIT continuous chain from close/preclose | strategy/math.py | CODE PASS；坏 preclose 破坏整个 chain |
| Support/resistance raw-equivalent 输出 | continuous analysis → 当日 raw-equivalent | structure/models | 有测试，但 contract 没有显式 domain tag |
| Vendor adjusted series | DERIVED_ADJUSTED_VIEW only | 不作为 canonical | PASS_BY_POLICY |
| Intraday 5m | RAW_UNADJUSTED | V02 protocol | 合同明确；runner 未安全实现 |
| Corporate-action affected | metadata/exclusion flag | catch-up 硬编码 false，canonical 丢字段 | FAIL |

所有关键 strategy/execution 价格逐项结论：

| Field | Required domain | Current audit |
|---|---|---|
| limit_price | RAW_UNADJUSTED | Code intent PASS；8/4–8/5 preclose input FAIL |
| support / invalid / S1 / trigger | PIT_CONTINUOUS 计算后映射到 decision-day RAW-equivalent output | Core tests PASS；缺显式 domain tag |
| execution / paper entry | RAW_UNADJUSTED | TradePlan intent PASS；Forward contract incomplete |
| MA / position / trend | PIT_CONTINUOUS | Core math PASS |
| vendor QFQ/HFQ | display/secondary analysis only | 不进入 frozen historical evaluation |

### Canonical 数据实证

| 指标 | 7/31 SCREEN_READY | 8/5 CURRENT |
|---|---:|---:|
| Daily rows | 3,282,707 | 3,298,229 |
| Codes | 5,634 | 5,634 |
| Date range | 2024-01-02..2026-07-31 | 2024-01-02..2026-08-05 |
| Added rows | — | 15,522 TDX CONFIRMED |
| Limit-up pool | 901 rows，max 2026-07-31 | 同 901 行，max 2026-07-31 |
| Historical OHLCV/preclose parity through 7/31 | baseline | 与旧 snapshot 0 差异 |
| Basic null/duplicate/OHLC/negative-volume checks | 无直接异常 | 无直接异常；这些检查未发现 continuity bug |

### P0：multi-session preclose continuity

未跟踪脚本 research/tdx_tencent_catchup_v02.py lines 194–201 只构造 2026-07-31 close map，lines 173/175 对 8/3、8/4、8/5 每一行反复使用该值。

| 日期 | 可比较行 | preclose != lag(close) | 差异 > 0.011 元 | pct_change 错误 | 10% rounded limit reference 错误 |
|---|---:|---:|---:|---:|---:|
| 2026-08-03 | 5,174 | 0 | 0 | 0 | 0 |
| 2026-08-04 | 5,173 | 5,121 | 5,017 | 5,121 | 5,121 |
| 2026-08-05 | 5,175 | 5,130 | 5,002 | 5,130 | 5,130 |

全部 5,175 个 catch-up 代码在三天内都只有一个 distinct preclose。例：000001 在 8/5 存储 preclose=11.63，真实 8/4 close=11.44，8/5 close=11.25；存储 pct_change=-3.2674%，实际为 -1.6608%。

### Derived limit-up data

- 当前 pool 只有 901 行、601 个代码、日期 2026-07-13..2026-07-31。
- 新旧 pool membership 完全相同；新文件主要因 snapshot_id 改变而 hash 改变。
- 8/3–8/5 没有新 anchor enrichment，因此即使 daily bar 修正，screen 仍不能完整识别新 setup。
- Limit-up pool 应是 canonical daily + exchange rules + optional enrichment 的派生层；外部榜单可 enrich，不能成为不可解释的核心 membership 单点依赖。

| Derived membership requirement | Current implementation evidence | Result |
|---|---|---|
| price-limit rule table by board/effective date | 无 versioned rule table | MISSING |
| preclose continuity | 依赖 canonical preclose | FAIL latest |
| ST 5% rules | DailyBar有 is_st，但 derived builder 未实现 | MISSING |
| board 10%/20% rules | universe/board helper分散；无 derived builder | MISSING |
| IPO/no-limit sessions | 无 authoritative listing/no-limit calendar | MISSING |
| corporate action reference | reserved flag，无 detector | MISSING |
| tick rounding | strategy有 Decimal rounding相关逻辑；未形成 derived contract | PARTIAL |
| historical effective dates | 无 rule-version lineage | MISSING |
| first seal/break count/seal amount | 外部 pool enrichment | ALLOWED_AS_ENRICHMENT_ONLY |

### Canonical status handling

| Status | 应否进入 formal production | 当前路径 |
|---|---|---|
| CONFIRMED | 仅在 snapshot整体 SCREEN_READY 后可用 | daily loader formal query使用；但 snapshot gate缺失 |
| CONFIRMED_SINGLE_SOURCE | 仅限已批准的 pool enrichment policy | pool_quality 接受 |
| PROVISIONAL | NO | daily formal路径通常过滤；snapshot仍可发布并被 latest选择 |
| CONFLICTED | NO | 保存在 metadata/quarantine语境 |
| INCOMPLETE | NO | 可随 pending failures snapshot发布 |
| QUARANTINED | NO | 无统一 consumer hard gate |

### Corporate action

- ADR-008 预留 RAW 和 corporate_action_affected；V02 规定 true 时排除 quiet score。
- catch-up script 在未实现 detector 的情况下对所有行写 false。
- canonical publication schema 丢弃该字段，消费者无法区分“检测后为 false”和“从未检测”。
- 结论：CORPORATE_ACTION_CONTRACT_NOT_IMPLEMENTED。禁止把默认 false 当作已证明无除权影响。

### Lineage / publication

- 8/5 manifest canonical daily hash = ce9b489292b79d5a482bfc7f2aa027326587cf1687cea13e532ed1a30b405b16。
- 8/5 manifest 只记录两个绝对临时路径下的 TDX/Tencent source hash，暴露机器路径且不可移植。
- DuckDB 对 8/5 有 2 个 canonical_publications，但 reconciliation_results=0；source_files 最新记录仍停在 8/1，provider 只有 AKSHARE/BAOSTOCK/TUSHARE。
- 正式 src/limit_pullback/warehouse/validate.py lines 262–289 已实现非 Tushare provider 的 PRECLOSE_CONTINUITY gate，tests/test_warehouse_validate.py lines 103–109 也有例测；P0 的直接原因是未跟踪 ADR-008 publisher 绕过正式 pipeline/validator，而不是项目完全缺少 continuity check。
- data/tmp/canonical-catchup-2026-08/manifest.json 仍称 staged_only=true / production_snapshot_published=false，与真实 publication 冲突。
- create_snapshot 依次写 daily、pool、manifest，再依次插入 snapshot 和两条 publication；没有跨文件/DB transaction。

## 7. PIT / LEAKAGE AUDIT

### FUTURE_LEAKAGE_THREAT_MODEL

| Threat | Severity | Existing protection | Direct evidence | Test coverage | Result |
|---|---|---|---|---|---|
| 同日冻结 trigger 并确认 | P0 if broken | eligible_from=as_of+1 | model + engine | Covered | PASS |
| support/S1 使用未来 K线 | P0 if broken | as_of 截断、frozen snapshots | core tests | Covered examples | PASS |
| outcome 回写 setup | P0 if broken | 模型与研究层分离 | 未见生产回写 | Partial contract tests | PASS_STATIC |
| latest snapshot 晚于 as_of/未ready | P1 | resolve_snapshot(as_of) | 显式 as_of 路径存在；default latest无readiness | Missing readiness golden | PARTIAL |
| 坏 preclose 改写历史连续价 | P0 | 正式 validator 有 continuity check | ADR-008 publisher绕过；8/4–8/5已发生 | Old-provider unit test only；real publisher missing | FAIL_CORRECTNESS |
| Forward checkpoint 包含未来 5m bars | P0 | protocol要求checkpoint截止 | minute-of-day 585 与 int(0945)=945 比较 | Missing | FAIL_CONFIRMED_IF_RUN |
| 09:45/10:00 最少 bar 数 | P1 | completed-bar rule文本 | runner要求 len(sub)>=10 | Missing | FAIL_IMPLEMENTATION |
| D1 same-time volume | P0 if wrong | V02 protocol明确 | runner时间比较同样错误 | Missing | FAIL_IMPLEMENTATION |
| 候选冻结后回填 D1 fields | P1 | freeze-once contract | d1_close/d1_volume=None；source hash可空 | Missing | FAIL_PROVENANCE |
| Outcome 用于 reference membership | P0 if present | manifest outcome_based_filtering=false | builder membership逻辑未读 outcome；之后才QA | Reimplemented/partial | PASS_STATIC |
| 历史 Forward backfill | P0 if present | protocol forbidden | ledgers 0行 | Manifest assertion only | PASS_CURRENT |
| Calendar 在 dry-run 产生状态 | P2 | dry-run应无副作用 | previous_trading_day可写cache | Missing | FAIL_SIDE_EFFECT |
| Corporate action 进入 primary score | P1 | protocol要求排除 | flag未检测且发布丢失 | Constants only | FAIL |

### Forward 时间错误的确定性

runner lines 414–415 计算 hour × 60 + minute；09:45 为 585，15:00 为 900。它随后与 int("0945") = 945 比较，所以 09:45 checkpoint 会把 15:00 之前全部 48 根 bar 选入。该错误不是概率性风险，而是确定性 future leakage。当前 ledgers 为 0 行，因此没有既成 Forward observation 被污染；这不降低启动门禁。

### PIT 总结

核心日线策略的 PIT 设计和例测总体良好，但“输入数据 continuity”和“Forward intraday slicing”不属于模型层可自动补救的错误。PIT 结论必须同时满足：时间切片正确、输入 provenance 正确、price domain 正确、不可回填。当前仅第一套核心历史路径基本满足，latest production 和 Forward 均不满足。

## 8. RESEARCH GOVERNANCE AUDIT

### 方法治理

| Gate | 规则 | 观察 | 结论 |
|---|---|---|---|
| Hypothesis before analysis | 先定义问题/指标/样本 | 多数正式 research report 有版本和问题 | PARTIAL_PASS |
| No tune and validate on same sample | 同样本不能调参与验证 | frozen rules 未因研究放宽 | PASS_CORE |
| Forward cannot influence historical selection | 不用 Forward 回调历史参数 | Forward 0 行 | PASS_CURRENT |
| Immutable frozen artifacts | hash + manifest | corrected episodes、V01/V02 hash 可核验 | PASS_WITH_SCRIPT_OVERWRITE_RISK |
| Conclusion taxonomy | REJECT / OBSERVE_ONLY / SUPPORTED | 大部分报告遵循，另有 SUPPORTED_DESCRIPTIVE/NOT_SUPPORTED | NEED_NORMALIZATION |
| SUPPORTED != PROMOTED | 人工 promotion | 知识库明确 | PASS |
| Position sizing after proven edge | 先证明 entry edge | execution_risk_v01 明确 NO_PROVEN_ENTRY_EDGE，但脚本已做 sizing 情景 | FAIL_GOVERNANCE |
| Provenance | input hash/script/output/conclusion | 正式 artifact 多数具备；未跟踪脚本不完整 | PARTIAL |

### Outcome-label coherence and mechanical confounding

| Label | Intended definition | PIT/stability audit | Mechanical confounding |
|---|---|---|---|
| SUCCESS | first S1-touch event closes at/above S1 and volume is at least signal-day volume | Candidate selection precedes label；future bars used only for label；definition versioned in case builder | CUM_VOLUME/volume expansion is partly built into label，不能解释为独立 predictive edge |
| FAILED_BREAKOUT | S1 attack/touch without frozen SUCCESS acceptance | Event-date extraction version repaired in V01B | S1 touch/position features overlap label event，必须区分 pre-event 与 event-day descriptive analysis |
| NO_LAUNCH | no qualifying launch within horizon | PIT-safe as future label；class composition smaller in 5m cohort | Activation features naturally separate it，不能因此证明 SUCCESS vs FAILED edge |
| STRUCTURE_FAIL | structure invalidates/fails before successful launch | Stable in corrected case-set mapping | invalid/support-distance features can be mechanically related to label |
| UNKNOWN | insufficient/ambiguous future evidence | Must remain explicit，not silently dropped | Complete-case filtering can create selection bias |

结论：标签在 corrected case-set 中互斥且候选冻结后才使用 future outcome，整体 PIT-safe；但它们并非统计独立于所有研究 feature。特别是 volume expansion、S1 acceptance、invalid/support geometry 必须标为 label-adjacent/confounded，而不是直接称为预测 edge。

### Statistical threat audit

| Threat | Actual exposure | Current mitigation | Result |
|---|---|---|---|
| Multiple testing | intraday reports比较大量 checkpoint/features | conclusion降级为 descriptive，未 promotion | HIGH residual；无 multiplicity correction |
| Threshold hunting | 多个历史切片/geometry研究 | frozen thresholds未改，正式报告声明 no scan | PARTIAL_PASS |
| Post-hoc feature creation | V02A top composite为事后总结 | 明确未计算 joint metric | PASS_DISCIPLINE，仍不可验证 |
| Selection bias | 5m complete cases 206/8,746；V02A final 139 | availability report和missing count明确 | HIGH |
| Survivorship/universe bias | frozen canonical universe、provider可得性 | snapshot固定 | PARTIAL；listing/delisting contract未单列 |
| Time clustering | V02A 全部集中 2026-06-05..07-30 | report明确无 discovery/validation split | HIGH |
| Small sample | SUCCESS 40，NO_LAUNCH 12，Forward ref 195 | caveat + observe-only | HIGH |
| Label leakage/confounding | SUCCESS含 volume expansion；event-day S1 fields靠近label | report排除 CUM_VOLUME独立结论 | PARTIAL_PASS |
| Same-sample validation | descriptive feature与总结同样本 | 未 promotion，要求 Forward | PASS_GOVERNANCE if maintained |
| Outcome-driven membership | V02 builder eligibility需完整输入 | manifest和static audit显示 outcome-blind | PASS_STATIC |

### 证据等级规范化

| 项目标签 | 本审计统一解释 |
|---|---|
| REJECT / NOT_SUPPORTED / NO_CLEAR_EDGE | 未支持假设，不得用于规则 |
| OBSERVE_ONLY / DESCRIPTIVE_* / HUMAN_HEURISTIC_CANDIDATE | 仅描述/人工观察，不得 promotion |
| SUPPORTED_DESCRIPTIVE | 描述统计可复核，但不是交易 edge |
| SUPPORTED | 在声明的样本/检验下得到支持，仍不是 PROMOTED |
| PROMOTED | 只有 Human/Architect 通过独立验证与 PR 后才存在；当前无新 promotion |

### RESEARCH_EVIDENCE_MATRIX

| 研究主题 | 样本/证据 | 结论 | 可做什么 | 禁止推导 |
|---|---|---|---|---|
| 冻结 B1/B2 outcome + execution | corrected episodes 31,422；execution hash 3c3cfc… | NO_PROVEN_ENTRY_EDGE；多数切片 REJECT | 描述风险与失败结构 | 正期望开仓、加仓、position sizing |
| Weekly context | resolved 585 | REJECT_FOR_PROMOTION | 保留负结果 | 作为筛选 overlay |
| Price-volume context | reviewed historical study | REJECT_FOR_PROMOTION | 保留负结果 | 调阈值 |
| Joint context | resolved 310 | REJECT | 无 | 组合成新规则 |
| Washout possible | descriptive | OBSERVE_ONLY | 人工观察 | promotion |
| B-point morphology | frozen historical/intraday cases | HIGH_LEVEL_CONSOLIDATION 等 SUPPORTED_DESCRIPTIVE；nearest-neighbor REJECT | Forward candidate question | 声称形态有入场 edge |
| Quiet compression V02 | 195 reference-eligible cases；frozen reference | CANDIDATE_FOR_FORWARD_PAPER | 仅在修复 runner 后前向观察 | 历史回填或 refit |
| Intraday success pattern V01/V01C | SUCCESS/CONTROL frozen case set | OBSERVE_ONLY | 假设生成 | 因描述差异改 production |
| Intraday V02A 5m | verified minute case set | opening shakeout hypothesis NOT_SUPPORTED；FAST_RECLAIM NOT_MEASURED；S1_POSITION_PLUS_VWAP_STRENGTH_BY_1030 为 top descriptive | 人工 heuristic candidate | promotion、阈值搜索 |
| Human watch | 手工选择/拒绝 | qualitative only | 记录原话 | 统计 edge |
| Analog v03 | Draft PR #21 | 未完成 | 仅 draft research | production use |

### Detailed hypothesis inventory

这是防止重复研究负方向的最低全局 registry；“未形成单一 reviewed result”本身就是审计结果。

| Hypothesis | Dataset / N | Effect | Main confounders | Result level | Promotion Status |
|---|---|---|---|---|---|
| Weekly favorable context improves entry | historical resolved 585 | 10bp E[R] -0.6104；cap5 -1.2956 | regime/time clustering | REJECT | REJECT_FOR_PROMOTION |
| Price-volume context improves entry | reviewed historical study；N未在单一registry汇总 | negative/no robust edge | feature multiplicity | REJECT | REJECT_FOR_PROMOTION |
| Joint weekly + price-volume helps | resolved 310 | 10bp -0.4851；cap5 -1.0598 | reduced sample | REJECT | REJECT |
| Sector context | no reviewed frozen result located | NOT_MEASURED | taxonomy/provider mapping | UNRESOLVED | NOT_PROMOTED |
| Washout | descriptive artifacts | effect未统一登记 | post-hoc definition | OBSERVE_ONLY | NOT_PROMOTED |
| Chip distribution | local human-watch/chip snapshot only | no causal effect estimate | vendor/current-vintage/selection | QUALITATIVE | NOT_PROMOTED |
| B1/B2 entry edge | corrected execution cohorts；B1 747、B2_READY 1,627、B2_CONFIRMED 637 before resolution filters | means mostly negative；no supported subgroup | fill/T+1/selection | NO_PROVEN_ENTRY_EDGE | REJECT_PRODUCTION |
| High-level consolidation | morphology S=409，controls=8,095 | OR 1.64 vs all，CI 1.27–2.06 | same-sample archetype comparisons | SUPPORTED_DESCRIPTIVE | NOT_PROMOTED |
| Morphology nearest-neighbor selects SUCCESS | 97 analogs | SUCCESS 2.1% vs base 4.7% | representation/prototype choice | REJECT | DO_NOT_REPEAT_UNCHANGED |
| Opening panic drawdown predicts success | V02A S=40，F=99 | d≈0.03，near no difference | concentrated event dates | NOT_SUPPORTED | NOT_PROMOTED |
| Fast reclaim predicts success | V02A S=40，F=99 | reclaim occurrence +0.100/+0.154 later；speed not measured | metric does not measure duration | NOT_MEASURED / NO_CLEAR_EVIDENCE | NOT_PROMOTED |
| VWAP acceptance on outcome event day | V02A S=40，F=99 | dist-to-VWAP d=0.50@10:30、0.59@11:30 | event-day/label proximity、same sample | SUPPORTED_DESCRIPTIVE | HUMAN_HEURISTIC_ONLY |
| S1 acceptance | V02A S=40，F=99 | S1_STATE diff +0.227@10:30；rebreak diff -0.168 | S1 event defines label family | SUPPORTED_DESCRIPTIVE | HUMAN_HEURISTIC_ONLY |
| High progression | V02A S=40，F=99 | adjacent-checkpoint d=0.30/0.38 | checkpoint multiplicity | SECONDARY_DESCRIPTIVE | NOT_PROMOTED |
| Quiet D0 volume pace | intraday B-point S=40，F=97；reference eligible=195 | rank-biserial about +0.23→+0.31，SUCCESS lower volume | complete-case/time window/provider | CANDIDATE_FOR_FORWARD | NOT_STARTED |
| Shallow session low | intraday B-point S=40，F=97 | rb about -0.31→-0.27 | cohort/time clustering | CANDIDATE_FOR_FORWARD | NOT_STARTED |
| Narrow session range | intraday B-point S=40，F=97 | rb about +0.21→+0.27；CI often wide | small sample | OBSERVE/CANDIDATE COMPONENT | NOT_STARTED |
| Quiet Compression composite | V02 reference 195 | reference distribution frozen；no forward effect | same development sample、component dependence | CANDIDATE_FOR_FORWARD | FORWARD 0 ROWS |
| Human watch selection | daily manual cards | no controlled effect | discretionary selection | QUALITATIVE | NEVER_AUTO_PROMOTE |

### 冻结 artifact provenance

- corrected episodes：31,422 rows，SHA-256 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093。
- execution episodes：31,422 rows，SHA-256 3c3cfc044c820f20558a4ff363fa68229d38d035f72760aefe7c22a430db024d。
- 两者 snapshot_id 均为 snap-2026-07-31-b5f84004de8a，strategy_config_hash 均为 47a0ea2b…。
- 两者全部记录 strategy_commit=315fbe0，而 phase-2d0 内容 commit=e865de4。配置和数据哈希仍可复核，但精确代码 provenance 需解释 e865de4 中 outcome 修订与 315fbe0 的关系。

## 9. FORWARD INTEGRITY AUDIT

### 当前状态

| Artifact | 声明的 content hash | 物理文件状态 |
|---|---|---|
| V01 protocol | 4125a4496540… | 存在；已被 V02 prestart supersede |
| V01 reference | 9b8863a7dc71… | 存在；不得 refit |
| V02 protocol | aaca250e9bea… | 存在 |
| V02 reference | dd307825740e… | 存在，但 builder 可无条件覆盖 |
| V02 manifest | 0540ff9bd68b… | epoch_id=FORWARD_EPOCH_1_V02 |
| candidates/checkpoints/outcomes | — | 各 0 行，全部列为 Arrow null type |

FORWARD_STATUS = NOT_STARTED_CORRECTLY。0 行意味着没有 retroactive contamination，但 null schema 也意味着第一个 append 才会隐式决定物理类型，增加兼容风险。

### V01 → V02 repair integrity

| Check | Evidence | Audit |
|---|---|---|
| Supersede reason | PRESTART_REFERENCE_SEMANTIC_DEFECT | Legitimate because V01 forward rows=0 |
| Development membership | original 206；V02 eligible 195；11 missing required D1 same-time data | Explicit and same membership for components/checkpoints |
| Outcome-blind builder | manifest says outcome_based_filtering=false；static builder membership does not read outcome | PASS_STATIC |
| Historical backfill | false；cross-provider reference backfill=false | PASS_CURRENT |
| TDX compatibility | V02 manifest claims quartile agreement 1.0 / PASS_TDX_V02 | Artifact claim only |
| Governance conflict | local ADR-008 earlier records 94.4% <95% FAIL，then local V02 manifest claims repaired PASS | Requires reviewed chronological ADR; neither is in knowledge main |
| Start approval | no approval/start timestamp；ledgers 0 | NOT_STARTED |

### Runner 缺陷

| 严重度 | 缺陷 | Evidence | 后果 |
|---|---|---|---|
| P0 | HHMM 比较未来泄漏 | run_forward_bpoint_v01.py lines 414–437 | 09:45/10:00 使用未来 bars |
| P0 | V02 仍写 V01 epoch/reference | lines 365、405、466 | 协议、reference、ledger 不可一致复核 |
| P1 | early checkpoint 要求至少 10 bars | line 437 | 09:45=3、10:00=6，修正时间后仍不可运行 |
| P1 | d1_close/d1_volume 为 None | lines 377–378 | price-relative features 与 outcome provenance 不完整 |
| P1 | candidate_source_hash 可空 | line 387 | candidate freeze 无法证明来源 |
| P1 | read-concat-overwrite Parquet | lines 389–393 及后续 append | crash/concurrency 会丢失或重复 ledger |
| P1 | reference_repair_v02 无条件覆盖 | reference_repair_v02.py line 272 | “immutable reference”实际可被重写 |
| P2 | dry-run 可写 calendar cache | lines 302–323 | dry-run 非纯只读 |
| P2 | outcome 可产生 code=None 路径 | runner outcome construction | ledger contract 不完整 |

### Forward statistical plan audit

V02 已预注册：

- checkpoints：09:45、10:00；
- primary features：D0/D1 same-time volume pace、session low vs previous close、session range；
- equal-weight empirical midrank ECDF Quiet Score；
- fixed outcome taxonomy 和 3-session structural horizon；
- interim gate：SUCCESS ≥10、FAILED_BREAKOUT ≥20；
- decision gate：SUCCESS ≥30、FAILED_BREAKOUT ≥30、trading sessions ≥20；
- forbidden：threshold scan、weight change、outcome redefinition、historical backfill。

### QUIET → ACTIVATE → ACCEPT → EXPAND separation

该链条只能作为研究 ontology，不能在本审计中升级为 production rule：

| Stage | Meaning | Current V02 coverage | Conflation risk |
|---|---|---|---|
| QUIET | checkpoint前的相对量能、浅回踩、窄幅 quality context | Quiet Score三组件和quartile明确 | Quiet不是buy trigger，不能因Q4自动“可买” |
| ACTIVATE | 价格开始挑战 trigger/S1 的事件 | runner有 activation_state 字段但协议未给完整primary hypothesis | 易与 B2_CONFIRMED 或 S1_TOUCH 混名 |
| ACCEPT | checkpoint close/后续bar对关键位的站稳/接受 | V02研究有 S1/VWAP descriptive fields | acceptance是事件日中间态，不等于最终SUCCESS |
| EXPAND | 后续价格/量能扩张并在冻结 horizon 得到 outcome | structural outcome taxonomy | SUCCESS本身含volume条件，不能用同日volume作独立edge证明 |

当前 protocol 对 QUIET 定义最完整，对 ACTIVATE/ACCEPT/EXPAND 的统计 estimand、时间界限和primary endpoint不足；runner又把 activation_state 与最终 outcome 写在相邻流程，存在概念混用。启动前必须为每一层定义 timestamp、输入、输出、不可使用字段和唯一 namespace。

缺口：

1. 没有显式 primary hypothesis、effect size、confidence interval/test family、multiple-comparison policy。
2. gate 用 outcome class count，而不是总体样本/有效 checkpoint 数；UNKNOWN/MISSING 的停止规则不足。
3. 没有数据 outage、半日市、停牌、涨跌停无成交、corporate action 的 operational stop rule。
4. 没有 ledger schema version、idempotency key、sequence、write-ahead log、file hash chain。
5. 没有规定何时仅做 interim descriptive read、何时允许 final inference，以及谁签字。

### Forward 允许启动前的 hard gates

1. 8/5 canonical 和 states 必须被隔离，使用重新发布且 SCREEN_READY 的正确 D-1 数据。
2. V02 runner 必须只读加载唯一 V02 protocol/reference/manifest，并逐字段 hash 验证。
3. 09:45/10:00 bar slicing、D1 same-time、completed-bar semantics 必须有 golden + adversarial tests。
4. candidates 必须冻结 D1 close/volume、source snapshot/hash、setup/config/strategy commit。
5. ledgers 必须预建 typed schema、append-only/idempotent/atomic、具备 crash recovery。
6. reference 必须 create-once，任何 repair 只能生成新 version，不能覆盖。
7. Human/Architect 明确授权启动新的、非回填 epoch。

## 10. SOFTWARE ARCHITECTURE AUDIT

### 模块与依赖

| 层/模块 | 责任 | 观察 |
|---|---|---|
| models | Pydantic contracts、enums、signal invariants | 最清晰的领域层；signal model 较大但保护力强 |
| strategy | math、indicators、structure、patterns、scoring、engine | 冻结核心；evaluate_strategy 568 行，内部职责过多 |
| providers / warehouse | provider adapters、fetch、reconcile、snapshot、metadata、validate | 正式旧路径完整，但 provider policy 与 ADR-008 不一致 |
| screen | canonical loading、per-code engine、state、verify、chunk runner | streaming 优化有效；publication/status/universe/state transaction 边界弱 |
| replay / inspect | 单股可解释回放 | 与策略内核边界相对清晰 |
| trade_plan | 次日执行观察 | 依赖 screen state 和 strategy private concepts，单文件职责偏大 |
| outcome / execution / diagnosis / robustness | 研究与统计 | 研究逻辑进入 package，便于测试但与 production CLI 强耦合 |
| research scripts | migration、B-point、intraday、daily review、Forward | 多数是脚本式 pipeline，缺少公共 contract、review/lifecycle |
| cli | 全部 use case 的装配 | eager import warehouse 导致 base dependency 边界失效；build_parser 281 行 |
| reports/artifacts | Markdown/JSON/CSV/Parquet 分散在 research、data/tmp、docs | 没有统一 report service，符合 non-goal；但缺 artifact registry/lifecycle |

静态 import graph：67 个 package modules、258 条 internal edges、0 个强连通循环。未发现 strategy import research、strategy import provider，或 provider logic 直接进入 strategy core；主要 domain leakage 发生在 application/research 脚本绕过 warehouse，以及 outcome/trade_plan 等跨层调用 private helper。

### Domain-driven boundary review

推荐的现有 domain：

1. MarketData：raw/normalized/reconciled/canonical/snapshot。
2. StrategySetup：frozen lifecycle、price-domain math、signals。
3. Screening：universe + snapshot + state advancement。
4. ExecutionObservation：TradePlan/B1_PREP，不反写 setup。
5. HistoricalResearch：episodes/outcomes/diagnostics。
6. ForwardObservation：candidate freeze/checkpoint/outcome ledger。
7. Governance：truth manifests、ADR、promotion、provenance。

当前跨界：

- CLI import 所有 warehouse 模块，令可选依赖变成事实必需依赖。
- outcome、trade_plan、screen 调用 strategy/screen 私有 helper，形成隐式 API。
- migration 与 Forward 代码在 research 目录直接写 production data/ledger。
- knowledge promotion 和 runtime publication 没有 machine-enforced gate。

### 代码形态

本次 AST 统计：src/limit_pullback 下 67 个 Python 文件、20,826 行。最大定义包括：

| 定义 | 行数 | 风险 |
|---|---:|---|
| WarehouseMetadata class | 679 | schema、queries、mutations 责任集中 |
| evaluate_strategy | 568 | 冻结语义、PIT、scoring、lifecycle 难以局部验证 |
| TushareProProvider class | 433 | 旧 provider policy 的大型适配器 |
| pipeline._bootstrap_impl | 417 | fetch/reconcile/publish/metadata/error 混合 |
| outcome.run_outcome_study | 396 | orchestration 与研究计算混合 |
| build_score | 336 | 多维评分集中且反复排序 |
| pipeline._update_impl | 328 | 同类重复复杂度 |
| screen.run_screen | 322 | state/verify/output/manifest 事务边界不清 |

### Dependency audit

- pyproject core dependencies 只有 pydantic 和 PyYAML；duckdb、pyarrow 在 warehouse extra。
- cli.py lines 17–20 启动时 eager import warehouse modules，因此最小安装执行 help 也需要可选 extra。
- 系统 Python 直接运行 pytest 在 collection 阶段出现 24 个 duckdb/pyarrow import error；完整 .venv 环境可通过全部测试。
- 当前声明 Python >=3.11,<3.13；系统 Python 3.14 不在支持范围，这应由 tooling 明确拒绝，而非表现为随机缺模块。
- 没有 lockfile；依赖只用范围 pin，无法重现解析后的精确环境。
- wheel 只打包 src/limit_pullback；没有 package-data 声明，config/strategy.yaml 和 trade_plan.yaml 不在 wheel。
- 本地 pyproject.toml 未提交地增加 pytdx；远端 main 不具备这一 provider dependency 事实。

| Dependency class | Declared packages | Audit |
|---|---|---|
| core | pydantic、PyYAML | small and appropriate，but CLI cannot actually stay core-only |
| warehouse optional | duckdb、pyarrow、pytz、tushare | production screen/CLI事实必需，命名误导 |
| integration optional | akshare、baostock；local dirty pyproject adds pytdx | provider set与reviewed main不一致 |
| test | pytest | only test runner；no property/mutation/lint/type tools |
| dev | none | no formatter/linter/type checker/packaging test contract |
| research | none | scripts rely on pandas/numpy and additional transitive environment packages，not reproducible |

Provider package risk不是“是否能pip install”这么简单：pytdx最新PyPI release停在2019且项目自行声明不保证及时处理；应由多个服务器、protocol fixtures、timeout和audit provider缓解，不能因版本range满足就认定可用。

### Configuration / API / CLI

| 项目 | 结论 |
|---|---|
| Strategy config | Pydantic 校验强，hash 与冻结基线一致 |
| TradePlan config | 执行观察与策略分离是正确方向；默认值在 models/config.py 与 trade_plan.py fallback 重复 |
| Versioning | package 0.1.0、strategy_version 0.1.0、phase-2d0 三套版本无正式映射 |
| CLI errors | argparse 与 provider errors 有结构化/脱敏处理 |
| CLI composition | 单模块装配过大且 eager import |
| Backward compatibility | snapshot/state schema 缺少显式 schema_version/migration registry；Forward 0-row null schema 尤其脆弱 |
| Public API | 内部 helper 被跨模块依赖，缺少稳定 application service 接口 |

| Config class | Authoritative source today | Audit |
|---|---|---|
| Strategy thresholds | config/strategy.yaml | STRONG/FROZEN，hash verified |
| TradePlan observation | config/trade_plan.yaml | GOOD intent；model/fallback defaults duplicated |
| Provider/reconciliation | pyproject extras + warehouse policy objects + ADR | CONFLICTING；TDX servers/timeouts/session list remain script constants |
| Runtime/performance | CLI flags + module constants（workers/chunk size/resource policy） | PARTIAL；some hidden defaults and no single runtime manifest |
| Research | config/outcome_study.yaml + script constants/report metadata | MIXED；formal outcome config强，local B-point/migration scripts弱 |
| Forward | protocol/reference/epoch JSON | HASHED；runner hardcodes conflicting values |

Magic numbers that affect provider retries、TDX servers、5m sessions、checkpoint bar minimum、workers and paths must move to a typed runtime/protocol contract only when that improves ownership; frozen strategy numbers stay in strategy.yaml and must not be mixed into the refactor.

### Backward compatibility matrix

| Artifact | Current version marker | Reader/migration policy | Audit |
|---|---|---|---|
| Snapshot manifest/canonical | snapshot_id + policy string，no schema_version | readers assume current columns | WEAK；V2 needs V1 adapter |
| Screen state JSON | no schema_version；Pydantic current model | invalid state may rebuild，but no explicit migration | WEAK |
| Episodes Parquet | run path + config/commit/snapshot hashes | frozen bytes，new corrections in new directory | STRONGER；commit mapping gap |
| Forward reference JSON | protocol/hash fields | V01/V02 separate files，but builder can overwrite | FAIL_IMMUTABILITY |
| Forward ledger Parquet | no schema_version；0-row null columns | first append defines types | FAIL |
| Research metrics/reports | RUN_ID/version in document varies | supersede by new file conventions | PARTIAL |

### CLI behavior matrix

| Dimension | Audit | Result |
|---|---|---|
| Discoverability/help | argparse 子命令与 help 存在；.venv help通过 | PASS_FULL_ENV |
| Consistency | JSON error envelope部分统一，research scripts各自风格 | PARTIAL |
| Read-only distinction | inspect/replay/status语义可辨；scripts不统一声明 | PARTIAL |
| Dry-run/preflight | 部分重要动作有 dry-run；Forward dry-run仍可写calendar cache | FAIL_PURITY |
| Destructive/publish action | snapshot/publisher没有统一confirm/promotion token | FAIL_GUARD |
| Exit codes | argparse/provider paths可非零；脚本大量SystemExit文本 | PARTIAL |
| Dependency isolation | base CLI eager import optional warehouse deps | FAIL_BASE_INSTALL |
| Machine-readable output | CLI错误较好；普通运行日志/metrics不统一 | PARTIAL |

任何 publish、state promote、Forward append 必须先提供等价 preflight，输出将使用的 commit/config/snapshot/source/universe/hash、expected rows、disk estimate 和 gate result；preflight 必须零写入。

| Command class | Commands | Side effect / audit |
|---|---|---|
| Intentional unavailable guards | report、run、backtest | exit as not implemented；符合non-goal |
| Inspection/network | inspect、replay、provider-probe | provider access需timeout/classified errors；not purely local |
| Warehouse mutation | bootstrap、update | publishes data；must gain guarded dry-run/promotion |
| Warehouse read/validate | data-status、data-validate | intended read-only；memory-heavy |
| Production derived mutation | screen | writes states/runs；no transaction/status gate |
| Execution read model | trade-plan | depends on state/canonical；must fail on blocked snapshot |
| Research artifact writers | outcome-study、outcome-relabel、execution-reality | versioned derived outputs；outcome-relabel needs clear destructive/preflight language |
| Read-only research | diagnosis | read-only by intent |
| Environment diagnostic | hardware-profile | read-only |

Top-level help本身已漂移：标题仍停在 Phase 2C.1/2C.2A，footer称“不执行全市场筛选”，但同一help已经列出screen。CLI discoverability因此不是完全PASS。

### Naming / ownership / maintainability

- FIRST_ATTACK、SECOND_LAUNCH 等必须 namespace；setup、event、outcome、intraday 不得共用裸名。
- 名为 run_forward_bpoint_v01.py 的脚本支持 protocol v02，造成版本误导。
- CURRENT 与 SCREEN_READY 的语义没有状态机；“latest”也没有“latest usable”的明确定义。
- Main agent/human review 是唯一 writer 的流程规则存在，但运行时没有 CODEOWNERS、branch protection 或 required reviews 强制。
- 大量 research artifact 没有 owner、retention、promotion/deprecation metadata。

### Maintainability scores

| Question | 1–5 | Evidence |
|---|---:|---|
| 新人能否定位核心 strategy semantics | 4 | mandatory context + strategy/models清晰；agent-context过期 |
| 修改 provider 是否能隔离于 strategy | 3 | package方向正确且无strategy→provider import；publisher旁路破坏流程边界 |
| 新增 research 是否不污染 production | 1 | 未跟踪 research scripts 已直接发布 canonical |
| 新 feature 是否易于写可靠测试 | 3 | fixtures/Pydantic较好；真实data/Forward contract难导入、脚本重复helper |
| 模块是否容易局部理解 | 2 | evaluate_strategy/pipeline/runner/outcome有322–568行大函数 |
| 配置/版本是否单一可追踪 | 2 | 三套版本、重复defaults、无schema registry |
| 故障是否容易恢复和解释 | 2 | hashes/state字段丰富；无transaction/runbook/alerts |

平均 maintainability：2.43 / 5。重构优先改善 semantic boundary、testability 和 ownership，不因“代码长”机械拆分。

### Ownership and permissions

| Actor | Allowed | Forbidden | Enforcement today |
|---|---|---|---|
| ChatGPT / Research-Strategy Architect | 提假设、审阅语义、给promotion建议、维护知识候选 | 直接改production、启动/回填Forward、合并 | 文档约定，无machine enforcement |
| Codex / Execution Engineer | 在批准scope内实现、测试、profile、写审计报告 | 自行改frozen threshold/semantic、自动merge | AGENTS约定；branch protection缺失 |
| Human | 决定truth/promotion、批准strategy/ADR/Forward start、review/merge | 不应绕过证据gate直接把local artifact当production | 唯一真实gate，但无required review |
| CI | 应验证lint/type/test/golden/data contract/hash/security/package | 不得访问真实provider作为blocking default，不得promotion | 当前不存在 |
| Production pipeline | 只从clean reviewed commit stage→validate→promote | dirty script publish、silent fallback、partial publication | 当前未强制 |
| Research pipeline | 只读immutable input，写versioned research artifact | 修改canonical/frozen/Forward history | 当前script权限未隔离 |

## 11. PERFORMANCE AUDIT

### 本次真实只读 benchmark/profile

本次用最后一个 SCREEN_READY 快照 snap-2026-07-31-b5f84004de8a，对历史 benchmark 相同的 20 个主板代码做完整冷状态推进；不写 state、不写 run artifact、不访问网络。profile 包含 canonical streaming、策略计算和逐行稳定序列化：

| 指标 | 结果 |
|---|---:|
| Codes | 20 |
| Timeline rows | 11,173 |
| Wall time | 4.428 s |
| Throughput | 2,523.5 rows/s |
| Process peak RSS | 235,257,856 bytes，约 224.4 MiB |
| Strategy evaluate cumulative | 2.957 s |
| screen_code cumulative | 3.511 s |
| build_score cumulative | 0.971 s |
| repeated sorted cumulative | 0.783 s |
| canonical iterator cumulative | 0.541 s |
| calculate_indicators cumulative | 0.362 s |
| Function calls | 32,106,161 |

本次生成的流式审计 hash 为 2cf523f490178ba6fae07a68524b16853197db4b70637dbbe893ef0527bbe863，final-state 审计 hash 为 1953b80dcc233962680e4233889b01f978f421036a8fc9eadbbd17994fb24ca4。它们采用本次审计序列化格式，不应与生产 runner 的 output hash 直接比较。

第二次同样只读的 phase benchmark 将 20 个最终 state 写到自动清理的临时目录，不触碰 production：

| Phase / resource | Measured result |
|---|---:|
| Metadata + 901-row pool load | 0.1373s |
| Parquet iteration / conversion | 0.4887s |
| Strategy evaluation | 1.6649s |
| 11,173 timeline JSON serialization | 0.1541s；24,604,819 bytes |
| 20 atomic temp state writes | 0.0037s；96,296 bytes |
| Phase total | 2.4487s |
| Peak RSS | 233,291,776 bytes |
| Recorded Parquet rows scanned for same 20-code loader shape | 3,145,728 to return 11,173 rows |

两次 wall time不同来自 cProfile/serialization instrumentation；都不是用于交易结论的 benchmark。CPU 热点来自 cProfile，I/O 用 iterator wall time/recorded rows-scanned，serialization/state-write 是实测临时输出。

### 已冻结性能证据

| Artifact | 结果 | 解读 |
|---|---|---|
| data/tmp/cold-rebuild-profile/profile.json | 20 codes，11,173 rows，92.445s，peak RSS 419,495,936 bytes；rolling 85.503s | 优化前 O(N²) 指标重算基线 |
| data/tmp/one-pass-precompute/result.json | 60.231s → 2.754s，21.87x；output/state hash equal | one-pass precompute 的强等价性证据 |
| Phase 2D.1A full-market record | 3,191 codes，1,844,543 rows，440.736s；parent peak 155MB，child peak 2.403GB | 生产路径可在约 7.35 分钟完成，但 child memory 偏高 |
| daily-screen-benchmark/benchmark.json | 旧 fast-path artifact 曾记录 equivalence=false | 它是后来修复前的历史实验，不得用作当前正确性证明 |

### Required scale coverage

本次在安全的 7/31 snapshot 上补跑了 20-code cProfile，以及 200/1,000-code current read-only phase benchmark；所有 final states 都只写入自动清理的临时目录。没有重跑 full-market production runner，因为它会写 production state/run artifacts；full-market规模复用已经冻结、具有 output-hash 等价证据的记录。

Current phase attribution（wall seconds；strategy子项嵌套在screen total中，不能相加）：

| Current read-only phase / resource | 200 codes | 1,000 codes |
|---|---:|---:|
| Returned bars / rows | 117,234 | 575,376 |
| Metadata | 0.2521s | 0.1366s |
| Universe setup | 0.0119s | 0.0078s |
| Parquet iteration | 1.2749s | 4.7373s |
| Screen total | 17.0016s | 86.8476s |
| └─ evaluate_strategy | 13.3544s | 68.4350s |
| └─ calculate_indicators | 2.4827s | 12.4574s |
| Timeline serialization | 1.6016s / 247,899,546B | 8.0741s / 1,250,264,062B |
| Atomic temp-state writes | 0.0349s / 762,165B | 0.1743s / 3,996,420B |
| CPU user / sys | 19.8188s / 0.2375s | 98.9808s / 0.9012s |
| Peak RSS | 245,088,256B | 252,968,960B |
| Input file / row groups / total rows | 198,074,256B / 4 / 3,282,707 | 198,074,256B / 4 / 3,282,707 |
| Input block operations | 0（OS cache） | 0（OS cache） |
| Audit output hash | 4c75dbe… | f56c6748… |

这两次 current measurement把 I/O、strategy、indicator、serialization、state-write、CPU 和 RSS 分开记录，但不是 cold-cache benchmark。冻结 full-market artifact只提供总 wall、parent/child RSS、row count和等价 hash，不提供相同粒度的 phase attribution；若要补齐，必须在独立 diagnostics PR 中增加 no-write runner 后再测，不能在本次审计里冒险运行生产写路径。

| Scale | Measurement | Wall / RSS | Equivalence / status |
|---:|---|---|---|
| 20 | 本次 current read-only profile | 4.428s / 235MB（cProfile run） | 11,173 rows；本次审计hash |
| 200 | 本次 current phase benchmark；另有 scaling_curve_v01 | screen 17.0016s / 245MB；旧线23.56s / 2.22GB | current audit hash；旧线output hash equal |
| 500 | scaling_curve_v01 | 61.32s / 4.49GB | output hash equal |
| 1,000 | 本次 current phase benchmark；另有 scaling_curve_v01 | screen 86.8476s / 253MB；旧线122.43s / 6.32GB，swap +0.726GB | current audit hash；旧线output hash equal |
| 3,191 full market | process-isolated chunks | 440.736s；parent 155,320,320B；max child 2,403,237,888B | 1,844,543 rows；hash 9abb16e4…；incremental semantic diff=0 |

这满足规模审计但不构成当前坏 snapshot 的运行许可：所有 scale artifact 都基于 7/31 frozen data。

### Complexity analysis

| Path | 近似复杂度 | 热点/风险 |
|---|---|---|
| Canonical streaming | O(total rows read) | Parquet row-group 仍会读取约 3.1m rows 才筛 20 codes；小样本 I/O 放大 |
| One-pass indicators | O(N) per code | 已从 prefix 全量重算中脱离 |
| evaluate_strategy over timeline | 约 O(N²) worst-case | 每个日期仍对 prefix 做 anchor/structure scans、排序和 tuple.index |
| build_score | O(N × candidates log candidates) | 反复排序，占本次 0.971s |
| screen output manifest | O(output rows) memory + disk | JSON 内嵌所有 rows，直接导致 GB 级单文件 |
| state verification | O(codes × history) | state 先写再 verify，失败成本高 |
| warehouse validate/status | O(full market materialized) | 不完全 memory-bounded |
| Forward append | O(existing ledger) each write | read + concat + overwrite，随 ledger 线性变慢且不耐崩溃 |

### Memory architecture

- 正面：canonical iterator 按代码流式 yield；chunk process 能隔离回收子进程内存。
- 缺口：部分 validation/status/research 路径 materialize 全市场；full-market child peak 2.403GB。
- chunks.py 设置 PYTHONPATH 为 repo/src/src，依赖 editable install 偶然成功；child 没有 timeout，也没传 debug pool mode。
- 现有 per-code state 只有约 20MB；真正的空间风险是 run JSON 和未治理的 research/tmp artifacts。

### Storage architecture

| 路径 | 审计大小 | 风险 |
|---|---:|---|
| data/screen/runs | 23GB | 38 个 JSON 中 7 个超过 1GB；最大 5.589GB |
| 8/5 screen run | 4.302GB | 内嵌全量 row payload，且来自坏 snapshot |
| data/canonical | 695MB | 可接受，但需 snapshot lifecycle/retention |
| data/raw | 809MB | 已 gitignore；需 provenance retention policy |
| data/tmp | 2.0GB | staging 与 production 状态矛盾；无自动 expiry |
| data/screen/states | 20MB | 尺寸小但语义已污染 |

| Storage form | Role | System of record? | Overwrite policy |
|---|---|---|---|
| Raw provider Parquet | ingestion evidence | Source evidence，受retention保护 | append/versioned；不可无记录覆盖 |
| Canonical Parquet + manifest | production data truth for one snapshot | YES when SCREEN_READY | immutable |
| DuckDB | metadata/query/index layer | publication registry，不替代canonical bytes | transactional updates only |
| State JSON | rebuildable production read model | NO，derived from snapshot+strategy | only atomic promoted generation |
| Research CSV/JSON/Parquet | versioned artifact | YES only when frozen+manifested for a study | draft可新版本；frozen不可覆盖 |
| Screen run JSON | rebuildable run artifact | NO | 可按retention删除，先保留hash/summary |
| Forward event ledger | future observation truth | YES once started | append/correction only，never overwrite |
| Cache/tmp | ephemeral/staged | NO | 可清理；不得被production pointer引用 |

查询性能优化不得把 DuckDB 或新缓存悄悄升级为 canonical truth；canonical bytes、manifest 和 promotion record仍是唯一数据真源。

### Performance regression contract

任何优化 PR 必须同时验证：

1. frozen input snapshot/config/commit 相同；
2. output rows hash、final-state hash、row count 完全一致；
3. PIT、INVALID、B2、Entry Room 等语义 invariants 不变；
4. wall time、peak RSS、rows read、rows materialized、disk bytes 都记录；
5. cold rebuild、incremental、verify-replay 三条路径分别测；
6. 不能用关闭 verification、减少 universe、放宽 threshold 换性能。

### PERFORMANCE_ROADMAP

| Priority | 阶段 | 建议 | 预期收益 | 正确性 gate |
|---|---|---|---|---|
| P0 | NOW | 不在坏 snapshot 上做性能工作；先恢复 correctness gates | 避免优化错误结果 | validated SCREEN_READY input |
| P1 | NOW | 将 run payload 改为 typed Parquet/JSON summary，manifest只存hash/count/path | 从GB级JSON降为可控列式文件 | output hash与replay等价 |
| P1 | NOW | 为chunk child加timeout、正确PYTHONPATH、pool mode propagation | 消除挂死和环境偶然性 | chunk/rebuild hash equal |
| P1 | NEXT | screen state采用stage-and-promote transaction | 失败不污染state | fault-injection tests |
| P2 | NEXT | profile并缓存每prefix不变的anchor/structure索引 | 减少重复scan/sort | property + golden + frozen hash |
| P2 | NEXT | validator改为DuckDB/Arrow aggregate streaming | 降低full-market RSS | 与旧validator逐字段一致 |
| P2 | LATER | 按日期/代码分区canonical和research artifacts | 减少小样本row-group读取 | snapshot hash/version migration |
| P1 | LATER | append-only Forward event log + compacted views | O(new rows) append、可恢复 | hash chain/idempotency tests |

## 12. TESTING AUDIT

### 本次执行结果

| Check | 结果 |
|---|---|
| 系统环境 pytest -q | collection FAIL：24 个 duckdb/pyarrow import errors；该环境还使用项目不支持的 Python 3.14 |
| 项目 .venv 完整离线套件 | 357 passed，16 deselected，176.22s |
| compileall | PASS：src + tests |
| pip check | PASS：No broken requirements |
| CLI help in .venv | PASS |
| git diff --check + report whitespace/table-shape check（最终） | PASS |
| Report structure | PASS：20/20 required sections；0–65 coverage = 66/66；TD-001–040各有3张键关联记录 |

测试全绿不推翻 P0：现有测试没有读取真实 8/5 snapshot continuity，也没有调用真实 V02 runner 的时间过滤路径。

### Testing pyramid

| 层 | 现状 | 评价 |
|---|---|---|
| Unit | 43 个 test 文件，大量模型、math、strategy、warehouse helper 例测 | STRONG |
| Contract/invariant | signal guards、snapshot guard、CLI errors、pool quality | MEDIUM-STRONG |
| Golden | fixture expectations、one-pass equivalence、replay/screen comparisons | MEDIUM |
| Integration offline | DuckDB/Parquet/pipeline/screen tests | MEDIUM |
| Real-provider integration | 16 tests默认 deselected | 合理；需手工运行记录 |
| End-to-end production artifact | 缺少“真实 snapshot validation → screen-ready → state promotion”封闭测试 | WEAK |
| Fault injection | 部分 resume 测试；无 multi-file crash/ledger/state promotion | WEAK |
| CI | 0 workflow | ABSENT |

### TEST_N_BY_TYPE

用 373 个 collected pytest nodeid 按文件职责做互斥 primary classification；参数化后的 case 按 nodeid 计数。该分类用于审计规模，不替代未来 pytest marker：

| Primary type | Test N |
|---|---:|
| Unit / domain model / strategy math | 140 |
| Application integration（screen/replay/trade-plan/CLI） | 82 |
| Data integration（warehouse/provider/chunks/resources） | 63 |
| Research reproducibility（outcome/execution/diagnosis/robustness） | 68 |
| Golden / contract primary files | 4 |
| Real-provider integration marker | 16 |
| Total | 373 |

横向能力并非互斥：部分 unit/application tests 也具有 snapshot/golden/data-contract性质。独立 property-based tests=0，mutation tests=0，automated performance-regression tests=0；性能等价性目前由离线 artifact 记录，不由 CI 执行。

为避免 primary classification 掩盖用户要求的横向能力，下面给出可重叠计数。`snapshot`按 collected nodeid 含 snapshot 计；`data contract`按 warehouse/provider/resource/chunk contract测试文件集合计；golden/equivalence按显式fixture或语义等价测试计；因此这些数字不能与373相加：

| Overlapping capability | Selection rule | Test N |
|---|---|---:|
| Snapshot lifecycle / guards | collected nodeid包含 `snapshot` | 15 |
| Data-contract behavior | warehouse/provider/resource/chunk contract文件集合 | 57 |
| Named golden fixture / contract | 显式golden fixture或golden primary file | 4 |
| One-pass semantic equivalence | 显式比较旧/新执行结果与hash | 1 |
| Real-provider integration / provider E2E | `integration` marker且访问真实provider | 16 |
| Property-based framework | Hypothesis/同类生成式property tests | 0 |
| Performance semantic regression | 断言优化前后语义等价，不断言wall/RSS阈值 | 1 |
| Automated wall/RSS regression | 在测试内断言性能预算 | 0 |
| Formal production artifact E2E | 真实validated snapshot → SCREEN_READY → atomic state promotion | 0 |

### Golden regression audit

已有正面覆盖：

- same-day B2 trigger 不确认；
- eligible_from、support/S1 future-row guards；
- INVALID terminal、新 anchor；
- Entry Room 不改 setup stage；
- continuous price / preclose math；
- one-pass precompute 等价；
- replay vs screen 的样例等价；
- token redaction 与 structured CLI errors。

缺失或错误的 golden：

1. 三个连续交易日 preclose[n] == close[n-1]，并同时验证 pct_change/limit reference。
2. status 不是 SCREEN_READY 时 formal screen 必须 fail closed。
3. limit-up pool 必须覆盖 as_of 或有显式“无涨停”证明，不能静默复用旧 pool。
4. full-market universe 只能包含 000/001/002/003/600/601/603/605 等冻结主板范围。
5. B2_CONFIRMED 是否单调的单一人类决议 golden。
6. Forward 09:45 恰好 3 根 completed 5m bar、10:00 恰好 6 根；15:00 不得进入。
7. V02 runner 只能加载 V02 epoch/reference/hash。
8. reference create-once、ledger typed empty schema、append idempotency 和 crash recovery。
9. clean wheel 在支持 Python 上安装并执行 CLI/config resource。

### Property-based tests

没有 Hypothesis 或等价 property framework。建议的性质而非固定样本：

- 任意合法 bar sequence 下 as_of 增加不能改变过去 signal snapshot；
- INVALID 在同 setup 内不回退；
- entry/execution 字段变化不改变 setup stage；
- preclose continuity 与 price-domain round-trip；
- chunk size/ordering 不改变 output/state hash；
- provider row ordering 不改变 reconciliation；
- screen rebuild 与任意合法 incremental partition 等价；
- ledger 重试不重复 event。
- S1 必须位于合法 trigger/structure 上方且使用同一 price-domain；
- support 与 allowed close tolerance 的关系始终成立；
- 同一 setup 不产生 duplicate setup_id；
- 所有 frozen_as_of/eligible_from/decision timestamps 不越过 as_of；
- volume >= 0、high >= max(open,close,low)、low <= min(open,close,high)。

### Mutation / adversarial testing

未配置 mutmut/Cosmic Ray 等 mutation 工具。高价值 mutations：

- 将 eligible_from +1 day 改成 same day；
- 将 Forward minute comparison 改成 HHMM/midnight 混用；
- 将 selected whole row 改成 field merge；
- 忽略 snapshot status；
- 删除 main-board filter；
- 将 prior close 固定成首日；
- 将 B2_CONFIRMED 分支下移；
- 在 state verify 前后注入异常。
- provider primary失败时偷偷启用未批准 fallback；
- reference builder读取 outcome 后改变membership；
- empty provider result被当成“当日零数据”而不是 unavailable。

本次三路只读 adversarial review 已实际找出测试未覆盖的 P0/P1；说明 adversarial lane 有高边际价值，应进入 required CI。

### CI/CD

- GitHub Actions workflows = 0。
- main branch protection API 返回 Branch not protected。
- 无 required status checks、required reviews、CODEOWNERS enforcement、coverage gate、artifact hash gate。
- 因此“PR + human approval”目前只是流程约定，不是仓库控制。

建议 blocking 与 scheduled 分离：

| CI check | Blocking PR | Scheduled/manual |
|---|---|---|
| format/lint/type check | YES | — |
| 357 default offline tests | YES | — |
| frozen config/SPEC/DECISIONS hashes | YES | — |
| unit/golden/PIT/data-contract tests | YES | — |
| clean-wheel supported-Python smoke | YES | — |
| secret/privacy/path scan | YES | full-history scan scheduled |
| property/adversarial critical invariants | YES when added | extended mutation scheduled |
| real-provider integration/parity | NO network in default | scheduled/manual with artifact |
| 200/1000/full-market performance | NO per PR | scheduled and before performance merge |
| full canonical artifact validation | selected data PRs only | scheduled/explicit |

## 13. RELIABILITY / FAILURE MODE AUDIT

### FAILURE_MODE_MATRIX

| Failure mode | Detection | 当前行为 | 风险 | 要求的 fail-safe |
|---|---|---|---|---|
| Provider unavailable | retry/failure metadata | 旧 pipeline 可 provisional/pending | pending failures 仍可 publish | formal publication 必须 coverage gate |
| Provider silent schema/unit change | reconcile tolerance | unit heuristic 有限 | 错单位可污染 canonical | explicit normalized unit + dual-source contract |
| Multi-day preclose bug | 正式 validator 有 PRECLOSE_CONTINUITY | 未跟踪 publisher 绕过 validator 并发布 CURRENT | P0 correctness | 所有 publisher 强制调用 full-snapshot gate |
| Stale limit-up pool | 无 recency gate | 旧 901 行随新 snapshot 发布 | 漏新 anchors | derived coverage manifest |
| Partial snapshot crash | 单文件 atomic | 文件/manifest/DB 分步可见 | partial latest snapshot | staging namespace + single atomic pointer |
| Screen crash after state write | try/cleanup spool | state 已前进，verify/manifest 未完成 | retry 非幂等 | staged state + verify + atomic promote |
| Chunk child hang | 无 timeout | parent 无限等待 | operational hang | bounded timeout/kill/retry |
| Wrong universe | 无 formal assertion | 创造 2,006 非主板 states | 产品语义漂移 | universe contract + count/hash |
| Disk full | 无 preflight/retention | 23GB run JSON 持续增长 | partial artifacts | quota/preflight/compact retention |
| State JSON corrupt | load invalidates部分情况 | 可 rebuild | recovery 代价大 | checksum + journal + explicit rebuild runbook |
| Forward duplicate/concurrent append | date duplicate check only candidates | read-concat-overwrite | lost update/duplicate/corrupt | typed append log + idempotency key + lock |
| Reference accidental overwrite | 无 create-once guard | builder 覆盖同路径 | historical mutation | versioned immutable path + hash refusal |
| Calendar provider/cache failure | runtime fetch/write | dry-run 也变更 cache | non-determinism | frozen calendar snapshot |
| Dependency extra missing | import-time error | CLI/test collection fail | poor DX/ops | lazy import or correct dependency groups |
| Secret/provider error | redact helper | structured redaction tests | 相对较低 | central logging redaction |

### Error handling

正面：

- provider/auth errors 有结构化类型；
- token redaction 有测试；
- atomic helper 用于单个 JSON/Parquet；
- ingest run 可记录 COMPLETED/FAILED 和 pending failures；
- state prefix hashes 可检测部分输入变化。

缺口：

- pipeline 在 pending failures 非零时仍可创建 snapshot；测试甚至将其视为预期 resume 行为。
- latest/resolve_snapshot 没有 publication completeness/status 过滤；同日多个 partial snapshot 可能被解析。
- screen runner 在 verification 前写 state。
- research scripts 多用 SystemExit、裸文件 open、覆盖写；缺少统一 error envelope。
- Forward、snapshot 和 screen 缺少跨 artifact transaction。
- ADR-008 catch-up 在 lines 65–70 捕获任意 TDX Exception 后把 bars=None 并 continue；Tencent helper 在 lines 113–122 捕获任意 Exception、sleep 后返回 None。两者不保留异常分类、symbol failure record 或最终 coverage error，属于 silent partial-result path。
- empty result、provider unavailable 和“该日确实无行”在 prototype 中没有三态区分；这会把 outage伪装成缺失代码。

| External/data error | Classified? | Observable? | Recover/fail-fast? | Audit |
|---|---|---|---|---|
| Authentication/permission | 正式Tushare path有typed status | metadata/structured error | fail-fast/defer | PASS_OLD_PATH |
| Network timeout | 正式fetch部分有retry；prototype混用assert/generic except | prototype不可观测 | inconsistent | FAIL_ADR008 |
| Provider schema drift | model/required-field checks部分存在 | quarantine/issue in formal path | partial | PARTIAL |
| Empty result | formal capability语义有区分意图 | prototype无 | silent continue | FAIL |
| Partial result/day coverage | pending failures可记录 | formal metadata可见 | 仍可publish | FAIL_READINESS |
| Invalid OHLC | validator/model checks | issues/quarantine | reject row/snapshot depending path | PARTIAL_PASS |
| Duplicate bars | provider/validator tests存在 | issues | reject/dedupe policy | PASS_OLD_PATH |
| Missing preclose | snapshot writer过滤None；validator有checks | can silently reduce coverage | not fail-closed globally | FAIL_COVERAGE |
| Preclose discontinuity | PRECLOSE_CONTINUITY formal check | visible if validator invoked | ADR-008 bypassed | FAIL_PROMOTION |

### Provider/scenario resilience

| Scenario | Current behavior | Audit |
|---|---|---|
| TDX server down | connect assert 或 per-symbol Exception吞掉后continue | FAIL：既可能硬崩，也可能静默partial |
| Tencent unavailable | 两次generic retry后got=None；reconcile可生成PROVISIONAL | FAIL for production：无classified failure/coverage gate |
| Sina audit unavailable | research audit缺失，不应替代TDX | Acceptable only if明确AUDIT_MISSING且不改primary |
| One symbol malformed | 正式pipeline有quarantine思路；prototype可能异常/continue | PARTIAL |
| One day partial | 正式metadata可pending failure仍publish；prototype无day coverage hard gate | FAIL formal readiness |
| Canonical publish crash | 单文件atomic，多文件/DB分步 | FAIL transaction |
| Screen crash | state先写、verify后做 | FAIL idempotency |
| Forward checkpoint partial | whole-file rewrite，无event journal | FAIL durability |

### Observability

| 维度 | 现状 | 缺口 |
|---|---|---|
| Run identity | ingest_run_id、snapshot_id、screen run id | 未跟踪 scripts 没有统一 run registry |
| Metrics | warehouse metrics、benchmark JSON | production screen/Forward 没有统一 counters/latency/error schema |
| Logs | CLI JSON error +脚本 stdout | 无 structured logger、level、correlation ID、rotation |
| Data quality | reconciliation status、quarantine | latest ADR-008 bypass，0 formal reconciliation rows |
| Alerts | 无 | 无 snapshot continuity/pool freshness/storage/Forward mutation alert |
| Audit trail | Git PR + manifests | dirty worktree publication 打断链条 |

最低观测集合：run_id、git commit/tree、dirty flag、config hash、snapshot/source/canonical hashes、universe hash/count、row counts by status/date/provider、continuity failures、pool max date、state promotion status、wall/RSS/disk、error code、parent artifact、human approval ID。

| Operational question | Can answer now? | Evidence/gap |
|---|---|---|
| 今天用了哪个 snapshot？ | YES per state/run/manifest | default selection仍可能选错status |
| 哪个 provider？ | PARTIAL | snapshot provider_versions有；latest无formal reconciliation row |
| 多少 CONFIRMED？ | YES via Parquet/DB query | 没有自动日报/alert |
| 多少 stale/partial？ | PARTIAL | statuses可查；pool freshness/universe coverage未汇总 |
| screen run hash？ | YES | run artifact有hash但文件可达GB |
| candidate hash？ | INTENDED_NOT_RELIABLE | runner可写blank source hash；Forward 0 rows |
| Forward protocol hash？ | YES artifact | runner实际加载V01/V02错配 |
| dirty worktree是否参与production？ | NO standard field | 8/5事实说明需要强制记录 |

### Provenance

| Artifact | Provenance completeness |
|---|---|
| phase-2d0 config/SPEC/DECISIONS | STRONG，哈希与 tag 一致 |
| 7/31 snapshot | STRONGER，source_files/reconciliation/publications 可查 |
| 8/5 snapshot | FAIL，只有绝对 temp source hashes；0 source_files/reconciliation |
| Screen states | 字段丰富，但全部绑定坏 snapshot，故 provenance 可追但结果不可信 |
| Corrected episodes | hash/snapshot/config 强；strategy commit 映射缺口 |
| Reviewed research | 多数有输入/输出/结论；本地未跟踪研究不算 reviewed |
| Forward | protocol hash 强；runner/ledger durability 弱，尚无 observation |

### Security

- GitHub repository 为 PUBLIC。
- .env、data、venv、pyc 被 gitignore；tracked data/ 下文件数为 0。
- 静态源文件扫描未发现硬编码 credential assignment；认证错误有脱敏测试。
- 未跟踪 research/forward_paper_test_human_watch_v1.py 含精确私人持仓数量与成本字面量；不得提交或进入公共报告。
- 8/5 snapshot manifest 含 /Users/luke808/... 绝对路径，泄露本机用户名/目录结构且不可移植。
- 已跟踪 intraday case CSV 最大约 5.57MB，虽非 raw market warehouse，也应检查授权、去标识和 artifact policy。
- 无 dependency lock、SBOM、vulnerability scan、secret scan、signed release 或 branch protection。
- 本次 current-tree credential assignment scan 未发现真实 token；对 95 个 Git commits 的高置信 pattern（private key、GitHub token、OpenAI-style key、AWS key）和历史 .env path 做了只读 name-only scan，未命中 secret；历史只出现 .env.example。
- gitleaks/trufflehog 均未安装，因此上述不是全熵/全历史证明；仍需 CI 专用 secret scanner。

### Reproducibility environment

| Dimension | Audited value | Gap |
|---|---|---|
| Supported Python | pyproject >=3.11,<3.13 | clean matrix未自动执行 |
| Actual test Python | CPython 3.12.13 | PASS current machine |
| OS/arch | macOS 27.0 arm64 | Linux portability未验证 |
| Encoding/locale | UTF-8；C/C.UTF-8/C/C/C/C | locale assumptions未显式freeze |
| Timezone | process tzname CST；audit uses Asia/Shanghai；stored fetched_at UTC | CST歧义与timezone contract需测试 |
| Dependency resolution | current pip-freeze stream hash 6dd2ba86… | 没有版本lock，hash不能从repo重建 |
| Install | .venv CLI/tests pass | base extra/wheel config失败风险；未做clean clone wheel reproduction |
| Frozen artifact rebuild | hashes可核验 | 没有一键从clean tag重建episodes并证明hash |

结论：当前机器可以复核，不等于 clean-environment reproducible。最低目标是 clean clone → supported Python → locked install → offline tests → frozen hash validation；真实provider replay保持manual/scheduled。

### Disaster recovery

现有恢复能力：

- 可通过显式 snapshot_id 选择 7/31 SCREEN_READY 快照。
- strategy config/frozen tag、canonical hashes、corrected episode hashes可核验。
- screen state 理论上可从 canonical rebuild。

缺失：

- 无“隔离 bad snapshot → 恢复 publication pointer → 重建 states → 验证 TradePlan”的正式 runbook。
- 无 DuckDB/manifests/canonical 的一致性备份与 restore rehearsal。
- 无 multi-file transaction/journal，无法证明崩溃点恢复。
- 无 artifact retention/GC policy；存储满可能同时影响恢复。
- 无自动阻断“从坏 state 增量继续”。

### Forward ledger durability

当前 durability = FAIL：

- 0-row null schema；
- whole-file read/concat/overwrite；
- 无 lock、sequence、event id、schema version、hash chain、fsync/journal；
- reference 可原地覆盖；
- candidates/checkpoints/outcomes 之间无 referential constraint；
- 无恢复或 replay 工具。

Forward 启动前需要 event-sourced append log 或同等强度的本地事务方案；任何 derived Parquet 只能由 immutable events 重建。

## 14. DOCUMENTATION / KNOWLEDGE SYNC AUDIT

### KNOWLEDGE_SYNC_GAPS

| Gap | Knowledge state | Runtime/data state | Severity |
|---|---|---|---|
| Phase pointer | docs/agent-context 仍是 2C.2C / PR7 | main 已合并 PR25 | MEDIUM |
| Active provider policy | Master/Rule Catalog 写 Tushare+AKShare | 本地 ADR-008 写 TDX+Tencent；新 snapshot 标 ADR-008 | HIGH |
| ADR review state | ADR-007/008 未跟踪；008 GATE_PENDING | production publication 已发生 | CRITICAL |
| Current phase | KB main 最后记录 PR19 | 代码已有 PR20–25，另有大量本地研究 | HIGH |
| Research promotion | Context Pack 未含 8/3–8/5 全部本地研究 | scripts/reports 已生成 | MEDIUM |
| Forward | KB 旧 blocker 与本地 V02 PASS manifest 并存 | runner 仍不可运行，ledgers 0 | HIGH |
| Data migration | 无 reviewed source→canonical lineage record | 8/5 snapshot 0 reconciliation/source registry | CRITICAL |
| B2 lifecycle | State Machine 单调 | golden/code 可降级 | CRITICAL |
| Concept glossary | human terms较宽 | machine namespaces 缺失 | MEDIUM |

### Documentation audit

正面：

- SPEC、DECISIONS、STRATEGY_MASTER、RULE_CATALOG、STATE_MACHINE、Baseline Manifest 和 Context Pack 构成较完整的语义材料。
- README/strategy-overview 对产品用户路径有所改善。
- research reports 通常记录版本、样本、指标、结论边界。

缺口：

- 没有统一 system architecture、data contract、snapshot lifecycle、DR、Forward operations 文档。
- README 的 FIRST_ATTACK/SECOND_LAUNCH 语义比冻结机器规则宽。
- agent-context 明显陈旧，说明入口文档没有 freshness check。
- 绝对本机路径出现在正式文档/manifest，降低可移植性。
- Handoff、Current Phase、Baseline Manifest、GitHub main 缺少自动一致性检查。

| Document | Status | Audit note |
|---|---|---|
| README.md | CONFLICTING | product path有用；FIRST_ATTACK/SECOND_LAUNCH语义过宽 |
| SPEC.md | CURRENT_FROZEN | hash与phase-2d0一致 |
| DECISIONS.md | CURRENT_FROZEN | hash与phase-2d0一致 |
| CHANGELOG.md | STALE | 代码repo只记录到Unreleased Phase 2C.2B |
| docs/strategy-overview.md | CURRENT_BUT_HUMAN | 需受concept namespace约束 |
| docs/agent-context.md | STALE_CRITICAL_ENTRY | 仍指2C.2C/PR7 |
| AGENTS.md | CURRENT_PROCESS | 明确冻结和唯一writer，但无CI enforcement |
| STRATEGY_MASTER / RULE_CATALOG | FROZEN_STRATEGY_CURRENT；DATA_POLICY_STALE | strategy部分权威，provider policy落后 |
| Knowledge CHANGELOG / CURRENT_PHASE | STALE_AFTER_PR19 | 未覆盖8/3–8/5本地事实 |
| Research docs | MIXED | merged reports可审计；local-untracked不算reviewed |

### ADR governance

| Gate | 要求 | 现状 |
|---|---|---|
| Proposed/Accepted | 架构决议 review | ADR-008 local-untracked，无法证明 reviewed merge |
| Implementation | code/contracts/tests | 临时 research scripts，不在 main |
| Validation | parity、coverage、PIT、lineage | parity 研究有，multi-day preclose/pool/corp action漏检 |
| Promotion | status → production eligible | GATE_PENDING 时已发布 |
| Supersession | Master/Rule Catalog 同步 | 仍保留旧 active policy |
| Rollback | 明确 rejected snapshot/ADR status | 无 runbook |

结论：ADR 状态目前是文档标签，不是 machine-enforced promotion gate。

| Decision area | ADR coverage | Status |
|---|---|---|
| Dual price | ADR-001 | ACCEPTED/FROZEN |
| Snapshot timing | ADR-002 | ACCEPTED/FROZEN |
| Entry Room | ADR-003 | ACCEPTED/FROZEN |
| Setup-entry separation | ADR-004 | ACCEPTED/FROZEN |
| Main-board/provider boundary | ADR-005 | ACCEPTED/FROZEN；full screen违反 |
| Canonical reconciliation | ADR-006 | ACCEPTED/FROZEN historical |
| TDX/Tencent architecture | local ADR-008 | GATE_PENDING且未跟踪；被runtime越权使用 |
| Limit-up derived pool | no dedicated reviewed ADR | MISSING |
| Forward V02 repair/reference lifecycle | protocol/manifest，no reviewed ADR in KB | MISSING_GOVERNANCE |
| B2_CONFIRMED lifecycle conflict | no resolution ADR | P0_DECISION_REQUIRED |

### Git workflow / release governance

- 远端 main = e2d5b57，PR #25 已于 2026-08-06 前合并。
- 远端有 6 个 open Draft PR（#14–#18、#21）。
- main 无 branch protection；repository workflows 数为 0。
- phase tags 至 phase-2d0；phase-2d0 tag 解引用到 e865de4，且是 origin/main ancestor。
- GitHub Release 列表为空。
- 代码和知识工作区都 dirty；生产数据 mutation 来自未跟踪脚本。
- 没有签名 tag/release notes、artifact manifest bundle、rollback compatibility matrix。

推荐 PR labels：strategy-change、data-layer、research-only、performance-only、docs-only、forward-protocol、breaking-change、correctness-blocker、artifact-migration。strategy-change、data-layer、forward-protocol 和 breaking-change 必须触发专门 owner review。

### Version and release registry

不要让单一 version 同时代表所有层：

| Layer | Current marker | Required evolution |
|---|---|---|
| Software package | 0.1.0 | SemVer-like software release |
| Frozen strategy | phase-2d0 + config hash | 独立 strategy version，不随infra bump |
| Canonical schema | implicit function schema | CanonicalDailyV2 / schema_version |
| Snapshot instance | snap-date-random-id | immutable data release + validation/promotion hash |
| Research protocol | report/run IDs | protocol version + input/code/output hashes |
| Forward protocol/epoch | V01/V02 + epoch manifest | immutable version + start/close approval |
| Knowledge baseline | commit + Baseline Manifest | explicit compatibility map to code/data |

### Dead code / artifact lifecycle

不能仅凭静态扫描断言 dead code，但有以下 candidates：

| Candidate | Lifecycle class | 判定 |
|---|---|---|
| Tushare active CLI/provider path | LEGACY_COMPAT | 仍被旧warehouse import，不能直接删除；需deprecation plan |
| Eastmoney/AKShare old active adapters | LEGACY_COMPAT | 历史pool/provider仍依赖；在ADR-008完成前不可删 |
| PLANNED_COMMANDS report/run/backtest | ACTIVE_GUARD | intentional non-goal guard，不是待实现功能 |
| research v01/v01a/v01b/v01c scripts | ARCHIVE | 历史lineage，freeze/index/read-only |
| superseded V01 Forward files | ARCHIVE_IMMUTABLE | 标superseded，不能覆盖/删除 |
| 未跟踪 migration/Forward scripts | EXPERIMENTAL_STAGED | 不得视为production；review或隔离 |
| GB级 screen run JSON | SAFE_TO_REMOVE_AFTER_POLICY | 可重建derived；先留hash/summary并完成forensic决议 |
| pycache/tmp/cache | SAFE_TO_REMOVE | 非truth；不得被manifest引用 |

建议每个 artifact 声明：owner、schema_version、source hashes、status（draft/frozen/superseded/quarantined）、retention、rebuild command、promotion record。

### Artifact lifecycle matrix

| Class | Examples | Can overwrite? | Can delete? | Hash required? | Commit to Git? |
|---|---|---|---|---|---|
| EPHEMERAL | pycache、temporary spool | YES | YES | NO | NO |
| CACHE | provider minute cache、calendar cache | refresh by new generation | YES if reproducible | source/version recommended | NO |
| STAGED | raw catch-up、candidate snapshot before validation | NO in-place after manifest；create new | YES after expiry/quarantine policy | YES | NO raw data |
| CANONICAL | SCREEN_READY Parquet/manifest | NEVER | only explicit retention after replicas；normally keep | YES file+manifest | manifest/code only，not market bytes |
| FROZEN_RESEARCH | corrected episodes、approved reference | NEVER | NO | YES | small reviewed artifacts may commit |
| FORWARD | protocol/reference/events | protocol/reference NEVER；events append/correct only | NO | YES + chain | protocol/schema yes；private observation policy explicit |
| REPORT | reviewed Markdown/metrics summary | new version，not silent overwrite | superseded may archive | input/output hashes for research | YES if sanitized/reviewed |
| DERIVED_READ_MODEL | states、screen compact output | only atomic generation promotion | YES if rebuildable and safe source retained | root/file hash | NO production state |

## 15. TECHNICAL DEBT REGISTER

### Current project risk crosswalk

| Required risk area | Direct observation | Severity |
|---|---|---|
| GitHub truth drift | remote main e2d5b57，local code/KB dirty，production scripts untracked | HIGH |
| Local-only ADR-007/008 | ADR-008 GATE_PENDING且不在knowledge main | CRITICAL |
| Forward V02 local-only artifacts | hashes exist but runner/tests/artifacts不在remote main，ledgers 0 | HIGH |
| Limit-up pool dependency | latest pool max 7/31 and external membership hard dependency | CRITICAL/P0 |
| Corporate-action detector missing | hardcoded false，canonical drops field | HIGH |
| Provider dependency | TDX primary relies on stale pytdx protocol library；Tencent availability partial | HIGH |
| Research-production semantic drift | research scripts直接publish，B2 human/code semantics conflict | CRITICAL/P0 |

### Severity

- P0：stop-the-line，结果 correctness/PIT/provenance 已破坏。
- P1：开始任何新 Forward/production work 前必须解决。
- P2：稳定阶段解决；会持续放大维护、回归或运营风险。
- P3：整洁度与长期体验，不阻塞当前稳定化。

### TECH_DEBT_REGISTER

| ID | Sev | Debt / evidence | Consequence | Suggested owner | Exit criterion |
|---|---|---|---|---|---|
| TD-001 | P0 | 8/4–8/5 共 10,251 行 preclose 非 lag(close) | 连续价、涨停、收益、B2 全错 | Data | 坏 snapshot 隔离；正确重建且 continuity=0 |
| TD-002 | P0 | 5,197 states 全引用坏 snapshot | 当前 screen/TradePlan 不可信 | Screening | 从已验证 snapshot 全量 rebuild + hash/replay gate |
| TD-003 | P0 | 8/5 pool max date仍为7/31 | 漏 8/3–8/5 新 anchor | Data | derived pool coverage 到 as_of，明确 zero-day evidence |
| TD-004 | P0 | Forward HHMM 与 minute-of-day 混用 | 确定性 future leakage | Forward | completed-bar golden/adversarial tests 全过 |
| TD-005 | P0 | GATE_PENDING/untracked publisher 创建 production CURRENT snapshot | production result 不可追溯 | Governance/Data | reviewed ADR+code+lineage+promotion record |
| TD-006 | P1 | V02 runner 写 V01 epoch/reference | protocol mismatch | Forward | 单一 manifest-driven V02 loader + hash refusal |
| TD-007 | P0 | B2_CONFIRMED 可降回 B2_READY | 知识与代码语义冲突 | Architect/Strategy | 人工决议 +单一 golden；必要时独立 strategy PR |
| TD-008 | P1 | formal screen 不检查 SCREEN_READY | 坏 snapshot 静默消费 | Data/Screen | fail-closed status state machine |
| TD-009 | P1 | full-market 没有主板 universe gate | 2,006 越界 states | Screen | universe hash/count contract + tests |
| TD-010 | P1 | 8/5 无 source_files/reconciliation rows | 无法 audit provider row | Data | 每行/每源 lineage 可查询 |
| TD-011 | P1 | canonical 丢 confirmation/domain/unit/corp-action字段 | 合同不完整 | Data | versioned schema + migration |
| TD-012 | P1 | corporate_action_affected 全 false 且无 detector | 除权污染不可区分 | Data/Research | tri-state detector provenance |
| TD-013 | P1 | snapshot multi-file/DB 非事务 | partial publication | Warehouse | stage + validate + atomic pointer |
| TD-014 | P1 | state 在 verify 前写入 | 失败污染增量状态 | Screen | staged state atomic promotion |
| TD-015 | P1 | Forward ledger whole-file overwrite | crash/concurrency/lost update | Forward | typed append-only idempotent journal |
| TD-016 | P1 | V02 reference 可原地覆盖 | 历史 artifact mutation | Research/Forward | create-once versioned immutable path |
| TD-017 | P1 | 23GB screen run JSON | 磁盘/恢复风险 | Screen/Ops | compact artifact + retention policy |
| TD-018 | P1 | 无 CI、无 branch protection | 约定无法强制 | Maintainer | required offline suite/hash/security checks |
| TD-019 | P1 | Forward candidate D1 fields/hash 不完整 | checkpoint/outcome不可复核 | Forward | 完整 frozen candidate contract |
| TD-020 | P1 | ADR/Master/Rule Catalog/provider runtime 分叉 | 多真源 | Architect/KB | reviewed sync commit + automated freshness check |
| TD-021 | P2 | episodes strategy_commit 与 phase-2d0内容 commit 不同 | 精确复现解释不足 | Research | provenance note or immutable build mapping |
| TD-022 | P2 | migration tests 重写 production helper | 测试通过仍漏真实 bug | Data/Test | import shared implementation + real artifact contract test |
| TD-023 | P2 | optional warehouse deps被 CLI eager import | base install不可用 | Platform | lazy command imports or dependency regroup |
| TD-024 | P2 | wheel不含 configs | 安装后运行依赖 repo cwd | Platform | package resources + clean-wheel test |
| TD-025 | P2 | 无 dependency lock/SBOM | 环境不可精确复现 | Platform/Security | lock + reproducible env + scan |
| TD-026 | P2 | chunk child 无 timeout、PYTHONPATH=src/src、pool mode漏传 | 挂死/环境偶然 | Screen | subprocess contract tests |
| TD-027 | P2 | large functions 322–568 lines | 局部修改风险高 | Module owners | extract application services without semantic change |
| TD-028 | P2 | trade-plan defaults duplicated | config drift | Execution | one authoritative config model |
| TD-029 | P2 | strategy/package/phase版本无映射 | compatibility不清 | Architecture | version manifest |
| TD-030 | P2 | validator/status materialize全市场 | memory scale风险 | Data | aggregate streaming equivalence |
| TD-031 | P2 | 无 property/mutation/fault injection | invariants防护不足 | Test | targeted suites in CI |
| TD-032 | P2 | position-sizing研究先于 proven edge | governance drift | Research | archive as rejected exploratory; enforce gate |
| TD-033 | P2 | 私人持仓字面量在未跟踪脚本 | 公共仓库误提交风险 | Security/Human | exclude/sanitize + secret/privacy precommit |
| TD-034 | P2 | 绝对 /Users 路径进入 artifact | privacy/portability | Data/Docs | relative logical URIs |
| TD-035 | P2 | 无 DR/rollback rehearsal | 事故恢复不可预测 | Ops | documented tested runbook |
| TD-036 | P3 | 人工术语无 namespace | 语义沟通风险 | Docs/Domain | glossary lint |
| TD-037 | P3 | agent-context freshness drift | agent读取错误背景 | Docs | generated pointer/check |
| TD-038 | P3 | 无 release notes/signed artifact bundle | 交付治理弱 | Release | tagged release process |
| TD-039 | P3 | research artifacts缺 owner/retention | repo/磁盘持续膨胀 | Research/Ops | artifact catalog |
| TD-040 | P0 | ADR-008 provider prototype吞掉generic Exception并continue | outage可伪装成partial/empty canonical | Data | classified per-symbol/day failures + coverage fail-close |

上表 Sev 即 PRIORITY，Debt/evidence 即 DESCRIPTION，Consequence 是简要后果，Exit criterion 是验收。技术债登记采用ID归一化的三张表；以下先补齐每项的 AREA、CAUSE、EFFORT 和 PROPOSED_FIX，再把当前直接影响（IMPACT）与未来暴露（RISK）逐项分开。effort 为相对工程量 S/M/L，不代表可绕过 review。

| ID | AREA / debt class | CAUSE | EFFORT | PROPOSED_FIX |
|---|---|---|---|---|
| TD-001 | Data debt | 单一7/31 map复用于三日 | M | shared sequential preclose builder + full validator |
| TD-002 | Operations/data debt | state直接绑定latest坏snapshot | M | quarantine + clean full rebuild |
| TD-003 | Data debt | publisher复制旧pool | M | versioned canonical-derived pool builder |
| TD-004 | Research/PIT debt | minute-of-day与HHMM混型 | S | typed checkpoint time + completed-bar slicer |
| TD-005 | Governance/data debt | dirty untracked publisher有写权限 | M | reviewed promotion service + audit record |
| TD-006 | Forward debt | runner版本分支仍硬编码V01 | S | manifest-driven dependency injection |
| TD-007 | Strategy semantic debt | code/golden与State Machine长期分叉 | M decision / S–L migration | Human ADR first；then isolated semantic alignment |
| TD-008 | Data/architecture debt | loader只按latest/id解析 | S | require SCREEN_READY/validation hash |
| TD-009 | Domain debt | full-market codes未复用main-board contract | S | centralized UniverseContract |
| TD-010 | Provenance debt | prototype绕过metadata tables | M | raw/source/reconciliation registry writes |
| TD-011 | Data contract debt | staging fields未进入canonical schema | M | CanonicalDailyV2 + reader migration |
| TD-012 | Data/research debt | reserved flag先默认false | M/L | tri-state detector + source provenance |
| TD-013 | Reliability debt | 多文件/DB逐步publish | L | staging namespace + atomic pointer transaction |
| TD-014 | Reliability debt | state保存早于verify | M | staged state root + atomic promote |
| TD-015 | Forward/operations debt | whole-file concat overwrite | M/L | append-only event journal |
| TD-016 | Research governance debt | builder写固定reference path | S | create-once versioned artifact guard |
| TD-017 | Storage/performance debt | manifest内嵌全部rows | M | compact Parquet payload + summary manifest |
| TD-018 | Release/testing debt | GitHub controls未配置 | M | Actions + protected main + required reviews |
| TD-019 | Forward contract debt | candidate freezer不加载D1/source fields | M | typed CandidateFreezeEvent |
| TD-020 | Documentation/governance debt | knowledge promotion手工且未执行 | M | truth-sync PR + freshness checker |
| TD-021 | Reproducibility debt | artifact commit记录早于outcome fix | S/M | signed build provenance mapping/rebuild |
| TD-022 | Testing debt | tests复制prototype逻辑 | S/M | import shared production library + artifact E2E |
| TD-023 | Developer-experience debt | CLI eager import optional modules | S | lazy subcommand imports/dependency regroup |
| TD-024 | Packaging debt | wheel只包含src package | S | package resources + clean-wheel test |
| TD-025 | Supply-chain debt | range pins无resolution lock | M | lock per supported Python + SBOM |
| TD-026 | Reliability/DX debt | subprocess contract未建模 | S | timeout/env/pool-mode typed invocation |
| TD-027 | Architecture debt | orchestration与domain logic同函数增长 | L incremental | extract tested application services |
| TD-028 | Configuration debt | model和fallback各自定义default | S | one explicit TradePlanConfig source |
| TD-029 | Release debt | package/strategy/phase共用模糊版本 | M | compatibility/version manifest |
| TD-030 | Memory/performance debt | validators读取materialized rows | M | DuckDB/Arrow aggregate streaming |
| TD-031 | Testing debt | example tests占主导 | M | targeted property/mutation/fault suites |
| TD-032 | Research governance debt | sizing问题先于edge gate | S governance | archive/relabel and enforce research gate |
| TD-033 | Security/privacy debt | human portfolio写入script literal | S | external private overlay + precommit scan |
| TD-034 | Security/portability debt | manifest保存physical absolute path | S/M | logical URI relative to data root |
| TD-035 | Operations debt | 无事故演练责任人/步骤 | M | DR runbook + restore rehearsal |
| TD-036 | Naming/domain debt | human terms跨四种machine semantics | S/M | namespace glossary + lint |
| TD-037 | Documentation debt | hand-maintained entry pointer | S | generate/check agent context |
| TD-038 | Release debt | only tags/PRs，无release bundle | M | signed release manifest/SBOM/notes |
| TD-039 | Artifact/operations debt | artifact生成无registry/retention | M | artifact catalog + lifecycle policy |
| TD-040 | Error-handling/data debt | prototype用except Exception后返回None/continue | S/M | typed provider errors、failure registry、coverage gate |

| ID | IMPACT（当前直接后果） | RISK（继续运行或演进时的暴露） |
|---|---|---|
| TD-001 | 8/4–8/5价格、涨停判断、收益和信号输入错误 | 任一依赖该snapshot的筛选、研究或决策都可能得出假结论 |
| TD-002 | 当前5,197个screen states与TradePlan视图不可信 | 增量运行会把污染状态继续传播到后续日期 |
| TD-003 | 8/3–8/5的新涨停anchor缺失，产生假阴性/错阶段 | 后续pullback生命周期会从错误anchor集合继续演化 |
| TD-004 | 09:45/10:00 checkpoint确定性包含未来bar | 一旦启动Forward，样本外证据将因PIT泄漏整体失效 |
| TD-005 | CURRENT production snapshot无法由reviewed代码与lineage复现 | 未审prototype输出可再次绕过promotion gate成为生产真源 |
| TD-006 | V02候选与V01 epoch/reference混写 | 跨协议join可静默错配并污染后续checkpoint/outcome |
| TD-007 | runtime生命周期与冻结State Machine直接冲突 | 修复方向未决时，任一replay/backfill都可能改写历史语义 |
| TD-008 | formal screen可直接读取未达SCREEN_READY的snapshot | 后续坏snapshot也可能在无告警下进入生产消费 |
| TD-009 | 2,006个非冻结主板代码已被筛选并生成state | universe统计、候选率和资源估计会持续被越界标的扭曲 |
| TD-010 | 8/5数据无法逐源、逐文件追溯 | provider异常时无法定责、重放或证明覆盖完整性 |
| TD-011 | confirmation/domain/unit/corp-action语义在canonical层丢失 | 消费者会靠默认值猜测，导致跨provider计算不一致 |
| TD-012 | 除权影响被记录为确定的false而非unknown | 历史涨跌幅、anchor与outcome可能被公司行动静默污染 |
| TD-013 | 崩溃时可能暴露半套Parquet/manifest/DB publication | reader可能看到内部不一致的CURRENT snapshot |
| TD-014 | verify失败前production state已经改变 | 重试或增量screen会以失败运行的中间状态为起点 |
| TD-015 | Forward ledger在崩溃/并发下可能丢更新或损坏 | 一旦开始观察，无法保证append truth完整、可恢复或可审计 |
| TD-016 | 固定路径reference可覆盖既有版本 | 已做出的Forward决策将失去原始参考集，无法复核 |
| TD-017 | 38个run JSON占25,213,203,426B并拖慢读取/备份 | 磁盘耗尽或恢复窗口过长会中断日常筛选 |
| TD-018 | main分支没有自动required checks或保护 | correctness、安全或provenance回归可在约定之外直接进入main |
| TD-019 | frozen candidate缺D1字段与source hash | checkpoint和outcome无法证明使用了哪份候选输入 |
| TD-020 | ADR、Master、Rule Catalog和runtime表达不同真相 | 人、agent和代码会依据不同规则实施互不兼容的变更 |
| TD-021 | episodes记录的strategy_commit与内容冻结commit不一致 | 未来精确复现时无法仅凭manifest定位原始策略字节 |
| TD-022 | migration tests验证的是复制逻辑而非production helper | 真实publisher缺陷可以在测试全绿时进入artifact |
| TD-023 | 未安装warehouse extras时连无关CLI命令也可能import失败 | 可选依赖升级/缺失会扩大为整个CLI不可用 |
| TD-024 | wheel安装后缺少运行所需config资源 | 部署结果依赖repo cwd，clean环境行为与开发环境不同 |
| TD-025 | 同一版本声明可解析出不同依赖集合 | 重建环境不可精确复现，供应链风险也难形成可审计基线 |
| TD-026 | chunk子进程可挂死、依赖偶然PYTHONPATH且pool mode漂移 | full-market运行可能不可预测地超时或产生与parent不同结果 |
| TD-027 | 小改动需触碰322–568行编排函数 | 维护者更难隔离变更，冻结语义回归概率上升 |
| TD-028 | 相同TradePlan字段在多处拥有default | CLI、模型和配置缺省行为可能悄然分叉 |
| TD-029 | package、strategy、phase和artifact无兼容映射 | consumer无法可靠拒绝不兼容版本组合 |
| TD-030 | validator/status会materialize大规模数据 | 数据增长时可能OOM，使正确性gate本身不可用 |
| TD-031 | 边界、崩溃和组合不变量缺少系统化生成测试 | 示例未覆盖的输入可重复引入PIT、状态或promotion回归 |
| TD-032 | sizing探索越过“先证明entry edge”治理顺序 | 研究资源和风险讨论会建立在未证实收益上 |
| TD-033 | 未跟踪脚本包含精确私人持仓字面量 | 一次误add/push就会向公共仓库披露个人信息 |
| TD-034 | artifact泄露本机用户名并绑定物理目录 | 分享/迁移时暴露隐私且在其他环境不可解析 |
| TD-035 | 事故后没有经演练的恢复/rollback路径 | 数据损坏或错误promotion会造成更长停机和不可预测的数据损失 |
| TD-036 | 人类术语横跨setup、execution、research等不同语义 | 评审或盘前操作可能因同词异义做出错误判断 |
| TD-037 | agent入口背景与当前冻结阶段不同步 | 后续任务可能从错误假设开始并扩大文档漂移 |
| TD-038 | 没有可验证的release bundle/notes/SBOM | 交付、回滚和外部复核无法定位完整版本边界 |
| TD-039 | research artifact持续增长但无owner和retention | 磁盘、repo认知负担和孤儿数据会持续累积 |
| TD-040 | provider失败可被吞掉并返回partial/empty数据 | 局部或整体outage可能被误认作完整canonical并再次发布 |

## 16. TARGET ARCHITECTURE

### TARGET_ARCHITECTURE_VNEXT

目标是最小演进，不重写冻结策略：

~~~mermaid
flowchart LR
  subgraph Ingest["MarketData domain"]
    A["Provider adapters"]
    B["Typed raw rows + unit/domain metadata"]
    C["Whole-row reconciliation"]
    D["Staged canonical snapshot"]
    V["Validation gates: continuity, coverage, universe, pool, corp action"]
    P["Atomic SCREEN_READY pointer"]
    A --> B --> C --> D --> V --> P
  end

  subgraph App["Production application"]
    U["Frozen universe contract"]
    F["Frozen strategy core"]
    SR["Screen application service"]
    SJ["Staged state journal"]
    SA["Atomic state promotion"]
    PL["TradePlan read model"]
    P --> SR
    U --> SR
    F --> SR
    SR --> SJ --> SA --> PL
  end

  subgraph Hist["Historical research"]
    E["Immutable episode catalog"]
    R["Versioned research runs"]
    K["Reviewed conclusion registry"]
    P --> E --> R --> K
  end

  subgraph Forward["Forward observation"]
    M["Immutable epoch manifest"]
    CE["Candidate freeze event"]
    XE["Checkpoint events"]
    OE["Outcome events"]
    CV["Compacted typed views"]
    M --> CE --> XE --> OE --> CV
  end

  K -. Human promotion only .-> M
~~~

### Boundary rules

1. Strategy core 只接收 typed PIT market input，不认识 provider、DuckDB、CLI、Forward 或 TradePlan。
2. Warehouse 只发布通过 validation gates 的 immutable snapshot；CURRENT 不是可消费状态。
3. Screen 只能消费 SCREEN_READY + frozen universe，所有 state 先 stage/verify 后整体 promote。
4. TradePlan 只读 setup state 并派生 execution label，禁止改 setup lifecycle。
5. Research 只能读 immutable snapshots/episodes；每次 run 记录 code/config/input/output hash 和 conclusion。
6. Forward 只能读人工批准 manifest；任何 observation 是 append-only event，不能回填或覆盖。
7. Knowledge promotion 通过明确 PR/ADR，不由本地文件存在或脚本执行推断。

### 目标合同

| Contract | 必要新增 |
|---|---|
| SnapshotManifestV2 | schema_version、parent_snapshot、logical source URI、row counts/status by date/provider、universe hash、pool coverage、validation report hash、promotion approval |
| CanonicalDailyV2 | confirmation provider/hash、price_domain、source/normalized volume unit、corporate_action_status tri-state |
| ScreenRunV2 | input manifest hash、universe hash、compact row artifact path/hash、staged/final state root hash、verification status |
| ResearchRunManifest | hypothesis、sample split、input/code/config hashes、metrics、conclusion taxonomy、promotion status |
| ForwardEventV1 | epoch、event_id、sequence、event_time/as_of、source hashes、schema version、previous-event hash |

### Proposal evaluation

| Proposal | WHY / current pain | Expected benefit | Migration risk | Backward compatibility | Test plan |
|---|---|---|---|---|---|
| Guarded snapshot publisher | prototype可绕过validator/status | only validated data becomes visible | High：data operations | old snapshots remain readable；new status machine additive | continuity/coverage/fault injection/old-reader tests |
| CanonicalDailyV2 | domain/unit/confirmation/corp-action丢失 | explicit lineage and price semantics | Medium/High schema | V1 reader adapter；never rewrite V1 files | schema/property/parity/migration tests |
| Transactional screen state | verify失败后state已前进 | idempotent retry and safe rollback | Medium | existing state read-only import then new root generation | crash at every boundary + hash equality |
| Forward event ledger | null schema、whole-file overwrite | durable valuable observation truth | High before start，low migration because 0 rows | keep V01/V02 files immutable；new event schema | typed empty bootstrap、concurrency、idempotency、hash chain |
| Application-service boundaries | large functions/private helper imports | clearer ownership/test surfaces | Medium semantic regression | facade keeps existing CLI/contracts | characterization/golden before extraction |
| CI/release/knowledge gates | human conventions unenforced | prevent dirty/unreviewed promotion | Low/Medium ops | no runtime semantic change | clean clone, required checks, simulated blocked merge |

## 17. REFACTOR ROADMAP

### NOW — correctness stabilization

| Step | Scope | Exit gate |
|---|---|---|
| N1 | 标记/隔离 8/5 snapshot、states、run outputs；正式路径回到显式 safe snapshot | formal commands fail closed on quarantined/non-ready data |
| N2 | 修正 ADR-008 multi-day preclose、重建 daily + derived pool + lineage | continuity=0；coverage/universe/corp-action gate；new SCREEN_READY |
| N3 | 从新 validated snapshot 全量 rebuild states，不复用污染状态 | replay equivalence + state root hash +主板 count |
| N4 | 修复 Forward runner 的 V02 manifest、HHMM、bar count、D1 fields；不启动 epoch | golden/adversarial tests + dry-run no writes |
| N5 | 将 reference 和 ledgers harden 为 immutable/typed/append-only | fault injection/idempotency tests |
| N6 | Human/Architect 决定 B2_CONFIRMED 语义 | signed ADR +独立测试；未决前不改策略 |
| N7 | 同步 ADR/Master/Rule Catalog/Current Phase/agent-context | 两 repo clean、reviewed、hash pointers一致 |

### NEXT — reliability and boundaries

| Step | Scope | Exit gate |
|---|---|---|
| X1 | Snapshot stage-validate-promote transaction | crash at every boundary leaves old pointer intact |
| X2 | Screen staged state journal + compact output | verify failure leaves production states unchanged |
| X3 | CanonicalV2 typed lineage/domain/unit/corporate-action | schema compatibility tests |
| X4 | CLI lazy imports、package configs、lockfile、clean wheel | supported Python clean install passes |
| X5 | CI + protected main + adversarial/data contract checks | required checks/reviews enforced |
| X6 | Observability + DR runbook + storage retention | restore rehearsal and quota alert |

### LATER — maintainability and scale

| Step | Scope | Exit gate |
|---|---|---|
| L1 | 分离 application services，缩小 pipeline/engine/runner/CLI 大函数 | no frozen output change |
| L2 | 增量 anchor/structure indexes 与 validator streaming | hash equal + benchmark regression gate |
| L3 | Artifact catalog/registry 和 automatic knowledge freshness | owner/status/retention coverage |
| L4 | Versioned release bundle with manifests/SBOM | reproducible release from clean tag |

任何阶段都不得把性能、候选数量或 Forward 进度作为放宽正确性 gate 的理由。

### Requested stage view

| Stage | Scope | Expected PR count | Risk | Acceptance criteria |
|---|---|---:|---|---|
| Stage 0 — stabilization | quarantine、correct data/pool/universe、safe snapshot/state、Forward correctness/durability | 7 immediate PRs（PR-A–G） | HIGH | no P0 open；new SCREEN_READY；no Forward start |
| Stage 1 — truth sync | ADR/Master/Rule Catalog/Current Phase/agent context、B2 decision record | 1–2（PR-I + optional PR-J） | HIGH governance/semantic | one truth per domain；all reviewed |
| Stage 2 — architecture cleanup | CanonicalV2 boundaries、application services、package interfaces | 2–3 later PRs | MEDIUM | characterization hashes unchanged；V1 readers supported |
| Stage 3 — performance | compact artifacts、streaming validation、anchor/structure hotspots | 2–3 independent PRs | MEDIUM | 20/200/1000/full hash equal + RSS/wall baseline |
| Stage 4 — developer experience | lock/wheel/CI/branch protection/release/DR/artifact catalog | 2–3（PR-H + followups） | LOW/MEDIUM | clean clone reproduction and protected release workflow |

Stage 0/1 的 9 个 immediate PR 对应下一节；Stage 2–4 的数量是后续上限估计，必须在前一阶段重新审计后拆分，不能现在创建 mega-PR。

## 18. PR PLAN

建议拆成可独立 review 的小 PR；预估 9 个，不建 mega-PR：

| PR | Scope | Risk | Acceptance criteria | Depends on |
|---|---|---|---|---|
| PR-A Stop-use guards | snapshot status/quarantine、formal latest usable gate；不改数据 | Medium | bad/CURRENT snapshot formal screen hard-fails；旧 SCREEN_READY 可显式读 | none |
| PR-B ADR-008 data correctness | multi-session preclose、pct/limit reference、typed lineage shared library + tests | High data | 3-day continuity/property tests；no field merge；source rows traceable | PR-A |
| PR-C Derived pool + universe | limit-up derived coverage、主板 filter/hash | High semantic input | as_of coverage；2,006越界不再产生；anchors parity reviewed | PR-B |
| PR-D Atomic snapshot promotion | stage/validate/SCREEN_READY pointer | High reliability | fault injection across file/DB boundaries | PR-B/C |
| PR-E Screen transaction/storage | staged states、verify-before-promote、compact run artifact、chunk timeout/env | Medium | rebuild/incremental hashes equal；failure leaves state unchanged；disk benchmark | PR-D |
| PR-F Forward V02 correctness | manifest-driven V02、time slicing、candidate contract、dry-run pure | High PIT | 09:45=3 bars、10:00=6；no future bars；no ledger writes in dry-run | PR-D/E |
| PR-G Forward durability | typed event schemas、append-only/idempotency、immutable reference | High provenance | crash/concurrency/hash-chain tests；0-row typed bootstrap | PR-F |
| PR-H Packaging/CI/security | lazy imports、package resources、lock/SBOM、Actions、secret/privacy checks | Medium | clean wheel + 357 suite + data-contract lint；protected main setup documented | independent after urgent guards |
| PR-I Knowledge truth sync | reviewed ADR-008、Master/Rule Catalog/Current Phase/agent-context、DR docs | Medium governance | no unresolved truth conflicts；both repos clean | PR-B–H facts |

B2_CONFIRMED 决议不得藏在上述 PR。若 Human/Architect 决定代码需变更，单独建立 PR-J Strategy semantic alignment，明确是否改变历史 labels、是否需要新 strategy version、是否重算 artifacts；在决定前 expected PR count 不包含 PR-J。

## 19. DO-NOT-CHANGE LIST

在 Human/Architect 明确批准前，不得改：

1. phase-2d0 的 setup_stage、LIMIT_ANCHOR、WATCH_PULLBACK、B1_READY、B2_READY、B2_CONFIRMED、INVALID 定义。
2. B1/B2 frozen thresholds、confirmation rules、S1/S2、Entry Room、setup/entry quality scoring。
3. config/strategy.yaml、SPEC.md、DECISIONS.md 的冻结哈希。
4. corrected episodes hash 66d5943…、execution episodes hash 3c3cfc… 及其历史 labels/outcomes。
5. Quiet Score V01/V02 reference 内容；修复只能创建新 version，不能原地覆盖。
6. Forward V01/V02 既有 manifest/protocol/history；当前 0 行 ledger 不得历史回填。
7. Forward outcome taxonomy 和 3-session horizon。
8. REJECT / OBSERVE_ONLY 结论，不得因新候选需求升级。
9. 研究阈值、权重或样本 membership，不得同样本调参与验证。
10. position sizing，不得在 entry edge 未证明时继续。
11. 原始行情、tokens、.env、私人持仓、截图、cache，不得提交 Git。
12. Draft PR 不得自动 ready/merge；不得 rebase、force-push、squash。

允许且应优先的 correctness 修复仅限：数据 continuity/lineage、status/universe/pool gates、PIT slicing、事务/durability、测试/CI、知识同步。任何看似需要改变 frozen strategy 的 P0，必须先形成单独 ADR 和影响分析。

## 20. FINAL VERDICT

### SWE maturity score

| 维度 | 0–5 | 理由 |
|---|---:|---|
| Requirements | 3.0 | goals/non-goals较明确；machine traceability 和 readiness contract不足 |
| Architecture | 2.5 | 模块已分层；research/production/publication 边界破裂 |
| Domain Modeling | 3.0 | signal/PIT/setup-entry模型强；但human namespace和B2 lifecycle存在P0冲突 |
| Data Engineering | 1.5 | immutable/hash设计有基础；latest canonical 已发生系统性错误且 lineage bypass |
| Research Governance | 3.0 | taxonomy/negative results/Forward freeze意识强；未跟踪研究和 sizing 违规 |
| Testing | 3.0 | 357 个离线测试且核心例测强；真实合同、property、mutation、CI缺失 |
| Performance | 3.5 | one-pass 21.87x、full-market可运行；仍有重复扫描、2.4GB child和23GB输出 |
| Reliability | 1.5 | 单文件 atomic/resume 有基础；多文件/state/ledger非事务 |
| Observability | 1.5 | 有 manifests/metrics片段；无统一日志、alerts、promotion telemetry |
| Documentation | 2.0 | 冻结文档丰富；入口/provider/phase/ADR严重漂移 |
| Developer Experience | 2.0 | pytest/config模型可用；optional deps、无 lock、wheel config、子进程env问题 |
| Release Governance | 1.0 | 有 PR/tag习惯；无 CI、branch protection、release、machine gate |
| Security | 2.5 | gitignore/redaction较好；public repo隐私路径、私人持仓、无扫描/SBOM |
| Reproducibility | 2.5 | 多个关键 hash 可核验；dirty scripts、commit映射、依赖和publication provenance缺口 |

平均分：2.32 / 5。此分数反映“核心模型基础比生产数据与治理成熟”，不能用测试强项掩盖数据和语义 P0。

### Final decision

CORRECTNESS_BLOCKER_FOUND

理由：

1. 已找到并独立量化 production canonical 的实质数值错误，不只是架构建议。
2. 该错误已传播到全部当前 screen states，且当前 derived limit-up pool 与 universe 同时不满足产品合同。
3. Forward runner 存在确定性 future leakage；虽尚无 ledger 行，但不具启动资格。
4. B2_CONFIRMED lifecycle 的 State Machine 与代码/golden冲突；按审计规则属于 strategy semantic drift P0。
5. production snapshot 来自未跟踪脚本，且在 ADR gate 未完成时绕过正式 validator/lineage 发布。
6. frozen files的哈希和历史 evidence 大体完好，因此不需要重写项目；正确方向是先隔离、决议语义、重建数据、加硬门禁和事务，再恢复 Forward 评审。

### Human / Architect decisions required

1. 确认立即冻结使用 snap-2026-08-05-d9e93fccc966 及其全部 states/run outputs。
2. 指定 ADR-008 是继续修复、回退还是重新 proposal；只有 reviewed implementation 才能 promotion。
3. 决定 B2_CONFIRMED 是单调 lifecycle state 还是每日条件 state。
4. 决定 V02 reference 是否接受现有 content hash；无论决定为何，都不得原地覆盖。
5. 批准按 PR-A → PR-I 的稳定化顺序实施；在 PR-F/G 通过前不启动 Forward。

审计在此停止。等待 Human/Architect 决策，不自动修复、不启动 Forward、不修改冻结 artifact。

---

## Appendix A — Key evidence index

| Evidence | Location / value |
|---|---|
| Frozen strategy config | config/strategy.yaml，SHA-256 47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf |
| Frozen SPEC | SPEC.md，SHA-256 0c146b6e4ae1ce3b0c34657a49ded2dca2919593f78a6d51ad97990629b5b81b |
| Frozen decisions | DECISIONS.md，SHA-256 07f8ca7ca5350816acfe6071b34aa011c21260937efdc0a33389462c4ebba004 |
| Frozen tag | phase-2d0 → e865de4，tree cb786d72 |
| Knowledge pointers | /Users/luke808/AI/a-share-strategy-brain/05_Codex/CURRENT_PHASE.md；exports/LLM_CONTEXT_PACK.md |
| Human strategy truth | knowledge/01_Strategy/STRATEGY_MASTER.md、STATE_MACHINE.md、RULE_CATALOG.md |
| Safe snapshot | data/manifests/snap-2026-07-31-b5f84004de8a.json |
| Blocked snapshot | data/manifests/snap-2026-08-05-d9e93fccc966.json |
| Bad catch-up code | research/tdx_tencent_catchup_v02.py lines 173–201 |
| Snapshot consumer gap | src/limit_pullback/screen/canonical.py lines 157–185 |
| State write ordering | src/limit_pullback/screen/runner.py lines 345–397 |
| B2 conflict | src/limit_pullback/strategy/engine.py lines 897–916 vs knowledge STATE_MACHINE lines 10–12 |
| Forward leakage | research/run_forward_bpoint_v01.py lines 397–463 |
| Reference overwrite | research/reference_repair_v02.py lines 268–275 |
| Snapshot transaction | src/limit_pullback/warehouse/snapshot.py lines 45–121 |
| Corrected episodes | SHA-256 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093 |
| Execution episodes | SHA-256 3c3cfc044c820f20558a4ff363fa68229d38d035f72760aefe7c22a430db024d |
| Historical performance | data/tmp/cold-rebuild-profile/profile.json；data/tmp/one-pass-precompute/result.json |
| Current profile | 本报告 11. PERFORMANCE AUDIT；4.428s / 20 codes / 11,173 rows |
| Remote controls | GitHub API：0 workflows、main unprotected、0 releases |

## Appendix B — Audit request coverage

| Request section | Coverage in this report | Completion/result |
|---:|---|---|
| 0 Project background | Scope、Section 1–2 | AUDITED |
| 1 Review principles | Evidence levels、read-only discipline、Section 19 | FOLLOWED |
| 2 Truth Layer | Section 3 TRUTH_SOURCE_MATRIX | FAIL_LATEST_TRUTH |
| 3 Requirements Engineering | Section 4 goals/non-goals/tree | AUDITED |
| 4 Requirement Traceability | Section 4 matrix/orphans | AUDITED |
| 5 Strategy Semantic | Section 5 invariants | P0_B2_CONFLICT |
| 6 Human vs Machine | Section 5 CONCEPT_MAPPING | NAMESPACE_REQUIRED |
| 7 Data Architecture | Section 6 flow/provider roles | FAIL_LATEST |
| 8 Data Contract | Section 6 contracts | GAPS_FOUND |
| 9 Price Domain | Section 6 PRICE_DOMAIN_MATRIX | CODE_PASS_DATA_FAIL |
| 10 Canonical Data | Section 6 direct Parquet/DuckDB audit | P0_FOUND |
| 11 Derived Data | Section 6 limit-up pool audit | STALE |
| 12 Corporate Action | Section 6 corporate action audit | NOT_IMPLEMENTED |
| 13 PIT / Future Leakage | Section 7 threat model | FORWARD_FAIL |
| 14 Research Methodology | Section 8 gates | PARTIAL |
| 15 Statistical Governance | Section 8 taxonomy/gates | SIZING_VIOLATION |
| 16 Research Result Inventory | Section 8 evidence matrix | AUDITED |
| 17 Forward Integrity | Section 9 artifacts/runner | NOT_READY |
| 18 Forward Statistical Plan | Section 9 plan/gaps | PARTIAL |
| 19 Software Architecture | Section 10 | AUDITED |
| 20 Domain Boundaries | Section 10 DDD review | GAPS_FOUND |
| 21 Dependency Audit | Section 10 dependencies | GAPS_FOUND |
| 22 Error Handling | Section 13 | PARTIAL |
| 23 Resilience | Section 13 FAILURE_MODE_MATRIX | WEAK |
| 24 Performance | Section 11 real profile | AUDITED |
| 25 Complexity | Section 11 complexity table | AUDITED |
| 26 Performance Regression | Section 11 regression contract | DEFINED |
| 27 Memory Architecture | Section 11 memory | PARTIAL |
| 28 Storage Architecture | Section 11 storage | FAIL_RETENTION |
| 29 Testing Pyramid | Section 12 | AUDITED |
| 30 Golden Regression | Section 12 | GAPS_FOUND |
| 31 Property-Based Tests | Section 12 | ABSENT |
| 32 Mutation / Adversarial | Section 12 | MUTATION_ABSENT |
| 33 CI/CD | Section 12 | ABSENT |
| 34 Git Workflow | Section 14 | UNENFORCED |
| 35 Release Governance | Section 14 | WEAK |
| 36 Configuration | Section 10 | PARTIAL |
| 37 API / CLI | Section 10 and 12 | DEPENDENCY_GAP |
| 38 Observability | Section 13 | WEAK |
| 39 Provenance | Section 13 | LATEST_FAIL |
| 40 Security | Section 13 | PARTIAL |
| 41 Reproducibility | Sections 3、8、13 | PARTIAL |
| 42 Documentation | Section 14 | DRIFT |
| 43 ADR Governance | Section 14 | GATE_BYPASSED |
| 44 Knowledge Repo Sync | Section 14 KNOWLEDGE_SYNC_GAPS | FAIL_SYNC |
| 45 Dead Code | Section 14 candidates/lifecycle | AUDITED_NO_BLIND_DELETE |
| 46 Technical Debt | Section 15 P0–P3 | AUDITED |
| 47 Maintainability | Sections 10、15 | MEDIUM_LOW |
| 48 Code Quality | Sections 10、12 | PARTIAL |
| 49 Ownership | Sections 10、15、16 | NOT_ENFORCED |
| 50 Naming | Sections 5、10 | NAMESPACE_REQUIRED |
| 51 Backward Compatibility | Section 10 contracts | WEAK_VERSIONING |
| 52 Artifact Lifecycle | Sections 14、16 | GAPS_FOUND |
| 53 Disaster Recovery | Section 13 | RUNBOOK_ABSENT |
| 54 Forward Ledger Durability | Sections 9、13 | FAIL |
| 55 Current Project Risk | Sections 1、15 | P0_STOP |
| 56 Architecture Proposal | Section 16 TARGET_ARCHITECTURE_VNEXT | PROVIDED |
| 57 Performance Proposal | Section 11 PERFORMANCE_ROADMAP | PROVIDED |
| 58 Refactoring Roadmap | Section 17 NOW/NEXT/LATER | PROVIDED |
| 59 Stop-the-line | Sections 1、20 | TRIGGERED |
| 60 SWE Maturity | Section 20，14 dimensions | SCORED_2.32 |
| 61 Required report format | Sections 1–20 exact structure | FOLLOWED |
| 62 Output discipline | Evidence-backed tables, findings, gates, roadmap | FOLLOWED |
| 63 Git modification limits | Only this report added；no code/config/data/Forward mutation | FOLLOWED |
| 64 Do not rewrite project | Section 16 minimal evolution；Section 19 | FOLLOWED |
| 65 Final purpose | Section 20 decisions and stop point | ACHIEVED_PENDING_HUMAN |
