"""H9 v01: triple-volume (F19>=3) alone vs combined with B2 structural
condition. Population: resolved B2-stage episodes (B2_READY/B2_CONFIRMED,
outcome in WIN_S1/LOSS_INVALID/CANCEL_GAP_INVALID), frozen corrected
episodes (SHA 66d5943f...) + frozen snapshot snap-2026-07-31-b5f84004de8a
canonical bars. DESCRIPTIVE ONLY, no threshold search, no promotion.

Assumptions (stated in the report):
- b2 event date := signal_date for B2-stage episodes (frozen semantics).
- Structural condition (PIT on B2 day): close(B2) >= support_high (S_plat);
  robustness echo with close(B2) >= b2_trigger_price (S_trig).
- F19 needs a non-empty pullback window (anchor < bar < b2_date):
  days_since_anchor == 1 rows are reported as undefined, not imputed.
- Metrics are dual-lens (win share AND mean R among fills) because H10
  showed win share alone can misjudge odds-type effects.
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
B2_STAGES = ("B2_READY", "B2_CONFIRMED")
GROUPS = ("WIN_S1", "LOSS_INVALID", "CANCEL_GAP_INVALID")
OUT_DIR = Path("research/factor-lab/runs/h9-v01")
STARTED = time.time()


def _log(msg: str) -> None:
    print(f"[{time.time() - STARTED:7.1f}s] {msg}", flush=True)


def _parse_r(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(EPISODES.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise SystemExit(f"episodes hash mismatch: {sha}")
    _log("episodes hash verified")

    con = duckdb.connect()
    rows = con.execute(
        "SELECT code, setup_stage, anchor_date, signal_date, days_since_anchor, "
        "support_high, b2_trigger_price, outcome, r_multiple FROM read_parquet(?) "
        "WHERE setup_stage IN ('B2_READY', 'B2_CONFIRMED')"
        " AND outcome IN ('WIN_S1', 'LOSS_INVALID', 'CANCEL_GAP_INVALID')",
        [str(EPISODES)],
    ).fetchall()
    episodes = [
        {
            "code": r[0],
            "setup_stage": r[1],
            "anchor": date.fromisoformat(str(r[2])),
            "signal": date.fromisoformat(str(r[3])),
            "days_since_anchor": r[4],
            "support_high": Decimal(str(r[5])),
            "trigger": Decimal(str(r[6])),
            "outcome": r[7],
            "r": _parse_r(r[8]),
        }
        for r in rows
    ]
    _log(f"B2-stage resolved episodes: {len(episodes)}")

    by_code: dict[str, list[dict]] = {}
    for ep in episodes:
        by_code.setdefault(ep["code"], []).append(ep)

    layout = _layout()
    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snapshot = md.snapshot_by_id(SNAPSHOT_ID)
    if snapshot is None or snapshot.status != "SCREEN_READY":
        raise SystemExit(f"frozen snapshot unavailable: {snapshot}")

    groups: dict[str, dict] = {
        "base": {"n": 0, "wins": 0, "r": []},
        "triple_only": {"n": 0, "wins": 0, "r": []},
        "triple_struct": {"n": 0, "wins": 0, "r": []},
    }
    stage_split: dict[str, dict] = {g: {"B2_READY": 0, "B2_CONFIRMED": 0} for g in groups}
    undefined_f19 = 0
    missing_trigger = 0
    processed = 0
    f19_values: list[float] = []

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
            try:
                f19 = fl.b2_volume_vs_pullback_mean(bars, ep["anchor"], ep["signal"])
            except ValueError:
                f19 = None
            if f19 is None:
                undefined_f19 += 1
                continue
            by_date = {b.trade_date: b for b in bars}
            b2_bar = by_date.get(ep["signal"])
            if b2_bar is None:
                missing_trigger += 1
                continue
            triple = f19 >= Decimal("3")
            s_plat = b2_bar.close >= ep["support_high"]
            s_trig = b2_bar.close >= ep["trigger"]
            structure = s_plat and s_trig
            if not triple:
                key = "base"
            elif structure:
                key = "triple_struct"
            else:
                key = "triple_only"
            f19_values.append(float(f19))
            g = groups[key]
            g["n"] += 1
            if ep["outcome"] == "WIN_S1":
                g["wins"] += 1
            if ep["r"] is not None:
                g["r"].append(ep["r"])
            stage_split[key][ep["setup_stage"]] += 1
        processed += 1
        if processed % 500 == 0:
            _log(f"codes processed: {processed}")

    def summarize(g: dict) -> dict:
        n = g["n"]
        win = round(g["wins"] / n, 4) if n else None
        mean_r = round(sum(g["r"]) / len(g["r"]), 4) if g["r"] else None
        win_r = [x for x in g["r"] if x > 0]
        mean_r_given_win = (
            round(sum(win_r) / len(win_r), 4) if win_r else None
        )
        return {
            "n": n,
            "win_share": win,
            "n_with_r": len(g["r"]),
            "mean_r_fills": mean_r,
            "mean_r_given_win": mean_r_given_win,
        }

    def _q(values: list[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(int(q * len(ordered)), len(ordered) - 1)]

    payload = {
        "inputs": {
            "episodes": str(EPISODES),
            "episodes_sha256": sha,
            "snapshot_id": SNAPSHOT_ID,
        },
        "population": {"b2_stage_resolved": len(episodes), "undefined_f19": undefined_f19, "missing_b2_bar": missing_trigger},
        "f19_quantiles": {
            "n": len(f19_values),
            "p50": _q(f19_values, 0.50),
            "p75": _q(f19_values, 0.75),
            "p90": _q(f19_values, 0.90),
            "p95": _q(f19_values, 0.95),
            "p99": _q(f19_values, 0.99),
            "max": max(f19_values) if f19_values else None,
        },
        "groups": {k: summarize(v) for k, v in groups.items()},
        "stage_split": stage_split,
    }
    out = OUT_DIR / "h9-v01.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _log(f"stats -> {out}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
