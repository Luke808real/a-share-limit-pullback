# News Observation Layer — v01 研究笔记（2026-08-14）

Owner: news-analysis agent. Status: OBSERVATION layer only; nothing here feeds
the frozen strategy.

## 已落地

1. ASL 灌数（经 ASL 自身 JobEngine，未手写任何抓取/写库）：
   - announcement_index（cninfo）：4,214 行，覆盖 2026-08-10 .. 2026-08-13。
   - dragon_tiger（eastmoney）：254 行，覆盖 2026-08-10 .. 2026-08-13。
   - 驱动脚本：research/news-observation-v01/asl_news_ingest_driver.py
     （用 ASL venv 运行；注意取消 ALL_PROXY=socks5h，httpx 不支持该 scheme）。
   - 运行摘要：research/news-observation-v01/runs/ingest-20260813-summary.json。
2. V flash 只读消费端：src/limit_pullback/news_brief/（asl_reader + brief +
   models），入口 ops news-brief --as-of DATE [--codes .. | --plan-json ..]。
   离线测试 tests/test_news_brief.py 8 项全绿。
3. 真实产出示例：data/tmp/news-brief-20260813/brief.md（605198 命中一条
   cninfo 公告）。

## 关键发现（数据源语义）

- EastMoney 7×24 快讯（news_headlines / flash_news_wire，np-listapi
  getFastNewsList）只返回**最新约 200 条**（分页游标 sortEnd 存在但回翻历史
  不现实）。结论：这两个表**只能在当日盘后采集**，历史日期回补必然 0 行 →
  brief 对该表显式 NO_ROWS_IN_WINDOW，不视为「无消息」。
- cninfo 公告与 eastmoney 龙虎榜支持历史日期查询，回补可行（本次已验证）。
- 采集顺序：sentiment_scores 是派生 step，依赖 announcement_index +
  news_headlines + hot_rank，本轮未启用（hot_rank 未灌、非 brief 必需）。
- 日常规程建议：交易日盘后跑 targeted steps（news_headlines、flash_news_wire
  当日；announcement_index、dragon_tiger 当日），跑完再生成 brief。

## N/A 语义（fail-closed）

- TABLE_MISSING：表不存在（ASL schema 缺失）→ 数据缺口。
- NO_ROWS_IN_WINDOW：表存在但窗口内 0 行 → 可能是「无消息」也可能是「当日未采集」。
- STALE：表最新日期早于窗口起点 → 明确的数据滞后。
- brief 顶部表状态行 + 每标的 N/A 行都显式标注，绝不猜测内容。

## 边界重申

- 本层只输出事件提醒，不参与 setup_stage / 评分 / B1/B2 / 阈值。
- 任何把消息面引入策略的意图都必须走 Owner 单独批准与 ADR 流程。
