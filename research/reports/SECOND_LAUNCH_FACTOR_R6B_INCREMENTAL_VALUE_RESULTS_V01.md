# SECOND_LAUNCH_FACTOR_R6B_INCREMENTAL_VALUE_RESULTS_V01

> R6B — Incremental Value Execution V01（执行冻结的 R6A contract）
> AS_OF: 2026-08-09 · research-only · conditional residual discrimination

STATUS: **COMPLETE**

```text
BRANCH: research/second-launch-factor-r6b-incremental-execution-v01
BASE_HEAD: 7e046c7ba14c8822ad042a2915e3ed4cf16df132
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## INPUT_GATE

```text
FEATURE_SHA a485a484… / OUTCOME_SHA 01a9f2fa… / R5B SIGNALS SHA ee1c13… /
R6A REGISTRY SHA 08b8e01d… / SOURCE_HEAD 7e046c7…：PASS
feature 8,682 / outcome 8,682 / signals 8,682；episode unique + 三方 1:1；
symbol / anchor_date / candidate_date binding：PASS
```

## PRIMARY_QUESTION

```text
已经知道 D 日成交量 <= 0.85×T0（B6 信号）有效后，
更丰富的回调收缩结构（F3）是否仍能增加 SUCCESS 区分信息？
方法 = CONDITIONAL RESIDUAL DISCRIMINATION（R6A frozen）。
```

## B6_F3_COMMON_RESULTS（PRIMARY：B6 × F3 × COMMON × SIGNAL，3D）

```text
eligible_group_n = 2,486；factor 非缺失 ≈2,342-2,343；outcome known ≈2,307-2,308
success_n = 151；non_success_n ≈2,156-2,157

factor                 native_auc  dir     R3      effect  match  5D auc   分类
median_range_ratio     0.4222     NEG     NEG     0.0778  yes    0.4099   INCREMENTAL_SUPPORTED
pullback_volume_ratio  0.5035     POS     NEG     0.0035  no     0.4944   NO_INCREMENTAL_VALUE
min_volume_ratio       0.5049     POS     NEG     0.0049  no     0.4948   NO_INCREMENTAL_VALUE
quiet_days_n           0.5148     POS     POS     0.0148  yes    0.5294   INCREMENTAL_WEAK
```

## B6_F3_OWN_RESULTS

```text
与 COMMON 一致：median_range_ratio SUPPORTED（0.4222 / 0.0778 / 5D 0.4099）；
pvr / mvr NO_INCREMENTAL_VALUE；quiet_days_n INCREMENTAL_WEAK。
```

## PRIMARY_CONCLUSION

```text
PRIMARY 回答 = YES（一个明确、一个弱）：
  在 B6 缩量信号组内，median_range_ratio（波动区间收缩）仍保留
  R3-native NEGATIVE 条件区分（effect 0.078 >= 0.03，3D/5D 一致）
  -> INCREMENTAL_SUPPORTED（SUPPORTED_HYPOTHESIS，非 VALIDATED）
  quiet_days_n 同向但 effect < 0.03 -> INCREMENTAL_WEAK
  而 pullback/min_volume_ratio 在 B6 组内方向消失（近中性）：
  简单量缩（B6）已吸收这两个 volume-factor 的区分信息（冗余）
  -> 这正说明 F3 结构 ≠ B6 单条件：range-contraction 与 volume 是
  可分离的信息维度
```

## SECONDARY_BASELINE_RESULTS（B4/B5/B7 × F3 × COMMON）

```text
B4（回调 2-5 日）：4/4 F3 SUPPORTED
  pvr 0.4561/0.0439；mvr 0.4377/0.0623；mrr 0.4187/0.0813；quiet 0.5765/0.0765
B5（深度 >=-4%）：4/4 F3 SUPPORTED（效应最强）
  pvr 0.4013/0.0987；mvr 0.3849/0.1151；mrr 0.4203/0.0797；quiet 0.5998/0.0998
B7（新高代理）：mrr 0.4559/0.0441 SUPPORTED；quiet 0.5525/0.0525 SUPPORTED；
  pvr / mvr NO_INCREMENTAL_VALUE（近中性）
解读：F3 增量信息跨不同 simple baselines 存在（非 B6-specific）；
  volume 类因子只在未被 B6 缩量条件占用的样本中保留信息。
```

## ROBUSTNESS_CONTROLS（F6，COMMON；独立报告，不与 F3 混合排名）

```text
B4: close 0.5873/0.0873 SUPPORTED；high 0.5514/0.0514 SUPPORTED
B5: close 0.5567/0.0567 SUPPORTED；high 0.5029/0.0029 WEAK
B6: close 0.5967/0.0967 SUPPORTED；high 0.5633/0.0633 SUPPORTED
B7: close 0.6739/0.1739 SUPPORTED；high 0.6123/0.1123 SUPPORTED
仅 diagnostic incremental observation；不得推翻 R4：
  high_vs_pullback_high = UNSTABLE；close_vs_pullback_high = TIME_DEPENDENT
```

## 3D_5D_SENSITIVITY

```text
同一 baseline signal / factor / sample membership（仅 outcome-known mask
可因 UNKNOWN 差异变化 —— QA 验证 membership 不变）；
SUPPORTED 项 3D/5D 方向一致；pvr/mvr 的 5D 同向近中性（不改变 NO_VALUE）；
quiet 5D 0.5294（保持 WEAK）。
```

## OBSERVATIONS

```text
O1 B6 组内 median_range_ratio 是唯一 MATERIAL 的 F3 增量
  （0.0778，3D/5D 一致）——F3 的 range-contraction 维度与 B6 volume
  条件是互补信息
O2 volume 类 F3（pvr/mvr）在 B6 信号组内方向消失（AUC ~0.50-0.505），
  在 B4/B5（未按量筛选）内恢复强信息 —— B6 已吸收其条件信息
O3 quiet_days_n 在全部 baseline 同向但效应弱-中（0.015-0.100）
O4 F6 controls 在信号组内普遍有诊断性增量（尤其 B7 close 0.174），
  但 R4 稳定性结论（UNSTABLE / TIME_DEPENDENT）不受影响
```

## HYPOTHESES_SUPPORTED

```text
（SUPPORTED_HYPOTHESIS，非 VALIDATED）
F3 结构在简单 benchmark 之上保留条件区分信息，尤其：
  median_range_ratio（区间收缩）在 B6 缩量基线上为
  INCREMENTAL_SUPPORTED（B6×COMMON×SIGNAL，3D/5D 一致）
```

## HYPOTHESES_NOT_SUPPORTED

```text
volume-ratio 类 F3（pvr/mvr）在已满足 B6 缩量的样本内无增量信息
（NO_INCREMENTAL_VALUE）——与"量缩条件吸收量类因子信息"一致。
```

## R4_SEMANTIC_NOTE

```text
F3 x4 R4 OVERALL = DATA_LIMITED（部分 coverage 维度不可回答），
  不是 UNSTABLE；answerable TIME / REGIME / GAP 维度方向稳定。
F6：high_vs_pullback_high = UNSTABLE；close_vs_pullback_high =
  TIME_DEPENDENT（ROBUSTNESS_CONTROL only，R6B 结果不覆盖）。
```

## ASL_UPSTREAM_SYNC_NOTE（仅记录，非实现）

```text
UPSTREAM: rootSunc/ashare-lake
未来版本状态区分：ASL_UPSTREAM_HEAD / ASL_CANDIDATE / ASL_ACTIVE
ASL_ACTIVE 必须 pin exact upstream commit SHA；
上游更新只能先进 CANDIDATE，不得 git pull 后直接替换 ACTIVE；
未来 Cloud CI 只检测 UPDATE_AVAILABLE；
未来 Mac self-hosted Data CI 手动验证 candidate：
  ASL own verify / Adapter contract / bounded golden parity /
  canonical compatibility；
禁止：自动 asl repair / 自动 full backfill / 自动修改正式 lake /
  自动 promote / 自动改变 Snapshot/Universe/State/Strategy semantics；
稳定边界保持：ASL -> ASL Adapter -> Canonical Contract -> Snapshot ->
  Universe -> State -> Strategy
ASL_SYNC_IMPLEMENTATION=false
ASL_ACTIVE_CHANGED=false
DATA_LAYER_CHANGED=false
```

## QA

```text
input pins（4 SHA + SOURCE_HEAD）：PASS
registry gate（24 combos / B4-B7 / primary B6 / direction / effect 0.03）：PASS
conditional rows 192 / summary 48；无重复行；24 combos 全覆盖
OWN/COMMON reconciliation：PASS（signal + non-signal == eligible known）
signal/non-signal disjoint：PASS
factor missing / UNKNOWN reconciliation：PASS
3D/5D membership invariance：PASS（仅 known mask 可不同）
classification 状态机冻结先于 outcome 读取（synthetic tests 先行）
确定性：两次运行输出哈希一致
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R6_STATUS_RECOMMENDATION / R7_RECOMMENDATION

```text
R6_STATUS_RECOMMENDATION = COMPLETE
R7_RECOMMENDATION = AUTHORIZED
（>=1 个 F3 factor 在 B6 × COMMON × SIGNAL = INCREMENTAL_SUPPORTED：
  median_range_ratio；且 CORRECTNESS_BLOCKER=NO —— 预注册 R7 gate 触发）
（未开始 R7；F6 control 不计入该 gate）
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## VALIDATION

```text
compile: PASS
tests/test_r6b_incremental_execution_v01.py: 18 PASS（cloud_ci，
  仅读 committed artifacts：方向/状态机 7 例/样本语义/无翻转/registry pins）
cloud CI 命令（4 文件）：72 passed, 3 deselected（本地等价）
ci.yml 最小扩展：加入 test_r6b_incremental_execution_v01.py
git diff --check: PASS
```
