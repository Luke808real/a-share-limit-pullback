# H6 F23 Pullback Selling-Pressure — Study Report v01

研究问题：F23「回调期放量下跌」（T0 后可见交易日内 close(i)<close(i-1) 且
volume(i)>volume(i-1) 的交易日计数）是否为第二次启动失败的负向结构因子。

## 1. Input Provenance

| 项 | 值 |
| --- | --- |
| episodes | `data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106/corrected-b2-trigger-outcome/episodes.parquet` |
| episodes SHA256 | `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093` ✓（与任务 INPUT GATE 一致） |
| daily bars | `data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet` |
| daily bars SHA256 | `e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514` |
| snapshot id | `snap-2026-07-31-b5f84004de8a` |
| R 源 | episodes.r_multiple（Phase 2D.0 corrected outcome study，strict variant） |

## 2. F23 定义（PIT 纯函数）

`pullback_down_volume_count(bars, anchor_date, as_of)`：T0 之后、截至 as_of
（= signal_date）的可见交易日中，`close(i) < close(i-1)` 且
`volume(i) > volume(i-1)` 的天数；首个可见日的 i-1 为 T0 本身。
`F23_ANY = count >= 1`（仅作预注册分组，不搜索阈值）。
duplicate / multi-code / anchor 缺失 → ValueError（fail-closed）。

## 3. Sample Accounting

| 项 | 值 |
| --- | --- |
| resolved_n（WIN_S1 ∪ LOSS_INVALID ∪ CANCEL_GAP_INVALID） | 9,625（与 H10 SAMPLE_N 一致） |
| F23 defined | 9,625（100%，undefined = 0） |
| F23_ANY=true | 4,238 |
| F23_NONE | 5,387 |
| MIN_N（小样本置 null） | 20 |

## 4. Primary Comparison（F23_ANY=false vs true）

| 指标 | ANY=true (n=4,238) | NONE (n=5,387) | delta |
| --- | --- | --- | --- |
| WIN | 1,071 | 1,257 | — |
| LOSS | 2,451 | 3,078 | — |
| CANCEL_GAP_INVALID | 716 | 1,052 | — |
| win_share | 0.2527 | 0.2333 | **+0.0194** |
| strict_win_rate | 0.3041 | 0.2900 | **+0.0141** |
| mean_R | -0.1159 | -0.0126 | **-0.1033** |
| median_R | -1.0 | -1.0 | 0.0 |
| P(R>0) | 0.2462 | 0.2404 | — |
| P(R>=2) | 0.0440 | 0.0443 | — |

方向判断：假设为「F23_ANY → 更高失败率 / 更差收益」。win_share 与
strict_win_rate 方向与假设**相反**（ANY 更高）；mean_R 方向与假设一致
（ANY 显著更差）。主指标 win_share delta >= 0 → 按预注册规则 REJECT。

## 5. Confounding Strata（预注册分层）

### 5.1 setup_stage

| stage | any_n | none_n | win_share delta | mean_R delta |
| --- | --- | --- | --- | --- |
| B1_READY | 2,810 | 3,601 | +0.0055 | -0.1713 |
| B2_READY | 713 | 930 | +0.0401 | +0.0321 |
| B2_CONFIRMED | 715 | 856 | +0.0241 | -0.0064 |

stage 三层 win_share delta **全部为正**：负向关系在 stage 内不存在。

### 5.2 timing（days_since_anchor）

| timing | any_n | none_n | win_share delta | mean_R delta |
| --- | --- | --- | --- | --- |
| T+1~2 | 2,641 | 4,178 | -0.0395 | -0.2333 |
| T+3 | 743 | 506 | -0.1013 | +0.1400 |
| T+4~5 | 471 | 451 | -0.0241 | +0.1196 |
| T+6~10 | 383 | 252 | -0.1463 | -0.0187 |

timing 四层 win_share delta **全部为负**：负向关系仅在 timing 分层内出现。

### 5.3 结论

全局主对比 win_share 为正（0.0194），stage 分层为正、timing 分层为负 ——
**负向关系不是全局存在，且 stage/timing 分层方向互相矛盾**，说明主对比的
方向是构成（composition）驱动的；不存在「全局负向结构因子」的证据。
附带观察：F23_ANY 的 mean_R 全局 -0.1033、B1_READY 内 -0.1713、T+1~2 内
-0.2333 —— 放量下跌与右尾收益显著收缩相关（胜率略高但盈亏比恶化）。

## 6. R Distribution / Small-Cell Null

- 所有分组 n >= MIN_N=20，无小样本置 null 单元；解释性统计全部按
  MIN_N=20 门槛计算（未触发）。
- strict 口径 R 缺失计数：全部分组 `r_missing_n = 0`（WIN∪LOSS 行均有
  r_multiple）。

## 7. Verdict

```
VERDICT: REJECT
```

预注册判定逻辑：primary win_share delta 已定义且 >= 0 → REJECT；
SUPPORTED 需 primary win_share delta < 0 且 mean_R delta < 0（若定义）
且全部分层 win_share delta < 0；否则 OBSERVE_ONLY。

H6/F23「回调期放量下跌为失败负向结构因子」在冻结样本主指标（win_share /
strict_win_rate）上方向相反 → REJECT。mean_R 的负向关联（右尾收缩）是
独立于本假设的附带观察，若继续研究需单独预注册（如 R 分布右尾假设），
不属于本任务结论，亦不改任何生产规则。

## 8. Artifacts

| 项 | 值 |
| --- | --- |
| 研究脚本 | `research/factor-lab/h6_f23_selling_pressure_v01.py` |
| script SHA256 | `4ab33c82c3d93da201ba99ab64e09000d0272eccb50e5db1a7f46ebde0818b55` |
| 输出 JSON | `research/factor-lab/runs/h6-f23-v01/h6-f23-v01.json` |
| output JSON SHA256 | `3e64bf508b551758439b94e7d8dc292ecbcaa7ebfcf16f4682e5c22b354a683e` |

SUPPORTED != PROMOTED。本报告不改 setup_stage / 评分 / 阈值 / 生产规则。
