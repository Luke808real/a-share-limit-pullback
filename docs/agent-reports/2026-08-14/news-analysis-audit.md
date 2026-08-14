# news-analysis 只读审计报告（四 Agent 架构开篇）

## step 清单与数据源
- 有 step（8/8 全部齐）：flash_news_wire(eastmoney:news_wire.py, group=research)、news_headlines(eastmoney:rotation.py/stock_news.py, research)、announcement_index(cninfo:announcements.py, capital)、dragon_tiger(eastmoney:capital.py, signals)、economic_calendar(eastmoney:economic_calendar.py, macro_risk)、sentiment_scores(derived, research, depends_on=[announcement_index, news_headlines, hot_rank])。
- 另：regulatory_events(macro_risk, cninfo:regulatory.py)、analyst_consensus(research) 亦为现成；无「仅 schema 无 step」的孤儿表。
- 关键差异：sentiment_scores 是 derived 派生 step（非抓取，输入靠 announcement/news_headlines/hot_rank），allow_empty=True；其余为抓取 step。

## CLI 最小命令
- 命令名 asl run daily（子命令）→ 签名 run_daily(config_path, --group, --trade-date, --backfill, --stale-only, --quiet)；按单 step 无直接 --steps 参数，最小形态是按 group 灌：asl run daily --group research --trade-date 2026-08-11。
- 另可用 asl run catchup --trade-date YYYY-MM-DD 分段灌 core/research/macro_risk/signals；run-daily 成功输出 {"run_id","status"} JSON，非 success/skipped_non_trading_day 即 SystemExit(1)。
- run_id 由 JobEngine 自动生成并返回；config 默认 configs/ashare-lake.toml，但 configs/ 下仅 ashare-lake.example.toml，缺实际 toml（需 MAIN 授权阶段补齐）。

## 落库语义
- run_incremental_fetched(config,trade_date,run_id,dataset,fetch_fn,source,allow_empty=False) → fetch_incremental_daily 增量取数 → write_fetched → write_simple（加 provenance，写 curated 并注册 dataset）。
- allow_empty=False 时：空结果会 fail-loud（newsboard.py:18-19 注释明确）。flash_news_wire 用 allow_empty=False；economic_calendar 用 empty_ok() 直接 raise；sentiment_scores 用 allow_empty=True（派生，可空）。

## 灌数计划（2026-08-11~08-13）
- 08-11：asl run daily --group capital --trade-date 2026-08-11（announcement_index 属 capital，cninfo）；--group research（flash_news_wire/news_headlines/sentiment_scores，注意 sentiment 依赖前两者）；--group macro_risk（economic_calendar/regulatory_events）。
- 08-12、08-13：同命令改 --trade-date；或条带式 asl run catchup --trade-date 2026-08-13 一次分段灌全三个交易日。
- 顺序约束：sentiment_scores 依赖 announcement_index+news_headlines+hot_rank，须等三者先成功再跑；dragon_tiger（signals group）与前两者无依赖可并行。

## 失败模式与 N/A 处理
- 抓取空（eastmoney 无当日快讯/cninfo 分页失败）：allow_empty=False/empty_ok 会 raise → run 标 failed、lake_health 记 finding（fail-loud）。
- 派生空：sentiment_scores allow_empty=True 静默 0 行——news_brief 读侧须显式判空而非假定存在。
- 建议：news_brief 读侧对 flash_news_wire/announcement_index/news_headlines 三表必须先查 lake_health/finding 再渲染，任何 0 行都输出显式 N/A（不是省略），并区分「无消息=真没消息」vs「取数失败=数据缺口」。

## join 契约建议
- TradePlan 输出 code(6 位数字) 与 plan_date；news 表用 symbol/related_symbols(VARCHAR, 逗号串) 与 publish_date/announce_date。契约：news_brief 用 symbol = 去 .SH/.SZ 的 6 位 code 或直接按 6 位数字匹配，日期用 for_trade_date/plan_date 前溯窗口；related_symbols 是逗号分隔串需 split 展开后再 join，不能直接相等匹配。
- 只做 OBSERVATION：news_brief 仅汇总 per-code 的标题/类别/重要性/sentiment 摘要，评分与 B1/B2 阈值零介入。

VERDICT: 消息面 8 张表 step 全齐、CLI 灌数路径清晰，唯一硬缺口是 configs/ashare-lake.toml 需由 MAIN 授权阶段补齐后即可跑通，且 sentiment_scores 为派生 step 须先灌其三个输入 step 并统一以 fail-loud + 显式 N/A 处理空结果。
