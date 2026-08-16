# Handoff — F20 OUTCOME VALIDATION V01

STATUS

branch: research/f20-outcome-validation-v01
commit: 64fe9e3
PR: 无（本地 research 分支；未 merge，未 force）
worktree: /Users/luke808/AI/V flash-f18-validation-v01

CHANGED

- research/factor-lab/f20_outcome_validation_v01.py（新增）：预注册 outcome
  validation 流水线——SHA 门禁（episodes 66d5943f / daily e7243dee，无
  DataFrame bypass）、B2-stage defined population（PRE20_N==20 且窗口均量
  非零）、H5A 连续 Spearman 双 gate、quartile Q1-Q4 描述、robustness、
  stage/timing composition（SMALL_CELL 排除）、accounting invariants
  fail closed（defined+undefined==resolved；strict+cancel_gap==defined）。
- research/factor-lab/runs/f20-outcome-validation-v01/f20-outcome-validation-v01.{json,md}（新增）
- research/factor-lab/FACTOR_CATALOG.md：F20 OUTCOME VALIDATION
  PREREGISTERED/NOT RUN → REJECT（V01）
- research/factor-lab/README.md：追加 f20-outcome-validation-v01 条目

OBSERVED

- RESOLVED_N=9625；F20_DEFINED_N=3207；F20_UNDEFINED_N=6418
  （NON_B2_STAGE 6411 + F20_UNDEFINED 7）；STRICT_N=2891；
  CANCEL_GAP_ACCOUNTING_N=316；R_DEFINED_N=2891
- rho_strict=+0.0338（N=2891，p=0.069）；rho_R_positive=-0.0383（N=2891，
  p=0.039）→ 第二 gate 非正 → **H5A = REJECT**
- B2_READY 层两 rho 均 +0.056（该层 strict 编码与 R>0 100% 一致，已复核
  非 bug）；B2_CONFIRMED 层 -0.015/-0.093；T1-2/T3 strict 正、T4-5/T6-10 负
- quartile Q1-Q4 无单调（Q2 strict_win_rate 0.664 最低；P(R>0) 0.595→0.527 递减）
- F20 分布（defined）：p50=1.48，p90=2.67，p95=3.21，p99=4.33，max=6.53
- b2 event date := signal_date（B2-stage frozen semantics，h9 doc）

DECISIONS_NEEDED

- 是否将 B2_READY 层正方向（两 rho 均正）记为 NEW_HYPOTHESIS 留给未来
  独立样本验证（当前未写入，需 SOL/人工评审确认后再填）
- 后续是否执行 F19 outcome validation（同族因子，h9 事件频率层已 REJECT）

VALIDATION

pytest: tests/test_factor_lab.py 71 passed（0.21s）
compileall: OK（src + 新脚本）
diff-check: OK
runtime validation: 流水线 OK（SHA 门禁通过；accounting 守恒校验通过；
B2_READY rho 一致性已独立复核）

BLOCKERS

NONE

NEXT

- 回传 SOL 验证结果并等待评审；若评审通过，按预注册纪律归档
  （NEW_HYPOTHESES 如实填写后 commit）
