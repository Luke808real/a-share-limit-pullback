# VOLUME SEMANTIC AUDIT V01

RUN: PRE-FORWARD GATE（FORWARD_PAPER_D0_BPOINT_V01）
SAMPLE: 206 个完整 5m cases（development sample，仅用于 audit + reference）

## VOLUME_RATIO_EXACT_DEFINITION（当前实现）

- NUMERATOR = D0 cumulative volume up to checkpoint（5m bars 求和）
- DENOMINATOR = D-1 full-day volume（canonical daily bar）
- CHECKPOINT = 09:45 / 10:00（primary）
- DATA_FREQUENCY = 5m（1m complete = 0）
- 该定义即 V01 的 CUM_VOLUME_VS_D1_RATIO。

## DECOMPOSITION（206 cases）

| 变量 | 定义 | 09:45 medians S/F/NL/SF | rb vs F / SF |
|---|---|---|---|
| A | D0cum / D1 full | 0.225 / 0.285 / 0.189 / 0.324 | +0.23 / +0.33 |
| B | D0cum / anchor full | 0.282 / 0.316 / 0.172 / 0.359 | +0.21 / +0.29 |
| C | D0cum（绝对值，不跨股比） | — | — |
| D | D1 full volume | — | — |
| E | anchor full volume | — | — |
| D0cum / median5 | within-stock 归一分子 | 0.324 / 0.410 / 0.176 / 0.387 | +0.21 / +0.21 |
| D1full / median5 | within-stock 归一分母 | 1.239 / 1.340 / 1.000 / 1.078 | -0.01 / -0.19 |
| F | D0cum / D1 same-time cum（coverage 206/206） | 0.243 / 0.308 / 0.193 / 0.326 | +0.24 / +0.26 |

10:00 方向一致（A +0.29/+0.40；F +0.28/+0.32；D0cum/median5 +0.26/+0.23）。

## DENOMINATOR CONFOUNDING AUDIT

- 分子（D0cum/median5）：SUCCESS 低于 FAILED 与 STRUCTURE_FAIL（rb +0.21/+0.21）→ 分子驱动。
- 分母（D1full/median5）：SUCCESS 与 FAILED 无差异（rb -0.01）；vs STRUCTURE_FAIL 反而更低（rb -0.19，方向不构成“S 的分母更高”）。
- 结论：ratio 差异不是“SUCCESS 的 D-1 量特别高”造成。

VOLUME_CONCLUSION = VOLUME_PACE_SIGNAL_CONFIRMED

## APPROVED_VOLUME_PACE_PRIMARY

F = CUM_VOLUME_VS_D1_SAME_TIME
（D0 cum volume to checkpoint / D1 cum volume to same checkpoint；
development 206/206 可计算，09:45 与 10:00 方向一致）

仅此一项进入 LAYER A QUALITY；A/B/within-stock 归一列保留为 audit columns，
不进入 score。

PRODUCTION_FILES_CHANGED = false
