# SECOND_LAUNCH_FACTOR_R4_STABILITY_REPORT

> R4 STABILITY — 跨时间 / 市场环境 / 板块 / T0 类型子样本的稳定性验证
> AS_OF: 2026-08-08 · research-only · 契约见
> `SECOND_LAUNCH_FACTOR_R4_STABILITY_CONTRACT_V01.md`

STATUS: **COMPLETE（V01）** — 无 correctness blocker；未发现任何
`VALIDATED trading factor`；结论全部为 OBSERVATION / SUPPORTED_HYPOTHESIS

BRANCH: `research/second-launch-factor-r4-stability-v01`
HEAD_BEFORE: `0f3473189babc3d014179f87d6f23e48b41316b2`（R3B.1）
HEAD_AFTER: 见 GIT 段

## INPUT_GATE

```text
FEATURE_SHA: a485a484… / OUTCOME_SHA: 01a9f2fa… / 8,682 / episode 1:1 /
anchor/candidate/symbol 一致 / feature_snapshot_id 绑定: PASS
```

## 维度与数据可用性（V01 实测）

```text
TIME year/quarter : candidate_date；8 个可报告季度（2024Q3..2026Q2；
                    2026Q3 仅 7 月、success_n=7 < 10 门槛，不计入）
REGIME           : 广度代理（canonical 全市场 breadth vs 前 20 会话中位数）
                    589 个有效会话；episode 全部有标签（DATA_LIMITED=0）；
                    NEUTRAL 未出现（只有 RISK_ON 4,731 / RISK_OFF 3,951）
BOARD            : cohort 仅含 SH_MAIN 4,244 / SZ_MAIN 4,438；
                    SZ_CHINEXT / SH_STAR / BSE = 0 episode（覆盖缺口）
T0_POSITION      : HIGH 5,287 / MID 1,669 / LOW 276 / missing 1,450
T0_GAP_UP        : GAP_UP 4,987 / NO_GAP_UP 3,229 / missing 466
```

## PRIMARY 6 — 各维度判定（3D，SUCCESS vs KNOWN_NON_SUCCESS）

### 全局参考（与 R3A.1 数值一致）

```text
pullback_volume_ratio    AUC 0.4211 NEG  n=7,837
min_volume_ratio         AUC 0.4122 NEG  n=7,837
median_range_ratio       AUC 0.4156 NEG  n=7,838
quiet_days_n             AUC 0.5847 POS  n=7,838
high_vs_pullback_high    AUC 0.5557 POS  n=4,263
close_vs_pullback_high   AUC 0.5898 POS  n=4,263
```

### TIME — year（3/3 同向 → STABLE，全部 6 因子）

```text
pvr  0.4535 / 0.4333 / 0.3630（2024/2025/2026，逐年增强）
mvr  0.4501 / 0.4195 / 0.3582
mrr  0.4094 / 0.4239 / 0.3894
quiet 0.5444 / 0.5859 / 0.6260（逐年增强）
high_vs_ph 0.6021 / 0.5401 / 0.5343
close_vs_ph 0.6658 / 0.5691 / 0.5503
```

方向 3/3 一致；F3 效应逐年**增强**（非衰减）——如实记录，不做外推。

### TIME — quarter（正式稳定性协议，区别于 R3B EARLY_R4_SANITY_ONLY）

```text
pvr / mvr / mrr / quiet : STABLE（8/8 或 7/8 同向；
  pvr 2024Q4 AUC 0.5020 反向但 effect 0.002 < 0.03 非实质）
close_vs_pullback_high  : MIXED -> TIME_DEPENDENT
  （7/8 POSITIVE；2025Q1 AUC 0.4642，effect 0.036 >= 0.03 = 实质反转）
high_vs_pullback_high   : UNSTABLE
  （6/8 POSITIVE；2025Q1 AUC 0.4219 实质反转 + 2026Q1 0.4885 反向）
```

### REGIME（RISK_ON vs RISK_OFF，二值维度条款）

全部 6 因子 STABLE：两态与全局同向、effect >= 0.03

```text
pvr          0.4439 / 0.3771（NEG / NEG）
quiet        0.5748 / 0.6029（POS / POS）
high_vs_ph   0.5673 / 0.5435（POS / POS）
close_vs_ph  0.5813 / 0.5877（POS / POS）
```

F3/F6 方向在风险偏好（广度高于/低于近 20 会话中位数）两态下保持一致。

### BOARD

```text
DATA_LIMITED（预注册 >=3 层规则 + 覆盖缺口：仅 2/5 板块有 episode）
描述性（不构成判定）：SH vs SZ 同向
  pvr 0.4538 / 0.3879；quiet 0.5564 / 0.6146；
  close_vs_ph 0.5855 / 0.5940
```

### T0 TYPE — position（t0_position_20d 绝对 1/3-2/3 边界）

```text
DATA_LIMITED：LOW 层 success_n = 9（F3）/ 5（F6）< 10 门槛，
  仅 MID/HIGH 可报告 -> 不足 3 层
描述性：MID / HIGH 与全局同向（pvr 0.4376 / 0.4380；
  close_vs_ph 0.5684 / 0.5931）
```

### T0 TYPE — gap（二值维度条款）

```text
F3 x3 + close_vs_ph : STABLE（两态同向且均实质）
  pvr 0.4326 / 0.3976；quiet 0.5823 / 0.5893；
  close_vs_ph 0.6077 / 0.5443
high_vs_ph : DATA_LIMITED（NO_GAP_UP effect 0.023 < 0.03，非 directional）
```

## 判定汇总（3D）

```text
factor                     year  quarter  regime  gap  board  pos  OVERALL
pullback_volume_ratio      STABLE STABLE  STABLE STABLE DL   DL   DATA_LIMITED
min_volume_ratio           STABLE STABLE  STABLE STABLE DL   DL   DATA_LIMITED
median_range_ratio         STABLE STABLE  STABLE STABLE DL   DL   DATA_LIMITED
quiet_days_n               STABLE STABLE  STABLE STABLE DL   DL   DATA_LIMITED
high_vs_pullback_high      STABLE UNSTABLE STABLE DL    DL   DL   UNSTABLE
close_vs_pullback_high     STABLE MIXED   STABLE STABLE DL   DL   TIME_DEPENDENT
```

DL = DATA_LIMITED。OVERALL 按预注册规则（任一 UNSTABLE -> UNSTABLE；
任一 MIXED -> <DIM>_DEPENDENT；任一 DATA_LIMITED -> DATA_LIMITED）。

F3 的 OVERALL=DATA_LIMITED **不是不稳定**，而是 board（覆盖缺口）与
t0_position（LOW 样本不足）两个维度数据受限所致；在数据足够的维度
（year / quarter / regime / gap）F3 全部 STABLE。

## 负控 / 对照（10 因子，不改变其 R3 状态）

```text
t0_return                 : TIME_DEPENDENT（quarter MIXED，2026Q2 实质反转）
t0_gap                    : UNSTABLE（quarter）
t0_position_20d           : TIME_DEPENDENT（quarter MIXED）
t0_close_location         : NO_GLOBAL_SIGNAL（|AUC-0.5| < 0.01）
t0_gain_retention         : NO_GLOBAL_SIGNAL
low_vs_t0_mid             : UNSTABLE（year/quarter）
max_drawdown_...          : NO_GLOBAL_SIGNAL
days_since_t0             : TIME_DEPENDENT（year/quarter MIXED）
days_to_pullback_low      : TIME_DEPENDENT
pullback_duration         : TIME_DEPENDENT
```

对照因子整体不满足跨维度稳定；F1/F2/F5 未出现新的稳定信号。

## 5D SENSITIVITY（PRIMARY 6）

```text
全部 6 因子 verdict_5d == verdict_3d（SENSITIVITY_DIFF = 0）
（5D 全局 AUC 与 3D 接近：pvr 0.4177 / quiet 0.5845 /
  close_vs_ph 0.5819 / high_vs_ph 0.5518）
```

## 解释（OBSERVATION，非 VALIDATED）

```text
O1 F3 CONTRACTION：在数据充分的全部维度（year / quarter / regime /
   gap）方向一致（收缩越强 SUCCESS 越高），year 效应逐年增强；
   结论 = SUPPORTED_HYPOTHESIS（延续 R3B），非 VALIDATED RULE
O2 F6 close_vs_pullback_high：year/regime/gap STABLE，但 quarter 维度
   TIME_DEPENDENT（2025Q1 实质反转 0.4642）——activation 信号存在
   季度间不稳定性
O3 F6 high_vs_pullback_high：quarter 维度 UNSTABLE（2025Q1 + 2026Q1
   反向）——该因子跨季度不稳健
O4 BOARD：本 cohort 无法回答板块稳定性（无 20% 板/北交所 episode）；
   需未来 cohort/feature 扩展（如历史 limit_up_pool）方可评估
O5 T0 POSITION：LOW 位启动样本过小（n=276），无法评估"低位/中低位"
   子样本稳定性；T0 类型（首板/连板/一字/T字）在 frozen V01 中
   UNAVAILABLE_FOR_V01（不伪造）
O6 REGIME：广度代理下 F3/F6 在 RISK_ON / RISK_OFF 两态均稳定；
   严格指数式 regime 仍 DEFERRED（缺 PIT-safe 指数 artifact）
```

## 结论

```text
R4 V01 回答：R3 的 F3 contraction 证据在时间（年/季）、市场环境
（广度 regime）、T0 gap 类型子样本中稳定存在；F6 activation 的
close_vs_pullback_high 在季度层面为 TIME_DEPENDENT，
high_vs_pullback_high 为 UNSTABLE。
board 与 T0-position 维度结论 = DATA_LIMITED（数据覆盖，非证据缺失）。

没有产生任何 VALIDATED trading factor / VALIDATED RULE。
R4 未完项（V01.1+，仍属 R4，不属 R6/R7）：历史涨停池/指数 artifact
  -> board 与严格 regime 稳定性；LOW-position T0 样本扩展。
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## VALIDATION

```text
测试：tests/test_r4_stability_v01.py 24 tests PASS
（board 映射 / tertile 绝对边界 / gap 符号 / regime 中位数 /
  层门槛 / verdict 规则 / 二值维度条款 / overall 优先级 /
  AUC 方向不翻转）
全脚本重算：单次有界运行（~3s，16 factors x 6 dims）；
  全局 AUC 与 R3A.1 数值一致；5D 敏感度与 3D 结论一致
REGIME 审计：589/624 会话有效（n>=4000 门槛）；0 episode DATA_LIMITED
```

## FILES_CHANGED

```text
research/reports/SECOND_LAUNCH_FACTOR_R4_STABILITY_CONTRACT_V01.md（新增，冻结）
research/second_launch/factors_v01/r4_stability_v01.py（新增）
research/second_launch/factors_v01/r4_stability_global_3d.csv（新增）
research/second_launch/factors_v01/r4_stability_strata_3d.csv（新增）
research/second_launch/factors_v01/r4_stability_verdicts_3d.csv（新增）
research/second_launch/factors_v01/r4_stability_sensitivity_5d.csv（新增）
tests/test_r4_stability_v01.py（新增）
research/reports/SECOND_LAUNCH_FACTOR_R4_STABILITY_REPORT.md（本报告）
```

## GIT

```text
COMMIT: research: add r4 factor stability analysis v01
PUSH: origin/research/second-launch-factor-r4-stability-v01
```

---

# R4.1 PATCH — direction NEUTRAL 语义 + regime snapshot immutable gate

> 2026-08-08 · 审计补丁 · 不改研究结论

## 1. AUC == 0.5 direction 语义（严格符合 frozen contract §4）

```text
修正前：direction_of(auc) = POSITIVE if auc >= 0.5 else NEGATIVE
        （0.5 精确值被归为 POSITIVE，与 sign(AUC - 0.5) = 0 矛盾）
修正后：AUC > 0.5 -> POSITIVE；AUC < 0.5 -> NEGATIVE；
        AUC == 0.5（精确）-> NEUTRAL
NEUTRAL 语义（契约已明确）：effect = 0；计入 reportable 分母；
  不计入 same / opposite；永不构成 material reversal；
  不得因此触发 UNSTABLE
```

同时修正 `dimension_verdict` 的 opposite 计数：NEUTRAL 层不再计入
opposite（此前 `len(reportable) - same` 会把 NEUTRAL 误计为反向证据）。

## 2. Regime canonical snapshot immutable provenance/hash gate

```text
gate 1（不可变哈希）: SHA256(snap-2026-07-31-b5f84004de8a.parquet)
  == e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
  （pin 自 data/manifests/snap-2026-07-31-b5f84004de8a.json
    canonical_file_hashes[...]；与 outcome/extractor 的
    EXPECTED_FEATURE_SNAPSHOT_SHA256 相同值）
gate 2（快照绑定）: 全部行 dataset_snapshot_id == snap-2026-07-31-b5f84004de8a
gate 3（日期覆盖）: 快照会话范围必须覆盖 cohort candidate_date 范围
任一失败 -> RuntimeError（FAIL CLOSED，不输出结果）
```

## 3. 新增 regression tests（test_r4_stability_v01.py：24 -> 32）

```text
test_direction_exact_0_5_is_neutral             （sign 语义 + 边界）
test_stratum_exact_0_5_neutral_effect_zero      （全同值 -> AUC 精确 0.5）
test_verdict_neutral_stratum_counts_denominator_only（NEUTRAL 只进分母）
test_verdict_neutral_never_material_reversal    （NEUTRAL 不触发 UNSTABLE）
test_snapshot_gate_pass / _hash_mismatch_fails / _binding_mismatch_fails
test_snapshot_date_coverage_gate
```

## 4. Before / After 对比（patch 前后 PRIMARY 6 必须不变）

```text
r4_stability_global_3d.csv         : PRIMARY 6 字节级一致（0 行变化）
r4_stability_strata_3d.csv         : PRIMARY 6 字节级一致
r4_stability_verdicts_3d.csv       : PRIMARY 6 字节级一致
r4_stability_sensitivity_5d.csv    : PRIMARY 6 字节级一致

全量变化（唯一）：
  t0_close_location（CONTROL / NO_GLOBAL_SIGNAL）
    - 2026Q3 层 direction: POSITIVE -> NEUTRAL（AUC 精确 0.5）
    - quarter consistency: 0.7778 -> 0.6667（同分母 9、same 6）
    - quarter verdict: MIXED -> MIXED（不变）

主结论不变：
  F3 x4      OVERALL DATA_LIMITED（维度覆盖受限，非不稳定）
  high_vs_pullback_high OVERALL UNSTABLE（quarter 维度）
  close_vs_pullback_high OVERALL TIME_DEPENDENT（quarter 维度）
  5D 敏感度与 3D 全部 SAME
```

## 5. 验证

```text
仅运行 R4 targeted tests + R4 script（按要求，未跑其他测试集）
tests: 32 passed
全脚本重跑: gate PASS（哈希 / 绑定 / 覆盖），输出确定（两次哈希一致）
CONFIRM: STRATEGY/PRODUCTION/FORWARD/TRADEPLAN 均未改变
```
