"""HISTORICAL_ANALOG_ENGINE_V0.1 (research-only, no production change).

PIT analog search: each observation uses only data <= T. Fingerprint =
20-session normalized price shape + volume/MA20 shape + level features.
Similarity = standardized feature distance + normalized price-shape distance
(explainable, no neural nets, no threshold scan).

Stage-filtered libraries: B1_READY (PREPOSITION-like proxy), B2_READY,
B2_CONFIRMED (LAUNCH_READY proxy). Forward paths (MFE/MAE/return/new-high/
S1/invalid/second-launch timing) are read only after analog selection.

Output: data/tmp/historical-analog-engine-v01/metrics.json
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from limit_pullback.screen.canonical import (
    iter_canonical_code_bars,
    load_canonical_metadata,
)
from limit_pullback.warehouse.layout import WarehouseLayout


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODES_DIR = (
    DATA_ROOT
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome"
)
EOD_PARQUET = DATA_ROOT / "tmp" / "eod-recovery-2026-08-03" / "eod_20260803.parquet"
OUT_DIR = DATA_ROOT / "tmp" / "historical-analog-engine-v01"
WINDOW = 20
STAGE_OF_LABEL = {"B1_READY": "PREPOSITION", "B2_READY": "B2_READY", "B2_CONFIRMED": "LAUNCH_READY"}


def _ema(values, n):
    if not values:
        return []
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def adx(highs, lows, closes, n=14):
    if len(closes) <= 2 * n:
        return None
    trs, pds, mds = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pds.append(up if up > dn and up > 0 else 0)
        mds.append(dn if dn > up and dn > 0 else 0)
        trs.append(tr)
    atr = sum(trs[:n]) / n
    pdi = sum(pds[:n]) / n
    mdi = sum(mds[:n]) / n
    for i in range(n, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        pdi = (pdi * (n - 1) + pds[i]) / n
        mdi = (mdi * (n - 1) + mds[i]) / n
    dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0
    return dx


def fingerprint(bar_list, idx):
    """20-session PIT fingerprint ending at idx (inclusive)."""

    if idx + 1 < WINDOW + 20:
        return None
    start = idx - WINDOW + 1
    closes = [float(b.close) for b in bar_list[start : idx + 1]]
    highs = [float(b.high) for b in bar_list[start : idx + 1]]
    lows = [float(b.low) for b in bar_list[start : idx + 1]]
    opens = [float(b.open) for b in bar_list[start : idx + 1]]
    vols = [float(b.volume) for b in bar_list[start : idx + 1]]
    cT = closes[-1]
    if cT <= 0:
        return None
    price_shape = [round(c / cT - 1, 6) for c in closes]
    vol_ma = []
    for i in range(start, idx + 1):
        v = float(bar_list[i].volume)
        base = statistics.fmean(float(bar_list[j].volume) for j in range(max(0, i - WINDOW), i)) or 1
        vol_ma.append(min(v / base, 5.0))
    ma5 = statistics.fmean(closes[-5:])
    ma10 = statistics.fmean(closes[-10:])
    ma20 = statistics.fmean(closes[-20:])
    high20 = max(highs)
    high40 = max(float(bar_list[i].high) for i in range(max(0, idx - 40 + 1), idx + 1))
    attack_idx = max(
        range(max(0, idx - 40 + 1), idx + 1),
        key=lambda i: float(bar_list[i].high),
    )
    trs = []
    for i in range(start + 1, idx + 1):
        h, l, pc = float(bar_list[i].high), float(bar_list[i].low), float(bar_list[i - 1].close)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = statistics.fmean(trs)
    rs = rsi(closes)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    hist = [a - b for a, b in zip(dif, dea)]
    macd_slope = (hist[-1] - hist[-4]) / cT if len(hist) >= 4 else None
    start40 = max(0, idx - 39)
    highs40 = [float(b.high) for b in bar_list[start40 : idx + 1]]
    lows40 = [float(b.low) for b in bar_list[start40 : idx + 1]]
    closes40 = [float(b.close) for b in bar_list[start40 : idx + 1]]
    ad = adx(highs40, lows40, closes40)
    sd = statistics.pstdev(closes)
    bw = 4 * sd / ma20 if ma20 else None
    rng = highs[-1] - lows[-1]
    return {
        "price_shape": price_shape,
        "vol_shape": vol_ma,
        "close_vs_ma5": closes[-1] / ma5 - 1,
        "close_vs_ma10": closes[-1] / ma10 - 1,
        "close_vs_ma20": closes[-1] / ma20 - 1,
        "dist_20d_high": closes[-1] / high20 - 1,
        "dist_attack_high": closes[-1] / high40 - 1,
        "pullback_depth": closes[-1] / min(lows) - 1,
        "days_since_attack": idx - attack_idx,
        "atr20_pct": atr / cT,
        "rsi14": rs,
        "macd_hist_slope": macd_slope,
        "adx14": ad,
        "bollinger_bw": bw,
        "close_loc": (closes[-1] - lows[-1]) / rng if rng else None,
    }


LEVEL_FEATURES = [
    "close_vs_ma5", "close_vs_ma10", "close_vs_ma20", "dist_20d_high",
    "dist_attack_high", "pullback_depth", "days_since_attack", "atr20_pct",
    "rsi14", "macd_hist_slope", "adx14", "bollinger_bw", "close_loc",
]


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ep = pd.read_parquet(EPISODES_DIR / "episodes.parquet")
    sig = ep[ep["execution_label"].isin(("B1_READY", "B2_READY", "B2_CONFIRMED"))].copy()
    for col in ("signal_date",):
        sig[col] = pd.to_datetime(sig[col]).dt.date
    for col in ("invalid_price", "s1_price"):
        sig[col] = pd.to_numeric(sig[col].astype(str), errors="coerce")

    layout = WarehouseLayout(DATA_ROOT)
    snap, _, _ = load_canonical_metadata(layout, snapshot_id=SNAPSHOT_ID)
    by_code: dict[str, list] = defaultdict(list)
    for _, r in sig.iterrows():
        by_code[str(r["code"])].append(r)

    library = []
    for code, bars in iter_canonical_code_bars(
        layout, snap, codes=sorted(by_code.keys())
    ):
        if not bars or code not in by_code:
            continue
        idx_by_date = {b.trade_date: i for i, b in enumerate(bars)}
        bar_list = list(bars)
        for row in by_code[code]:
            idx = idx_by_date.get(row["signal_date"])
            if idx is None:
                continue
            fp = fingerprint(bar_list, idx)
            if fp is None:
                continue
            inv = float(row["invalid_price"]) if pd.notna(row["invalid_price"]) else None
            s1 = float(row["s1_price"]) if pd.notna(row["s1_price"]) else None
            rec = {
                "code": str(code),
                "T": row["signal_date"].isoformat(),
                "stage": STAGE_OF_LABEL[str(row["execution_label"])],
                "invalid": inv,
                "s1": s1,
                **fp,
            }
            # forward path T+1..T+10 (only after selection; stored here but never used in similarity)
            end = min(len(bar_list), idx + 11)
            if idx + 1 < len(bar_list) and inv is not None and s1 is not None:
                cT = float(bar_list[idx].close)
                high20 = max(float(b.high) for b in bar_list[max(0, idx - 19) : idx + 1])
                rec["fwd"] = {}
                mfe = mae = 0.0
                t_launch = None
                for k in (1, 3, 5, 10):
                    if idx + k < len(bar_list):
                        seg = bar_list[idx + 1 : idx + k + 1]
                        mfe = max(mfe, max(float(b.high) for b in seg) / cT - 1)
                        mae = min(mae, min(float(b.low) for b in seg) / cT - 1)
                        rec["fwd"][f"mfe_{k}d"] = mfe
                        rec["fwd"][f"mae_{k}d"] = mae
                        rec["fwd"][f"ret_{k}d"] = float(seg[-1].close) / cT - 1
                rec["fwd"]["new_high_10d"] = any(
                    float(b.high) > high20 for b in bar_list[idx + 1 : end]
                )
                rec["fwd"]["s1_hit"] = any(float(b.high) >= s1 for b in bar_list[idx + 1 : end])
                rec["fwd"]["invalid_hit"] = any(float(b.low) <= inv for b in bar_list[idx + 1 : end])
                for j in range(idx + 1, end):
                    if float(bar_list[j].high) > high20:
                        t_launch = j - idx
                        break
                rec["fwd"]["time_to_second_launch"] = t_launch
            library.append(rec)
    print("library size", len(library), flush=True)

    # z-score standardization over the full library (feature-level, not target)
    fstats = {}
    for f in LEVEL_FEATURES:
        vals = [r[f] for r in library if r[f] is not None]
        fstats[f] = {"mean": statistics.fmean(vals), "std": statistics.pstdev(vals) or 1}

    def vec(sample, price_weight=1.0):
        out = [v * price_weight for v in sample["price_shape"]]
        out += [v for v in sample["vol_shape"]]
        for f in LEVEL_FEATURES:
            v = sample.get(f)
            out.append(0.0 if v is None else (v - fstats[f]["mean"]) / fstats[f]["std"])
        return out

    def dist(a, b):
        va, vb = vec(a), vec(b)
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(va, vb)))

    # current candidates (T = 8/3 close via EOD fallback + canonical history)
    eod = pd.read_parquet(EOD_PARQUET)
    eod["trade_date"] = pd.to_datetime(eod["trade_date"]).dt.date
    eod = eod[eod["trade_date"] == date(2026, 8, 3)]
    eod_by = {str(r["code"]): r for _, r in eod.iterrows()}
    candidates = [
        {"code": "603980", "name": "吉华集团", "stage": "B2_READY", "invalid": 6.23, "s1": 7.02},
        {"code": "600756", "name": "浪潮软件", "stage": "B2_READY", "invalid": 15.66, "s1": 16.99},
    ]
    cand_rows = []
    for cand in candidates:
        code = cand["code"]
        for c, bars in iter_canonical_code_bars(layout, snap, codes=[code], as_of=date(2026, 7, 31)):
            bar_list = list(bars)
            r8 = eod_by[code]
            # append 8/3 bar as a synthetic DailyBar-like row
            class B:
                pass
            b = B()
            b.trade_date = date(2026, 8, 3)
            b.open = float(r8["open"]); b.high = float(r8["high"])
            b.low = float(r8["low"]); b.close = float(r8["close"])
            b.volume = float(r8["volume"]); b.preclose = float(bar_list[-1].close)
            bar_list.append(b)
            idx = len(bar_list) - 1
            fp = fingerprint(bar_list, idx)
            if fp is not None:
                cand_row = {"code": code, "name": cand["name"], "stage": cand["stage"], "T": "2026-08-03", "invalid": cand["invalid"], "s1": cand["s1"], **fp}
                cand_rows.append(cand_row)
            print("candidate fingerprint", code, "ok" if fp else "FAIL", flush=True)

    reports = {}
    for cand in cand_rows:
        lib = [r for r in library if r["stage"] == cand["stage"] and r.get("fwd")]
        ranked = sorted(lib, key=lambda r: dist(cand, r))[:150]
        report = {
            "code": cand["code"],
            "name": cand["name"],
            "T": cand["T"],
            "stage_filter": cand["stage"],
            "library_n": len(lib),
            "analog_n": len(ranked),
            "similarity_dist": {
                "min": round(dist(cand, ranked[0]), 3) if ranked else None,
                "median": round(dist(cand, ranked[len(ranked) // 2]), 3) if ranked else None,
                "max": round(dist(cand, ranked[-1]), 3) if ranked else None,
            },
            "analog_codes": [r["code"] for r in ranked[:10]],
            "fwd": {},
            "time_to_second_launch": {},
        }
        for k in ("mfe_1d", "mfe_3d", "mfe_5d", "mfe_10d", "mae_1d", "mae_3d", "mae_5d", "mae_10d", "ret_1d", "ret_3d", "ret_5d", "ret_10d"):
            vals = [r["fwd"][k] for r in ranked if k in r["fwd"]]
            qs = {}
            for q in (0.25, 0.5, 0.75, 0.9):
                qs[str(q)] = round(sorted(vals)[int((len(vals) - 1) * q)], 4) if vals else None
            report["fwd"][k] = {"median": round(statistics.median(vals), 4) if vals else None, **qs}
        for k in ("new_high_10d", "s1_hit", "invalid_hit"):
            vals = [1 if r["fwd"][k] else 0 for r in ranked]
            report["fwd"][k + "_rate"] = round(statistics.fmean(vals), 4) if vals else None
        tl = [r["fwd"]["time_to_second_launch"] for r in ranked if r["fwd"]["time_to_second_launch"] is not None]
        report["time_to_second_launch"] = {
            "T+1": sum(1 for x in tl if x == 1),
            "T+2": sum(1 for x in tl if x == 2),
            "T+3": sum(1 for x in tl if x == 3),
            "T+4-5": sum(1 for x in tl if x in (4, 5)),
            ">T+5": sum(1 for x in tl if x > 5),
            "none_in_10d": len(ranked) - len(tl),
        }
        report["target_band"] = {
            "ANALOG_S1_RANGE": {
                "p50_5d_mfe": report["fwd"]["mfe_5d"]["0.5"],
                "p75_5d_mfe": report["fwd"]["mfe_5d"]["0.75"],
            },
            "ANALOG_S2_RANGE": {
                "p75_10d_mfe": report["fwd"]["mfe_10d"]["0.75"],
                "p90_10d_mfe": report["fwd"]["mfe_10d"]["0.9"],
            },
            "STRUCTURAL_S1": cand["s1"],
            "STRUCTURAL_S2": "N/A (no frozen S2 price target)",
        }
        reports[cand["code"]] = report

    metrics = {
        "title": "HISTORICAL_ANALOG_ENGINE_V0.1",
        "snapshot_id": SNAPSHOT_ID,
        "source_episodes_sha256": "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093",
        "evaluate_strategy_calls": 0,
        "conclusion_status": "RESEARCH_OVERLAY_ONLY",
        "ANALOG_METHOD": {
            "fingerprint": "20-session normalized price shape + vol/MA20 shape + 13 level features",
            "distance": "equal-weight: price-shape Euclidean + z-standardized level-feature Euclidean",
            "analog_count": 150,
            "relative_strength": "DATA_UNAVAILABLE (no sector/index series in fallback)",
        },
        "LEAKAGE_GUARDS": [
            "features use bars <= T only",
            "forward paths read only after analog selection",
            "z-score standardization is feature-level, not target-based",
            "no neural nets; no threshold scan",
        ],
        "FEATURE_SET": {
            "price_shape": "20 dims (close_i/close_T - 1)",
            "volume_shape": "20 dims (vol_i / MA20_vol_i, clipped at 5)",
            "level_features": LEVEL_FEATURES,
        },
        "REPORTS": reports,
        "LIMITATIONS": [
            "relative strength unavailable",
            "attack high proxied by trailing-40d max high",
            "analog library = frozen episode signals (not every session)",
            "second-launch proxy = new 20d high within 10d",
            "small candidate set (2) for example report; no tuning",
        ],
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    run()
