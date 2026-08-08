# SECOND_LAUNCH_FACTOR_R1A4_ARTIFACT_PROVENANCE_REPORT

> R1A.4 — artifact provenance freeze（R1B 前最后一个 label-package gate）
> two-commit workflow：COMMIT A（code/tests）→ 重新生成 → COMMIT B（artifacts/report）

STATUS: **COMPLETE** — provenance 加固完成；verify PASS；内容稳定性 0 差异；
artifact 已冻结（37/37 tests）

BRANCH: `research/second-launch-label-v01`

BASE_HEAD: `029cc60d7482f672da45e0131417f0b52c61dd6d`
CODE_COMMIT_A: `307e75bcffd80b1a9c9762ad3be8aa8615b513b8`（research: harden reproducible artifact provenance）
ARTIFACT_COMMIT_B: 见 GIT 段（research: freeze reproducible label artifact）

## GENERATOR

```text
GENERATOR_COMMIT: 307e75bcffd80b1a9c9762ad3be8aa8615b513b8（== Commit A == 生成时 git HEAD）
GENERATOR_SHA256: d455e99aab26d8b2ec739f8c14873b09df5c4d82219812da038d7d6669527dea（运行时计算）
WORKTREE_SOURCE_CLEAN_BEFORE_GENERATION: true（git status --porcelain -- generator tests/
  为空；仅 data/.venv 符号链接与 bounded/ scratch 未跟踪）
```

语义：`generator_commit` = 生成 artifact 所用的精确已提交源码（Commit A），
不指向最终 artifact commit（B）；生成前强制 `_require_clean_generator_source()`（CLI --interim）。

## ARTIFACT

```text
ARTIFACT_ID: SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE
ROW_N: 8,682
ARTIFACT_PATH: research/second_launch/outcome_v01/second_launch_outcome_v01b_reproducible.csv
ARTIFACT_SHA256: 01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d
```

## QUARANTINE

```text
N: 64
PATH: research/second_launch/outcome_v01/quarantine_v01b.csv
SHA256: c5d028ca60c1b73f454aeec4da098c13129968bce26ad3f70f5fae96f45a2d66
ID_SET_MATCH: true（quarantine id set == 当前 3D mismatch id set，双向精确）
DUPLICATE_ID_N: 0（load_quarantine 校验 episode_id 唯一）
NULL_ID_N: 0（episode_id 非空校验）
```

## INPUTS

```text
PARENT_CASE_SET_SHA256: b22eae1dd438ed1b4053ce2cfce7ce668010518462261cb724f149615894f4e6
  （parent_case_set_path: research/intraday/success_control_cases_v01b.csv）
FEATURE_SNAPSHOT_SHA256: e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
LABEL_SNAPSHOT_SHA256: 7cc614bf4e1e7f91f34ed1a866827b3b70772a32ff5ff04a5ad67e205e23813e
```

## MANIFEST

```text
PATHS_PORTABLE: true（artifact_path / quarantine_path / parent_case_set_path 全部
  repo-relative POSIX；无 /Users/…、无反斜杠、无 file://；validate_manifest_paths_portable 校验）
ABSOLUTE_PATH_N: 0（_repo_relative 对仓库外路径 FAIL CLOSED）
VERIFY_STATUS: PASS（verify_interim_manifest_artifacts 全项通过：
  CSV SHA / quarantine SHA / parent SHA / generator SHA / feature SHA / label SHA；
  另校验 generator_commit == 生成时 HEAD）
```

发布语义：temp write → CSV atomic replace → manifest-last atomic replace →
hash verification → mismatch fail closed（即 manifest-last, hash-verified
publication；manifest 存在 + 哈希验证成功 = published）。

## CONTENT_STABILITY

```text
PREVIOUS_ROW_N: 8,682（029cc60 版）
NEW_ROW_N: 8,682
DATAFRAME_VALUE_MISMATCH_N: 0（全 25 列 cell 级比较）
OUTCOME_3D_CHANGED_N: 0
OUTCOME_5D_CHANGED_N: 0
BYTES: 完全一致（prev_bytes == new_bytes）
```

CSV 与 quarantine 字节级稳定（与上一版完全相同，Commit B 无需重新提交）；
仅 manifest 因新增 provenance 字段而更新。

## TESTS

```text
OLD: 29（15 generator + 8 forensic + 7 interim，全部继续通过）
NEW: 8（manifest paths repo-relative / absolute quarantine rejected /
     artifact CSV SHA verifies / mutated CSV FAIL CLOSED /
     mutated quarantine FAIL CLOSED / mutated generator FAIL CLOSED /
     duplicate quarantine id BLOCK / null quarantine id BLOCK）
TOTAL: 37 passed（~1.6s）；git diff --check 通过；未跑 full-market
```

## FILES_COMMIT_A

- `research/second_launch/outcome_v01/build_second_launch_outcome_v01.py`（M：
  manifest provenance 字段、_repo_relative、validate_manifest_paths_portable、
  _require_clean_generator_source、load_quarantine 校验、temp+replace 发布语义、
  verify_interim_manifest_artifacts、compare_artifact_csvs）
- `tests/test_interim_reproducible_package.py`（M：in-repo tmp 路径适配）
- `tests/test_artifact_provenance_freeze.py`（新增，8 tests）

## FILES_COMMIT_B

- `research/second_launch/outcome_v01/manifest_v01b_reproducible.json`（M：provenance 字段）
- `research/reports/SECOND_LAUNCH_FACTOR_R1A4_ARTIFACT_PROVENANCE_REPORT.md`（本报告）
- （CSV / quarantine 字节级稳定，无变化，不重复提交）

## CONFIRM

```text
V01B_CHANGED=false（sha b22eae1d… 复验）
QUARANTINE_SEMANTICS_CHANGED=false（仅新增 null/unique 校验，未重新定义）
LABEL_SEMANTICS_CHANGED=false（8,682 行数据 0 变化）
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
```

## NEXT_RECOMMENDED_ACTION

**R1B — DAILY FACTOR CONTRACT**（人工批准后启动；输入 = 冻结的
SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE 8,682 行 + quarantine 64 行 +
EXPLORATORY_FACTOR_RESEARCH_ONLY 使用边界）。未获授权前不进入 R1B、
不提取 factor、不训练模型、不创建 V01C。

---

## VALIDATION（本任务）

- 37/37 targeted tests；`git diff --check` 通过；未跑 full-market
- 发布门：quarantine 精确集 → subset 3D mismatch=0 → temp+replace 发布 →
  verify_interim_manifest_artifacts PASS → 内容稳定性 0 差异（字节级）
- 结论状态：OBSERVE_ONLY；INTERIM 标签仅允许探索性因子研究
