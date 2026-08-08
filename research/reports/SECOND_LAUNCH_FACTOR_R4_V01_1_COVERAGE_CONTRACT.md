# SECOND_LAUNCH_FACTOR_R4_V01_1_COVERAGE_CONTRACT

> R4 V01.1 — STABILITY COVERAGE EXTENSION 契约（预注册，先冻结后计算）
> AS_OF: 2026-08-08 · research-only · BASE_HEAD `2f030d4b92bc77f258baac5a739704380e773a96`

STATUS: **FROZEN（pre-registered）**

## 0. 输入冻结（与 R4 V01 相同，fail-closed）

```text
FEATURE_SHA: a485a484d68e80b7514112c19a7380b4296595c17f3634df0d1467151e7affa8
OUTCOME_SHA: 01a9f2fac6cab66686648b112c53eebf0526cee8a5c07559bdd3381578fa108d
ROW_N: 8,682 / episode 1:1 / anchor/candidate/symbol 一致 /
feature_snapshot_id = snap-2026-07-31-b5f84004de8a
```

## 1. 目标与范围

补齐 R4 V01 的 DATA_LIMITED / DEFERRED 三项：BOARD、strict REGIME、
LOW-position T0。仍属 R4 stability；禁止 R5/R6/R7、策略/生产/forward/
TradePlan 修改、ML/回测/参数寻优、修改 frozen SUCCESS/outcome 定义。

## 2. 可用性结论（2026-08-08 bounded search 后冻结，先于任何 SUCCESS 分层）

### 2.1 BOARD — DATA_LIMITED（cohort 构成）

```text
证据：
  frozen case set（research/intraday/success_control_cases_v01b.csv，
  SHA b22eae1d…，8,746 行）symbol 前缀 100% 为 10% 涨跌停主板
  （002/603/600/000/605/601/001/003；无 300/301/688/689/920）；
  frozen feature CSV 同（8,682 行，SH_MAIN 4,244 / SZ_MAIN 4,438）
  历史涨停池：canonical limit_up_pool 仅 2026-07-13..07-31（15 日，
  且只含 10% 主板代码）-> 无法覆盖 2024-07..2026-06 cohort
  price_limits（raw tushare，ingest 50ed7fb2…，624 日）仅 72 个
  600 前缀代码 -> episode 覆盖 65/8,682 = 0.7%
结论：不改变 frozen cohort/anchor 定义则无法增加板块 episode；
  扩 cohort 属 R-未来冻结决策，本任务禁止。
判定：BOARD = DATA_LIMITED（>=3 reportable 规则无法满足，
  且"两块主板一致"不得升级为 STABLE）
```

### 2.2 STRICT REGIME（指数）— UNAVAILABLE

```text
bounded search 范围（data/canonical、data/raw/**、data/outcome-study、
  data/manifests、research/、src/）未发现任何指数 artifact
  （无 000001.SH / sh.000001 / 沪深300 等代码或文件）。
禁止临时抓取 / 新增 provider。
公式（为未来 artifact 预注册，本任务不执行）：
  index = 上证指数 000001.SH daily close（需独立 provenance artifact）
  regime(D) = BULL if close(D) >= MA60(D) else BEAR
  MA60(D) = mean(close, 60 sessions <= D)（PIT：只用 <=D 数据）
  前 60 会话不足 -> INSUFFICIENT_HISTORY（不输出 regime）
判定：STRICT_REGIME = UNAVAILABLE（DEFERRED 状态保持）
  V01 breadth regime 仍为唯一 regime 证据；BREADTH vs STRICT 对比 = N/A
```

### 2.3 LOW POSITION — DATA_LIMITED（自然稀有 + CA 缺失）

```text
根因分解（frozen feature CSV）：
  t0_position_20d 非缺失 7,232；缺失 1,450 = CORPORATE_ACTION_UNKNOWN 737
    + CORPORATE_ACTION_EVENT 713（全部为 CA 契约原因，无其他原因）
  非缺失分布：mean 0.811 / p25 0.645 / median 0.926 / p75 1.000
    -> cohort 锚点强烈右偏（强势启动多位于 20 日高位）
  LOW(<1/3) N = 279（非缺失的 3.9%）；anchor 范围 2024-07-01..2026-07-27
    覆盖全期 -> 非时间窗口缺口，是自然样本稀少
  无额外 frozen cohort/feature artifact 可扩展（intraday case set 多出的
    64 行来自 corrected-episodes 66d5943f…，不属于 frozen 8,682 cohort，
    纳入即改变 frozen cohort —— 禁止）
禁止：改 1/3、2/3 边界 / T0 定义 / SUCCESS / outcome window
判定：T0_POSITION = DATA_LIMITED（保持 V01 结论）
```

### 2.4 T0 TYPE（几何）— DATA_LIMITED（cohort 构造性退化）

```text
几何分类（PRICE_ONLY，仅用 T0 当日 OHLC，PIT-safe；不伪造封板时间/连板数）：
  ONE_PRICE  : round4(H0) == round4(L0)
  T_SHAPE    : round4(O0) == round4(H0) 且 round4(L0) < round4(H0)
  NORMAL_LIMIT: 其余（O0 < H0）
  T0 为 CA 日（t0_return__missing_reason 非空）-> CA_EXCLUDED（不计入）
实测（frozen canonical b5f84004de8a，8,682 个 T0 bar 全覆盖）：
  ONE_PRICE = 0；T_SHAPE = 0；NORMAL_LIMIT = 8,216；CA_EXCLUDED = 466
  bar range 最小 0.27 元分 -> frozen anchor 构造不含一字/T字
判定：T0_TYPE = DATA_LIMITED（单一类别，无法达到 >=3 reportable）
FIRST_BOARD / MULTI_BOARD = UNAVAILABLE：
  STRATEGY_MASTER 冻结规则"不伪造…连板数"；pool consecutive_count
  仅覆盖 2026-07-13..31（15 日），无法恢复历史首板/连板
```

## 3. 判定规则（复用 R4 V01，除结构性 bug 外不改）

```text
AUC（R3A.1 实现，不翻转）；direction = sign(AUC-0.5)，0.5 -> NEUTRAL；
effect = |AUC-0.5|；reportable gate：n>=60 且 success_n>=10 且 nonsuccess_n>=10；
verdict：reportable<3 -> DATA_LIMITED；consistency>=0.8 且无 material
  reversal(>=0.03) -> STABLE；…（同 V01 契约 §5）
overall 优先级：UNSTABLE > <DIM>_DEPENDENT > DATA_LIMITED > STABLE
3D primary / 5D sensitivity（PRIMARY 6）
```

## 4. 本任务计算范围（全部维度按 §2 判定；无 READY 维度）

```text
产出（确定性、可复现）：
  r4_v01_1_coverage_audit.csv   （可用性/覆盖审计表）
  r4_v01_1_board_strata.csv     （board 描述性 strata，判定 DATA_LIMITED）
  r4_v01_1_stability_results.csv（t0_type 退化 strata + overall）
不新增 SUCCESS 分层研究（无 READY 维度 -> 不执行新稳定性研究）
```

## 5. 禁止事项（同 R4 V01 + 本任务）

```text
临时抓取 / 新增 provider / 猜板块 / 当前 metadata 回填历史 /
未来状态解释过去 / 绕过 lineage gate / 伪造 coverage /
为 success_n>=10 改边界 / 重复计算已有 episode / 改 frozen cohort
```

## 6. Baseline invariance（强制）

```text
原 8,682 episode set / feature 值 / outcome 值不变；
r4_stability_v01.py 重跑输出与 2f030d4 提交版字节一致；
任何偏差 -> STATUS=BLOCKED（报告首个 divergent episode/field）
```
