# TTL T0 TRANSITION-TIME PREREGISTRATION V01 — 预注册统计设计

- 状态：**PREREG_FROZEN**（只冻结统计设计；**NO result run / NO curve /
  NO TTL cutoff**）
- 日期：2026-08-16
- 分支：`research/ttl-t0-transition-prereg-v01`
- BASE_HEAD：7c501901cef8a520bfd6dd5b54b5f36d4b88ac42

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

## 1. ESTIMAND（冻结；不是 classical survival）

**不预注册 Kaplan-Meier / hazard。**

PRIMARY ESTIMAND：

```
F_STAGE(k) = 
  在"至少具有 k 个 generator-visible CONFIRMED 后续 trading session"的 T0 中，
  首次达到 STAGE 的 session distance <= k 的 setup 比例
```

分别对：
- STAGE_B1 = B1_READY
- STAGE_B2_READY = B2_READY
- STAGE_B2_CONFIRMED = B2_CONFIRMED

```
numerator_stage(k)   = first_event_time(stage) <= k
denominator(k)       = T0 后截至 OBSERVATION_END 至少存在 k 个
                       CONFIRMED per-code sessions 的 setup 数
```

即 **matured-cohort cumulative transition incidence**（成熟队列累计转换发生率），
不是 classical survival probability。

## 2. TIME CONTRACT（冻结）

- TIME_ORIGIN = T0 anchor_date
- TIME_SCALE = generator-visible CONFIRMED per-code trading sessions
- EVENT_TIME = index(signal_date) − index(anchor_date)
  （在 CONFIRMED per-code 序列上）
- 允许使用 frozen `days_since_anchor` 作为等价实现：
  timebase lineage 已验证 31,422/31,422 match、MAX_ABS_DIFF = 0
  （见 research/ttl-setup-survival-contract-v01，lineage CLOSED）

## 3. EVENT EXTRACTION（冻结）

每个 setup / stage 只允许一个 first event：

- FIRST_B1_READY
- FIRST_B2_READY
- FIRST_B2_CONFIRMED

必须满足：`B1_READY <= B2_READY <= B2_CONFIRMED`。

- 若 same-(setup,stage) duplicate → **FAIL CLOSED**（禁止 silent FIRST；
  现有 frozen data duplicate = 0 是 authority fact，但 runner 仍须 fail closed）
- **B1_PREP：NOT a primary state-transition event**，不得混入 B1_READY。

## 4. NO-EVENT SEMANTICS（冻结）

完整 registry 中没有对应 stage event 的 T0：

- event = NOT OBSERVED
- 只要该 setup 对 k 已具备足够 follow-up sessions，就进入 denominator(k)
  并作为 event_by_k = false
- 不得把 INVALID / NO_FILL / LOSS / CANCEL 当 event
- 不得因为不知道 invalidation date 而伪造 right censor

## 5. ADMINISTRATIVE MATURITY（冻结；唯一允许的 observation-boundary exclusion）

对每个 T0 计算：

```
FOLLOWUP_SESSIONS_AVAILABLE =
  CONFIRMED per-code sessions after anchor_date through 2026-07-31
```

对某 k：

```
FOLLOWUP_SESSIONS_AVAILABLE < k
  → exclude from denominator(k)
  → ADMINISTRATIVE_NOT_MATURE
```

- 这是唯一允许的 observation-boundary exclusion。
- **禁止**用 outcome rows 的 `future_sessions_available` 替代 registry-level
  follow-up（never-signal setups 没有 episode row）。

## 6. k AXIS（冻结）

- 不选择 outcome-driven TTL cutoff。
- 预注册报告轴：k = 1, 2, 3, ...，一直报告到 denominator(k) > 0。
- **必须同时输出 denominator(k)**。
- 策略配置中的 B1 `days_after_anchor = 1..7`、optimal = 2..5 只允许作为
  预先存在的 strategy reference bands，不是研究结果，也不能据此把 T+5/T+7
  宣布成 validated TTL。
- 不得根据本次数据再选"最好看的 k"。

## 7. FUTURE RESULT OUTPUT CONTRACT（本轮只冻结字段，不计算）

未来结果至少包括：

```
TOTAL_T0_N
for each k:
  MATURED_N(k)
  B1_READY_BY_K_N
  B1_READY_BY_K_RATE
  B2_READY_BY_K_N
  B2_READY_BY_K_RATE
  B2_CONFIRMED_BY_K_N
  B2_CONFIRMED_BY_K_RATE
```

另输出 first-event timing distribution：

```
EVENT_TIME
EVENT_N
```

这是 structural timing distribution，不是 outcome success rate。

## 8. EXPLICITLY FORBIDDEN INTERPRETATION（冻结）

必须写明：

```
F_STAGE(k) != Kaplan-Meier survival
F_STAGE(k) != probability setup remains alive
F_STAGE(k) != trading win rate
F_STAGE(k) != P(profit | B2)
F_STAGE(k) != validated TTL cutoff
```

不得使用 WIN_S1 / LOSS_INVALID / CANCEL_GAP_INVALID / R multiple /
MFE / MAE 做任何分组或 threshold selection。

## 9. CLASSICAL SURVIVAL STATUS（冻结）

```
CLASSICAL_KM_HAZARD_READY = NO
MATURED_CUMULATIVE_TRANSITION_READY = YES
```

- CLASSICAL_KM_HAZARD_READY = NO 的原因：没有完整的逐日 setup exit lineage
  （INVALID / superseded / expiry 的每日状态未记录）。
- 这两个概念不得混为一谈。

## 10. OUTPUT（本轮）

- 只创建：
  `research/factor-lab/runs/ttl-t0-transition-prereg-v01/ttl-t0-transition-prereg-v01.md`
- 不得创建 result CSV / JSON / plot。
- 状态只能 PREREG_FROZEN 或 BLOCKED。
- 如果发现任何 denominator / event / time semantics 无法按 authority 实现
  → BLOCKED，不得自行改 estimand。

## 11. FORBIDDEN（冻结）

- NO transition-rate computation
- NO survival result / Kaplan-Meier / hazard
- NO outcome analysis / WIN/LOSS/CANCEL comparison
- NO P(success | T+k)
- NO TTL cutoff / T+5/T+6 promotion
- NO factor threshold mining / F22 rescue / ML
- NO strategy / production / forward / TradePlan changes
- NO full-market strategy replay
- NO frozen artifact mutation

## 12. VERIFICATION（本轮已完成 + runner 必须复验）

- registry authority exists：是（research/factor-lab/runs/t0-registry-v01/t0-registry-v01.csv）
- REGISTRY_SHA256 exact：130a5698...441c ✓
- episodes authority exact：66d5943f...093 ✓
- daily authority exact：e7243dee...514 ✓
- TOTAL_T0_SETUP_N = 22393 ✓
- registry duplicate = 0 ✓
- episode setup not in registry = 0 ✓
- git diff --check（本轮）

---

*本文件为预注册设计，不含任何 transition-time 结果。正式 runner 与结果将在
后续独立任务中实现（SHA 门禁 + fail-closed + matured-cohort 合同）。*
