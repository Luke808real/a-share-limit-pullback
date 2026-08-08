# SECOND_LAUNCH_FACTOR_R1A2_PROVENANCE_FORENSICS_REPORT

> R1A.2 — code-review fixes + 64 行 3D provenance conflict forensic audit（research-only）
> 未发布 5D package；未创建 V01C；未进入 R1B

STATUS: **COMPLETE** — 代码审查问题已修复（15/15 tests）；64 行冲突已完成全量 forensic audit

BRANCH: `research/second-launch-label-v01`
BASE_HEAD: `8a4890bcad13c150c793e294fdc6f980dbd1ccab`
HEAD_AFTER: 见 GIT 段

## CODE_REVIEW_FIXES

- **BOUNDED_OUTPUT_ISOLATION: 已修复** — `--codes`（bounded）模式只能写入
  `research/second_launch/outcome_v01/bounded/`（独立子目录），
  禁止触碰 `second_launch_outcome_v01.csv` / `manifest.json` /
  `pattern_provenance_mismatch.csv` / `case_provenance_conflicts_v01.csv`；
  新增回归测试验证正式目录字节级不变
- **FEATURE_HASH_PIN: 已修复** — 新增 `EXPECTED_FEATURE_SNAPSHOT_SHA256`
  = `e7243dee…3514`（读取自 data/manifests/snap-2026-07-31-b5f84004de8a.json
  canonical_file_hashes，非报告文字）；运行前校验实际文件哈希，不一致 FAIL CLOSED
- **LABEL_HASH_PIN: 已修复** — `EXPECTED_LABEL_SNAPSHOT_SHA256`
  = `7cc614bf…3813`（读取自 data/manifests/snap-2026-08-06-e798f88ff67b.json）
- **CENSOR_SEMANTICS: 已修复** — 拆分 `window_incomplete_5d` /
  `window_incomplete_10d`（会话数 < horizon）与 `first_event_right_censored_10d`
  （= window_incomplete_10d AND first_event_type == NONE）；
  已观察到 S1_FIRST / INVALID_FIRST / AMBIGUOUS 时不算 event 右截尾；
  `time_to_s1_10d` / `time_to_invalid_10d` 保留为 marginal 字段；未引入 survival model

## TESTS

```text
OLD_TESTS: 10（全部继续通过；2 个断言随列名语义拆分更新）
NEW_TESTS: 5（bounded 隔离 / feature hash pin / label hash pin /
           incomplete window + observed event 不 censored /
           incomplete window + no event 则 censored）
TOTAL: 15 passed
```

运行：`PYTHONPATH=src python -m pytest tests/test_second_launch_outcome_v01.py -q`（~1.2s）
`git diff --check` 通过。

## 64_CONFLICT_FORENSICS

（动态计算，未硬编码 48+16；产物 `case_provenance_conflicts_v01.csv`，64 行 × 20 列）

```text
TOTAL: 64
PATTERN_CHANGED: 48（episodes pattern_3d ≠ validated bars 重算）
S1_TOUCH_RESOLUTION_CHANGED: 14（冻结「no S1-touch bar found」但当前 bars 明确触及）
ACCEPTANCE_CHANGED: 2（603778 / 603083：冻结 SUCCESS 要求首触日 close>=S1，当前 close 不足）
EXPANSION_CHANGED: 0
MISSING_BAR_OR_VALUE: 0
OTHER: 0
```

全部 64 行的 candidate 行 reconciliation_status = CONFIRMED（48+14+2）；
episode_snapshot_id 全部 = snap-2026-07-31-b5f84004de8a；
feature_snapshot_hash = e7243dee…（pin 值）。

## PROVIDER_CROSSCHECK

（64 行全部参与；对比 candidate + 3D 窗口共 4 个日期 × 2 个 raw provider；无新抓取）

```text
CURRENT_CANONICAL_MATCHES_BOTH: 16
CURRENT_CANONICAL_MATCHES_TUSHARE: 0
CURRENT_CANONICAL_MATCHES_AKSHARE: 48
RAW_PROVIDERS_DISAGREE: 0
RAW_DATA_MISSING: 0
```

关键差异字段：`canonical_vs_*_diff_fields` 全部为空。
48 例 MATCHES_AKSHARE 的根因 = **tushare 在 115 个参与日期缺行**（值无任何差异；
akshare 缺行 0）——即 canonical 修复用 tdx/akshare 补齐了 tushare 缺失的 bar；
16 例 MATCHES_BOTH 中 canonical 与两个 raw 源完全一致（这些正是冻结标签与当前数据
直接矛盾的 16 例，证明冲突来自修复前的内容，而非当前 canonical 自身错误）。

## ROW_POLICY

（candidate + 3D(feature) + 5D(label) 窗口，8,746 case 全量统计）

```text
CONFIRMED_N: 76,946
PROVISIONAL_N: 1,768（2.25%）
CONFLICT_WITH_PROVISIONAL_N: 49（窗口内至少 1 行 PROVISIONAL）
CONFLICT_ALL_CONFIRMED_N: 15
RECOMMENDATION: KEEP_LEGACY_ALL_CANONICAL
```

理由：15 个全 CONFIRMED 冲突证明即使只使用 CONFIRMED 行也无法消除冲突
（修复同时改了 CONFIRMED 与 PROVISIONAL 行）；PROVISIONAL 在窗口中仅占 2.25%，
CONFIRMED-only（V01C_CONFIRMED_ONLY）会无谓丢样本且不解决根因。
建议：保留 all-canonical 口径，把 reconciliation_status 作为逐行分层字段进入 R1B。

## COHORT_PROVENANCE

```text
STATUS: PARTIAL
EVIDENCE:
- candidate 日：64/64 当前 canonical == tushare == akshare
- anchor 日：64/64 当前 canonical 有 bar 且 == 双 raw（修复前误报为 0，已修 date 转换 bug）
- episodes snapshot_id 单一（snap-2026-07-31-b5f84004de8a）；64/64 INFERRED_LIMIT_ANCHOR
- 全部 64 例冲突仅发生在 candidate_date 之后的窗口 bars（pattern 序 / 触及 / 接受 / 扩张），
  无任何证据涉及 anchor / candidate 日 bars
UNPROVEN: 无修复前 bars 可对比 → 无法证明冻结 episodes 的 s1_price / invalid_price /
anchor_date / setup_stage 在构建时未受旧 canonical 影响（按要求不猜，判 PARTIAL）
```

## REPRODUCIBLE_SUBSET

```text
REPRODUCIBLE_N: 8,682
QUARANTINE_N: 64（动态；8,746 - 64）
```

CONCENTRATION（quarantine 64 行）：

| 维度 | 分布 | 与全集的偏差 |
|---|---|---|
| year | 2024: 8 / 2025: 5 / 2026: 51（79.7%） | 2026 显著集中 |
| month | 2026-03: 23 / 2026-07: 14 / 2026-01: 12 / 其余 15 个月 0-3 | 修复批次日期簇 |
| outcome | UNKNOWN 31 / STRUCTURE_FAIL 23 / NO_LAUNCH 6 / SUCCESS 3 / FAILED_BREAKOUT 1 | **UNKNOWN 的 12.8%（31/242）被隔离**，其余 0.1-0.7% |
| data_quality | PARTIAL 64 / OK 0 | 与池一致（OK 仅 33 例） |
| candidate_provider | TUSHARE 64 / 其他 0 | 与池一致（TUSHARE 主导） |
| code | 601975 2 / 603090 2 / 其余各 1 | 无单票集中 |

SELECTION_BIAS_RISK: **中等，且方向可预期**——V01B_REPRODUCIBLE_SUBSET 会系统性
减少 UNKNOWN 与 2026 年样本；UNKNOWN 在 V01B 语义中本就不参与比较（AMBIGUOUS/缺K），
对 SUCCESS/FB/NL/SF 的比值影响很小（0.1-0.7%），但按年份/月份的 time-series 分析
需显式标注 2026-01/03/07 的覆盖率缺口。本轮未替换 V01B。

## DECISION

```text
INTERIM_A_RECOMMENDED: true（在 8,682 行 reproducible 子集上重跑 R1A.1 package，
  冻结 V01B 不动；quarantine 64 行单独登记）
LONG_TERM_V01C_RECOMMENDED: true（基于当前 validated bars 新建修正 case set 时，
  保留 reconciliation_status 分层与修复日期批次元数据；V01B 保持冻结）
```

## FILES_CHANGED

- `research/second_launch/outcome_v01/build_second_launch_outcome_v01.py`（修改：A1/A2/A3）
- `research/second_launch/outcome_v01/audit_conflict_forensics_v01.py`（新增：PART B-F 审计）
- `research/second_launch/outcome_v01/case_provenance_conflicts_v01.csv`（新增：64 行 forensic 产物）
- `tests/test_second_launch_outcome_v01.py`（修改：2 处断言更新 + 5 个新测试）
- `research/reports/SECOND_LAUNCH_FACTOR_R1A2_PROVENANCE_FORENSICS_REPORT.md`（本报告）
- 未发布：second_launch_outcome_v01.csv / manifest.json（gate 仍 BLOCKED）

## CODE_REVIEW_TARGETS

1. `build_package()`（build_second_launch_outcome_v01.py:494）——bounded/full 输出隔离 +
   双 snapshot hash pin fail-closed + 审计先于 gate 落盘
2. `_build_rows()`（:339）——window_incomplete_* / first_event_right_censored_10d 语义拆分
3. `audit_conflict_forensics_v01.py::classify_conflict()`（:98）——动态 conflict_class（无硬编码计数）
4. `audit_conflict_forensics_v01.py::provider_crosscheck()`（:180）——64 行 × 4 日期 × 双 provider 交叉核对
5. `audit_conflict_forensics_v01.py::row_policy_audit()`（:243）——CONFIRMED/PROVISIONAL 行策略

## GIT

```text
COMMIT: research: harden label provenance audit
PUSH: origin/research/second-launch-label-v01
```

## CONFIRM

```text
5D_PACKAGE_PUBLISHED=false
V01B_CHANGED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
```

## NEXT_RECOMMENDED_ACTION

1. 人工评审本报告；批准 INTERIM_A（8,682 子集重跑 R1A.1 package）或 LONG_TERM_V01C
2. 若批准 INTERIM_A：重跑生成器（<20s）发布 5D package；quarantine 64 行登记为
   `case_provenance_conflicts_v01.csv`（已就绪）
3. 在第二大脑登记「冻结 case set 构建于 canonical 修复前 bar 内容」缺陷（64 行，含
   tushare 115 缺失日期证据）
4. 未获授权前：不创建 V01C、不发布 5D、不进入 R1B

---

## VALIDATION（本任务）

- 15/15 targeted tests；`git diff --check` 通过；未跑 full-market tests
- 全部统计有界：64 行 × 4 日期 × 2 provider 交叉核对；8,746 行窗口行策略统计（~80s）
- 哈希 pin 值来源：data/manifests/*.json（正式 manifest），非报告文字
- 结论状态：OBSERVE_ONLY（数据取证；不构成 edge 结论）
