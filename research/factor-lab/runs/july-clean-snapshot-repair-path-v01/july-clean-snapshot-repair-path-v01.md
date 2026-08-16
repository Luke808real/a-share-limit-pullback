# JULY CLEAN SNAPSHOT REPAIR PATH V01 — 只读修复路径审计

- 状态：**REPAIR_PATH_DECISION = MINIMAL_PATCH_REQUIRED**（无现成安全路径；
  需最小 patch 引入独立 repair lineage）
- 日期：2026-08-16
- 分支：`audit/july-clean-snapshot-repair-path-v01`
- BASE_HEAD：f4738696519fc0eeb045d8031f5d4a3371465252

---

## 0. 背景

- 污染事实：TUSHARE 全市场批次 359774eea 在 07-09..07-24 无行 →
  silent-empty 被当成功 → CONFIRMED_N=0 × 12 sessions → 2026-07-31 snapshot
  与 T0 registry（22,393）被污染。
- 已关闭的代码缺陷：98432f0（bulk date presence fail-closed + pre-snapshot
  coverage gate + reuse gate）、f473869（historical lineage preservation）。
- 数据本体未修复。本轮只读确定"如何在保留旧 lineage 的前提下生成新的
  clean snapshot lineage"。

## 1. DETERMINISTIC RUN IDENTITY

```
CURRENT_BOOTSTRAP_RUN_ID_INPUTS:
  _run_id("bootstrap", start, end, codes_tuple, policy.policy_version)
  = sha256("bootstrap|2024-01-01|2026-07-31|{codes}|phase-2c2a-r1")[:24]

OLD_CONTAMINATED_RUN_ID:
  359774eea1675b329e747cbb（ingest_runs 确认：kind=bootstrap,
  all_main_board=true, policy=phase-2c2a-r1, start=2024-01-01,
  end=2026-07-31, COMPLETED）

SAME_ARGS_REGENERATE_SAME_RUN_ID:
  YES —— 同参数（start/end/codes/policy）重新 bootstrap 必然得到
  359774eea1675b329e747cbb；这是 sha256 纯函数，无随机成分。

FORCE_FINALIZE_MUTATES_OLD_LINEAGE:
  YES —— force_finalize=True 绕过 reuse gate 后调用 begin_ingest_run()，
  其 SQL 为 INSERT ... ON CONFLICT (run_id) DO UPDATE SET status='RUNNING',
  started_at=..., error=NULL —— 会原地改写 359774eea 的
  status/started_at/finished_at/error。f473869 的 guard 只保护"reuse
  校验失败"路径，不保护 force_finalize 主动改写。因此同参数 +
  force_finalize 是破坏 lineage 的，禁止用于 repair。
```

## 2. 现有安全路径检查

| 路径 | 新 run_id? | 补 07/09–24 TUSHARE? | 复用 AK/BS raw? | 重新 reconciliation? | 新 snapshot? | 不改旧 lineage? | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bootstrap（同参数） | 否（同 run_id） | 不适用（reuse gate 阻断） | — | — | — | 失败路径被 guard 保护；force_finalize 会污染 | 不可直接用于 repair |
| update | 是（"update" 前缀） | **否**——fetch 窗口仅 previous.as_of−7d..as_of，且继承旧 canonical（fallback 机制读旧 snapshot 的 CONFIRMED 历史） | 部分（fallback 旧行） | 是 | 是 | 是 | **不适合**：仅近 7 天增量，07/09–24 远在窗口外；且继承污染历史 |
| aux_backfill | 是（"aux-backfill" 前缀） | **否**——只抓 adj_factor/daily_basic/suspension/price_limits，**不抓 daily_bars** | — | 仅 preclose 重新发布 | RESEARCH_READY（基于旧 snapshot） | 是 | **不适合**：无 daily_bars 抓取 |
| daily_catchup / ops cmd_daily | 是（CATCHUP_/adr008-staging- 前缀） | 单 session 增量 | TDX/Tencent 新抓 | ADR008 staging | promote 新 snapshot | 是 | **不适合**：生产日更路径，逐日推进且继承旧 snapshot 基线；不是全量 clean rebuild |
| 其他 repair/backfill 入口 | 无 | — | — | — | — | — | 仓库中无其他 repair 入口 |

**EXISTING_REPAIR_PATH_FOUND = NO**：没有任何现成路径能在保留旧 lineage
的前提下生成新的全量 clean 2026-07-31 snapshot。

## 3. REPAIR_PATH_DECISION = MINIMAL_PATCH_REQUIRED

### 3a. 必须的最小 patch：独立 repair run identity

- 在 bootstrap 输入中引入 **repair lineage 标识**，纳入 `_run_id` 输入，
  例如 CLI 新增 `--repair-lineage <tag>`（或内部参数
  `repair_lineage: str | None = None`），run_id 变为：

  ```
  _run_id("bootstrap", start, end, codes_tuple, policy.policy_version,
          repair_lineage or "")
  ```

  任何非空 repair_lineage 都会生成与 359774eea 不同的全新 run_id →
  begin_ingest_run 创建全新 RUNNING 记录 → 旧 359774eea 记录分毫不动。

- 其余全部复用现有（已修复的）机制：
  - fetch_rows + require_date_presence=True（gap 日期缺行 → PENDING 失败）
  - pre-snapshot coverage gate（`_tushare_daily_missing_sessions`）
  - _stream_reconcile_market（新 run_id 的 raw 文件）
  - create_snapshot（新 snapshot_id）
  - finish_ingest_run(COMPLETED)（仅新 run）

- 这是"最小 contract"：不重构 pipeline、不改 metadata schema、不引入
  新架构。**本轮不实现，只定义。**

### 3b. 可选优化（单独 contract，不并入最小 patch）

- 若要求"仅补 07/09–24 TUSHARE + 复用已验证 AK/BS raw"（而不是全量
  重抓），需要额外扩展：
  - `_stream_reconcile_market` 接受多 run 输入（新 run 的 TUSHARE gap
    raw + 旧 run 的 AK/BS raw），或
  - repair 前将旧 run 的 AK/BS raw 文件复制进新 run_id 命名空间
    （文件级复制，不改旧文件）。
  - 该扩展改动面更大；如时间/网络成本可接受，全量重抓（3a）更简单、
    更符合 fail-closed 精神。**不作为本轮要求。**

## 4. OLD LINEAGE PRESERVED（f473869 之后）

- 新 repair run 使用全新 run_id → 旧 359774eea 的 status/started_at/
  finished_at/error/snapshot/manifest 全部保留（contaminated evidence）。
- reuse gate（COMPLETED_RUN_DAILY_COVERAGE_INVALID）不会改写旧记录
  （run_started_this_attempt guard）。
- 禁止 force_finalize 重跑旧 run（见 §1）。

## 5. POST-REPAIR GATES（冻结验收，本轮不执行）

修复完成后新 snapshot 的最低验收（runner 必须 fail-closed 实现）：

```
EXPECTED_JULY_SESSION_N = 23
07/09–07/24 TUSHARE session presence = 12/12
每个 gap date 的 TUSHARE code breadth 达到可信 full-market coverage
  （不得只检查 date present；需 code×date 计数与修复前正常日对齐）
CONFIRMED_N > 0 on all 23 July sessions
07/09–07/24 不得再出现 market-wide CONFIRMED_N = 0
old snapshot SHA unchanged（修复前记录）
old run metadata unchanged（359774eea 的 status/started_at/finished_at/error）
new snapshot:
  new SNAPSHOT_ID
  new content SHA
  new manifest / source lineage
```

## 6. ASL 边界

- 长期数据底座为 ASL（ashare-lake；其 daily_bars 在 07-09..07-24 已有
  tdx_protocol 全市场覆盖，可作为 repair 的参考/交叉验证源）。
- 本轮：NO ASL migration、NO adapter redesign。只解决被冻结研究数据的
  clean rebuild lineage。（ASL 数据是否可作为 TUSHARE gap 的替代输入，
  属 future 单独决策，不在本 patch contract 内。）

## 7. 本轮状态

```
DATA_REPAIR_AUTHORIZED = NO
T0_REBUILD_AUTHORIZED   = NO
TRANSITION_RERUN_AUTHORIZED = NO
```

- 禁止：network / live Tushare / raw mutation / warehouse mutation /
  reconciliation run / snapshot creation / T0 rebuild / transition rerun /
  strategy / production / forward / TradePlan / ASL migration。
