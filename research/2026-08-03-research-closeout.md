# TODAY RESEARCH CLOSEOUT — 2026-08-03（研究收口，非 production）

RESEARCH_STATUS = PAUSED

PRODUCTION_CHANGED = false

STRATEGY_CHANGED = false

FORWARD_SAMPLE_CHANGED = false

## 最终结论

1. **Mechanical B1 exact-entry optimization PAUSED**（不再继续精确成交价研究）。
2. 当前 B1 / confirmation / entry geometry 均无 proven positive trading edge
   （10bp conservative 全负或 ~0，D/V 无正段，20bp 转负）。
3. Old buy-zone 存在 **adverse-selection evidence**（FILLED 组结构成功率 ~10%，
   高开越区未回组 64.9%；FILLED 只覆盖 6.5% 的 actionable 窗口），
   **不再作为必须触及的人工买入语义**。
4. **B_ACTIONABLE_WINDOW 比 exact entry price 更符合当前人工实盘目标**
   （未来 1-3 日是否进入“值得盯盘窗口”，而非精确买价）。
5. **GEOMETRY_ONLY_EXPLAINS_MOST**：`close_vs_s1 + dist_20d_high` 是当前最稳定的
   radar ranking 信息（top10 actionable lift 1.64，D/V/年份稳定）。
6. QUALITY_ONLY 有弱信息（lift 1.27），但 **COMBINED 不优于 GEOMETRY**（66.9% < 73.4%）。
7. B_ACTIONABLE score 只作为 **RESEARCH_OVERLAY**，不 promotion。
8. **ENTRY_CANDIDATE / FILLED 不再作为人工盯盘的唯一 gate**。
9. unmapped signals（缺 frozen levels）不得静默删除：标 `DATA_LIMITED / MANUAL_REVIEW`。
10. **不做 position-sizing promotion**（历史无 proven edge）。

## 本轮研究产物（均 research-only）

- `research/b_actionable_window_v01.py` + `data/tmp/b-actionable-window-v01/metrics.json`
- `research/b_actionable_state_v01.py` + `data/tmp/b-actionable-state-v01/metrics.json`
- `research/b_entry_geometry_v01.py` + `data/tmp/b-entry-geometry-v01/metrics.json`
- `research/b1_execution_funnel_audit_v01.py` + `data/tmp/b1-execution-funnel-audit-v01/metrics.json`

输入固定：corrected episodes `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093`；
snapshot `snap-2026-07-31-b5f84004de8a`；`evaluate_strategy_calls=0`。
