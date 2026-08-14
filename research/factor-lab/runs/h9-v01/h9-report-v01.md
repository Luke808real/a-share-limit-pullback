# H9 研究报告 v01（2026-08-14，描述性，无调参；审计修订版）

审计修订（ChatGPT research-QC）：v01 初稿用 broad except 把数据错误
静默转为 undefined。本版 fail-closed：anchor/B2 bar 缺失、重复日期、
多 code 等数据错误直接抛错；只有因子自身的 None 返回算 undefined。
语义表述同时收窄（见结论）。

## 口径

- B2 事件日 := signal_date（B2 阶段 episode，冻结语义）
- F19 := vol(B2 日) / mean(vol, T+1..B2 前一日)；结构条件 := 收盘≥support_high
  且收盘≥b2_trigger_price（B2 日 PIT 可测）
- 双口径指标：win share + mean R（成交子集）

## 结果（fail-closed 重跑，与 386966d 版本完全一致）

- population：B2 阶段 resolved n = 3,214；undefined_f19 = 0；missing_b2_bar = 0
- F19 分布：p50=0.85 / p75=1.14 / p90=1.36 / p95=1.52 / p99=1.73 / max=3.34
- **F19≥3 仅 1 例（0.03%）**，落入 triple_struct 且为 LOSS_INVALID；
  triple_only n=0
- 对照组（F19<3）：win share 63.27%，mean R −0.011（n_with_r=2,897）

## 结论

- **H9 = REJECT (event-frequency level)**：三倍量事件在冻结 B2 语义下
  几乎不存在（1/3,214），「单独 vs 组合」的区分度检验因事件为空集而
  无法进行。
- 在 F19 口径下，相对 T+1..B2 前一日回调均量，B2 日成交量通常未明显
  扩张（p50=0.85，p90 才 1.36）；本结果不覆盖 F20、盘中量能或换手。
- 不得解释成「成交量对 B2 无用」——本结论只说明该口径下该事件罕见。

## Forward 假设（预注册，不在当前样本验证）

- days_since_anchor>=3 + F19>=2 = NEW / PRE-REGISTERED FORWARD HYPOTHESIS。
  这是新的阈值假设；禁止在当前 frozen 样本重新验证，仅限 forward 复查。

## Provenance

- episodes SHA256: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093
- snapshot: snap-2026-07-31-b5f84004de8a（frozen，输入未变）
- script SHA256: 80ef9df982698976b3d8aebe83a5c2d904cd3c4fbdcf147d7e40d5822703d38a
- output JSON SHA256: 53d2b0f017240a11584f4c062852cf2c6b77a28173e68c23c3674c627561ff47
- conclusion status: REJECT (event-frequency level)
