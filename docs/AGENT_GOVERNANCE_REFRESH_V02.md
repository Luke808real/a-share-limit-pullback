# AGENT GOVERNANCE REFRESH V02

STATUS: **COMPLETE（未推送；待人工审查）**

## REPOS

```text
1. Luke808real/a-share-limit-pullback（code repo）
2. Luke808real/a-share-strategy-brain（KB repo）
```

## BEFORE

```text
- post-close TradePlan 被写成唯一项目边界
- historical chronological split 被称作 validation（R3 早期文档残留）
- 旧 Phase 2C / 2026-07-31 context 硬编码（agent-context.md / AGENTS.md）
- taxonomy 仅 REJECT / OBSERVE_ONLY / SUPPORTED
- Adversarial reviewer 只审普通代码风险
- AGENTS.md 含用户绝对路径 + "KB 赢了 chat" 过强规则
- research-cycle skill 硬编码 corrected-episodes SHA 66d5943 与
  DISCOVERY<=2025-06-30 / VALIDATION>=2025-07-01
```

## AFTER

```text
- Production Plane 与 Research Plane 分离（ASL 为长期数据底座；
  R0-R8 = development evidence；R9 = true prospective validation）
- Authority Matrix（7 项）；Frozen KB 只覆盖 frozen strategy semantics；
  stale KB phase note 不得覆盖 newer exact-HEAD / provenance / reviewed
  research facts
- taxonomy：OBSERVATION / HYPOTHESIS / SUPPORTED_HYPOTHESIS / VALIDATED /
  STRATEGY_CANDIDATE / PROMOTED + 正交 IMPLEMENTATION_STATUS /
  PRODUCTION_STATUS；SUPPORTED != VALIDATED != PROMOTED
- PIT / prospective 规则：historical split = DEVELOPMENT_STABILITY，
  非自动 clean OOS；clean prospective = protocol freeze -> OOS_START ->
  immutable feature -> later endpoint
- population / label fail-closed invariants（maturity 不得影响 identity）
- superseded / invalidated artifact 不得作为 current evidence
```

## FILES_CHANGED（code repo）

```text
AGENTS.md（重写：双平面 / Authority Matrix / taxonomy / PIT / population /
  superseded；去除绝对路径与过强 KB 规则）
docs/agent-context.md（重写为 PROJECT_STATE_SNAPSHOT 指针）
.codex/agents/data-reader.toml（新增 SHA/AS_OF/vintage/order/timestamp/
  timezone/units/reconciliation/missingness 检查；明确 parquet 物理行序不可信）
.codex/agents/adversarial-reviewer.toml（10 项检查 + GO/GO_WITH_CONDITIONS/
  NO_GO）
.codex/agents/code-reader.toml（PIT 数据依赖追踪）
.codex/skills/ashare-research-cycle/SKILL.md（更名 Development Research
  Cycle；CHRONOLOGICAL_VALIDATION -> DEVELOPMENT_STABILITY；删除硬编码
  split 与 66d5943 default；frozen dataset 从 registry/report 解析）
.codex/skills/ashare-prospective-validation/SKILL.md（新增：PRE_AUDIT ->
  PROTOCOL_FREEZE -> OOS_START -> APPEND_ONLY -> LABEL_MATURITY ->
  READINESS -> EVALUATION；PRE_R9_STATUS=GO gate；VALIDATED 条件）
.codex/skills/ashare-premarket-review/SKILL.md（新增 READINESS GATE /
  WATCHLIST_NOT_READY；rebuild 非默认路径）
.codex/skills/ashare-pr-closeout/SKILL.md（validation policy：development
  targeted / closeout CI-equivalent once / real-data only when gate requires；
  KB 路径改 A_SHARE_STRATEGY_BRAIN_ROOT）
tests/test_agent_governance_contract.py（新增 checker）
docs/AGENT_GOVERNANCE_REFRESH_V02.md（本报告）
```

## AUTHORITY_MODEL

```text
用户指令 > exact HEAD+tests > data lineage(SHA) > latest research report >
frozen strategy semantics（STRATEGY_MASTER/RULE_CATALOG/BASELINE_MANIFEST）>
PROJECT_STATE_SNAPSHOT > 历史日志。
```

## PRODUCTION_VS_RESEARCH

```text
Production：ASL -> Snapshot -> State -> Strategy -> post-close 计划。
Research：frozen datasets -> factor/stability/benchmark/multivariate/intraday
  -> prospective validation。Research minute data 不使 production 变
  intraday；R0-R8 只是 development evidence。
```

## DEVELOPMENT_VS_PROSPECTIVE

```text
historical split 若已参与 discovery -> DEVELOPMENT_STABILITY；
clean OOS 只来自 R9 式协议（freeze -> OOS_START -> immutable -> endpoint）。
```

## AGENT_CHANGES / SKILL_CHANGES

```text
agents：data-reader（数据语义清单）、adversarial-reviewer（10 项 + verdict）、
  code-reader（PIT 依赖追踪）
skills：research-cycle 改名与去硬编码、新增 prospective-validation、
  premarket READINESS GATE、pr-closeout validation policy
```

## STALE_CONTEXT_REMOVED

```text
- Phase 2C.2C / PR #7 / 2026-07-31 硬编码 authority（agent-context）
- 2025-06-30 / 2025-07-01 全局 split（research-cycle）
- 66d5943 作为永恒 default dataset（research-cycle）
- /Users/luke808 绝对路径（AGENTS.md / pr-closeout）
- "KB 赢了 chat" 过强规则（替换为 Authority Matrix 分层）
```

## INTENTIONALLY_NOT_CHANGED

```text
src/、config/strategy.yaml、config/trade_plan.yaml；
STRATEGY_MASTER.md / RULE_CATALOG.md / BASELINE_MANIFEST.yaml /
STATE_MACHINE.md（KB）；
任何 frozen research result CSV/parquet；R7/R8 结果；R9 protocol；
工程纪律（single writer / fail closed / targeted tests / no auto merge 等）
```

## KNOWN_REMAINING_GAPS

```text
- KB 侧治理文件（AGENTS.md / PROJECT_STATE_SNAPSHOT.md）尚未合并到 main，
  远端不可审计；checker 的 KB 检查在文件进入 sibling main 前会 SKIP
- PROJECT_STATE_SNAPSHOT 中部分 production 细节标记
  NOT_YET_REMOTE-AUDITABLE（保守处理）
- EXPIRED/TTL 与 research authority 的语义张力仅记录，未改 frozen 文件
```

## VALIDATION

```text
tests/test_agent_governance_contract.py：8 passed, 1 skipped（KB 未合并）
git diff --check：PASS
git status：worktree 仅含本任务文件
未运行 full pytest / full-market / ASL / R9。
```
