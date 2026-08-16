# TTL T0 TRANSITION-TIME PREREGISTRATION V01 — 预注册统计设计（fixed-cohort v01.1）

- 状态：**PREREG_FROZEN**（fixed-cohort closeout 修订版；只冻结统计设计；
  **NO result run / NO curve / NO TTL cutoff**）
- 日期：2026-08-16
- 分支：`research/ttl-t0-transition-prereg-v01`（fix/ttl-t0-transition-prereg-fixed-cohort-v01 修订后）
- BASE_HEAD：dcfbf027cd1b6301d27afac75eee0f9957c5393a

---

## 0. INPUT AUTHORITY（冻结，任何 mismatch → FAIL CLOSED）

| 输入 | 路径 | SHA256 / 值 |
| --- | --- | --- |
| T0 registry | research/factor-lab/runs/t0-registry-v01/t0-registry-v01.csv | 130a56986307fed3e382dd65f4a4f9a4a9df61a7387a7b7a15b049cf72d9441c |
| TOTAL_T0_SETUP_N | — | 22393 |
| episodes | data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet | 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093 |
| daily | data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet | e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514 |
| OBSERVATION_END | — | 2026-07-31 |

结构性验证（已在本 prereg 前完成）：
- TOTAL_T0_SETUP_N = 22393（registry 行数）
- registry duplicate setup_id = 0
- code-anchor conflict = 0
- episode setup not in registry = 0（全部 17,691 个 observed-signal setup 都在 registry 中）

## 1. K_MAX AUTHORITY（冻结；非经验最优 TTL）

```
K_MAX = 9
```

依据（策略已有语义，非结果驱动）：
- frozen config：`anchor.lookback_trade_days = 10`
  （历史 authority 315fbe0d 与当前 HEAD 的 config/strategy.yaml 均为 10）
- frozen `detect_anchor()` 只在最近 `lookback_trade_days`（10）根
  generator-visible bars 中寻找 anchor
- 因此一个 T0 的原始 anchor 在 generator-visible per-code session 时间轴上
  最迟可见到 **T+9**：T+10 时 anchor 已退出 10-bar lookback

**K_MAX=9 是 frozen setup observability boundary，不是 validated trading TTL。**

## 2. PRIMARY ESTIMAND（冻结；固定成熟 cohort；不是 classical survival）

**不预注册 Kaplan-Meier / hazard。** 删除动态 denominator 定义
（denominator(k) = followup >= k 会使相邻 k 的 cohort 成员不同）。

定义：

```
FULL_WINDOW_MATURED =
  FOLLOWUP_SESSIONS_AVAILABLE >= 9

FIXED_MATURED_N = count(FULL_WINDOW_MATURED)
```

Primary（每个 k 使用**同一个** denominator）：

```
F_STAGE(k) =
  count( FULL_WINDOW_MATURED AND first_event_time(stage) <= k )
  / FIXED_MATURED_N
  for k = 1..9
```

分别对：
- STAGE_B1 = B1_READY
- STAGE_B2_READY = B2_READY
- STAGE_B2_CONFIRMED = B2_CONFIRMED

性质：固定 cohort 保证

```
F_STAGE(1) <= F_STAGE(2) <= ... <= F_STAGE(9)
```

且 `F(k) − F(k−1)` 可干净解释为固定 cohort 中**恰好在 T+k 首次进入该 stage**
的比例。

术语：**fixed-matured-cohort cumulative transition rate**。

## 3. TIME CONTRACT（冻结）

- TIME_ORIGIN = T0 anchor_date
- TIME_SCALE = generator-visible CONFIRMED per-code trading sessions
- EVENT_TIME = index(signal_date) − index(anchor_date)
  （在 CONFIRMED per-code 序列上）
- 允许使用 frozen `days_since_anchor` 作为等价实现：
  timebase lineage 已验证 31,422/31,422 match、MAX_ABS_DIFF = 0
  （见 research/ttl-setup-survival-contract-v01，lineage CLOSED）

## 4. EVENT SOURCE CONTRACT（冻结）

```
EVENT_SELECTOR_COLUMN = execution_label
EVENT_DATE_COLUMN     = signal_date
EVENT_TIME_COLUMN     = days_since_anchor
```

Primary labels：B1_READY / B2_READY / B2_CONFIRMED。

一致性要求：对 B1_READY / B2_READY / B2_CONFIRMED 这些 rows，必须满足

```
execution_label == setup_stage
```

否则 **FAIL CLOSED**（frozen 数据理论上一致，但 runner 不得留下选择空间）。

**B1_PREP：NOT a primary state-transition event**，不得混入 B1_READY。

## 5. STAGE COMPLETENESS / ORDER（冻结，fail closed）

每个 setup 只允许一个 first event：

- FIRST_B1_READY
- FIRST_B2_READY
- FIRST_B2_CONFIRMED

必须 fail closed：

```
B2_READY exists AND B1_READY missing            -> FAIL CLOSED
B2_CONFIRMED exists AND B2_READY missing       -> FAIL CLOSED
B2_CONFIRMED exists AND B1_READY missing       -> FAIL CLOSED
```

存在时必须满足：

```
T_B1_READY <= T_B2_READY <= T_B2_CONFIRMED
```

same-(setup,stage) duplicate → **FAIL CLOSED**（禁止 silent FIRST；
现有 frozen data duplicate = 0 是 authority fact，但 runner 仍须 fail closed）。

## 6. NO-EVENT SEMANTICS（冻结）

完整 registry 中没有对应 stage event 的 T0：

- event = NOT OBSERVED
- 只要该 setup 属于 FULL_WINDOW_MATURED，就进入 FIXED_MATURED_N 并作为
  event_by_k = false（对全部 k=1..9）
- 不得把 INVALID / NO_FILL / LOSS / CANCEL 当 event
- 不得因为不知道 invalidation date 而伪造 right censor

## 7. ADMINISTRATIVE MATURITY（冻结；唯一允许的 observation-boundary exclusion）

对每个 T0 计算：

```
FOLLOWUP_SESSIONS_AVAILABLE =
  CONFIRMED per-code sessions after anchor_date through 2026-07-31
```

```
FOLLOWUP_SESSIONS_AVAILABLE < 9
  -> ADMINISTRATIVE_NOT_FULLY_MATURE
  -> exclude from PRIMARY fixed cohort
```

未来输出合同必须包含（守恒 fail closed）：

```
TOTAL_T0_N = FIXED_MATURED_N + ADMINISTRATIVE_NOT_FULLY_MATURE_N
```

- 这是唯一允许的 observation-boundary exclusion。
- **禁止**用 outcome rows 的 `future_sessions_available` 替代 registry-level
  follow-up（never-signal setups 没有 episode row）。

## 8. FUTURE RESULT OUTPUT CONTRACT（本轮只冻结字段，不计算）

未来 runner 对每个 k = 1..9 输出：

```
FIXED_MATURED_N
B1_READY_BY_K_N
B1_READY_BY_K_RATE
B2_READY_BY_K_N
B2_READY_BY_K_RATE
B2_CONFIRMED_BY_K_N
B2_CONFIRMED_BY_K_RATE
```

**所有 rate 的 denominator 都必须是 FIXED_MATURED_N。**

另输出 exact first-event timing distribution：

```
EVENT_TIME = 1..9
EVENT_N
EVENT_RATE = EVENT_N / FIXED_MATURED_N
```

这是 structural timing distribution，不是 outcome success rate。

**MONOTONICITY GATE（fail closed）**：对每个 stage，F_STAGE(k) 必须
monotonic non-decreasing（k=1..9）；否则 FAIL CLOSED。

## 9. EXPLICITLY FORBIDDEN INTERPRETATION（冻结）

必须写明：

```
F_STAGE(k) != Kaplan-Meier survival
F_STAGE(k) != probability setup remains alive
F_STAGE(k) != trading win rate
F_STAGE(k) != P(profit | B2)
F_STAGE(k) != validated TTL cutoff
```

T+9 是 frozen setup observability boundary，不是 validated trading TTL。
不得使用 WIN_S1 / LOSS_INVALID / CANCEL_GAP_INVALID / R multiple /
MFE / MAE 做任何分组或 threshold selection。

## 10. CLASSICAL SURVIVAL STATUS（冻结）

```
CLASSICAL_KM_HAZARD_READY = NO
FIXED_COHORT_TRANSITION_READY = YES
```

- CLASSICAL_KM_HAZARD_READY = NO 的原因：没有完整的逐日 setup exit lineage
  （INVALID / superseded / expiry 的每日状态未记录）。
- 这两个概念不得混为一谈。

## 11. OUTPUT（本轮）

- 只修改：
  `research/factor-lab/runs/ttl-t0-transition-prereg-v01/ttl-t0-transition-prereg-v01.md`
- 不得创建 result CSV / JSON / plot。
- 状态只能 PREREG_FROZEN 或 BLOCKED。
- 如果发现任何 denominator / event / time semantics 无法按 authority 实现
  → BLOCKED，不得自行改 estimand。

## 12. FORBIDDEN（冻结）

- NO result run / transition-rate computation
- NO survival result / Kaplan-Meier / hazard
- NO outcome analysis / WIN/LOSS/CANCEL comparison
- NO P(success | T+k)
- NO TTL cutoff / T+5/T+6 promotion
- NO factor threshold mining / F22 rescue / ML
- NO strategy / production / forward / TradePlan changes
- NO full-market strategy replay
- NO frozen artifact mutation

## 13. VERIFICATION（本轮已完成 + runner 必须复验）

- registry authority exists：是（research/factor-lab/runs/t0-registry-v01/t0-registry-v01.csv）
- REGISTRY_SHA256 exact：130a5698...441c ✓
- episodes authority exact：66d5943f...093 ✓
- daily authority exact：e7243dee...514 ✓
- TOTAL_T0_SETUP_N = 22393 ✓
- registry duplicate = 0 ✓
- episode setup not in registry = 0 ✓
- K_MAX=9 authority：config/strategy.yaml `anchor.lookback_trade_days: 10`
  （315fbe0d 与 HEAD 一致）✓
- git diff --check（本轮）

---

*本文件为预注册设计，不含任何 transition-time 结果。正式 runner 与结果将在
后续独立任务中实现（SHA 门禁 + fail-closed + fixed matured cohort 合同）。*
