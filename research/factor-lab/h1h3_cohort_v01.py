"""H1-H3 cohort study v01: T0 quality / pullback timing / volume contraction
vs execution outcome (WIN_S1 / LOSS_INVALID / CANCEL_GAP_INVALID).

DESCRIPTIVE ONLY. No threshold search, no parameter tuning, no promotion.
Inputs: frozen corrected episodes (SHA 66d5943f...) + frozen snapshot
snap-2026-07-31-b5f84004de8a canonical bars. Conclusions use
REJECT / OBSERVE_ONLY / SUPPORTED and are written into the report.

Honest limitations (stated in the report):
- outcome labels are EXECUTION outcomes under the frozen T+1 model, not a
  direct "second wave happened" label; NO_FILL (20897) censors two thirds of
  signals and is reported separately.
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
EXPECTED_EPISODES_SHA = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
SNAPSHOT_AS_OF = date(2026, 7, 31)
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
FACTORS = (
    ("F01_t0_position_60", "anchor"),
    ("F02_dist_from_120d_high", "anchor"),
    ("F06_t0_turnover", "anchor"),
    ("F07_t0_volume_vs_20d", "anchor"),
    ("F09_pullback_depth", "signal"),
    ("F11_trough_index", "signal"),
    ("F14_min_volume_ratio", "signal"),
)
OUT_DIR = Path("research/factor-lab/runs/h1h3-v01")
STARTED = time.time()


def _log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", flush=True)


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal("2")


def _percentile(values: list[Decimal], q: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(q * Decimal(len(ordered) - 1))
    return ordered[index]


def _compute(code: str, anchor: date, as_of: date, bars, row: dict, buckets: dict) -> None:
    outcome = row["outcome"]
    if outcome not in GROUPS:
        return
    for name, kind in FACTORS:
        try:
            if name == "F01_t0_position_60":
                value = fl.t0_position_60(bars, anchor)
            elif name == "F02_dist_from_120d_high":
                value = fl.dist_from_120d_high_pct(bars, anchor)
            elif name == "F06_t0_turnover":
                value = fl.t0_turnover(bars, anchor)
            elif name == "F07_t0_volume_vs_20d":
                value = fl.t0_volume_vs_20d_mean(bars, anchor)
            elif name == "F09_pullback_depth":
                value = fl.pullback_depth_pct(bars, anchor, as_of)
            elif name == "F11_trough_index":
                value = fl.pullback_trough_index(bars, anchor, as_of)
            elif name == "F14_min_volume_ratio":
                value = fl.pullback_min_volume_ratio(bars, anchor, as_of)
            else:
                continue
        except ValueError:
            value = None
        if value is None:
            continue
        buckets[name].setdefault(outcome, []).append(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes_sha = _sha256(EPISODES)
    if episodes_sha != EXPECTED_EPISODES_SHA:
        raise SystemExit(f"episodes hash mismatch: {episodes_sha}")
    _log("episodes hash verified")

    con = duckdb.connect()
    rows = con.execute(
        "SELECT code, setup_stage, anchor_date, signal_date, days_since_anchor, outcome "
        "FROM read_parquet(?)",
        [str(EPISODES)],
    ).fetchall()
    episodes = [
        {
            "code": r[0],
            "setup_stage": r[1],
            "anchor": date.fromisoformat(str(r[2])),
            "signal": date.fromisoformat(str(r[3])),
            "days_since_anchor": r[4],
            "outcome": r[5],
        }
        for r in rows
    ]
    _log(f"episodes loaded: {len(episodes)}")

    by_code: dict[str, list[dict]] = {}
    excluded: dict[str, int] = {}
    for ep in episodes:
        if ep["outcome"] not in GROUPS:
            excluded[ep["outcome"]] = excluded.get(ep["outcome"], 0) + 1
            continue
        by_code.setdefault(ep["code"], []).append(ep)
    _log(f"resolved episodes: {sum(len(v) for v in by_code.values())} over {len(by_code)} codes; excluded={excluded}")

    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id(SNAPSHOT_ID)
    if snapshot is None or snapshot.status != "SCREEN_READY":
        raise SystemExit(f"frozen snapshot unavailable: {snapshot}")
    buckets: dict[str, dict[str, list]] = {name: {} for name, _ in FACTORS}
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
        for ep in eps:
            _compute(code, ep["anchor"], ep["signal"], bars, ep, buckets)
        processed += 1
        if processed % 500 == 0:
            _log(f"codes processed: {processed}")

    stats: dict[str, dict] = {}
    for name, by_outcome in buckets.items():
        stats[name] = {}
        for outcome in GROUPS:
            values = by_outcome.get(outcome, [])
            if not values:
                stats[name][outcome] = None
                continue
            stats[name][outcome] = {
                "n": len(values),
                "median": str(_median(values)),
                "mean": str(sum(values, Decimal("0")) / Decimal(len(values))),
                "p25": str(_percentile(values, Decimal("0.25"))),
                "p75": str(_percentile(values, Decimal("0.75"))),
            }

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": episodes_sha,
            "snapshot_id": SNAPSHOT_ID,
        },
        "groups": GROUPS,
        "excluded_outcomes": excluded,
        "stats": stats,
    }
    out_json = OUT_DIR / "factor-cohorts-v01.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"stats -> {out_json}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
