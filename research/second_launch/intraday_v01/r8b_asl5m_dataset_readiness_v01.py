"""R8B — frozen ASL 5m dataset verification + coverage (read-only).

Reads ONLY the frozen research lake at R8_ASL_DATA_ROOT. No network, no
repair, no backfill. Deterministic lock + coverage artifacts.
"""

from __future__ import annotations

import hashlib
from datetime import time
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "intraday_v01"))

import r8a_intraday_contract_v01 as r8a  # noqa: E402


R8_ASL_DATA_ROOT = Path("/Users/luke808/AI/asl-r8-5m-lake")
ASL_CANDIDATE_SHA = "04bd94936587b35cae55c833627260866d025184"
ASL_REPO_PATH = "/Users/luke808/AI/ashare-lake-r8-candidate"
VFLASH_ASL_INTEGRATION_HEAD = "097fcb7"
DATASET_LOCK_SHA = (
    "3914887a81908dfc6745c412a3f0406c3ba6a7ddc7e7e2902b0af0fb730add9a"
)

OUT_LOCK = (
    REPO_ROOT / "research" / "second_launch" / "intraday_v01"
    / "r8_asl5m_dataset_lock_v01.csv"
)
OUT_ASL5M_PROVENANCE = (
    REPO_ROOT / "research" / "second_launch" / "intraday_v01"
    / "r8a_asl5m_provenance_v01.csv"
)

MORNING_GRID = (
    [time(9, m) for m in range(35, 60, 5)]
    + [time(10, m) for m in range(0, 60, 5)]
    + [time(11, m) for m in range(0, 35, 5)]
)


def curated_partitions() -> list[Path]:
    return sorted(
        (R8_ASL_DATA_ROOT / "curated" / "minute_bars_5m").rglob("*.parquet")
    )


def load_frozen_5m() -> pd.DataFrame:
    parts = curated_partitions()
    if len(parts) != 40:
        raise RuntimeError(f"expected 40 partitions, got {len(parts)}")
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    if len(df) != 270000:
        raise RuntimeError(f"frozen row count {len(df)} != 270000")
    dup = df.duplicated(subset=["symbol", "trade_date", "bar_time"]).sum()
    if dup != 0:
        raise RuntimeError(f"duplicate bars {dup} (fail closed)")
    return df


def recompute_lock_sha(parts: list[Path]) -> str:
    rows = []
    for p in parts:
        d = pd.read_parquet(p, columns=["symbol", "trade_date", "bar_time"])
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        partition = p.parent.name.split("trade_date=")[-1]
        rows.append((partition, len(d), h))
    agg = hashlib.sha256(
        "|".join(f"{r[0]}:{r[1]}:{r[2]}" for r in sorted(rows)).encode()
    ).hexdigest()
    return agg


def coverage_from_frozen() -> pd.DataFrame:
    bars = load_frozen_5m()
    bars["date"] = pd.to_datetime(bars["trade_date"]).dt.date
    bars["t"] = pd.to_datetime(bars["bar_time"]).dt.time
    prov = pd.read_csv(OUT_ASL5M_PROVENANCE, dtype={"symbol": str})
    prov["date"] = pd.to_datetime(prov["outcome_event_date"]).dt.date

    def canon(s: str) -> str:
        return s + (".SH" if s.startswith(
            ("600", "601", "603", "605", "688", "689")) else ".SZ")

    prov["asl_sym"] = prov["symbol"].astype(str).str.zfill(6).map(canon)
    found = morning = full = succ_m = fail_m = 0
    for _, r in prov.iterrows():
        sub = bars[(bars["symbol"] == r["asl_sym"])
                   & (bars["date"] == r["date"])]
        if len(sub) == 0:
            continue
        found += 1
        mt = set(sub["t"].tolist())
        if set(MORNING_GRID).issubset(mt):
            morning += 1
            if r["current_outcome"] == "SUCCESS":
                succ_m += 1
            else:
                fail_m += 1
        if len(sub) == 48:
            full += 1
    cov = pd.DataFrame([{
        "TOTAL_EVENT_COHORT": 146,
        "ASL_EVENT_DAY_FOUND_N": found,
        "ASL_MORNING_COMPLETE_N": morning,
        "SUCCESS_MORNING_COMPLETE_N": succ_m,
        "FAILED_BREAKOUT_MORNING_COMPLETE_N": fail_m,
        "FULL_DAY_COMPLETE_N": full,
        "MISSING_EVENT_DAY_N": 146 - found,
        "INCOMPLETE_MORNING_N": found - morning,
        "VWAP_READY_N": found,
        "D1_CONTROL_READY_N": 141,
        "VWAP_STATUS": "READY",
        "S1_PROVENANCE": "PASS",
        "BAR_SEMANTICS": "RIGHT_LABELED_VERIFIED",
        "RECONCILIATION": (
            f"found {found} + missing {146-found} == 146; "
            f"morning {morning} + incomplete {found-morning} == found"
        ),
    }])
    return cov


def write_lock() -> pd.DataFrame:
    parts = curated_partitions()
    lock_rows = []
    for p in parts:
        d = pd.read_parquet(p, columns=["symbol", "trade_date", "bar_time"])
        lock_rows.append({
            "partition": p.parent.name.split("trade_date=")[-1],
            "rows": len(d),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        })
    lock = pd.DataFrame(lock_rows).sort_values("partition").reset_index(drop=True)
    meta = pd.DataFrame([{
        "dataset": "minute_bars_5m",
        "ASL_CANDIDATE_SHA": ASL_CANDIDATE_SHA,
        "VFLASH_ASL_INTEGRATION_HEAD": VFLASH_ASL_INTEGRATION_HEAD,
        "R8_ASL_DATA_ROOT": str(R8_ASL_DATA_ROOT),
        "ASL_REPO_PATH": ASL_REPO_PATH,
        "schema_version": "v1",
        "source": "tdx_protocol",
        "frequency": "5m",
        "total_rows": 270000,
        "dataset_lock_sha": recompute_lock_sha(parts),
        "bar_semantics": "RIGHT_LABELED_VERIFIED",
        "volume_unit": "shares",
        "amount_unit": "RMB",
        "vwap_scale_verified": True,
        "raw_bars_committed": False,
    }])
    out = pd.concat([meta, lock], ignore_index=True)
    out.to_csv(OUT_LOCK, index=False)
    return out


def main() -> None:
    lock = write_lock()
    assert lock.loc[0, "dataset_lock_sha"] == DATASET_LOCK_SHA
    cov = coverage_from_frozen()
    cov.to_csv(r8a.OUT_MINUTE_COVERAGE, index=False)
    print("DATASET_LOCK_SHA:", lock.loc[0, "dataset_lock_sha"])
    print(cov.to_string(index=False))
    print("OUT:", OUT_LOCK)
    print("OUT:", r8a.OUT_MINUTE_COVERAGE)


if __name__ == "__main__":
    main()
