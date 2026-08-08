# SECOND_LAUNCH_FACTOR_R2A_CODE_REVIEW_REPORT

> R2A extractor 独立代码审查（对照冻结 25-factor contract + R1B.1/R1B.2 CA 契约）
> 审查范围：extract_daily_factors_v01.py + 两个 R2A 测试文件 + 冻结合同 + R2A 报告

```text
STATUS: FIXED_AND_PASS（3 类问题已最小修复 + 4 个回归测试；37/37 tests；golden 无回归）

BRANCH: research/second-launch-factor-extractor-v01
HEAD_BEFORE: 9bb49366e48d13768a158cc103921234c400cb56
HEAD_AFTER: 见 GIT 段
```

## CONTRACT_MATCH

```text
PASS
- FACTOR_REGISTRY 与 contract CSV 双向精确相等（无缺失/额外/重复；derive alias 正确）
- 25 个 formula 与 CSV formula_symbolic 逐条核对一致（#1-#25 全检）
- window / T0 inclusion / PB 窗口 / predecessor / denominator / min sessions /
  missing reason 与 CSV 逐字段核对一致
```

## PIT

```text
PASS
- usecols 白名单（11 列）；FORBIDDEN ∩ USECOLS = ∅ 静态断言
- FactorCaseContext 无 outcome/event 字段（dataclass 字段集断言）
- 仅 feature snapshot（hash pin）；无未来 bar；无间接 join 泄漏（输出 schema 不含 label 列）
- mutation 测试：修改 outcome/event 字段不改变任何 factor（assert_frame_equal）
```

## CA_SEMANTICS

```text
PASS（含 1 处修复）
- edge-based CA_TRANSITION；严格 canonical predecessor；EVENT > UNKNOWN（冻结优先级）
- duplicate identical dedupe；conflict FAIL CLOSED（RuntimeError）
- row-level reason 分开：CORPORATE_ACTION_EVENT / CORPORATE_ACTION_UNKNOWN
修复：左边界 predecessor 严格化 —— ca_guard 改为接收 (span_start, span_end)，
  span_start < 0（predecessor session 在快照历史之外）→ CORPORATE_ACTION_UNKNOWN。
  此前 _ca_obs_from_span 会把下界 clamp 到 0，导致 i0==0 或恰好最低历史时
  predecessor edge 被静默跳过（违反冻结左边界规则）
```

## WINDOW_OFF_BY_ONE

```text
PASS（审查核对 + 既有测试覆盖）
- T0=offset 0；首个 post-T0 session=1；D=days_since_t0（iD−i0）
- #5: 19 prior + T0（iloc[i0-19:i0+1]，20 sessions；CA obs T0-20..T0）
- #6: close(T0-1)/close(T0-6)，5 intervals（iloc[i0-1]/iloc[i0-6]）
- #7: close(T0-1)/close(T0-21)，20 intervals
- #8: prior 5 sessions mean，T0 不入 denominator
- #10: prior_peak 更新在 dd_j 计算之后（当日 high 不入 prior peak；含 T0_high 初值）
- #23: reference = iloc[i0:iD]（含 T0、排 D）；tie → LAST occurrence（reversed argmax）
- #24/#25: PRE_D = iloc[i0+1:iD]（D 不入 reference）；D edge 独立检查
```

## MISSING_REASON

```text
PASS（含 1 处修复）
- 全缺失走 NULL + reason；无 0/epsilon/imputation
- FactorResult 不变量强制（value/reason 互斥、非有限 float 拒绝）
修复：preclose <= 0（非 NaN 的 0 值）此前会 ZeroDivisionError 崩溃；
  现按零分母政策返回 ZERO_DENOMINATOR（#1/#2/#3 T0 preclose；#18/#19 PB preclose）
```

## FULL_PATH_GATE

```text
PASS（含 1 处加固）
- --allow-full 与 bounded 走完全相同的 run_input_gate()
  （contract SHA pin + immutable manifest verify + feature snapshot SHA）
- 无 bounded 有校验 / full 绕过校验的分叉路径
加固：移除 --skip-input-gate 手动 bypass 旋钮（CLI 无条件执行输入门）
```

## FINDINGS

```text
1. [FIXED] CA 左边界 predecessor 静默跳过（FINDING 级别：MEDIUM）
   - _ca_obs_from_span 对负起点 clamp 到 0；i0==0 或恰好最低历史（如 #6 在 i0=6）
     时，span 首 session 的 predecessor edge 无法构造但被当作“无此 obs”继续评估
     其余 edges → 可能返回 OK 而非契约要求的 CA_UNKNOWN
   - 修复：ca_guard(ctx, span_start, span_end)，span_start<0 → CA_UNKNOWN
   - 回归测试：test_ca_predecessor_outside_history_unknown /
     test_pre_t0_predecessor_outside_history_unknown
2. [FIXED] preclose==0 除零崩溃（FINDING 级别：MEDIUM）
   - #1/#2/#3 与 #18/#19（及 t0_range_pct 基准）在 preclose==0 时 ZeroDivisionError
   - 修复：D(preclose) <= 0 → ZERO_DENOMINATOR（与冻结合同零分母政策一致）
   - 回归测试：test_t0_preclose_zero_denominator / test_pb_preclose_zero_denominator
3. [FIXED] --skip-input-gate 多余 bypass（FINDING 级别：LOW）
   - 移除该 CLI 开关；输入门无条件执行
4. [CONFIRMED-OK] #24/#25 在 i0==0 的正确语义：
   F6 required span 起点是 T0（其 predecessor 即 T0 自身，存在）→ 不触发 UNKNOWN；
   与 PB 类 factor（span 起点 T0-1）不同 —— 已加测试固化
5. [CONFIRMED-OK] 共享 helper（_pb_window/_pb_ranges/ca_guard/future_window）单一实现，
   无多个 factor 偷偷共用错误窗口；#11/#12 恒等由同一 min_pb_close 保证
```

## PATCHES

```text
- extract_daily_factors_v01.py：
  · ca_guard 签名改为 (ctx, span_start, span_end) + span_start<0 → CA_UNKNOWN
  · 19 处调用点改为显式 (start, end)（机械替换）
  · #1/#2/#3：T0 preclose <= 0 → ZERO_DENOMINATOR
  · _pb_ranges：PB preclose <= 0 / t0 preclose <= 0 → ZERO_DENOMINATOR
  · 移除 --skip-input-gate；移除未用 field import
- tests/test_daily_factor_extractor_v01.py：既有公式测试按契约前置 predecessor session
  （T0 移出 snapshot 首 session）；+4 个回归测试
- tests/test_daily_factor_ca_v01.py：test_f18_f19_ca_event_null 按契约移位
```

## TESTS

```text
- executed: pytest tests/test_daily_factor_extractor_v01.py tests/test_daily_factor_ca_v01.py
- passed: 37 / 37（R2A 33 + 新增 4 回归）
- bounded golden re-run：17 cases 输出与修复前逐 cell 一致（无回归）
- git diff --check: PASS
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R2B_RECOMMENDATION

```text
AUTHORIZED
```

（授权仅指正确性门通过；本任务未执行 R2B / 8,682 full extraction ——
仍须人工确认后另行启动。）

## FILES_CHANGED

- `research/second_launch/factors_v01/extract_daily_factors_v01.py`（M：上述修复）
- `tests/test_daily_factor_extractor_v01.py`（M：移位 + 4 回归测试）
- `tests/test_daily_factor_ca_v01.py`（M：1 测试移位）
- `research/reports/SECOND_LAUNCH_FACTOR_R2A_CODE_REVIEW_REPORT.md`（本报告）

## GIT

```text
COMMIT: research: review fix extractor ca edge and zero denominator
PUSH: origin/research/second-launch-factor-extractor-v01
```

---

## VALIDATION NOTES

- 未运行 8,682 full extraction；未做 outcome join / attribution；未修改 frozen contract
- 审查基于：冻结 CSV（SHA a67e7e2a…）、DAILY_FACTOR_CONTRACT_V01.md、
  CORPORATE_ACTION_CONTRACT_V01.md（R1B.1/R1B.2）、R2A 报告
