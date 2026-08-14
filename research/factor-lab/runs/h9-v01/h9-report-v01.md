# H9 研究报告 v01（2026-08-14，描述性，无调参）

输入：frozen corrected episodes（SHA 66d5943f...，B2 阶段 resolved 子集
n=3,214 = B2_READY 1,643 + B2_CONFIRMED 1,571）+ frozen snapshot
snap-2026-07-31-b5f84004de8a canonical bars。
脚本：research/factor-lab/h9_triple_volume_v01.py；
输出：research/factor-lab/runs/h9-v01/h9-v01.json。

假设（H9，P2）：三倍量（F19≥3）单独无区分度，仅与 B2 结构条件组合有增量。

## 口径

- B2 事件日 := signal_date（B2 阶段 episode，冻结语义）
- F19 := vol(B2 日) / mean(vol, T+1..B2 前一日)；结构条件 := 收盘≥support_high
  且收盘≥b2_trigger_price（B2 日 PIT 可测）
- 双口径指标：win share（胜率）+ mean R（成交子集赔率，呼应 H10 口径警示）

## 结果

**F19 分布（n=3,214，全部 B2 阶段 resolved）**：
p50=0.85 / p75=1.14 / p90=1.36 / p95=1.52 / p99=1.73 / max=3.34。

**三倍量事件频率：3,214 例中仅 1 例（0.03%）**；该例落入 triple_struct
且为 LOSS_INVALID。triple_only 组 n=0。

对照组（F19<3）：win share 63.3%，mean R −0.011（n_with_r=2,897）。

## 结论

- **H9 按 F19 口径 REJECT（事件频率层面）**：三倍量事件在冻结 B2 语义下
  几乎不存在，无法进行「单独 vs 组合」的区分度检验——不是区分度为零，
  而是事件本身为空集。
- 更值得注意的实证发现：**B2 日量能中位数仅为回调均量的 85%**（p90 才
  1.36 倍）。「B2 放量突破」的叙述与冻结引擎产出的历史 B2 事件不吻合——
  B2 确认靠的是结构与启动条件，量能扩张并不是普遍特征。
- 复核选项（不做阈值松动，不做同样本再验）：F20 口径（相对 B2 前 20 日
  均量）重测 H9；或对 days_since_anchor≥3 子样本重测 F19≥2。均属新假设，
  需 forward 样本。

## 对架构的启示

- 叙述性策略语言（“三倍量”）必须先做**事件频率普查**再设计假设检验，
  否则会在空事件上做统计；
- 冻结因子目录定义（F19/F20）与研究结论（“B2 量能通常不扩张”）应回写
  FACTOR_CATALOG，供 Owner 决定是否调整叙述与阈值。
