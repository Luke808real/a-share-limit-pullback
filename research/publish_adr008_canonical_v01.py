"""ADR-008 production canonical publish (research-orchestrated, production data layer).

Publishes staged TDX+Tencent CONFIRMED catch-up rows (2026-08-03..05) into a new
immutable canonical snapshot, reusing the existing warehouse create_snapshot
atomic publish path. Old snapshot files are never modified.

No strategy changes; no Forward ledger writes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limit_pullback.warehouse.layout import WarehouseLayout, resolve_data_root  # noqa: E402
from limit_pullback.warehouse.metadata import WarehouseMetadata  # noqa: E402
from limit_pullback.warehouse.parquet import read_rows, sha256_file  # noqa: E402
from limit_pullback.warehouse.snapshot import create_snapshot  # noqa: E402


OLD_ID = "snap-2026-07-31-b5f84004de8a"
AS_OF = date(2026, 8, 5)
CATCH = ROOT / "data/tmp/canonical-catchup-2026-08"


def old_hashes(layout: WarehouseLayout) -> dict:
    daily = layout.canonical_daily_dir / f"{OLD_ID}.parquet"
    pool = layout.canonical_pool_dir / f"{OLD_ID}.parquet"
    man = layout.manifests_dir / f"{OLD_ID}.json"
    return {
        "daily_sha256": sha256_file(daily),
        "pool_sha256": sha256_file(pool),
        "manifest_sha256": sha256_file(man),
    }


def main() -> None:
    layout = WarehouseLayout(resolve_data_root())
    before = old_hashes(layout)
    print("OLD_SNAPSHOT_HASHES_BEFORE:", json.dumps(before, indent=2))

    old_rows = read_rows(layout.canonical_daily_dir / f"{OLD_ID}.parquet")
    old_pool = read_rows(layout.canonical_pool_dir / f"{OLD_ID}.parquet")
    print("OLD_DAILY_ROW_N:", len(old_rows), "OLD_POOL_ROW_N:", len(old_pool))

    new_rows = []
    for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
        df = pd.read_parquet(CATCH / f"{d}.parquet")
        df = df[df["reconciliation_status"] == "CONFIRMED"].copy()
        if len(df) != df[["code", "trade_date"]].drop_duplicates().shape[0]:
            raise SystemExit("STOP: duplicate code+date in staged CONFIRMED")
        if df[["open", "high", "low", "close", "volume", "amount"]].isna().any().any():
            raise SystemExit("STOP: NaN OHLCV in staged CONFIRMED")
        if (df["preclose"].isna()).any():
            n_drop = int(df["preclose"].isna().sum())
            print(f"WARN {d}: dropping {n_drop} rows with missing preclose")
            df = df[df["preclose"].notna()]
        from decimal import Decimal

        for _, r in df.iterrows():
            new_rows.append({
                "code": r["code"],
                "trade_date": date.fromisoformat(d),
                "open": Decimal(str(r["open"])),
                "high": Decimal(str(r["high"])),
                "low": Decimal(str(r["low"])),
                "close": Decimal(str(r["close"])),
                "preclose": Decimal(str(r["preclose"])),
                "volume": Decimal(str(r["volume"])),
                "amount": Decimal(str(r["amount"])),
                "turnover_rate": None,
                "pct_change": Decimal(str(r["pct_change"])) if r["pct_change"] is not None else None,
                "trade_status": True,
                "is_st": None,
                "selected_provider": "TDX",
                "reconciliation_status": "CONFIRMED",
                "source_row_hash": r["source_row_hash"],
            })
        print(d, "confirmed rows to publish:", int((df["code"]).size))

    daily_rows = old_rows + new_rows
    print("NEW_DAILY_ROW_N:", len(daily_rows), "NEW_ROWS:", len(new_rows))

    metadata = WarehouseMetadata(layout.duckdb_path)
    import importlib.metadata as md

    record = create_snapshot(
        layout=layout,
        metadata=metadata,
        as_of=AS_OF,
        provider_versions={
            "TDX": md.version("pytdx"),
            "TENCENT": md.version("akshare"),
        },
        daily_rows=daily_rows,
        pool_rows=old_pool,
        source_file_hashes={
            str(CATCH / "raw_tdx_full.parquet"): sha256_file(CATCH / "raw_tdx_full.parquet"),
            str(CATCH / "raw_tencent_full.parquet"): sha256_file(CATCH / "raw_tencent_full.parquet"),
        },
        reconciliation_policy_version="ADR-008",
        status="CURRENT",
    )
    metadata.close()
    after = old_hashes(layout)
    print("OLD_SNAPSHOT_UNCHANGED:", before == after)
    print("NEW_SNAPSHOT_ID:", record.snapshot_id)
    daily_path = layout.canonical_daily_dir / f"{record.snapshot_id}.parquet"
    man_path = layout.manifests_dir / f"{record.snapshot_id}.json"
    print("NEW_SNAPSHOT_HASH:", sha256_file(daily_path))
    print("NEW_MANIFEST_HASH:", sha256_file(man_path))

    # QA on new snapshot
    new_daily = pd.read_parquet(daily_path)
    new_daily["trade_date"] = pd.to_datetime(new_daily["trade_date"]).dt.date
    old_df = pd.read_parquet(layout.canonical_daily_dir / f"{OLD_ID}.parquet")
    old_df["trade_date"] = pd.to_datetime(old_df["trade_date"]).dt.date
    hist_new = new_daily[new_daily["trade_date"] <= date(2026, 7, 31)].sort_values(["code", "trade_date"]).reset_index(drop=True)
    hist_old = old_df.sort_values(["code", "trade_date"]).reset_index(drop=True)
    qa = {
        "total_row_n": len(new_daily),
        "20260803_row_n": int((new_daily["trade_date"] == date(2026, 8, 3)).sum()),
        "20260804_row_n": int((new_daily["trade_date"] == date(2026, 8, 4)).sum()),
        "20260805_row_n": int((new_daily["trade_date"] == date(2026, 8, 5)).sum()),
        "confirmed_row_n": int((new_daily["reconciliation_status"] == "CONFIRMED").sum()),
        "duplicate_row_n": int(new_daily.duplicated(subset=["code", "trade_date"]).sum()),
        "max_trade_date": str(new_daily["trade_date"].max()),
        "historical_row_count_diff": len(hist_new) - len(hist_old),
    }
    merge = hist_new.merge(hist_old, on=["code", "trade_date"], suffixes=("_n", "_o"))
    ohlc_diff = int(
        ((merge["open_n"].astype(float) != merge["open_o"].astype(float)) |
         (merge["high_n"].astype(float) != merge["high_o"].astype(float)) |
         (merge["low_n"].astype(float) != merge["low_o"].astype(float)) |
         (merge["close_n"].astype(float) != merge["close_o"].astype(float)) |
         (merge["volume_n"].astype(float) != merge["volume_o"].astype(float)) |
         (merge["amount_n"].astype(float) != merge["amount_o"].astype(float))).sum()
    )
    qa["historical_ohlcv_diff_n"] = ohlc_diff
    json.dump(qa, open(ROOT / "research/data-source-migration-v01/publish_qa_v01.json", "w"), ensure_ascii=False, indent=2)
    print("QA:", json.dumps(qa, ensure_ascii=False, indent=2))
    # staged -> production exact match for sample codes
    staged = pd.concat([pd.read_parquet(CATCH / f"{d}.parquet") for d in ("2026-08-03", "2026-08-04", "2026-08-05")])
    staged["trade_date"] = pd.to_datetime(staged["trade_date"]).dt.date
    for code in ("600756", "603980", "000001", "600000"):
        s = staged[(staged["code"] == code) & (staged["reconciliation_status"] == "CONFIRMED")][["trade_date", "open", "high", "low", "close", "volume", "amount"]]
        p = new_daily[new_daily["code"] == code][["trade_date", "open", "high", "low", "close", "volume", "amount"]]
        m = s.merge(p, on="trade_date", suffixes=("_s", "_p"))
        ok = len(m) > 0 and all(
            (m[f"{k}_s"].astype(float) == m[f"{k}_p"].astype(float)).all() for k in ("open", "high", "low", "close", "volume", "amount")
        )
        print(code, "staged->prod exact:", ok, "rows:", len(m))


if __name__ == "__main__":
    main()
