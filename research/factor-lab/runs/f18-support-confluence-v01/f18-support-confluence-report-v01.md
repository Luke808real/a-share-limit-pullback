# F18 SUPPORT CONFLUENCE CONTRACT V01 — 冻结合同与实现报告

研究层报告。contract / implementation only：不读 outcome、不搜索阈值、
无 ±2% 容差、无 MA5/MA20、不改 strategy/score/setup_stage、不触碰
production/forward/TradePlan。代码基线：2235816（H4 SUPPORT ZONE CONTRACT
AUDIT FIX V01，Sol 审计 PASS）。

## 1. 合同来源说明

Sol（ChatGPT 评审者）下发的任务消息在传输中发生截断：完整收到的是设计
动机与输出字段清单（同交易日触发 + 价格区间真实重合；字段含
SAME_DAY_SEMANTICS / PRICE_OVERLAP_SEMANTICS / TOLERANCE /
MISSING_SUPPORT / INSUFFICIENT_MA10 / FAIL_CLOSED 等），以及
Z_MA10(D) = [MA10(D), MA10(D)] 的明确定义；Z_T0 与 Z_PLATFORM 的正文
定义未到达。本合同按"全部组件取自已冻结定义"原则补全：
Z_T0 取 E04 冻结的 T0 实体区间，Z_PLATFORM 取 E05 冻结的
support_low/high。任何偏差由 Sol 审 exact commit 校正。

## 2. 冻结的支撑区间（对交易日 D）

| 区间 | 定义 | 来源 |
| --- | --- | --- |
| Z_MA10(D) | [MA10(D), MA10(D)]（单点退化区间） | Sol 任务原文 |
| Z_T0 | [min(open,close)(T0), max(open,close)(T0)] | E04 冻结合同 |
| Z_PLATFORM | [support_low, support_high] | E05 冻结值（SupportSnapshot） |

MA10(D) = 截至 D 的最近 10 个可见 session 收盘均值（PIT，复用
factor_lab._ma10）；不足 10 个 session 的日子 MA10 未定义。

## 3. 共振谓词（Sol 权威版：同日触发 + 真实公共交集 + 无容差）

单日深度 c(D)（D ∈ (anchor_date, as_of]）：

- 触发：某区间 Z 当日被 K 线触发 ⟺ candle(D) ∩ Z ≠ ∅
  （low(D) <= Z.high 且 high(D) >= Z.low，冻结的 E05 相交语义）。
- c(D) = 当日被触发的三个区间中，「两两存在真实公共交集」的最大子集
  大小（0–3）。三区间全 active ≠ 三重共振：必须
  Z_MA10 ∩ Z_BODY ∩ Z_PLATFORM ≠ ∅ 才允许 c(D)=3（Z_MA10 为单点，
  即 MA10(D) ∈ Z_BODY 且 MA10(D) ∈ Z_PLATFORM）。
- 深度 2：存在被触发的区间对，其区间交集非空（实体∩平台重叠，或
  MA10(D) ∈ 实体，或 MA10(D) ∈ 平台）。
- 深度 1：至少一个区间被触发；0：无。

**F18 = max_{D ∈ (anchor_date, as_of]} c(D)**（取值 {0,1,2,3}，非天数计数）。

## 4. 语义边界（对 Sol 字段清单的逐项声明）

- ZONE_MA10 = [MA10(D), MA10(D)]；ZONE_BODY = [min(o,c)(T0), max(o,c)(T0)]；
  ZONE_PLATFORM = [support_low, support_high]（均取已冻结定义）。
- SAME_DAY_SEMANTICS：区间当日被市场触发 = K 线区间与区间相交
  （low<=Z.high 且 high>=Z.low）；c(D) 只统计同日触发的区间子集。
- PRICE_OVERLAP_SEMANTICS：两两真实公共交集（区间对交集非空，退化区间按
  单点参与）；F18=3 必须 Z_MA10∩Z_BODY∩Z_PLATFORM≠∅。
- ACROSS_DAY_ACCUMULATION：NO——不同交易日分别触发的区间绝不累计
  （F18 = max_D c(D)，非跨日拼接）。
- TOLERANCE：无。±2% 废弃（LEGACY CATALOG DRAFT / NOT FROZEN）。
- MISSING_SUPPORT：support_low/high 任一为 None → 返回 None。
- INSUFFICIENT_MA10：窗口内无任何可见日 MA10 已定义（不足 10 个
  session）→ 返回 None；部分日 MA10 未定义时只跳过那些日子。
- MALFORMED_BARS_PRECEDENCE：结构完整性优先——多 code / 重复日期在
  任何语义短路（含 missing support → None）之前 fail closed（ValueError）；
  然后才是 missing support → None、区间非正/倒挂 → ValueError、
  anchor 缺失 → ValueError。
- FAIL_CLOSED：同 MALFORMED_BARS_PRECEDENCE + 区间非法/anchor 缺失。
- OUTCOME_READ = NO；THRESHOLD_SEARCH = NO；MA5_MA20_READ = NO。

## 5. 实现

函数：`factor_lab.f18_support_confluence(bars, anchor_date, as_of,
support_low, support_high) -> int | None`

- 复用 _ordered / _require_anchor / _after / _ma10 / _candle_intersects。
- 逐日判断 SAME_DAY_TRIGGER ∧ PRICE_OVERLAP，累计计数。

## 6. 测试（tests/test_factor_lab.py，F18 共 14 例）

- THREE_WAY_TEST：test_f18_max_depth_three_all_intersect（三重共振 → 3）
- TWO_WAY_TEST：test_f18_all_active_but_no_common_intersection_depth_two
  （Sol 裁决用例：全 active 无公共交集 → 2）+ test_f18_ma_body_pair_depth_two
- ACROSS_DAY_TEST：test_f18_across_day_no_accumulation（跨日不累计 → 2，非 3）
- NO_OVERLAP_TEST：test_f18_no_overlap_depth_one（active 但零对交集 → 1）
- BOUNDARY_TEST：test_f18_boundary_closed_interval_and_degenerate_platform
  （闭合区间含端点 + 退化实体/退化平台单点精确命中 → 3）
- FUTURE_LEAK_TEST：test_f18_pit_cutoff_no_future_leak（as_of 截止，1→3 max）
- MISSING_SUPPORT_TEST：test_f18_missing_support_returns_none（low=None /
  high=None）
- INSUFFICIENT_MA10_TEST：test_f18_insufficient_ma10_returns_none（<10
  session → None）+ test_f18_no_post_anchor_bar_is_none
- BAD_BARS_WITH_MISSING_SUPPORT_TEST：test_f18_bad_bars_with_missing_support_fail_closed
  （重复日期 + support=None → ValueError，结构校验优先）
- FAIL_CLOSED：test_f18_invalid_zone_fail_closed（倒挂/零价/anchor 缺失）

## 7. 结论状态

| 项 | 结论 |
| --- | --- |
| F18 | CONTRACT FROZEN + IMPLEMENTED（max 深度 0–3，PIT 纯函数 + 合成测试 10 例） |
| outcome / threshold / ±2% / MA5 / MA20 | 未读取、未搜索、未使用 |
| strategy / score / setup_stage / production / forward / TradePlan | 未改动 |

## 8. 语义修订记录（2026-08-15，Sol 权威版）

首版（7062990）按截断消息把 F18 实现为「满共振天数计数」；Sol 权威版
明确验收核心（同日触发、真实公共交集、无距离阈值）与裁决「三区间全
active 必须 Z_MA10∩Z_BODY∩Z_PLATFORM≠∅ 才允许 F18=3」，且指标为
「max confluence count = 0/1/2/3」。本修订（见 git log）将 F18 改为
单日最大共振深度，测试与文档同步更新。
