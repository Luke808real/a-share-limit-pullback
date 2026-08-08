# SECOND_LAUNCH_FACTOR_R1A5_IMMUTABLE_VERIFIER_REPORT

> R1A.5 — immutable manifest verifier bugfix（R1B 前最后一个 provenance bugfix）
> 修复：verify_interim_manifest_artifacts() 错误要求 generator_commit == 当前 HEAD
> 未修改任何 label / quarantine / cohort 内容

STATUS: **COMPLETE** — immutable verifier 修复；真实分支状态（HEAD != generator_commit）验证 PASS；
42/42 tests

BASE_HEAD: `a13615517711968de8da9abfcf728cb1ea786645`
HEAD_AFTER: 见 GIT 段

CURRENT_HEAD: `a13615517711968de8da9abfcf728cb1ea786645`（artifact commit B）
MANIFEST_GENERATOR_COMMIT: `307e75bcffd80b1a9c9762ad3be8aa8615b513b8`（Commit A）
HEAD_EQUALS_GENERATOR_COMMIT: **false**（这正是本轮要修复的长期自验证场景）

## IMMUTABLE_VERIFY

```text
STATUS: PASS
GENERATOR_COMMIT_EXISTS: true（git cat-file 可读 307e75b）
GENERATOR_PATH_EXISTS_AT_COMMIT: true（research/second_launch/outcome_v01/build_second_launch_outcome_v01.py）
COMMITTED_GENERATOR_SHA256: d455e99aab26d8b2ec739f8c14873b09df5c4d82219812da038d7d6669527dea
MANIFEST_GENERATOR_SHA256: d455e99aab26d8b2ec739f8c14873b09df5c4d82219812da038d7d6669527dea
MATCH: true
```

实现变更：

- 新增 `git_blob_at_commit(commit, repo_relative_path)`（git cat-file，显式 repo cwd，
  commit/path 缺失 FAIL CLOSED，无 silent fallback）
- `verify_interim_manifest_artifacts()` 不再要求 HEAD == generator_commit；改为读取
  `<generator_commit>:<generator_path>` 的 committed blob，校验
  SHA256(blob) == manifest.generator_sha256（永不使用当前 working-tree generator）
- 新增独立 `verify_reproduction_environment()`（HEAD == generator_commit 且
  当前 generator 文件 SHA == generator_sha256）—— 与 immutable integrity 完全分离；
  在本轮真实分支上它正确 FAIL（HEAD=a136155 ≠ 307e75b）

## ARTIFACT

```text
ROW_N: 8,682
ARTIFACT_SHA256: 01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d
QUARANTINE_SHA256: c5d028ca60c1b73f454aeec4da098c13129968bce26ad3f70f5fae96f45a2d66
```

## CONTENT_FREEZE

```text
ARTIFACT_CHANGED: false（git status 无 CSV 修改；实际文件 SHA == manifest 01a9f2fa…）
QUARANTINE_CHANGED: false（实际文件 SHA == manifest c5d028ca…）
OUTCOME_3D_CHANGED_N: 0（未重新生成 labels）
OUTCOME_5D_CHANGED_N: 0
```

## TESTS

```text
OLD: 37（全部继续通过；其中 1 个 mutated-generator 测试按新语义改写为
  “generator_commit 指向 blob 内容不同的有效 commit → FAIL”）
NEW: 5（ancestor generator_commit + HEAD 不同 → PASS（核心回归）/
      不存在的 generator_commit → FAIL CLOSED /
      指定 commit 中 generator_path 不存在 → FAIL CLOSED /
      generator_sha256 被篡改 → FAIL CLOSED /
      worktree generator 被改但 committed blob 未变 → immutable PASS，
      reproduction verifier FAIL）
TOTAL: 42 passed（~1.7s）；git diff --check 通过；未跑 full-market
```

## FILES_CHANGED

- `research/second_launch/outcome_v01/build_second_launch_outcome_v01.py`（M：
  git_blob_at_commit、immutable verify 修复、verify_reproduction_environment、
  发布语义注释改为 manifest-last, hash-verified publication）
- `tests/test_artifact_provenance_freeze.py`（M：1 个改写 + 5 个新增）
- `research/reports/SECOND_LAUNCH_FACTOR_R1A4_ARTIFACT_PROVENANCE_REPORT.md`（M：
  发布语义措辞修正为 temp write → CSV atomic replace → manifest-last atomic
  replace → hash verification → fail closed）

## CONFIRM

```text
LABEL_SEMANTICS_CHANGED=false
V01B_CHANGED=false
QUARANTINE_CHANGED=false
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
```

## NEXT_RECOMMENDED_ACTION

**R1B — DAILY FACTOR CONTRACT**（人工批准后启动；输入 = 冻结的
SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE 8,682 行 + quarantine 64 行 +
EXPLORATORY_FACTOR_RESEARCH_ONLY 边界；artifact 现在可脱离当前 HEAD 长期自验证）。
未获授权前不进入 R1B、不提取 factor、不创建 V01C。

---

## VALIDATION（本任务）

- 42/42 targeted tests；`git diff --check` 通过；未跑 full-market
- 真实分支最终验证：HEAD=a136155 ≠ generator_commit=307e75b →
  IMMUTABLE_VERIFY_STATUS=PASS（本轮核心修复的实证）
- 内容冻结：artifact/quarantine 文件零修改，SHA 与 manifest 一致
- 结论状态：OBSERVE_ONLY；INTERIM 标签仅允许探索性因子研究
