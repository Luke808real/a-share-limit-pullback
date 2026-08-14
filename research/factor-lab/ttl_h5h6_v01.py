"""H2/TTL + F14 robustness + H5/H6 first pass (v01).

Part 1 (pure parquet): days_since_anchor buckets x outcome — the TTL decay
curve (NO_FILL share + resolved WIN share per bucket).
Part 2 (bars): F14 split by setup_stage; F19 (B2 volume vs pullback mean);
F21 (next-day close under support_low) for B2 rows.

DESCRIPTIVE ONLY. No thresholds tuned, no promotion. Frozen inputs:
episodes SHA 66d5943f... + snap-2026-07-31-b5f84004de8a.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from limit_pullback import factor_lab as fl
from limit_pullback.ops import _layout
from limit_pullback.screen.canonical import iter_canonical_code_bars
from limit_pullback.warehouse.metadata import WarehouseMetadata

EPISODES = Path(
    "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    "/corrected-b2-trigger-outcome/episodes.parquet"
)
EXPECTED_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
SNAPSHOT_AS_OF = date(2026, 7, 31)
OUT_DIR = Path("research/factor-lab/runs/ttl-h5h6-v01")
STARTED = time.time()
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")


def _log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", flush=True)


def _median(values) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal("2")


def _bucket(days: int) -> str:
    if days <= 5:
        return str(days)
    if days <= 10:
        return "6-10"
    return "11+"


def part1() -> dict:
    con = duckdb.connect()
    rows = con.execute(
        "SELECT days_since_anchor, outcome FROM read_parquet(?) WHERE outcome IS NOT NULL",
        [str(EPISODES)],
    ).fetchall()
    buckets: dict[str, dict[str, int]] = {}
    for days, outcome in rows:
        b = _bucket(int(days))
        d = buckets.setdefault(b, {})
        d[outcome] = d.get(outcome, 0) + 1
    out = {}
    for b in sorted(buckets, key=lambda k: int(k) if k.isdigit() else (10 if k == "6-10" else 100)):
        d = buckets[b]
        total = sum(d.values())
        resolved = sum(d.get(g, 0) for g in GROUPS)
        wins = d.get("WIN_S1", 0)
        out[b] = {
            "n": total,
            "no_fill_share": round(d.get("NO_FILL", 0) / total, 4),
            "resolved_n": resolved,
            "win_share_of_resolved": round(wins / resolved, 4) if resolved else None,
        }
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes_sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if episodes_sha != EXPECTED_SHA:
        raise SystemExit(f"episodes hash mismatch: {episodes_sha}")
    _log("hash verified")

    ttl = part1()
    _log(f"ttl buckets: {json.dumps(ttl)}")

    con = duckdb.connect()
    rows = con.execute(
        "SELECT code, setup_stage, anchor_date, signal_date, outcome, support_low "
        "FROM read_parquet(?)",
        [str(EPISODES)],
    ).fetchall()
    episodes = [
        {
            "code": r[0],
            "stage": r[1],
            "anchor": date.fromisoformat(str(r[2])),
            "signal": date.fromisoformat(str(r[3])),
            "outcome": r[4],
            "support_low": r[5],
        }
        for r in rows
        if r[4] in GROUPS
    ]
    by_code: dict[str, list[dict]] = {}
    for ep in episodes:
        by_code.setdefault(ep["code"], []).append(ep)
    _log(f"resolved episodes for factors: {len(episodes)} over {len(by_code)} codes")

    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id(SNAPSHOT_ID)
    if snapshot is None or snapshot.status != "SCREEN_READY":
        raise SystemExit("frozen snapshot unavailable")

    f14_by_stage: dict[str, dict[str, list]] = {}
    f19: dict[str, list] = {}
    f21: dict[str, dict[str, int]] = {}
    processed = 0
    for code, eps in by_code.items():
        bars = next(
            (
                b
                for c, b in iter_canonical_code_bars(
                    layout, snapshot, codes=[code], as_of=SNAPSHOT_AS_OF
                )
                if c == code
            ),
            (),
        )
        if not bars:
            continue
        by_date = {bar.trade_date: bar for bar in sorted(bars, key=lambda b: b.trade_date)}
        for ep in eps:
            stage = ep["stage"]
            outcome = ep["outcome"]
            key = f"{stage}|{outcome}"
            value = None
            try:
                value = fl.pullback_min_volume_ratio(bars, ep["anchor"], ep["signal"])
            except ValueError:
                value = None
            if value is not None:
                f14_by_stage.setdefault(key, []).append(value)
            if stage in ("B2_READY", "B2_CONFIRMED"):
                try:
                    v19 = fl.b2_volume_vs_pullback_mean(bars, ep["anchor"], ep["signal"])
                except ValueError:
                    v19 = None
                if v19 is not None:
                    f19.setdefault(outcome, []).append(v19)
                if ep["support_low"]:
                    try:
                        support = Decimal(str(ep["support_low"]))
                        next_days = [d for d in by_date if d > ep["signal"]]
                        if next_days:
                            under = by_date[min(next_days)].close < support
                            bucket = f21.setdefault(outcome, {"under": 0, "total": 0})
                            bucket["total"] += 1
                            if under:
                                bucket["under"] += 1
                    except Exception:
                        pass
        processed += 1
        if processed % 500 == 0:
            _log(f"codes: {processed}")

    f14_stats = {}
    for key, values in f14_by_stage.items():
        if len(values) < 20:
            continue
        f14_stats[key] = {
            "n": len(values),
            "median": str(_median(values)),
            "mean": str(sum(values, Decimal("0")) / Decimal(len(values))),
        }
    f19_stats = {}
    for outcome, values in f19.items():
        if len(values) < 20:
            continue
        f19_stats[outcome] = {
            "n": len(values),
            "median": str(_median(values)),
            "mean": str(sum(values, Decimal("0")) / Decimal(len(values))),
        }
    f21_stats = {
        outcome: {"n": b["total"], "under_share": round(b["under"] / b["total"], 4) if b["total"] else None}
        for outcome, b in f21.items()
        if b["total"] >= 20
    }

    payload = {
        "inputs": {"episodes": str(EPISODES), "episodes_sha256": episodes_sha, "snapshot_id": SNAPSHOT_ID},
        "ttl_buckets": ttl,
        "f14_by_stage_outcome": f14_stats,
        "f19_b2_volume_by_outcome": f19_stats,
        "f21_under_support_share": f21_stats,
    }
    out_json = OUT_DIR / "ttl-h5h6-v01.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"written: {out_json}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
