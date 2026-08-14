# daily-run-20260814 运行手册索引（2026-08-14 真实盘后流程的脚本与证据）

当日完成：真实链条 08-07/08-10/11/12/13 推进、B2 语义评审、asl fast 集成、
重建耗时优化、测试套件提速。以下为脚本与证据清单。

## 脚本

- probe_providers_20260807.py — 三源真实输入探测（baostock/tencent/tdx）
- self_review.py — 通用独立自评审（FULL/GATE 两种期望模式）
- self_review_20260807.py — 08-07 专用评审（已归档）
- rebuild_generation_20260810.py — 08-10 代全量重建（B2 单调修复后）
- complete_tail_20260810.py — 08-10 链条尾部补齐（plan/brief/watchlist/reconcile）
- bench_fetch_20260814.py — 冷抓取基准（并发+workers 测量）
- equiv_check_20260810.py / equiv_check_v2_20260810.py — 黄金等价校验
  （v1 有 formal-pointer 解析缺陷；v2 显式 pin 快照，为权威版本）

## 证据

- rounds-log.md — 逐轮命令、exit code、差异、测试、产物证据
- self-review-20260807/10/11/12/13.json — 各会话自评审结果

## 关联文档

- research/b2-semantic-review-2026-08-14/RESOLUTION.md — B2 单调性决议（D-026）
- docs/ARCHITECTURE_GOAL.md — 三层架构目标
- docs/agent-reports/2026-08-14/ — 四 Agent 开篇审计
