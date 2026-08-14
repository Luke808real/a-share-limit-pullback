# B2 语义评审决议 — B2_CONFIRMED 单调性（2026-08-14）

Owner 指令：2026-08-14「完成 B2 语义评审」。本文件是评审的完整记录与决议。

## 评审问题

策略实现中 B2_CONFIRMED 生命周期与冻结人类真源冲突（SWE 审计报告
2026-08-06 P0/CRITICAL 第 4 项）：代码 strategy/engine.py 的 stage 决策链
允许已 B2_CONFIRMED 的 setup 在次日条件不再满足时降回 B2_READY；
tests/fixtures/golden_expectations.yaml 的 s2_exhausted 期望 B2_READY，
即 golden 固化了降级行为。

## 冻结真源

a-share-strategy-brain/01_Strategy/STATE_MACHINE.md L12：

| B2_CONFIRMED | 已站稳冻结触发价 | 高点触发、收盘站稳、量价多数 | 失效、新锚点或过期 |

即：B2_CONFIRMED 的退出仅限失效（INVALID）、新锚点（LIMIT_ANCHOR）、
过期（EXPIRED）。不存在降回 B2_READY 的合法转移。

项目规则（AGENTS.md）：代码与知识库冲突时，reviewed/frozen 知识库规则胜出。

## 决议

1. B2_CONFIRMED 是单调状态。一旦确认，保持 B2_CONFIRMED，直到失效 /
   新锚点 / 过期。
2. 代码修复：strategy/engine.py 在 invalid 与新锚点分支之后、b2_confirmed
   重估之前插入同 setup 保持分支（previous_same.stage == B2_CONFIRMED →
   保持 B2_CONFIRMED）。
3. s2_exhausted golden 期望修正为 B2_CONFIRMED：S2_EXHAUSTED 是事件标记，
   不是阶段退出。
4. 「过期（EXPIRED）」退出在实现中尚不存在：本次决议不新增过期机制，只消除
   降级；过期语义如需要由后续 ADR 单独定义（不进本次范围）。
5. 决策输出门开放：B2 语义评审已闭环 → trade_plan.build_trade_plan_output
   默认 allow_decision_output=True；显式传 False 仍可阻塞。state generation
   的 decision_use_status 由 BLOCKED_STRATEGY_SEMANTIC_REVIEW 改为
   AVAILABLE_FOR_DECISION，reason 改为
   B2_SEMANTIC_REVIEW_RESOLVED_MONOTONIC_2026-08-14。
6. 历史语义：冻结快照 snap-2026-07-31-b5f84004de8a 与 08-05/08-06/08-07
   生成代保持原样（冻结 artifacts 不可变，且不回放重建历史）；单调语义自
   2026-08-10 及之后的新评估生效。08-07 代状态是评审前产物，后续推进以其为
   seed 属预期内的过渡，不回改。

## 变更清单

- src/limit_pullback/strategy/engine.py：B2_CONFIRMED 单调保持分支
- src/limit_pullback/trade_plan.py：allow_decision_output 默认 True + docstring
- src/limit_pullback/screen/generation.py：DECISION_USE_STATUS / REASON 更新
- tests/fixtures/golden_expectations.yaml：s2_exhausted → B2_CONFIRMED
- tests/test_strategy_engine.py：新增 test_b2_confirmed_is_monotonic_no_demotion
- tests/integration/test_pre_real_state_generation.py：门断言改为显式 False 才阻塞
- DECISIONS.md：D-026 条目

## 验证

- 定向：test_strategy_engine / test_replay / test_b2_confirmation /
  test_models 共 86 passed（含新单调性测试）。
- 全量离线：526 passed, 25 deselected（234.6s）。
- 冻结规则、B1/B2 阈值、S1/S2、Entry Room、评分语义未做任何其他改动。
