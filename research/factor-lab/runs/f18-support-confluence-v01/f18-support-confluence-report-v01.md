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

## 3. 共振谓词（两个条件必须同时成立）

F18(D) = SAME_DAY_TRIGGER(D) ∧ PRICE_OVERLAP(D)

- SAME_DAY_TRIGGER（同日触发）：D 的 K 线区间与三个区间均相交
  （low(D) <= Z.high 且 high(D) >= Z.low，冻结的 E05 相交语义推广到
  三个区间；退化区间退化为单点）。
- PRICE_OVERLAP（价格真实重合）：MA10(D) ∈ Z_T0 且 MA10(D) ∈ Z_PLATFORM，
  即三个区间共享价格 MA10(D)——真实几何重合，而非"不同日各自碰过"
  的事后拼接。

F18 计数 = |{ D ∈ (anchor_date, as_of] : F18(D) }|。

## 4. 语义边界（对 Sol 字段清单的逐项声明）

- TOLERANCE：无。±2% 废弃（LEGACY CATALOG DRAFT / NOT FROZEN，
  h4-support-zone-v01 报告 §5 备注）。
- MISSING_SUPPORT：support_low/high 任一为 None → 返回 None。
- INSUFFICIENT_MA10：窗口内没有任何可见日 MA10 已定义（不足 10 个
  session）→ 返回 None；部分日子 MA10 未定义时只跳过那些日子。
- FAIL_CLOSED：冻结区间非正/倒挂 → ValueError；anchor 缺失 → ValueError；
  多 code / 重复日期 → ValueError（_ordered）。
- 无 T0 后 bar → None（与 E04/E05 一致）。
- OUTCOME_READ = NO；THRESHOLD_SEARCH = NO。

## 5. 实现

函数：`factor_lab.f18_support_confluence(bars, anchor_date, as_of,
support_low, support_high) -> int | None`

- 复用 _ordered / _require_anchor / _after / _ma10 / _candle_intersects。
- 逐日判断 SAME_DAY_TRIGGER ∧ PRICE_OVERLAP，累计计数。

## 6. 测试（tests/test_factor_lab.py，新增 9 例）

1. test_f18_confluence_same_day_count_one — 同日三区间触发 + 重合 → 1
2. test_f18_two_confluence_days_count_two — 两日共振 → 2（计数语义）
3. test_f18_partial_trigger_days_not_counted — 不同日/部分触发 → 0
4. test_f18_trigger_but_no_price_overlap_zero — 触发但价格未重合 → 0
5. test_f18_pit_cutoff_no_future_leak — as_of 截止（PIT）
6. test_f18_missing_support_returns_none — missing → None
7. test_f18_insufficient_ma10_returns_none — MA10 不足 → None
8. test_f18_no_post_anchor_bar_is_none — 无 T0 后 bar → None
9. test_f18_invalid_zone_fail_closed — 倒挂/零价/anchor 缺失 → ValueError

## 7. 结论状态（已被 §8 审计修复撤销）

| 项 | 结论 |
| --- | --- |
| F18 | ~~CONTRACT FROZEN + IMPLEMENTED~~ → 见 §8（NOT CLOSED，待复审） |
| outcome / threshold / ±2% / MA5 / MA20 | 未读取、未搜索、未使用 |
| strategy / score / setup_stage / production / forward / TradePlan | 未改动 |

## 8. AUDIT FIX V01（2026-08-15，Sol 审计 CHANGES_REQUIRED 修复）

Sol 审计 7062990 否决（AUDIT_STATUS: CHANGES_REQUIRED），5 个 blocker
修复（分支 fix/f18-support-confluence-contract-audit-v01，BASE_HEAD
7062990；不得重新设计 F18）：

1. **F18 数学量（Blocker 1）**：错误实现"三重共振天数计数"→ 规范函数
   `support_confluence_max_count`，F18 = max_D C(D) ∈ {0,1,2,3}。
2. **双支撑共振（Blocker 2）**：实现 MA+BODY / MA+PLATFORM /
   BODY+PLATFORM 三种深度 2 语义（active 对 + 区间公共交集）。
3. **日级激活复用冻结谓词（Blocker 3）**：MA_ACTIVE = low<=MA10<=close
   （E01 touch-hold）；BODY_ACTIVE = BODY_LOW<=low<=BODY_HIGH（E04）；
   PLATFORM_ACTIVE = low<=support_high 且 high>=support_low（E05）。
   不再把 E05 区间相交语义推广到 MA/实体。
4. **MALFORMED_BARS_PRECEDENCE（Blocker 4）**：_ordered + _require_anchor
   先于 missing support 短路（坏 bar / anchor 缺失 + support=None →
   ValueError，不被静默掩盖）。
5. **撤销文档 FROZEN 标记（Blocker 5）**：F18 CONTRACT = NOT CLOSED，
   7062990 implementation = REJECTED BY AUDIT；本报告 §7 结论撤销，
   FACTOR_CATALOG / README 同步。

测试：17 个 F18 用例（THREE_WAY / TWO_WAY×3 / ACROSS_DAY / NO_OVERLAP /
BOUNDARY / FUTURE_LEAK / MISSING_SUPPORT / INSUFFICIENT_MA10 / 无 T0 后
bar / FAIL_CLOSED / 坏 bar+missing / anchor 缺失+missing / E01 激活回归 /
E04 激活回归），factor_lab 56 passed；compileall 与 git diff --check
通过。待 Sol 复审 exact commit 通过后 F18 才可标记 CONTRACT FROZEN，
随后进入 outcome validation design。
