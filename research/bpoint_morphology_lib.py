"""B_POINT_ENTRY_MORPHOLOGY_V01 — helper library (research-only).

Daily-K morphology features computed strictly PIT (bars through D0 only),
rank-biserial effect sizes, bootstrap CIs, and fixed descriptive archetypes.
No threshold scanning; archetype thresholds are pre-registered descriptive
definitions, not optimised.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1.0) * 100.0, 4)


def kline_fields(row: pd.Series, prev_close: float | None) -> dict:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    if h <= l:
        close_loc = None
    else:
        close_loc = round((c - l) / (h - l), 3)
    return {
        "body_pct": round((c / o - 1.0) * 100.0, 4),
        "range_pct": round((h - l) / o * 100.0, 4),
        "upper_shadow_pct": round((h - max(o, c)) / o * 100.0, 4),
        "lower_shadow_pct": round((min(o, c) - l) / o * 100.0, 4),
        "close_location": close_loc,
        "gap_pct": pct(o, prev_close),
        "daily_return": pct(c, prev_close),
    }


def rank_biserial(x: np.ndarray, y: np.ndarray) -> float | None:
    x = x[~np.isnan(x)]
    y = y[~np.isnan(y)]
    if len(x) < 2 or len(y) < 2:
        return None
    combined = np.concatenate([x, y])
    if np.ptp(combined) == 0:
        return 0.0
    sorted_vals = np.sort(combined)
    left = np.searchsorted(sorted_vals, combined, side="left")
    right = np.searchsorted(sorted_vals, combined, side="right")
    ranks = (left + right + 1) / 2.0  # average ranks for ties
    n1, n2 = len(x), len(y)
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2.0
    return 1.0 - 2.0 * u / (n1 * n2)


def bootstrap_median_diff(
    x: np.ndarray, y: np.ndarray, n_boot: int = 500, seed: int = 42
) -> tuple[float | None, float | None]:
    x = x[~np.isnan(x)]
    y = y[~np.isnan(y)]
    if len(x) < 5 or len(y) < 5:
        return None, None
    rng = np.random.default_rng(seed)
    meds = np.empty(n_boot)
    for i in range(n_boot):
        sx = np.median(rng.choice(x, size=len(x), replace=True))
        sy = np.median(rng.choice(y, size=len(y), replace=True))
        meds[i] = sx - sy
    return round(float(np.percentile(meds, 2.5)), 4), round(float(np.percentile(meds, 97.5)), 4)


def bootstrap_or_ci(
    s_hit: int, s_n: int, c_hit: int, c_n: int, n_boot: int = 500, seed: int = 42
) -> tuple[float | None, float | None]:
    if not (0 < s_hit < s_n and 0 < c_hit < c_n):
        return None, None
    rng = np.random.default_rng(seed)
    logs = np.empty(n_boot)
    for i in range(n_boot):
        a = rng.binomial(s_n, s_hit / s_n)
        b = rng.binomial(c_n, c_hit / c_n)
        if 0 < a < s_n and 0 < b < c_n:
            logs[i] = np.log((a / (s_n - a)) / (b / (c_n - b)))
        else:
            logs[i] = np.nan
    logs = logs[~np.isnan(logs)]
    if len(logs) < 50:
        return None, None
    return round(float(np.exp(np.percentile(logs, 2.5))), 3), round(
        float(np.exp(np.percentile(logs, 97.5))), 3
    )


def midrank_ecdf_percentile(sorted_vals: np.ndarray, x: float) -> float:
    """EMPIRICAL_MIDRANK_ECDF_V1: (count(<x) + 0.5*count(==x)) / n.

    Below min -> 0, above max -> 1.
    """
    if len(sorted_vals) == 0:
        return 0.0
    below = float((sorted_vals < x).sum())
    equal = float((sorted_vals == x).sum())
    p = (below + 0.5 * equal) / len(sorted_vals)
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return p


def quiet_quartile_v02(score: float, q25: float, q50: float, q75: float) -> str:
    """Fixed V02 quartile rule: <=Q25->Q1, <=Q50->Q2, <=Q75->Q3, >Q75->Q4."""
    if score <= q25:
        return "Q1"
    if score <= q50:
        return "Q2"
    if score <= q75:
        return "Q3"
    return "Q4"


def archetype_flags(f: dict) -> dict:
    """Fixed descriptive archetype definitions (research labels, not rules)."""
    dd = f.get("max_dd_from_post_anchor_high_pct")
    low_prog = f.get("low_progression_3d_pct")
    dry = f.get("pullback_min_vol_ratio")
    reexp = f.get("d0_vol_d1_vol_ratio")
    damage = bool(f.get("damage_day_exists_3d"))
    repair = f.get("days_to_recover_damage_open")
    shadow_rev = bool(f.get("lower_shadow_reversal_day_exists"))
    close_anchor = f.get("candidate_close_vs_anchor_pct")
    probes = f.get("probe_count_3d")
    return {
        "ARCH_SHALLOW_PULLBACK_HIGHER_LOW": bool(
            dd is not None and dd >= -10.0 and low_prog is not None and low_prog > 0.0
        ),
        "ARCH_VOLUME_DRY_UP_REEXPANSION": bool(
            dry is not None and reexp is not None and dry <= 0.60 and reexp >= 1.20
        ),
        "ARCH_DAMAGE_FAST_REPAIR": bool(damage and repair is not None and repair <= 3),
        "ARCH_SUPPORT_SHAKEOUT_RECLAIM": bool(
            shadow_rev
            and close_anchor is not None
            and f.get("damage_open") is not None
            and f["candidate_close"] >= f["damage_open"]
        ),
        "ARCH_HIGH_LEVEL_CONSOLIDATION": bool(
            close_anchor is not None
            and dd is not None
            and close_anchor >= -5.0
            and dd >= -8.0
            and (f.get("days_since_anchor") or 0) >= 2
        ),
        "ARCH_MULTI_PROBE_BREAKOUT_PREP": bool(
            probes is not None and probes >= 2 and low_prog is not None and low_prog > 0.0
        ),
        "ARCH_WEAK_REBOUND": bool(
            damage
            and f.get("damage_close") is not None
            and f["candidate_close"] > f["damage_close"]
            and not (
                (dd is not None and dd >= -10.0 and low_prog is not None and low_prog > 0.0)
                or (dry is not None and reexp is not None and dry <= 0.60 and reexp >= 1.20)
            )
        ),
        "ARCH_STRUCTURE_DECAY": bool(
            f.get("low_d0") is not None
            and f.get("low_d1") is not None
            and f.get("close_d0") is not None
            and f.get("close_d1") is not None
            and f["low_d0"] < f["low_d1"]
            and f["close_d0"] < f["close_d1"]
            and (
                (f.get("d0_vol_ma5vol_ratio") or 0) >= 1.3
                or (f.get("d0_daily_return") or 0) <= -2.0
            )
        ),
    }
