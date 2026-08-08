# SECOND_LAUNCH_FACTOR_R1A1_LABEL_PACKAGE_REPORT

> R1A.1 — provenance-safe multi-horizon label package（research-only）
> 结论：**STATUS = BLOCKED**（3D regression gate: MISMATCH_N=64 > 0；未生成正式 5D package）
> AS_OF: 2026-08-08 · 开发于隔离 worktree（未触碰原 dirty worktree）

STATUS: **BLOCKED** — 3D regression gate 失败（64 例），根因 = 冻结 case set 构建于
canonical 修复前的 bar 内容；当前 validated canonical 与两个 raw provider 一致。
5D package（second_launch_outcome_v01.csv / manifest.json）**未生成**。
Provenance 审计产物已全量落盘（8,746 行）。

REPO: `Luke808real/a-share-limit-pullback`（隔离 worktree `/Users/luke808/AI/V flash-r1a1-label`）
BRANCH: `research/second-launch-label-v01`
BASE_HEAD: `0f08348fd1fa7e04bdf468acc5516d6001e169b9`
HEAD_AFTER: 提交后见 GIT 段

## FILES_CHANGED

- `research/second_launch/outcome_v01/build_second_launch_outcome_v01.py`（生成器，新增）
- `research/second_launch/outcome_v01/pattern_provenance_mismatch.csv`（全量 8,746 行审计，新增）
- `tests/test_second_launch_outcome_v01.py`（10 个 targeted tests，新增）
- `research/reports/SECOND_LAUNCH_FACTOR_R1A1_LABEL_PACKAGE_REPORT.md`（本报告，新增）
- 未生成：`second_launch_outcome_v01.csv`、`manifest.json`（gate BLOCKED，符合契约）
- 未修改：`SUCCESS_CONTROL_CASESET_V01B`、`episodes.parquet`、任何 src/ 策略代码

## CONTRACT

```text
FEATURE_SNAPSHOT: snap-2026-07-31-b5f84004de8a（canonical daily bars；sha256 e7243dee…，
  与 data/manifests/snap-2026-07-31-b5f84004de8a.json 记录一致）
LABEL_SNAPSHOT:  snap-2026-08-06-e798f88ff67b（SCREEN_READY + validation PASS；sha256 7cc614bf…）
CASE_SET:        SUCCESS_CONTROL_CASESET_V01B（research/intraday/success_control_cases_v01b.csv，
  sha256 b22eae1d…，8,746 行，无重复）
```

- 事件排序完全从 validated canonical daily bars 重算；**未读取 episodes.pattern_5d/pattern_10d 用于标签**
- 复用 `limit_pullback.outcome._pattern_result`（冻结 bar 序语义，未复制第二套实现）
- signal-day volume 只读 FEATURE snapshot（PIT at D）；08-06 snapshot 仅用于 5D/10D 标签窗口
- SUCCESS 三条件冻结：S1_BEFORE_INVALID + 首触日 close>=S1 + 首触日 volume>=候选日 volume
- FAILED_BREAKOUT 拆 FAILED_ACCEPTANCE / FAILED_EXPANSION（reason 字段）

## REGRESSION

```text
ROW_N: 8746
3D_MISMATCH_N: 64（> 0）
STATUS: BLOCKED —— 按契约不生成正式 5D package
```

根因（三层证据，全部只读）：

1. **48 例**：episodes `pattern_3d` 与 FEATURE snapshot bars 重算不一致
   （如 603629:20260325:6268：episodes=S1_BEFORE_INVALID，当前 bars 2026-03-26 high=68.29
   触 S1 且 low=63.00 未触 invalid=62.37 —— bars 支持 S1_BEFORE_INVALID；但冻结 reason 引用
   close 65.87，当前 canonical/tushare/akshare 当日 close 均为 66.05，65.87 在任何源中不存在）
2. **16 例**：pattern_3d 一致但 outcome 不可能由当前 bars 产生：
   - 601236:20240709:662：冻结 UNKNOWN「no S1-touch bar found」，但 2024-07-11 high=6.87 == s1=6.87
     明确触及（canonical 与 tushare/akshare 三方一致）
   - 603083:20260408:11155 / 603778:20241014:345：冻结 SUCCESS（需首触日 close>=S1），
     当前 bars 首触日 close 分别为 118.58 < 119.98、3.41 < 3.52
3. **独立交叉验证**：抽查 601236（2024-07-10~16）与 603629（2026-03-25~30），
   current canonical == raw tushare == raw akshare（完全一致）→ 当前 canonical 是自洽版本；
   冻结标签引用的是修复前 bar 内容（ADR-008 catch-up / canonical repair 已改动对应日期区间，
   与 R1A 发现的 episodes pattern_5d/10d 缺陷同源）

结论：**冻结 V01B outcome 列对 64/8,746 行不可从当前 validated 数据复现**；门按设计 fail-closed。

## 5D

（内存计算值，**未发布**——gate BLOCKED）

```text
OUTCOME_COUNTS: SUCCESS 483 / FAILED_BREAKOUT 1,168 / NO_LAUNCH 1,021 /
                STRUCTURE_FAIL 5,855 / UNKNOWN 219（=8,746）
CENSORED_N: 0（contract 达成；5D 全 cohort 可用 validated 08-06 snapshot 完整评估）
```

## 10D_EVENT_TIME

```text
RIGHT_CENSORED_N: 88（会话级；与 R1A 预期一致；47 例 7 会话 / 41 例 8 会话 / 其余 10+）
FIRST_S1_N:      1,873
FIRST_INVALID_N: 6,207
NO_EVENT_N:      447
AMBIGUOUS_N:     219
time_to_s1 可观测 3,777 例 / time_to_invalid 可观测 7,079 例（10 会话窗口内边际首触）
```

注：pattern 级 `CENSORED`（窗口内无任何事件 → 16 行）与会话级右截尾（窗口不足 → 88 行）是两个
不同概念；`_pattern_result` 在窗口内命中事件时先返回事件（冻结语义），本 package 二者都保留。

## PROVENANCE_DEFECT

```text
MISMATCH_N: 87（动态计算；MATCH 8,659 / PATTERN_DIFF 71 / LABEL_CENSORED 16）
OUTPUT_PATH: research/second_launch/outcome_v01/pattern_provenance_mismatch.csv（8,746 行）
```

- 口径：episodes.pattern_5d/10d（冻结）vs 本 package 从 **validated 08-06 snapshot** 重算的
  pattern_5d/10d；R1A 的 183 为 episodes vs **feature (07-31) snapshot** 口径，两者都证明同一缺陷
  （episodes 模式列不可信，必须以 validated bars 重算）；87 vs 183 的差异来自：(a) 88 例尾部在
  label snapshot 有更多会话，(b) 部分行重算后事件命中故非 CENSORED
- 仅登记，未修改 episodes.parquet

## GOLDEN_CASE_CHECK

（17 个 setups / 5 股，与 R1A 观察方向一致）

- 601858:20260311：3D NO_LAUNCH → 5D FAILED_BREAKOUT（FAILED_ACCEPTANCE，S1@4）✓
- 600756:20240926：3D NO_LAUNCH，10D 首事件 S1@9 ✓
- 600468:20260629：STRUCTURE_FAIL（invalid@2）；600756:20260313：SUCCESS ✓
- 002498:20260415：FAILED_EXPANSION；002498:20260429：FAILED_ACCEPTANCE ✓
- 600756:20260708：UNKNOWN（同日 AMBIGUOUS），right_censored_10d=True ✓
- 3D 冻结等价：17/17 无 mismatch（golden 子集在门内）

## TESTS

`tests/test_second_launch_outcome_v01.py` — **10 passed**（targeted，offline，~0.5s）：

1. 3D frozen equivalence（golden 5 codes 真实数据）
2. 5D horizon session counting（停牌日不计会话）
3. same-bar S1+invalid => AMBIGUOUS => UNKNOWN
4. FAILED_ACCEPTANCE
5. FAILED_EXPANSION
6. NO_LAUNCH
7. STRUCTURE_FAIL
8. right censoring（5D/10D 窗口不足）
9. feature/label snapshot 分离（signal volume 只取 feature；5D 窗口只取 label）
10. gate fail-closed（BLOCKED 时无 5D CSV，审计 CSV 仍写）

运行：`PYTHONPATH=src python -m pytest tests/test_second_launch_outcome_v01.py -q`；
`git diff --check` 通过。未跑 full-market tests。

## CODE_REVIEW_TARGETS

1. `classify_outcome()`（build_second_launch_outcome_v01.py:236）—— 5D 标签判定，
   SUCCESS 三条件 + FAILED_ACCEPTANCE/FAILED_EXPANSION 拆分
2. `recompute_pattern()`（:216）—— 复用 `limit_pullback.outcome._pattern_result`，
   事件排序唯一来源，无第二套语义
3. `_build_rows()`（:331）—— 3D gate + 5D + 10D 事件时间逐 case 计算与 censoring 标记
4. `build_package()`（:470）—— 门顺序（先审计落盘、再 gate、后发布）、fail-closed、manifest
5. `_provenance_mismatch_rows()`（:416）—— episodes 缺陷登记口径

## GIT

```text
COMMIT: research: build provenance-safe second launch labels（见 HEAD_AFTER）
PUSH: origin/research/second-launch-label-v01
PR: 未创建（保持 Draft 前状态；如需要可后续创建 Draft PR）
```

## CONFIRM

```text
FROZEN_CASESET_CHANGED=false
EPISODES_CHANGED=false
STRATEGY_CHANGED=false
STATE_MACHINE_CHANGED=false
PRODUCTION_CHANGED=false
```

## BLOCKERS

1. **冻结 case set 与 validated bars 存在 64 行 provenance 冲突**（R1A 已预告 episodes
   pattern_5d/10d 缺陷，本任务进一步证明 pattern_3d 与 outcome 列同样不可从当前数据复现）——
   gate 按契约 BLOCKED，5D package 未发布
2. 10D 尾部 88 例仍缺 validated 标签数据（需到 ~2026-08-11 的 snapshot）—— 与 R1A 一致
3. R1A 的 pattern_5d/10d 不一致（183 行口径）与本次 64 行 outcome 冲突同源，需一次性登记处置

## DECISION_REQUIRED

1. 64 行冲突的处理方案（三选一）：
   - A：隔离（quarantine）64 行，在其余 8,682 行上重跑本 package（最小改动，冻结 V01B 不动）
   - B：基于当前 validated bars 新建修正 case set（新 artifact，如 V01C；V01B 保持冻结）后重跑
   - C：接受 V01B 现状并放宽 gate 契约（**不推荐**：会掩盖数据缺陷）
2. 5D 标签发布是否在处置 64 行后重新执行（生成器已就绪，一次运行 <20s）
3. 10D 事件时间字段是否随 5D 一起发布（不依赖 outcome_10d）

## NEXT_RECOMMENDED_ACTION

1. 人工评审本报告 + 上述 DECISION_REQUIRED
2. 推荐方案 A 或 B（research-only，不触碰冻结 artifact），批准后重跑生成器发布 5D package
3. 在第二大脑登记「冻结 case set 与 canonical 修复冲突」provenance 缺陷
4. 未获授权前：不进入 R1B、不提取任何 factor

---

## VALIDATION（本任务）

- 隔离 worktree（branch `research/second-launch-label-v01`，HEAD = BASE_HEAD 精确值），
  未携带原 worktree 未提交改动；data/.venv 为只读符号链接
- targeted pytest 10 passed；`git diff --check` 通过；未跑 full-market tests
- 生成器全量运行 <20s（有界 parquet 过滤读取 + DailyBar 投影）
- 输入哈希全部显式校验：case set b22eae1d…、feature e7243dee…（与 canonical manifest 一致）、
  label 7cc614bf…
- 结论状态：BLOCKED（gate 契约）；不构成任何 edge 结论
