# Handoff — F20 VALIDATION FINAL HARDENING V01

STATUS

F20 CONTRACT = CLOSED；F20 PREREG = CLOSED
F20 VALIDATION LOGIC = CORRECTED / CORE PASS（Sol review @69a6a77：population/Spearman/
fail-closed/undefined 拆分均确认）
CORRECTED OBSERVED RESULT: rho_strict = -0.112699；rho_R_positive = -0.118177；H5A = REJECT
FORMAL CLOSE = PENDING SOL FINAL AUDIT（audit-closeout v01 后由 Sol 正式冻结；不得写 FINAL_ACCEPTED）
VALIDATED = NO；PROMOTED = NO

branch: fix/f20-validation-audit-closeout-v01
commit: （本轮提交后确定）
PR: 无（本地 research 分支；推送 review 分支，未 merge）
worktree: /Users/luke808/AI/V flash-f18-validation-v01

CHANGED（本轮：audit hardening only，统计逻辑与 corrected 数字不变）

- tests/test_f20_validation.py：tie test 改为手算用例（x=[1,1,2,3],
  y=[1,2,2,3] → 5/6，无 scipy oracle）；新增：B1_READY materialization
  不被预排除、OTHER_ERROR 阻止 artifact（B2 bar 缺失 → OTHER_ERROR）、
  nonfinite rho fail closed（monkeypatch isfinite）、verdict 双分支
  （双正 SUPPORTED_DIRECTIONALLY / 任一非正 REJECT）
- research/factor-lab/f20_outcome_validation_v01.py：仅新增
  RECONCILIATION 元数据字段（AUDIT_FIX=PREREG_COMPLIANCE_V01、
  SUPERSEDES_HEAD=648aa069、OLD_RESULT_STATUS=NOT_ADJUDICATED_PREREG_MISMATCH、
  RESULT_CHANGED=YES）——不改任何统计逻辑
- research/factor-lab/runs/f20-outcome-validation-v01/*.{json,md}：确定性重跑
  （数字必须与 69a6a77 完全一致）
- docs/HANDOFF_f20_outcome_validation_v01.md：状态与 Catalog 一致（REJECT 收口前）

OBSERVED（corrected 数字，硬化后不变）

- RESOLVED_N=9625 = F20_DEFINED_N=9508 + F20_UNDEFINED_N=117
  （INSUFFICIENT_PRE20=117；ZERO_DENOMINATOR=0；OTHER_ERROR=0）
- STRICT_N=7765 + CANCEL_GAP=1743 = 9508；R_DEFINED_N=7765
- rho_strict = -0.112699；rho_R_positive = -0.118177（均 N=7765）
- H5A = REJECT（双 gate 均非正；pre-registered gate 未改）
- stage 观察（不改变 verdict）：B1_READY -0.010/-0.010、B2_READY
  +0.056/+0.056、B2_CONFIRMED -0.015/-0.093；timing strict 在
  T3/T4-5/T6-10 为正但 R-positive 全非正 → global -0.11 含 stage/timing
  composition 成分，仅作 OBSERVATION，同样本不救 F20

DECISIONS_NEEDED

- 等待 Sol 最终硬化审计通过后正式收口：
  F20 OUTCOME VALIDATION V01 = REJECT / CLOSED；VALIDATED = NO；PROMOTED = NO
- 收口后转下一个因子（不在 F20 上继续同样本挖阈值）

VALIDATION

pytest: tests/test_f20_validation.py + tests/test_factor_lab.py（全量，见提交时结果）
compileall: OK（src/limit_pullback/factor_lab + f20_outcome_validation_v01.py，已固化）
diff-check: OK（已固化）
runtime validation: 相同 frozen inputs 确定性重跑；数字与 69a6a77 比对一致

BLOCKERS

NONE

NEXT

- 提交硬化并推送 review/f20-validation-final-hardening-v01，回传 SOL
  [AUTHOR_REPORT]（含数字不变确认）等待最终收口
