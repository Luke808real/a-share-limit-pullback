# JULY 2026 RECONCILIATION FAILURE ROOT-CAUSE V01 — 只读取证

- 状态：**ROOT_CAUSE_CLASS = A_PROVIDER_CODE_COVERAGE（主）+ F_SOURCE_BATCH_BOUNDARY（辅）**
- FAILURE_ONSET = 2026-07-09；RECOVERY_DATE = 2026-07-27
- 日期：2026-08-16
- 分支：`audit/july-reconciliation-root-cause-v01`
- BASE_HEAD：31d931d3f521f7525988da4e8ccffbdb0e6918d7

---

## 0. AUTHORITY

- SNAPSHOT_ID = snap-2026-07-31-b5f84004de8a
- DAILY_SHA256 = e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514（已验证）
- GAP = 2026-07-09..2026-07-24（12 个 expected sessions）
- 确认 canonical：CONFIRMED_N = 0 on all 12（fail closed 通过；见 july-2026-session-coverage-audit-v01）

## 1. PROVIDER CODE×DATE COVERAGE（control / failure / recovery）

| 日期 | AK codes | TS codes | BS codes | AK∩TS∩BS | AK∩TS | AK∩BS | TS∩BS | ONLY_AK | ONLY_TS | ONLY_BS | 角色 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-08 | 3186 | **5518** | 3186 | 3186 | 3186 | 3186 | 3186 | 0 | 2332 | 0 | control（正常） |
| 2026-07-09 | 3186 | **70** | 3186 | 70 | 70 | 3186 | 70 | 0 | 0 | 0 | failure onset |
| 2026-07-15 | 3190 | **70** | 3190 | 70 | 70 | 3190 | 70 | 0 | 0 | 0 | failure middle |
| 2026-07-24 | 3190 | **70** | 3190 | 70 | 70 | 3190 | 70 | 0 | 0 | 0 | failure end |
| 2026-07-27 | 3189 | **5523** | 3189 | 3189 | 3189 | 3189 | 3189 | 0 | 2334 | 0 | recovery control |

**TUSHARE 是唯一的断裂源**：07-08（5518 codes）→ 07-09（70 codes）→ 07-27（5523 codes）。
AKSHARE / BAOSTOCK 全程完整（~3186-3190 codes）。

## 2. RECONCILIATION STATUS DECOMPOSITION

| 日期 | CONFIRMED | CONFIRMED_SINGLE_SOURCE | PROVISIONAL | CONFLICTED | INCOMPLETE |
| --- | --- | --- | --- | --- | --- |
| 2026-07-08 | **3151** | 0 | 2332 | 35 | 116 |
| 2026-07-09 | **0** | 0 | 3143 | 43 | 2448 |
| 2026-07-15 | **0** | 0 | ~3160 | ~29 | ~2444 |
| 2026-07-24 | **0** | 0 | ~3170 | ~20 | ~2443 |
| 2026-07-27 | **3186** | 0 | 2334 | 0 | 0 |

结构性跳变：**07-09 起 CONFIRMED 从 ~3150 归零**，PROVISIONAL 主体改为
PARTIAL_CROSS_VALIDATION（AKSHARE+BAOSTOCK 双源、无 TUSHARE）。

## 3. SAME-CODE FIELD DIFF（70 个 TUSHARE code）

07-09 / 07-15 / 07-24 三个失败日，对 TUSHARE 存在的 70 个 code 与 AKSHARE
逐字段比对（open/high/low/close/volume/amount/preclose）：

- 07-09：70 个 code 全部字段 diff = 0（merge 70/70 完全一致）
- 07-15：70 个 code 全部字段 diff = 0
- 07-24：70 个 code 全部字段 diff = 0

**结论：不是字段 disagreement。** 若这些 TUSHARE 行进入 reconciliation，
它们应得 CONFIRMED（双源一致）——但它们没有进入。

## 4. RECONCILIATION POLICY TRACE

- CONFIRMED 判定（src/limit_pullback/warehouse/reconciliation.py L266-280）：
  `if "TUSHARE" in usable and "AKSHARE" in usable -> CONFIRMED /
  TUSHARE_AKSHARE_AGREEMENT`；否则 `PARTIAL_CROSS_VALIDATION -> PROVISIONAL`。
- 07-08 600000：providers=[AKSHARE, BAOSTOCK, TUSHARE]，CONFIRMED（TUSHARE_AKSHARE_AGREEMENT）
- 07-09 600000：providers=**[AKSHARE, BAOSTOCK]**，PROVISIONAL（PARTIAL_CROSS_VALIDATION）
- 07-27 600000：providers=[AKSHARE, BAOSTOCK, TUSHARE]，CONFIRMED

**关键事实：07-09 的 reconciliation 输入中根本没有 TUSHARE 行**——
即使磁盘上 50ed7fb2 批次含 600000 的 07-09 行。

## 5. CHANGE-POINT TEST（WHAT_CHANGED_AT_2026-07-09 / WHAT_RECOVERED_AT_2026-07-27）

### 5a. TUSHARE 全市场批次（359774eea）的日期覆盖

逐 part 检查 data/raw/tushare/daily_bars/359774eea1675b329e747cbb-*.parquet：

| part | 覆盖日期 |
| --- | --- |
| -0029 | ...07-06?（部分） |
| -0030 | **06-30, 07-01, 07-02, 07-03, 07-06, 07-07, 07-08, 07-27**（8 个日期） |
| -0031 | 03-03..03-30（历史日期，part 边界错位） |
| -0032 | 07-28, 07-29, 07-30, 07-31（4 个日期） |

**TUSHARE 全市场批次在 07-09..07-24 整段无行**（12 个 expected sessions 全部缺失）。
07-08 有（0030），07-27 有（0030），07-28 起有（0032）。

### 5b. 补充批次（50ed7fb2）

- 独立 bootstrap run：50ed7fb2...（started 2026-07-31 21:04，COMPLETED），
  **codes 仅 [600000..600099] 前 100 个 600xxx 主板的子集**
- 该批次的 TUSHARE daily_bars 覆盖全部 7 月日期（含 07-09..07-24），
  但只有 **72 个 600xxx code**
- 正式全市场 run：359774eea...（started 2026-08-01 10:49，all_main_board=true，
  COMPLETED 12:18）——bootstrap 的 `_bootstrap_impl` 用
  `globs[provider] = directory / f"{run_id}-*.parquet"` 只读 359774eea 文件，
  **50ed7fb2 数据被 run_id 隔离，未进入 359774eea 的 reconciliation 输入**

### 5c. 机制链

```
TUSHARE 全市场批次（359774eea）在 07-09..07-24 无行（fetch 窗口缺口）
  -> reconciliation 输入中 TUSHARE 该窗口为空
  -> CONFIRMED 需要 TUSHARE+AKSHARE 双源一致（policy phase-2c2a-r1）
  -> 12 天全部落入 PROVISIONAL（PARTIAL_CROSS_VALIDATION，仅 AK+BS）
  -> canonical CONFIRMED_N = 0
  -> generator-visible CONFIRMED 时间轴缺 12 个 session
  -> T0 registry / transition result 在该窗口失去数据基础
补充批次 50ed7fb2（有这些日期、仅 72 个 600xxx）
  -> bootstrap run_id 隔离，未并入正式全市场 run
  -> 无法补救 CONFIRMED
```

- WHAT_CHANGED_AT_2026-07-09：TUSHARE 全市场日线 fetch 在 07-09 起断档
  （359774eea 批次 0030 part 止于 07-08，0032 从 07-28 起）
- WHAT_RECOVERED_AT_2026-07-27：TUSHARE 全市场日线在 07-27 恢复
  （0030 part 含 07-27）

## 6. IMPACT CLASS

- **A_PROVIDER_CODE_COVERAGE（主）**：TUSHARE 全市场 code×date 覆盖在
  07-09..07-24 = 0（code 覆盖从 5518 跌到 70，再回到 5523）
- **F_SOURCE_BATCH_BOUNDARY（辅）**：50ed7fb2 补充批次（含缺口日期）因
  bootstrap run_id 隔离未进入正式 reconciliation 输入
- 排除：B（字段 diff=0）、C（三源 schema 一致，含 preclose 列）、
  D（preclose 无冲突；无 CA 证据）、E（policy 判定路径稳定，07-08/07-27 正常）、
  G（无其他机制证据）
- **ROOT_CAUSE_STATUS = PARTIALLY_PROVEN**：机制链已完全证明（TUSHARE 输入缺失
  → CONFIRMED 归零）；但 TUSHARE fetch 为什么缺这 12 天（provider API 间歇失败 /
  限流 / fetch 日历窗口）本地无 fetch 日志证据 → ROOT_CAUSE_LEVEL_2 = UNKNOWN

## 7. IMPACT SUMMARY

- 07-09..07-24 的 12 个 session 在 generator-visible CONFIRMED 时间轴中缺失
- T0 registry（22,393）与 transition result 在这 12 天无数据基础 → 均 INVALIDATED
- 175 个 CODE_LEVEL_SHORTFALL（如 06-26 anchor）由该缺口直接导致
- 07-08 与 07-27 的 CONFIRMED 正常 → 缺口边界清晰（07-09 起、07-27 恢复）

## 8. SAFE REPAIR DIRECTION（本轮禁止执行）

1. 重新 fetch TUSHARE 全市场 07-09..07-24 日线（或从 50ed7fb2 等已有源验证恢复）
2. 以新 run_id 重新执行 reconciliation（policy phase-2c2a-r1）→ 重建 canonical snapshot
3. 数据修复并 SHA 更新后：重建 T0 registry → 重跑 transition result
4. 若采用 50ed7fb2 数据：必须先证明其 72 个 code 的字段与 AKSHARE 一致
   （本报告 §3 已证明 07-09/15/24 一致），并完成 run 合并 accounting

```
DATA_REPAIR_REQUIRED        = YES
T0_REBUILD_AUTHORIZED       = NO（本轮）
TRANSITION_RERUN_AUTHORIZED = NO（本轮）
```

## 9. DECISION

- JULY_SESSION_COVERAGE_STATUS = BLOCKED（12/12 gap 日期 CONFIRMED_N=0）
- T0_REGISTRY_REBUILD_REQUIRED = YES（修复后）
- TRANSITION_RESULT_RERUN_REQUIRED = YES（修复后）
- 本轮禁止：canonical rewrite / snapshot rebuild / reconciliation rerun /
  T0 registry rebuild / transition rerun / strategy / production / forward / TradePlan
