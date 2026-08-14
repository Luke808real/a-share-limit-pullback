# BAR_TIMESTAMP_SEMANTICS_QA

Date of QA: 2026-08-05（Day 1 之前；实现 QA，不修改 protocol hash）
Data: 本地 5m/1m 缓存（AKSHARE/SINA）

## 结论

BAR_TIMESTAMP_MEANS = BAR_END_TIME

## 证据

1. 5m（002642，2026-07-28）：
   - 首根 bar timestamp 09:35，open = 6.65 = 当日 daily open（09:30 集合竞价价）
     → 09:35 bar 覆盖 09:30-09:35，timestamp 为 bar 结束时间。
   - 末根 bar timestamp 15:00，close = 7.26 = daily close
     → 15:00 bar 覆盖 14:55-15:00（含收盘竞价），结束时间语义。
   - 连续 5 分钟间隔 09:35→09:40→…→15:00。
2. 1m（600468，2026-08-03）：
   - 首根 bar 09:31，open = 5.76 = daily open → 09:31 bar = 09:30-09:31（end）。
   - 末根 15:00 close = daily close。
3. 5m 连续性与 OHLC 自洽：无异常 gap、无重复 timestamp。

## Checkpoint 最后完整 bar（bar-end 语义）

- CHECKPOINT_0945_MAX_INFORMATION_TIME ≤ 09:45:00
  → CHECKPOINT_0945_LAST_BAR = timestamp 09:45（bar 09:40-09:45）
- CHECKPOINT_1000_MAX_INFORMATION_TIME ≤ 10:00:00
  → CHECKPOINT_1000_LAST_BAR = timestamp 10:00（bar 09:55-10:00）

runner 使用 `tt <= checkpoint`（包含 09:45 / 10:00 当根 bar），与 end-time
语义一致；不使用任何覆盖 09:45-09:50 的数据。

FUTURE_LEAKAGE = 0
PROTOCOL_HASH 不变（实现 QA）
