# FACTOR LAB PHASE SYNTHESIS V01 — 阶段性综合决策

日期：2026-08-16
分支：`research/factor-lab-phase-synthesis-v01`
性质：研究综合决策（不实现、不跑验证、不改任何 factor verdict）

---

## 1. 已收口因子清单（verdict 汇总）

| Factor | 名称 | Verdict | 出处 |
| --- | --- | --- | --- |
| F11 | pullback_trough_index（回调见底天数） | **REJECT** | 因子验证链 |
| F14 | pullback_min_volume_ratio（回调缩量比） | **OBSERVE_ONLY** | 因子验证链 |
| H4A/H4B | MA10 触及/收回、MA10 reclaim | **REJECT** | H4 系列验证 |
| E03 | 破位后快速收回（j−i<=3） | **OBSERVATION**（非正式 verdict） | H4 事件研究 |
| F18 | support_confluence（支撑共振深度） | **REJECT**（H4C，Δswr 修正后为负；深度表无单调） | f18-support-confluence-validation-v01 |
| F23 | pullback_down_volume_count（放量下跌计数） | **REJECT** | 因子验证链 |
| F19 | B2 放量倍数（相对回调均量） | **REJECT**（OBSERVE_ONLY 弱 → 事件频率层 H9 REJECT） | ttl-h5h6 / h9-v01 |
| F20 | B2 放量倍数（相对前 20 日均量） | **REJECT / CLOSED**（双 rho 均负：-0.1127/-0.1182，N=7765） | f20-outcome-validation-v01（FINAL PASS，e736c1b） |
| TTL/F12 | 至 B2 事件天数 / TTL | 结构性信息（B2 后衰减观察） | ttl-h5h6-v01 |
| B2 stage/timing | B2_READY/B2_CONFIRMED × T1-2..T6-10 | 观察价值（composition，不改 global verdict） | f20-outcome-validation-v01 |

统计：**CLOSED_FACTOR_N = 8**；**REJECT_N = 6**（F11, H4A/H4B, F18, F23, F19, F20）；
**OBSERVE_ONLY_N = 1**（F14）；**OBSERVATION_N = 1**（E03）。

## 2. 模式总结

### 2.1 静态结构（形态/支撑）——连续失败
"形态越漂亮 / 支撑越多"的正向单因子主效应在 frozen sample 上连续失败：
F11（见底天数）、F18（支撑共振深度，深层反而更差：F18=0 层 strict_win_rate 0.312
最优，F18=3 层 mean_R −0.279）、F23（放量下跌）均 REJECT；F14 仅 OBSERVE_ONLY；
E03 仅 OBSERVATION。**结论：不能用"形态漂亮度"作全局 scoring。**

### 2.2 放量类——明确失败
F19/F20/H9（三倍量事件频率）全部 REJECT：B2 日成交量相对均量越大，
第二波成功概率越高——**全局连续主效应不成立**（F20 双 rho 均负）。F20 的
B2_READY 子层正方向（+0.056）仅保留 OBSERVATION，按 prereg 不得同样本 rescue。

### 2.3 时间/状态结构——有信息
TTL（B2 后衰减）与 B2 stage/timing composition 呈现结构性信息：
B2_READY 层两 rho 均正（+0.056）、B2_CONFIRMED 层为负（-0.015/-0.093）；
timing strict rho 在 T3/T4-5/T6-10 为正但 R-positive 全非正。
global -0.11 含明显 stage/timing composition 成分。

## 3. 方向判断

研究重心应从"正向形态确认"转向 **启动后的失败结构** 与 **时间/状态机阶段**：
- 简单"越漂亮越强"的单因子循环收益递减（连续 6 REJECT）
- 真正的问题：**区分真实 SECOND_LAUNCH 与假启动/失败启动**
- 时间位置（TTL/stage/timing）与失败结构（B2 后破位/出货形态）信息增益最大

## 4. 决策

### NEXT_FACTOR = F22（巨量长上影）

### WHY_NOW
1. **SOL 候选范围收敛**：本次决策在 F21/F22 之间；**F21（B2 次日跌回平台）已由
   ttl-h5h6-v01 REJECT**——"次日收破支撑"与 LOSS_INVALID/CANCEL_GAP 失效定义
   近义，属循环定义，**不是独立预测因子**（仅可作健全性检查）→ 排除。
2. **F22 是失败结构因子**：上影线/实体 大 + 5 日均量 >= 1.5 倍 = 出货/假突破的
   即时形态证据（B2 确认处的负面信号），直接服务"真确认 vs 假突破"判别——
   与静态"漂亮形态"正向确认（连续失败的模式）方向相反。
3. **信息增益定位**：F20 已回答"放量不代表成功"；F22 回答"B2 处是否出现
   假突破/出货证据"——这是判别目标（真确认 vs 假突破）缺失的一环。
4. **阈值预注册**：F22 定义中的固定阈值（上影/实体比、1.5x 5日均量）须在
   预注册中冻结，不得 outcome-aware 调整（遵守 F20 审计确立的纪律）。
5. **实现缺口**：factor_lab 无 F22 实现（CATALOG 状态 GAP）——下阶段：
   实现 + contract 冻结 + 预注册 + outcome validation（完整流程）。

### 边界声明
- 本决策不改变任何已收口 verdict（F20 = REJECT / CLOSED 不变）。
- F20 的 B2_READY 层观察仅作 OBSERVATION / NEW_HYPOTHESIS，不得同样本 rescue。
- 禁止 threshold mining（1.2/1.5/2/3x、top decile、outcome-aware cut）。
- NEW_VALIDATION_RUN = NO（本任务只做综合决策）。

## 5. 遗留缺口（FAILURE_STRUCTURE_GAPS）

- F21 循环定义不可用 → B2 后"平台失守"无独立验证路径（仅健全性检查）
- F22 未实现（GAP）→ 假突破即时形态无因子
- B2 后失败路径（破 anchor / 快速回撤 / 上影出货组合）无独立因子
- TTL 真口径 setup 级生存曲线（ttl-h5h6 报告"下一步"）未做

---

*本文件为阶段性综合决策，不含 outcome 验证结果。所有 verdict 引用以各自
validation run 的 FINAL 记录为准。*
