# SECOND_LAUNCH_FACTOR_R1A3_REPRODUCIBLE_PACKAGE_REPORT

> R1A.3 — audit hardening + INTERIM reproducible label package（approved INTERIM_A）
> research-only；COHORT_PROVENANCE=PARTIAL；EXPLORATORY_ONLY；未创建 V01C；未进入 R1B

STATUS: **COMPLETE** — 审计加固完成（29/29 tests）；quarantine 精确匹配门通过；
INTERIM reproducible package 已发布（8,682 行）

BRANCH: `research/second-launch-label-v01`
BASE_HEAD: `f9bea469675060c3980bd71ad98f106603964095`
HEAD_AFTER: 见 GIT 段

## CODE_REVIEW_FIXES

- **RAW_DUPLICATE_POLICY: 已加固** — `load_raw_provider` 不再 `drop_duplicates(keep="last")`；
  新增 `dedupe_raw()`：OHLCV 完全一致 → IDENTICAL_DUPLICATE（确定性去重，计数）；
  OHLCV 不一致 → RAW_PROVIDER_VERSION_CONFLICT（保留全部冲突记录并标记，
  crosscheck 对该日期永不判 MATCH）；输出 raw_duplicate_identical_n /
  raw_duplicate_conflict_n / raw_duplicate_conflict_dates
- **FIRST_EVENT_ROW: 已修复** — forensic 的 `event_row_reconciliation_status` 现在按
  `first_event_times()` 的真实 first-event 顺序（S1_FIRST / INVALID_FIRST / AMBIGUOUS / NONE）
  选择事件行，不再因窗口内未来存在 S1 而优先 S1 行
- **ROW_POLICY_METRICS: 已明确** — 双口径：ROW_ROLE_EXPOSURE（每个 (case, date, snapshot)
  role 出现计数）与 UNIQUE_CASE_DATE_SNAPSHOT（唯一 (case, date, snapshot) 三元组）；
  本数据下二者数值相等（日期在单一 snapshot 内唯一；同日期跨 snapshot 属不同三元组），
  语义已在测试中固化；conflict_with_provisional_n / conflict_all_confirmed_n 保留

## TESTS

```text
GENERATOR_TESTS: 15（原 10 + 5，全部继续通过）
FORENSIC_TESTS: 8（identical raw dup / conflicting raw dup / partial provider coverage /
               invalid-first event row / ambiguous first event row /
               row-policy role exposure / unique case-date-snapshot counting）
PACKAGE_TESTS: 7（quarantine 精确匹配 allow / 少 ID BLOCK / 多 ID BLOCK /
               subset 3D mismatch=0 / 父 V01B 字节不变 / 正式 blocked CSV 不被创建 /
               snapshot hash mismatch BLOCK）
TOTAL: 29 passed（~1.3s）；git diff --check 通过；未跑 full-market
```

## FORENSICS_RECHECK

```text
3D_MISMATCH_N: 64（稳定复现）
CONFLICT_CLASS_COUNTS: PATTERN_CHANGED 48 / S1_TOUCH_RESOLUTION_CHANGED 14 /
                       ACCEPTANCE_CHANGED 2
RAW_IDENTICAL_DUPLICATE_N: 0（tushare 与 akshare 冲突窗口内均无重复行）
RAW_CONFLICTING_DUPLICATE_N: 0
PROVIDER_CROSSCHECK: CURRENT_CANONICAL_MATCHES_AKSHARE 48 /
                     CURRENT_CANONICAL_MATCHES_BOTH 16 /
                     TUSHARE-only 0 / DISAGREE 0 / MISSING 0
（48 例 AKSHARE-only 根因不变：tushare 在 115 个参与日期缺行，值零差异）
```

## QUARANTINE

```text
N: 64
SHA256: c5d028ca60c1b73f454aeec4da098c13129968bce26ad3f70f5fae96f45a2d66
ID_SET_MATCH: true（quarantine id set == 当前 3D mismatch id set，双向精确相等；
  否则 BUILD 直接 BLOCKED）
PATH: research/second_launch/outcome_v01/quarantine_v01b.csv
（动态生成，未硬编码 64；含 episode_id / symbol / candidate_date / conflict_class /
  quarantine_reason / source_forensic_artifact）
```

## REPRODUCIBLE_PACKAGE

```text
PARENT_N: 8,746（SUCCESS_CONTROL_CASESET_V01B，sha b22eae1d…，字节不变）
REPRODUCIBLE_N: 8,682
3D_MISMATCH_AFTER_QUARANTINE: 0（fail-closed 断言）
OUTCOME_3D_COUNTS: SUCCESS 406 / FAILED_BREAKOUT 949 / NO_LAUNCH 1,724 /
                   STRUCTURE_FAIL 5,392 / UNKNOWN 211
  （= 父集 − quarantine：409−3 / 950−1 / 1,730−6 / 5,415−23 / 242−31，逐类精确）
OUTCOME_5D_COUNTS: SUCCESS 481 / FAILED_BREAKOUT 1,143 / NO_LAUNCH 1,016 /
                   STRUCTURE_FAIL 5,826 / UNKNOWN 216
```

产物（全部在 research/second_launch/outcome_v01/）：

- `second_launch_outcome_v01b_reproducible.csv`（8,682 行 × 25 列，含 reconciliation 分层列）
- `manifest_v01b_reproducible.json`（artifact_id=SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE，
  research_status=INTERIM_PARTIAL_PROVENANCE，allowed/prohibited use 完整）
- `quarantine_v01b.csv`

## CENSORING

```text
WINDOW_INCOMPLETE_5D: 0
WINDOW_INCOMPLETE_10D: 88
FIRST_EVENT_RIGHT_CENSORED_10D: 16（不完整窗口且无事件；与 pattern 级 CENSORED 一致）
```

## RECONCILIATION

```text
CANDIDATE（candidate_reconciliation_status）: CONFIRMED 8,682 / 其他 0
  （全部 reproducible case 的候选行均为 CONFIRMED）
FEATURE_3D_HAS_PROVISIONAL: 见输出列（逐 case 标记；未因 PROVISIONAL 删除任何 case）
LABEL_5D_HAS_PROVISIONAL: 见输出列
LEGACY_ALL_CANONICAL 口径保留；PROVISIONAL 仅作 stratification 字段
```

（附：窗口级行策略 —— ROW_ROLE_EXPOSURE / UNIQUE_CASE_DATE_SNAPSHOT 均为
CONFIRMED 76,946 / PROVISIONAL 1,768，2.25%；64 冲突中 49 例涉及 PROVISIONAL、
15 例全 CONFIRMED —— 与 R1A.2 一致）

## SELECTION_BIAS

quarantine（64）对 reproducible（8,682）的影响：

| 维度 | 隔离分布 | 影响提示 |
|---|---|---|
| year | 2024: 8 / 2025: 5 / 2026: 51（79.7%） | 2026 年样本缺口最大 |
| month | 2026-03: 23 / 2026-07: 14 / 2026-01: 12（共 49/64=76.6% 集中此三月） | **2026-01 / 2026-03 / 2026-07 需显式覆盖缺口提示** |
| outcome | UNKNOWN 31 / SF 23 / NL 6 / SUCCESS 3 / FB 1 | UNKNOWN 被隔离 12.8%（31/242），其余 0.1-0.7% |
| data_quality | PARTIAL 64 / OK 0 | 与池一致 |
| provider | TUSHARE 64 | 与池一致 |

SELECTION_BIAS_RISK: 中等且方向可预期（UNKNOWN 本就不参与比较；SUCCESS/FB/NL/SF 受影响
0.1-0.7%）；按年/月的时间序列分析必须标注 2026-01/03/07 覆盖率缺口。

## PROVENANCE

```text
COHORT_PROVENANCE=PARTIAL（candidate/anchor 日 64/64 与双 raw 一致；
  但无修复前 bars 可对比，冻结 s1/invalid/anchor 推导是否受影响未证）
ALLOWED_USE=EXPLORATORY_FACTOR_RESEARCH_ONLY
PROHIBITED_USE=STRATEGY_PROMOTION / PRODUCTION / FORWARD / TRADEPLAN
```

## FILES_CHANGED

- `research/second_launch/outcome_v01/build_second_launch_outcome_v01.py`（M：A1 哈希校验抽取、
  quarantine loader、interim builder + 精确 set gate、reconciliation 列、CLI --interim）
- `research/second_launch/outcome_v01/audit_conflict_forensics_v01.py`（M：dedupe_raw、
  first-event row 语义、双口径 row policy、quarantine 写出）
- `research/second_launch/outcome_v01/quarantine_v01b.csv`（新增，sha c5d028ca…）
- `research/second_launch/outcome_v01/second_launch_outcome_v01b_reproducible.csv`（新增）
- `research/second_launch/outcome_v01/manifest_v01b_reproducible.json`（新增）
- `tests/test_audit_conflict_forensics_v01.py`（新增，8 tests）
- `tests/test_interim_reproducible_package.py`（新增，7 tests）
- `research/reports/SECOND_LAUNCH_FACTOR_R1A3_REPRODUCIBLE_PACKAGE_REPORT.md`（本报告）
- 未提交：`bounded/`（golden 检查隔离产物，验证用 scratch）

## CODE_REVIEW_TARGETS

1. `dedupe_raw()`（audit:88）—— raw 重复 fail-closed（identical vs conflict）
2. `build_conflict_rows()`（audit:157）—— first-event row 真实顺序
3. `row_policy_audit()`（audit:355）—— 双口径统计
4. `build_interim_reproducible_package()`（generator:700）—— 精确 quarantine set gate、
   subset 3D mismatch=0 fail-closed、manifest
5. `load_quarantine()` / `_reconciliation_columns()`（generator:680/676）—— quarantine 身份 + 分层列

## GIT

```text
COMMIT: research: publish reproducible second launch labels
PUSH: origin/research/second-launch-label-v01
```

## CONFIRM

```text
V01B_CHANGED=false（sha b22eae1d… 复验）
V01C_CREATED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
```

## NEXT_RECOMMENDED_ACTION

1. 人工评审 INTERIM package（EXPLORATORY_ONLY）与 quarantine 64 行
2. 若后续要修正标签：走 V01C（新 artifact，基于 validated bars 重建，V01B 不动），
   并保留 reconciliation_status / 修复批次元数据分层
3. 在第二大脑登记「冻结 case set 构建于修复前 bar 内容」缺陷（64 行 + tushare 115 缺失日期证据）
4. 未获授权前：不进入 R1B、不提取任何 factor、不训练模型

---

## VALIDATION（本任务）

- 29/29 targeted tests；`git diff --check` 通过；未跑 full-market
- 发布门全链路验证：quarantine 精确集 → subset 3D mismatch=0 → 产物落盘
- 哈希 pin 全程生效（feature e7243dee… / label 7cc614bf… / 父集 b22eae1d…）
- 结论状态：OBSERVE_ONLY；INTERIM 标签仅允许探索性因子研究
