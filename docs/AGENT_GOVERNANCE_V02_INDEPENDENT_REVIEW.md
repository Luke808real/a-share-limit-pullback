# AGENT GOVERNANCE V02 INDEPENDENT REVIEW

# STATUS

**GO_WITH_CONDITIONS**（两处最小 patch 已应用；条件=审查后人工确认再推送）

# INPUTS

```text
CODE_HEAD: a5a1be53ded06c13c24a91b47ab6edf35af21cc0（== a5a1be5 前缀）PASS
KB_HEAD:   357d8b0ab3c1d3ba44ac10e78f9fda0dff5af98d（== 357d8b0 前缀）PASS
review branches: codex/agent-governance-review-v02（两 repo）
worktree cleanliness: clean（两 repo）
未触碰 main worktrees / 未 merge / 未 push / 未运行 R9
```

# AUDIT MATRIX

```text
AUTHORITY_MATRIX            = PASS
PLANE_SEPARATION            = PASS
TAXONOMY                    = FIXED_AND_PASS（一处遗留标签已修正）
PIT_PROSPECTIVE_GOVERNANCE  = PASS
PROJECT_STATE_ACCURACY      = FIXED_AND_PASS（KB 快照消歧 patch）
AGENT_CONTRACTS             = PASS
EXECUTION_GOVERNANCE        = PASS
PORTABILITY                 = PASS
```

# FINDINGS

## FINDING 1 — PROJECT_STATE_SNAPSHOT 语义坍缩（MAJOR；已 patch）

```text
file: KB_PROJECT_STATE_SNAPSHOT.md（RESEARCH 段 / CURRENT AUTHORITY 段）
问题：PRE_R9_STATUS=NOT_STARTED 将三类状态坍缩为一项：
  - pre-R9 设计/协议决策（已知状态=GO）
  - R9 accumulation 实现就绪度（已知状态=PATCH_REQUIRED，boundary
    hardening 未完成）
  - 远端可审计性（本地整理、未推送）
同时 "local pending: ... 均已 push" 的断言与已知 PRE-R9 lineage
  PENDING_PUSH 状态冲突（R0-R8 research branches 已推送 ≠ PRE-R9
  准备 lineage 已推送；两者被混写）。
patch（KB-only，最小）：
  PRE_R9_DESIGN_STATUS=GO（Gate2A=PASS / Gate2B semantics=PASS）
  R9_ACCUMULATION_IMPLEMENTATION=PATCH_REQUIRED
  R9_ACCUMULATION=NOT_STARTED
  R9_OOS_ROWS_WRITTEN=0
  REMOTE_AUDIT_STATUS=NOT_YET_REMOTE_AUDITABLE
  LOCAL_PRE_R9_LINEAGE=PENDING_PUSH
  local pending 行改为区分 R0-R8（RESEARCH_BRANCH_ONLY/NOT_MAIN_MERGED）
  与 PRE-R9 lineage（PENDING_PUSH）。
未修改 R9 protocol。
```

## FINDING 2 — research-cycle 遗留 taxonomy 标签（MINOR；已 patch）

```text
file: .codex/skills/ashare-research-cycle/SKILL.md EDGE_GATE 步（原 line 33）
问题：文件顶部已冻结新 taxonomy
  （OBSERVATION/HYPOTHESIS/SUPPORTED_HYPOTHESIS/VALIDATED/
  STRATEGY_CANDIDATE/PROMOTED），但 EDGE_GATE 失败分支仍输出旧标签
  "OBSERVE_ONLY / REJECT"。
patch（最小）：失败分支改为 "conclusion stays at OBSERVATION level；
  no edge claim (do not upgrade)"。checker 增加断言锁定
  （OBSERVE_ONLY/REJECT 不得出现在该 skill）。
```

## FINDING 3 — 报告文件含字面用户路径（MINOR；已 patch）

```text
file: docs/AGENT_GOVERNANCE_REFRESH_V02.md（STALE_CONTEXT_REMOVED 段）
问题：描述性提及 "/Users/luke808 绝对路径" 违反 PORTABILITY 检查。
patch：改为 "用户特定绝对路径（...）"。checker 的绝对路径检查现全绿。
```

## FINDING 4+ — NONE

```text
Authority Matrix 排序与预期方向一致（用户指令 > exact HEAD+tests >
lineage/SHA > latest research report > frozen semantics > snapshot > history）；
Frozen KB 仅覆盖 frozen semantics；stale KB 不得覆盖 newer exact-SHA 事实；
PROJECT_STATE_SNAPSHOT 定位为当前阶段恢复辅助（非普遍权威）。
Plane 分离：production 链与 research 链独立；research minute data !=
production intraday；SUPPORTED != VALIDATED != PROMOTED 全文档一致。
PIT/prospective：historical split=DEVELOPMENT_STABILITY；prospective skill
  有 PRE_R9_STATUS=GO gate、protocol freeze、outcome-blind、no refit /
  no checkpoint switching / no backfill；population/label/superseded 规则
  fail closed；adversarial-reviewer 覆盖 label circularity / population /
  maturity / multiplicity / cluster / superseded。
Agents：data-reader 覆盖 SHA/AS_OF/vintage/timestamp/timezone/units/
  row-order/reconciliation + 明确 parquet 物理行序不可信；code-reader 可
  追踪 PIT 依赖；adversarial verdict 词汇 GO/GO_WITH_CONDITIONS/NO_GO。
Execution：premarket READINESS GATE + WATCHLIST_NOT_READY + rebuild 非默认；
  pr-closeout 只跑 CI-equivalent once，real-data 仅 gate 要求时。
Portability：无用户绝对路径；A_SHARE_STRATEGY_BRAIN_ROOT / sibling /
  KB_UNAVAILABLE 机制齐备。
```

# PROJECT STATE CHECK

```text
PRE_R9_DESIGN_STATUS           = GO（Gate2A=PASS；Gate2B semantics=PASS）
R9_ACCUMULATION_IMPLEMENTATION = PATCH_REQUIRED（boundary hardening 未完成）
R9_ACCUMULATION                = NOT_STARTED
R9_OOS_ROWS_WRITTEN            = 0
REMOTE_AUDIT_STATUS            = NOT_YET_REMOTE_AUDITABLE
（未声明远端审计；未声明 R9 授权）
```

# VALIDATION

```text
tests run: tests/test_agent_governance_contract.py
  result: 8 passed, 1 skipped（KB 检查因 sibling main 未合并而 skip——
  KB 侧内容在独立 review worktree 中人工核验）
compile: tests/test_agent_governance_contract.py PASS
git diff --check: PASS（两 repo）
未运行 full pytest / strategy / full-market / network / R9。
```

# CHANGES

```text
CODE_REPO（本 review branch）:
  .codex/skills/ashare-research-cycle/SKILL.md（1 行：EDGE_GATE 失败分支）
  tests/test_agent_governance_contract.py（1 断言：锁定无 OBSERVE_ONLY/REJECT）
  docs/AGENT_GOVERNANCE_REFRESH_V02.md（1 行：去字面路径）
  docs/AGENT_GOVERNANCE_V02_INDEPENDENT_REVIEW.md（本报告）
KB_REPO（本 review branch）:
  PROJECT_STATE_SNAPSHOT.md（RESEARCH/CURRENT AUTHORITY 段消歧）
```

# RECOMMENDATION

```text
PUSH_GOVERNANCE_V02
（条件：两处 patch 经人工确认；无 BLOCKER；未推送——由用户决定推送/合并）
```
