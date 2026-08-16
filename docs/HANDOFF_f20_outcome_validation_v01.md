# Handoff — F20 VALIDATION PREREG-COMPLIANCE AUDIT FIX V01

STATUS

branch: fix/f20-validation-prereg-compliance-v01
commit: （本次提交后确定）
PR: 无（本地 research 分支；已推送 review 分支，未 merge）
worktree: /Users/luke808/AI/V flash-f18-validation-v01

CHANGED

- research/factor-lab/f20_outcome_validation_v01.py：prereg-compliance 修复
  1) 删除 B2_STAGES 预过滤——primary population = 全部 resolved episodes
     （冻结映射 anchor/b2_date=signal_date/as_of=signal_date），F20 自身定
     defined/undefined；setup_stage 仅用于 composition（B1_READY/B2_READY/
     B2_CONFIRMED 三层）
  2) 冻结 Spearman 实现：average ranks (method="average") + Pearson of ranks，
     移除 scipy 依赖；N<2 / 常量 / rho 非有限 → PRIMARY_RHO_UNDEFINED →
     fail closed（RuntimeError，不产出 artifact），绝不映射为 REJECT
  3) undefined reason 拆分：INSUFFICIENT_PRE20（PRE20_N<20，runner 用同一
     PIT bars 复算）/ ZERO_DENOMINATOR（>=20 根但窗口均量为 0）/ OTHER_ERROR
  4) quartile 输出补 STRICT_N / R_DEFINED_N
- tests/test_f20_validation.py（新增）：18 项 regression（wrong SHA ×2、
  no DataFrame bypass ×2、undefined isolation ×3、accounting fail closed ×2、
  average-rank ties、N<2/常量 rho fail closed ×2、CANCEL exclusion、
  numeric-R only、spearman_block fail closed、future leakage ×2、
  quartile outcome-independence）
- research/factor-lab/runs/f20-outcome-validation-v01/*.{json,md}：确定性重跑
- research/factor-lab/FACTOR_CATALOG.md、README.md：REJECT 最终数字
- docs/HANDOFF_f20_outcome_validation_v01.md → 本文件（v01 → audit fix）

OBSERVED

- RESOLVED_N=9625 = F20_DEFINED_N=9508 + F20_UNDEFINED_N=117
  （UNDEFINED_REASONS: INSUFFICIENT_PRE20=117；ZERO_DENOMINATOR=0；
  OTHER_ERROR=0）；STRICT_N=7765 + CANCEL_GAP=1743 = 9508；R_DEFINED_N=7765
- rho_strict = -0.1127（N=7765）；rho_R_positive = -0.1182（N=7765）
  → 双 gate 均非正 → **H5A = REJECT**（冻结 average-rank+Pearson 实现）
- stage 三层：B1_READY -0.010/-0.010（N 层内 4959）、B2_READY +0.056/+0.056、
  B2_CONFIRMED -0.015/-0.093；B1_READY 与 B2_READY 层 strict 编码与 R>0
  100% 一致（数据属性，WIN_S1→R>0 完全对应），B2_CONFIRMED 73.3%
  （419 例 WIN_S1 且 R<=0）——已复核非 bug
- quartile Q1-Q4（各 2377）：STRICT_N 2006/2012/1962/1785；无单调
- 与 B2-only 旧版本（648aa06，rho +0.034/-0.038）差异源于 population
  修复（6411 个 NON_B2_STAGE 曾被子集化排除）；REJECT 结论不变且证据更强

DECISIONS_NEEDED

- 等待 Sol 对 audit-fix 版本的 review（review/f20-validation-prereg-compliance-v01）
- B1_READY/B2_READY 层 rho 正方向是否记入 NEW_HYPOTHESES（待 Sol 确认）

VALIDATION

pytest: tests/test_f20_validation.py + tests/test_factor_lab.py = 89 passed
  （uv run python -m pytest；.venv 已装 pytest，避免 uv run pytest 的隔离环境）
compileall: 待最终提交前执行
diff-check: 待最终提交前执行
runtime validation: 相同 frozen inputs 确定性重跑（SHA 门禁通过；
  accounting 守恒：9625=9508+117；7765+1743=9508）

BLOCKERS

NONE

NEXT

- 提交 audit-fix 并推送 review/f20-validation-prereg-compliance-v01，
  回传 SOL [AUTHOR_REPORT] 等待评审
