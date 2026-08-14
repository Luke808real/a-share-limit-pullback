# data-processing 只读审计报告（V flash）

## 步骤输入输出
1. fetch_daily_delta：入 prev_snapshot(data/canonical/daily_bars/*.parquet)+runtime，出 data/tmp/canonical-catchup-<DATE>/{raw_tdx_full.parquet, raw_tencent_full.parquet, fetch-summary.json, raw_tdx_chunks/, raw_tencent/}，同时写 source_files 表。
2. run_adr008_staging（ADR-008）：入 prev snapshot canonical + TDX/Tencent raw rows，出 data/tmp/staging/adr008/<run_id>/{canonical_candidate.parquet, manifest.json, failures.jsonl} + staging-summary（STAGED_OK/fail-closed）。
3. BaoStock 停牌核验（_verify_no_trade_with_baostock）+ 派生涨停事件（build_derived_limit_events）：入 staged_rows + config/strategy.yaml，出 verified_no_trade 集合 + derived-summary（derived_event_n=74, hash）。
4. promote_snapshot（PR-D）：入 staged_rows+derived_events，出 data/canonical/{daily_bars,limit_up_pool}/snap-<id>.parquet + data/{manifests,lineage,validation}/*.json，原子写 dataset_snapshots + formal_screen_ready_pointer。
5. build_state_generation（fast path 增量）：入 promotion.snapshot_id + prev_gen_root(data/screen/generations/<prev>)，出 data/screen/generations/<gen>/ + stategen-summary（ACTIVE, state_n=3191），写 formal_state_generation_pointer。

## summary 字段（data/tmp/canonical-catchup-2026-08-06/）
6. fetch-summary：ingest_run_id/session/requested_code_n=5198/tdx|tencent_row_n=5198|5196/failures=0/tdx|tencent_full_sha256。
7. staging-summary：run_id/stage_status=STAGED_OK/publish_eligible=true/staging_canonical_hash/confirmed=5196/provisional=2/conflicted=0/preclose_mismatch=0/manifest_path。
8. promotion-summary：snapshot_id=snap-2026-08-06-e798f88ff67b/content_hash/status=SCREEN_READY/pointer_before|after/daily_total_n=3301481；stategen-summary：generation_id/status=ACTIVE/state_n=3191/semantic_root+compact_output hash；evolution-summary：4 日状态分布 + transition_counts + b2_ready_remaining_n=190；performance-baseline：002112|20codes 全指标。

## 仓库现状（data/warehouse.duckdb + ASL lake，均 read_only）
9. 17 张表；dataset_snapshots=8（07-31×5、08-05 一 QUARANTINED 一 SCREEN_READY、08-06 SCREEN_READY），state_generations=4（均 ACTIVE）。
10. formal pointer：formal_screen_ready_pointer → snap-2026-08-06-e798f88ff67b；formal_state_generation_pointer → stategen-2026-08-06-a846075a5ac7（catchup 已推进到 08-06）。
11. snapshot_promotion_records=2（08-05 a28a5e93、08-06 02d4cb05，均 STAGED→SCREEN_READY）；state_generation_promotion_records=4；snapshot_governance_records=1（08-05 QUARANTINE: PRECLOSE_CONTINUITY_FAILURE）。
12. ASL lake：daily_bars 4,887,134 行，MAX trade_date=2026-08-13；news_headlines/flash_news_wire/dragon_tiger/fund_flow 等事件表均 0 行。

## 缺口清单
13. fetch_daily_delta：仅整文件 sha256 于 fetch-summary，无逐 code 的 source_files 精确清单并入 promotion 的 input_artifact_hashes（快路径不写 source_files 行，与 historical bootstrap 未对齐）。
14. derived_event：derived-summary 有 hash，但 promote_snapshot 只收 derived_event_hash 入 promotion 记录，data/lineage 无每事件级明细清单。
15. sentinel_check：跑在 build_state_generation 之后、写 daily-summary 之前，结果仅打印进 daily-summary，无独立 receipt/audit 表落库（无 sentinel 校验 hash 持久化）。
16. provenance 链：快路径 seed 复用（prev_gen_root）无「前置 generation 指纹回填」；ST_READY/PRODUCTION_CUTOVER 无对应正式指针表。

## 对账检查清单建议（daily-run fail-closed）
17. 前置：formal_screen_ready_pointer 与 formal_state_generation_pointer 均存在且 as_of=前一交易日，否则 abort。
18. 每步：fetch request_n==unique_keys 且 failures=0 → staging publish_eligible=true 且 conflicted=0 → promotion status=SCREEN_READY 且 pointer_after=新 id → stategen status=ACTIVE 且 pointer_after=新 id。
19. 收尾：daily-summary 的 snapshot/generation pointer_after 与两张 formal_pointer 表实时一致 + sentinel 全 PASS → 写入对账 receipt 后放行。

## ASL 现状一句话
ASL lake 价格数据已到 2026-08-13（领先本项目 formal pointer 7 个交易日），但 news_headlines/flash_news_wire/dragon_tiger 等事件与情绪表全部 0 行——「外部价格源可用、新闻面未接入」。

VERDICT: 每日 catchup 快路径已把 formal snapshot/state 指针推进到 2026-08-06 且各步 hash 齐全，但快路径缺逐行 source 清单、sentinel 无独立落库、新闻衍生源未接入，provenance 与生产切换仍处 OPEN/NO_GO。
