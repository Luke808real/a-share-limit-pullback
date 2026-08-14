# H10 研究报告 v01（2026-08-14，描述性，无调参；审计修订版）

审计修订（ChatGPT research-QC）：v01 初稿把「ge80 vs 全体」当作因子效应。
本版改为同定义样本对照：score 已定义样本内 >=80 与 <80 互斥分层，missing
单列；总体 win share 仅作背景。新增 setup_stage 最小分层。无阈值搜索，
状态不升级。

## 总体背景（仅背景，不是因子效应）

resolved n = 9,625，win share = 24.19%。

## 对照口径（>=80 vs <80，仅 score 已定义样本）

| score | defined_n | missing_n | ge80_n | ge80_win | lt80_n | lt80_win | delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| setup_quality | 9,625 | 0 | 1,227 | 28.28% | 8,398 | 23.59% | **+4.69pp** |
| entry_quality | 9,625 | 0 | 556 | 10.07% | 9,069 | 25.05% | **−14.98pp** |

## 时点分层（setup_quality：ge80 vs lt80）

| bucket | all_n | all_win | ge80_n | ge80_win | lt80_n | lt80_win | delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1-2 | 6,819 | 10.22% | 898 | 14.59% | 5,921 | 9.56% | **+5.03pp** |
| 3 | 1,249 | 45.56% | 133 | 61.65% | 1,116 | 43.64% | **+18.01pp** |
| 4-5 | 922 | 65.51% | 119 | 67.23% | 803 | 65.26% | +1.97pp |
| 6-10 | 635 | 72.13% | 77 | 70.13% | 558 | 72.40% | −2.27pp |

entry_quality 时点桶：1-2 桶 delta −1.26pp；3 桶 −15.41pp（ge80 n=23）；
4-5 与 6-10 桶 ge80 n<20 → null，不解释。

## setup_stage 分层（setup_quality：ge80 vs lt80）

| stage | all_n | all_win | defined_n | ge80_n | ge80_win | lt80_n | lt80_win | delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1_READY | 6,411 | 4.60% | 6,411 | 779 | 7.70% | 5,632 | 4.17% | +3.53pp |
| B2_READY | 1,643 | 51.31% | 1,643 | 210 | 52.86% | 1,433 | 51.08% | +1.78pp |
| B2_CONFIRMED | 1,571 | 75.75% | 1,571 | 238 | 73.95% | 1,333 | 76.07% | −2.12pp |

## 结论（OBSERVE_ONLY，不升级）

- setup_quality>=80 正效应集中于早期窗口（1-2 桶 +5.03pp、3 桶
  +18.01pp）；后期（4-5、6-10）不保持正向。
- 后期高基线（all_win 65%→72%）可能来自 ceiling effect，也可能存在
  survival/conditioning selection；本报告不断言具体原因。
- entry_quality 的「赔率型」解释仅为 HYPOTHESIS，待独立 R/E[R] 复算。

## Provenance

- episodes SHA256: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093
- snapshot: snap-2026-07-31-b5f84004de8a（frozen，输入未变）
- script SHA256: 52d61522f888876318dec12f4f0a24275a0b0a3cce97859d214aefceabed5246
- output JSON SHA256: e91b55c39cc43ebc8f157d725ec39ae8350383703191daa0b7bf480ea8a0b587
- conclusion status: OBSERVE_ONLY
