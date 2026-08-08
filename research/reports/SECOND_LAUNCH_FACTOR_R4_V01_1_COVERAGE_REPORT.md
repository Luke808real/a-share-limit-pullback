# SECOND_LAUNCH_FACTOR_R4_V01_1_COVERAGE_REPORT

> R4 V01.1 — STABILITY COVERAGE EXTENSION（BOARD / strict REGIME / LOW-position）
> AS_OF: 2026-08-08 · research-only · 契约：
> `SECOND_LAUNCH_FACTOR_R4_V01_1_COVERAGE_CONTRACT.md`

STATUS: **COMPLETE（availability gate 完成；无 READY 维度；无伪造 coverage）**

```text
BRANCH: research/second-launch-factor-r4-v011-coverage-v01
BASE_HEAD: 2f030d4b92bc77f258baac5a739704380e773a96
HEAD_AFTER: 见 GIT 段
REMOTE_SHA: 见 GIT 段（push 后核对）
```

## INPUT_GATE

```text
FEATURE_SHA a485a484… / OUTCOME_SHA 01a9f2fa… / 8,682 / episode 1:1 /
anchor/candidate/symbol 一致 / feature_snapshot_id 绑定: PASS
```

## R4_BASELINE_REPRODUCTION

```text
r4_stability_v01.py（2f030d4 版）在新 worktree 重跑：
  输出 4 个 CSV 与提交版字节一致（git diff 为空）
F3 x4 OVERALL = DATA_LIMITED；high_vs_pullback_high = UNSTABLE；
close_vs_pullback_high = TIME_DEPENDENT：全部复现
```

## ARTIFACT_AVAILABILITY（先于任何 SUCCESS 分层冻结；见 coverage_audit.csv）

```text
BOARD              : DATA_LIMITED（frozen cohort 构成）
STRICT_REGIME      : UNAVAILABLE（无指数 artifact）
LOW_POSITION       : DATA_LIMITED（自然稀有 + CA 缺失）
T0_TYPE_GEOMETRY   : DATA_LIMITED（cohort 构造性退化：0 一字 / 0 T字）
FIRST/MULTI_BOARD  : UNAVAILABLE（冻结规则禁止价格推断连板数；pool 15 日）
```

## BOARD_COVERAGE

```text
证据：
  frozen case set（success_control_cases_v01b.csv，SHA b22eae1d…，8,746 行）
    symbol 前缀 100% 为 10% 涨跌停主板（002/603/600/000/605/601/001/003）
  frozen feature cohort：SH_MAIN 4,244 / SZ_MAIN 4,438 / 其它 0
  历史涨停池：canonical limit_up_pool（SHA 45faa1a2…，manifest pin）
    仅 2026-07-13..07-31 共 15 日，且只含 10% 主板代码
  price_limits（raw tushare，ingest 50ed7fb2…，624 日 72 个 600 代码）：
    episode anchor 覆盖 65/8,682 = 0.7%
结论：不改变 frozen cohort/anchor 定义则无法增加板块 episode；
  扩展板块覆盖需未来冻结新 cohort（R-未来决策，本任务禁止）
```

## STRICT_REGIME_COVERAGE

```text
bounded search（data/canonical、data/raw/akshare|baostock|tushare、
  data/outcome-study、data/manifests、research/、src/）：
  未发现任何市场指数 artifact（无 000001.SH / sh.000001 / 沪深300）
禁止临时抓取/新增 provider -> 如实保持 UNAVAILABLE（DEFERRED）
公式已预注册（契约 2.2）：000001.SH close vs 前 60 会话 MA（<=D，PIT）
```

## LOW_POSITION_COVERAGE

```text
根因分解（frozen feature CSV，t0_position_20d）：
  非缺失 7,232；缺失 1,450 = CA_UNKNOWN 737 + CA_EVENT 713（全部 CA 契约原因）
  分布：mean 0.811 / p25 0.645 / median 0.926 / p75 1.000
    -> frozen anchor 强烈右偏（强势启动多在 20 日高位）
  LOW(<1/3 严格边界) N = 276 = 非缺失的 3.8%；anchor 范围 2024-07-01..2026-07-27
    覆盖全期 -> 自然样本稀少，非时间窗口缺口
  无额外 frozen cohort/feature artifact 可扩展（intraday case set 多出 64 行
    来自 corrected-episodes 66d5943f…，不属于 frozen 8,682 cohort）
结论：T0_POSITION 保持 DATA_LIMITED；未改 1/3、2/3 边界
```

## BOARD_STABILITY

```text
PRIMARY 6 board strata（3D，r4_v01_1_board_strata.csv）：
  仅 SH_MAIN / SZ_MAIN 两板 reportable -> 按 >=3 规则 = DATA_LIMITED
  （不得将"两主板同向"升级为 STABLE）
描述性（不构成判定）：
  pvr         SH 0.4538 / SZ 0.3879（同向 NEGATIVE）
  quiet       SH 0.5564 / SZ 0.6146（同向 POSITIVE）
  high_vs_ph  SH 0.5683 / SZ 0.5436（同向 POSITIVE）
  close_vs_ph SH 0.5855 / SZ 0.5940（同向 POSITIVE）
```

## STRICT_REGIME_STABILITY

```text
UNAVAILABLE -> 未执行；BREADTH vs STRICT 对比 = N/A
V01 breadth regime 结论（PRIMARY 6 全部 STABLE）仍为唯一 regime 证据；
不寻找更漂亮的指数或 MA window
```

## LOW_POSITION_STABILITY

```text
无 READY 扩展样本 -> 不执行；T0_POSITION 保持 DATA_LIMITED（同 V01）
```

## T0_TYPE_STABILITY（coverage extension 附带维度）

```text
几何分类（PRICE_ONLY，仅 T0 bar，PIT-safe）：
  ONE_PRICE 0 / T_SHAPE 0 / NORMAL_LIMIT 8,216 / CA_EXCLUDED 466（全部）
  -> 单类别退化，按 >=3 规则 = DATA_LIMITED
FIRST_BOARD/MULTI_BOARD = UNAVAILABLE（STRATEGY_MASTER 冻结：
  "不伪造…连板数"；pool consecutive_count 仅覆盖 2026-07-13..31，
  cohort 落在窗口内的 anchor 日 = 1 天 / 33 个 episode = 0.4%）
```

## BASELINE_INVARIANCE

```text
原 8,682 episode set / feature 值 / outcome 值：未修改（SHA pin 复验 PASS）
r4_stability_v01.py 重跑输出与 2f030d4 提交版字节一致
本任务未触碰任何 V01 文件（r4_stability_* / r3a / r3b / frozen CSV）
```

## VALIDATION

```text
1. compileall: PASS（src/tests/两个研究脚本）
2. R4 V01 targeted tests: test_r4_stability_v01.py 32 PASS
3. R4 V01.1 new targeted tests: test_r4_v011_coverage_v01.py 14 PASS
   （T0 几何分类 / 浮点容差 / PIT 只用 T0 bar / CA 与缺 bar /
     board 构成 / LOW 分解与 1/3 严格边界 / snapshot gate 负向 x2 /
     baseline invariance x2）
4. provenance/hash 负向测试: PASS（SHA 错、绑定错均 fail closed）
5. PIT boundary 测试: PASS（未来 bar 不影响 T0 类型）
6. baseline invariance 测试: PASS（SHA pin + V01 CSV 字节一致）
7. deterministic rerun: PASS（两次输出哈希一致）
8. git diff --check: PASS
未运行：full-market extraction / production / forward / TradePlan /
  R5/R6/R7 / 无关 full test suite
```

## OBSERVATIONS

```text
O1 冻结 cohort 按构造只含 10% 涨跌停主板 episode（case set 8,746 前缀 100%
   主板；feature cohort SH/SZ 各半）——板块稳定性在本 cohort 内不可评估，
   与"两块主板一致"无关
O2 仓库无任何市场指数 artifact -> strict index regime 不可执行（非结果问题）
O3 LOW-position 启动自然稀少（3.8% 非缺失；p75=1.0 右偏）且 16.7% 因 CA
   契约缺失——低位强势涨停是策略的稀有样本，不是数据缺口
O4 T0 几何类型在 cohort 内构造性退化：0 一字板 / 0 T字板（bar range 最小
   0.27 分）——frozen anchor 选择排除了开盘即涨停形态
O5 唯一可用"新"数据源（price_limits 72 代码 / pool 15 日）覆盖 <1% 的
   episode，无法支撑任何分层
```

## HYPOTHESES_SUPPORTED

```text
R4 V01 主结论在扩展检查后未被动摇：
F3 contraction / F6 activation 方向在可覆盖的两个主板内一致（描述性），
但按契约不升级为 STABLE；breadth regime 稳定性维持
```

## HYPOTHESES_NOT_SUPPORTED / UNRESOLVED

```text
UNRESOLVED（保持 V01 状态）：
  BOARD 跨板块稳定性（需未来冻结含 20% 板/北交所的 cohort）
  strict index regime（需带 provenance 的指数 artifact）
  LOW-position / T0 几何类型稳定性（稀有样本，需未来 cohort 设计）
```

## CORRECTNESS_BLOCKER

```text
NO
```

## R4_COMPLETION_RECOMMENDATION

```text
R4 V01 + V01.1 已覆盖契约允许的全部数据：
  TIME（year/quarter）、REGIME（breadth）、BOARD（cohort 内 2 板）、
  T0 TYPE（position/gap/几何）——数据可答的问题均已答；
  数据不可答的问题如实 DATA_LIMITED/UNAVAILABLE。
建议 R4 关闭（COMPLETE），进入 R5 External Benchmark 前需人工确认：
  是否冻结新的含板块多样性/指数 artifact 的 cohort（属 R-未来研究契约）。
```

## CONFIRM

```text
STRATEGY_CHANGED=false
PRODUCTION_CHANGED=false
FORWARD_CHANGED=false
TRADEPLAN_CHANGED=false
```

## FILES_CHANGED

```text
research/reports/SECOND_LAUNCH_FACTOR_R4_V01_1_COVERAGE_CONTRACT.md（新增）
research/second_launch/factors_v01/r4_v01_1_coverage_v01.py（新增）
research/second_launch/factors_v01/r4_v01_1_coverage_audit.csv（新增）
research/second_launch/factors_v01/r4_v01_1_board_strata.csv（新增）
research/second_launch/factors_v01/r4_v01_1_stability_results.csv（新增）
tests/test_r4_v011_coverage_v01.py（新增）
research/reports/SECOND_LAUNCH_FACTOR_R4_V01_1_COVERAGE_REPORT.md（本报告）
```

## GIT

```text
COMMIT: research: add r4 v01.1 coverage extension audit
PUSH: origin/research/second-launch-factor-r4-v011-coverage-v01
```
