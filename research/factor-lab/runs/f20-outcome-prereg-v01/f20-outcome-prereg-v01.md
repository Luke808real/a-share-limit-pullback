# F20 OUTCOME VALIDATION PREREGISTRATION V01 — 预注册统计设计

状态：**PREREGISTERED / NOT RUN**（本文件冻结统计设计；正式验证未运行，未读取任何 outcome 数据）

日期：2026-08-16
分支：`research/f20-outcome-prereg-v01`
BASE_HEAD：0f068d4（= ff4ea77 算法修复 + 审计后测试/文档补充；F20 contract 源码语义定型于 ff4ea77，0f068d4 未改动 factor_lab 源码）

---

## 1. FACTOR AUTHORITY

- F20 authority：`factor_lab.b2_volume_vs_20d_mean(bars, anchor_date, b2_date) -> Decimal | None`
- Contract 源码 HEAD：`ff4ea77a80c2144fda181b6e412a795b6c1952d9`（F20 CONTRACT = FROZEN / CLOSED，Sol audit PASS）
- 只允许 **PRE20_N == 20** 的 defined F20 进入 primary population。
- undefined F20（PRE20_N < 20 或窗口均量为 0 → None）**单独 accounting**，不得塞进低 F20 组（沿用 F18 审计确立的 undefined-isolation 纪律）。

## 2. PRIMARY HYPOTHESIS — H5A

预注册方向：**更高的 F20 应与更高 SECOND_LAUNCH 成功概率相关**。

- 不预注册任何人为倍数阈值（不设 1.5x / 2x / 3x / top decile 等 cut）。
- F20 作为连续因子直接测试。

## 3. PRIMARY TEST — CONTINUOUS（strict outcome）

以 F20 连续值直接测试：

- strict outcome 编码：`WIN_S1 = 1`，`LOSS_INVALID = 0`
- `CANCEL_GAP_INVALID` **不进入** strict binary denominator（仅会计数）
- 统计量：**Spearman rank correlation（rho）between F20 and strict outcome**
- 报告：`rho`、`N`、`direction`

Primary gate（strict）：`rho_strict > 0` → strict direction positive；`rho_strict <= 0` → strict direction failed。

## 4. SECOND PRIMARY TEST — R-defined population

- 在 R-defined population（WIN_S1 + LOSS_INVALID）上：`Y = 1 if R > 0 else 0`
- 计算 `Spearman(F20, Y)`，报告 `rho`、`N`、`direction`

**Primary H5A verdict 规则**（唯一 gate）：

```
rho_strict > 0 AND rho_R_positive > 0  →  SUPPORTED_DIRECTIONALLY
否则                                    →  REJECT
```

- SUPPORTED_DIRECTIONALLY ≠ VALIDATED ≠ PROMOTED
- 不允许替换/增补 metric 来改变 verdict（verdict gate 预注册后不变）

## 5. DESCRIPTIVE BUCKETS（仅描述）

- 只允许固定分位数描述：**Q1 / Q2 / Q3 / Q4**（quartile boundaries 仅由 F20 自身分布产生，禁止 outcome-conditioned 分位）
- 每 quartile 输出：`N`、`strict_win_rate`、`P(R>0)`、`mean_R`、`median_R`
- quartile 仅为 descriptive，**不得作为 threshold rule**

## 6. ROBUSTNESS（固定输出）

F20 分布分位（defined population）：`p10, p25, p50, p75, p90, p95, p99, max`

R 尾部：沿用 H4B / F18 tail caveat —— `mean_R` 受极端右尾影响，**不作为 verdict gate**；R 相关指标只在 R-defined 子集上报告。

固定 composition strata（只报告各层连续 rho 方向，不改变 primary verdict）：

- stage：`B1_READY` / `B2_READY` / `B2_CONFIRMED`
- timing：`T1-2` / `T3` / `T4-5` / `T6-10`

**SMALL_CELL policy**：任一层 `N < 20` 标记 `SMALL_CELL`，该层不做强解释、不计入方向汇总。

## 7. NO THRESHOLD MINING（冻结禁令）

明确写入：**不得在看到 outcome 后**验证以下任何 cut 或新 cut：

- `F20 >= 1.2` / `>= 1.5` / `>= 2` / `>= 3`
- top decile
- 任何 outcome-aware 的分位/区间

若发现有趣区间：只能记 `NEW_HYPOTHESIS`，留给 future / new sample 验证（不得在当前 frozen sample 上继续挖）。

## 8. 预注册纪律（与 F18 对齐）

- `OUTCOME_AWARE_CONTRACT_CHANGE = False`（合同已冻结，不再改）
- `THRESHOLD_SEARCH = False`
- `NEW_HYPOTHESES = []`（正式报告时如实填写，不得为空表示）
- undefined F20 只做 accounting，不进入 primary population（F18 审计教训）

## 9. OUTPUT / VERIFY / 提交约束

- 正式验证脚本与报告将在**后续独立任务**中实现（本任务仅冻结设计）
- 正式验证运行前必须：SHA 门禁（frozen episodes / daily bars）、authoritative main 无 DataFrame bypass、accounting invariants fail closed（沿用 F18 validation hardening 标准）
- 禁止 full-market；禁止 PR / merge / force
- 正式验证不得读取 outcome 的 F20 分布 / outcome-conditioned 统计（本任务已遵守）

---

*本文件为预注册设计，不含任何 outcome 结果。验证未运行。*
