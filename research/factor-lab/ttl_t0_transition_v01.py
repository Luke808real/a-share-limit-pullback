"""TTL T0 FIXED-COHORT TRANSITION RESULT V01 — preregistered structural timing.

Executes the frozen prereg
(research/factor-lab/runs/ttl-t0-transition-prereg-v01/ttl-t0-transition-prereg-v01.md,
AUTHORITY d9c9abf1ce30dd2d08303bb8ccce0e5be13d4e09):

  K_MAX = 9
  FULL_WINDOW_MATURED  = FOLLOWUP_SESSIONS_AVAILABLE >= 9
  FIXED_MATURED_N      = count(FULL_WINDOW_MATURED)
  F_STAGE(k)           = count(FULL_WINDOW_MATURED AND first_event_time(stage) <= k)
                         / FIXED_MATURED_N   for k = 1..9

for stages B1_READY / B2_READY / B2_CONFIRMED. Same fixed denominator for
every k; F(1) <= ... <= F(9) enforced (fail closed).

This is STRUCTURAL transition timing only: no outcome analysis, no
Kaplan-Meier / hazard, no TTL cutoff, no profitability.

Frozen inputs (SHA gate, fail closed):
  registry: research/factor-lab/runs/t0-registry-v01/t0-registry-v01.csv
            (130a56986307fed3e382dd65f4a4f9a4a9df61a7387a7b7a15b049cf72d9441c)
  episodes: 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093
  daily:    e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
  OBSERVATION_END = 2026-07-31 ; TOTAL_T0_N = 22393 ; K_MAX = 9
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from limit_pullback.outcome import _iter_confirmed_code_bars  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "research/factor-lab/runs/t0-registry-v01/t0-registry-v01.csv"
EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome/episodes.parquet"
)
DAILY_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
OUT_DIR = ROOT / "research/factor-lab/runs/ttl-t0-transition-result-v01"

REGISTRY_SHA256 = "130a56986307fed3e382dd65f4a4f9a4a9df61a7387a7b7a15b049cf72d9441c"
EPISODES_SHA256 = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DAILY_SHA256 = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
PREREG_AUTHORITY_HEAD = "d9c9abf1ce30dd2d08303bb8ccce0e5be13d4e09"
BASE_HEAD = "d9c9abf1ce30dd2d08303bb8ccce0e5be13d4e09"
OBSERVATION_END = date(2026, 7, 31)
TOTAL_T0_N = 22393
K_MAX = 9
PRIMARY_LABELS = ("B1_READY", "B2_READY", "B2_CONFIRMED")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_registry(path: Path, expected_sha: str = REGISTRY_SHA256) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_registry: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"registry SHA mismatch: {path}")
    df = pd.read_csv(path, dtype={"setup_id": str, "code": str})
    if len(df) != TOTAL_T0_N:
        raise RuntimeError(f"registry total mismatch: {len(df)} != {TOTAL_T0_N}")
    return df


def load_episodes(path: Path, expected_sha: str = EPISODES_SHA256) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_episodes: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"episodes SHA mismatch: {path}")
    return pd.read_parquet(path)


def load_daily(path: Path, expected_sha: str = DAILY_SHA256) -> dict[str, tuple]:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_daily: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"daily SHA mismatch: {path}")
    return dict(_iter_confirmed_code_bars(path))


def build_followup_authority(
    registry: pd.DataFrame, daily: dict[str, tuple]
) -> tuple[pd.DataFrame, dict]:
    """FOLLOWUP_SESSIONS_AVAILABLE per T0 from generator-visible CONFIRMED
    per-code sequences (> anchor_date, <= OBSERVATION_END)."""
    session_dates: dict[str, tuple[date, ...]] = {}
    for code, bars in daily.items():
        session_dates[code] = tuple(b.trade_date for b in bars)
    followup: list[int] = []
    missing: list[str] = []
    for _, row in registry.iterrows():
        code = str(row["code"])
        anchor = date.fromisoformat(str(row["anchor_date"]))
        dates = session_dates.get(code, ())
        if not dates:
            missing.append(f"{row['setup_id']}: no CONFIRMED sessions for {code}")
            followup.append(0)
            continue
        followup.append(sum(1 for d in dates if anchor < d <= OBSERVATION_END))
    if missing:
        raise RuntimeError(f"missing CONFIRMED session authority: {missing[:5]}")
    out = registry.copy()
    out["FOLLOWUP_SESSIONS_AVAILABLE"] = followup
    return out, session_dates


def load_primary_events(
    episodes: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    """Primary event rows with all input gates (label/stage consistency,
    registry membership, duplicate fail closed, stage prerequisites, order,
    stored/recomputed event time reconciliation, event time <= K_MAX)."""
    primary = episodes[episodes["execution_label"].isin(PRIMARY_LABELS)].copy()
    primary["setup_id"] = primary["setup_id"].astype(str)
    primary["execution_label"] = primary["execution_label"].astype(str)
    primary["setup_stage"] = primary["setup_stage"].astype(str)
    primary["signal_date"] = primary["signal_date"].astype(str)
    primary["anchor_date"] = primary["anchor_date"].astype(str)
    primary["days_since_anchor"] = pd.to_numeric(primary["days_since_anchor"], errors="coerce")

    # label == stage
    label_stage_mismatch = int((primary["execution_label"] != primary["setup_stage"]).sum())
    if label_stage_mismatch:
        raise RuntimeError(f"LABEL_STAGE_MISMATCH_N = {label_stage_mismatch}: fail closed")

    # setup_id in registry
    registry_ids = set(registry["setup_id"].astype(str).unique())
    unknown = primary[~primary["setup_id"].isin(registry_ids)]
    if len(unknown):
        raise RuntimeError(
            f"primary event setup_id not in registry: {len(unknown)}; samples: {unknown['setup_id'].head(3).tolist()}"
        )

    # duplicate same (setup_id, execution_label)
    dup = int(primary.duplicated(subset=["setup_id", "execution_label"]).sum())
    if dup:
        raise RuntimeError(f"DUPLICATE_VIOLATION_N = {dup}: fail closed")

    # stage lineage gates (per setup)
    by_setup = primary.groupby("setup_id")
    prereq_violations: list[str] = []
    order_violations: list[str] = []
    for setup_id, grp in by_setup:
        stages = set(grp["execution_label"])
        if "B2_READY" in stages and "B1_READY" not in stages:
            prereq_violations.append(f"{setup_id}: B2_READY without B1_READY")
        if "B2_CONFIRMED" in stages and "B2_READY" not in stages:
            prereq_violations.append(f"{setup_id}: B2_CONFIRMED without B2_READY")
        if "B2_CONFIRMED" in stages and "B1_READY" not in stages:
            prereq_violations.append(f"{setup_id}: B2_CONFIRMED without B1_READY")
        times: dict[str, date] = {}
        for _, row in grp.iterrows():
            t = date.fromisoformat(row["signal_date"])
            lab = row["execution_label"]
            if lab not in times or t < times[lab]:
                times[lab] = t
        if "B1_READY" in times and "B2_READY" in times and times["B2_READY"] < times["B1_READY"]:
            order_violations.append(f"{setup_id}: B2_READY < B1_READY")
        if "B2_READY" in times and "B2_CONFIRMED" in times and times["B2_CONFIRMED"] < times["B2_READY"]:
            order_violations.append(f"{setup_id}: B2_CONFIRMED < B2_READY")
        if "B1_READY" in times and "B2_CONFIRMED" in times and times["B2_CONFIRMED"] < times["B1_READY"]:
            order_violations.append(f"{setup_id}: B2_CONFIRMED < B1_READY")
    if prereq_violations:
        raise RuntimeError(f"STAGE_PREREQUISITE_VIOLATION_N = {len(prereq_violations)}: {prereq_violations[:3]}")
    if order_violations:
        raise RuntimeError(f"STAGE_ORDER_VIOLATION_N = {len(order_violations)}: {order_violations[:3]}")

    return primary


def recompute_event_times(
    primary: pd.DataFrame, session_dates: dict[str, tuple[date, ...]]
) -> pd.DataFrame:
    """Recompute EVENT_TIME = index(signal_date) - index(anchor_date) on the
    CONFIRMED per-code sequence; must equal days_since_anchor (fail closed)."""
    out = primary.copy()
    recomputed: list[int] = []
    mismatch: list[str] = []
    max_abs = 0
    index_map: dict[str, dict[date, int]] = {}
    for code, dates in session_dates.items():
        index_map[code] = {d: i for i, d in enumerate(dates)}
    for _, row in out.iterrows():
        code = str(row["code"])
        anchor = date.fromisoformat(row["anchor_date"])
        signal = date.fromisoformat(row["signal_date"])
        idx = index_map.get(code, {})
        if anchor not in idx or signal not in idx:
            raise RuntimeError(f"event time recompute impossible for {row['setup_id']}")
        rt = idx[signal] - idx[anchor]
        recomputed.append(rt)
        stored = int(row["days_since_anchor"])
        diff = abs(rt - stored)
        max_abs = max(max_abs, diff)
        if diff != 0:
            mismatch.append(f"{row['setup_id']}: stored {stored} != recomputed {rt}")
        if not (1 <= rt <= K_MAX):
            raise RuntimeError(f"event time out of [1,{K_MAX}]: {row['setup_id']} rt={rt}")
    if mismatch:
        raise RuntimeError(
            f"EVENT_TIME_MISMATCH_N = {len(mismatch)}: fail closed; samples: {mismatch[:3]}"
        )
    out["RECOMPUTED_EVENT_TIME"] = recomputed
    out["_MAX_ABS_DIFF"] = max_abs
    return out


def first_event_times(primary: pd.DataFrame) -> dict[str, dict[str, int | None]]:
    """Per setup per stage: first event time (CONFIRMED session distance)."""
    first: dict[str, dict[str, int | None]] = defaultdict(dict)
    for _, row in primary.iterrows():
        sid = row["setup_id"]
        lab = row["execution_label"]
        t = int(row["RECOMPUTED_EVENT_TIME"])
        if lab not in first[sid] or (first[sid][lab] is not None and t < first[sid][lab]):
            first[sid][lab] = t
    return dict(first)


def compute_result(
    registry_matured: pd.DataFrame,
    primary: pd.DataFrame,
) -> dict:
    """Primary fixed-cohort result with mathematical QA (fail closed)."""
    fixed_matured_n = int(registry_matured["FULL_WINDOW_MATURED"].sum())
    first = first_event_times(primary)

    by_k: dict[str, dict[int, int]] = {s: {} for s in PRIMARY_LABELS}
    exact: dict[str, dict[int, int]] = {s: {k: 0 for k in range(1, K_MAX + 1)} for s in PRIMARY_LABELS}
    no_event: dict[str, int] = {s: 0 for s in PRIMARY_LABELS}

    for _, row in registry_matured.iterrows():
        if not row["FULL_WINDOW_MATURED"]:
            continue
        sid = row["setup_id"]
        fe = first.get(sid, {})
        for s in PRIMARY_LABELS:
            t = fe.get(s)
            if t is None:
                no_event[s] += 1
                continue
            exact[s][t] += 1
            for k in range(t, K_MAX + 1):
                by_k[s][k] = by_k[s].get(k, 0) + 1

    result: dict = {}
    for s in PRIMARY_LABELS:
        mono_ok = True
        prev = 0
        for k in range(1, K_MAX + 1):
            n = by_k[s].get(k, 0)
            if n < prev:
                mono_ok = False
            prev = n
        if not mono_ok:
            raise RuntimeError(f"MONOTONICITY VIOLATION: {s}")
        cum_check = all(
            by_k[s].get(k, 0) == sum(exact[s][kk] for kk in range(1, k + 1))
            for k in range(1, K_MAX + 1)
        )
        if not cum_check:
            raise RuntimeError(f"EXACT-EVENT CUMULATIVE IDENTITY VIOLATION: {s}")
        if by_k[s].get(K_MAX, 0) + no_event[s] != fixed_matured_n:
            raise RuntimeError(
                f"T9 + NO_EVENT conservation violation: {s}: "
                f"{by_k[s].get(K_MAX, 0)} + {no_event[s]} != {fixed_matured_n}"
            )
        result[s] = {
            "BY_K_N": {k: by_k[s].get(k, 0) for k in range(1, K_MAX + 1)},
            "BY_K_RATE": {
                k: round(by_k[s].get(k, 0) / fixed_matured_n, 6)
                for k in range(1, K_MAX + 1)
            },
            "EXACT_EVENT_N": {k: exact[s][k] for k in range(1, K_MAX + 1)},
            "EXACT_EVENT_RATE": {
                k: round(exact[s][k] / fixed_matured_n, 6)
                for k in range(1, K_MAX + 1)
            },
            "NO_EVENT_BY_T9_N": no_event[s],
            "NO_EVENT_BY_T9_RATE": round(no_event[s] / fixed_matured_n, 6),
            "BY_T9_N": by_k[s].get(K_MAX, 0),
            "BY_T9_RATE": round(by_k[s].get(K_MAX, 0) / fixed_matured_n, 6),
            "PEAK_FIRST_EVENT_T": max(
                range(1, K_MAX + 1), key=lambda k: exact[s][k]
            ),
        }
    return {
        "FIXED_MATURED_N": fixed_matured_n,
        "STAGES": result,
    }


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    registry = load_registry(REGISTRY_PATH)
    episodes = load_episodes(EPISODES_PATH)
    daily = load_daily(DAILY_PATH)

    reg, session_dates = build_followup_authority(registry, daily)
    reg["FULL_WINDOW_MATURED"] = reg["FOLLOWUP_SESSIONS_AVAILABLE"] >= K_MAX
    fixed_matured_n = int(reg["FULL_WINDOW_MATURED"].sum())
    admin_immature = int((~reg["FULL_WINDOW_MATURED"]).sum())
    if fixed_matured_n + admin_immature != TOTAL_T0_N:
        raise RuntimeError("TOTAL != FIXED_MATURED + ADMINISTRATIVE_NOT_FULLY_MATURE")

    primary = load_primary_events(episodes, registry)
    primary = recompute_event_times(primary, session_dates)

    result = compute_result(reg, primary)
    result.update(
        {
            "BASE_HEAD": BASE_HEAD,
            "PREREG_AUTHORITY_HEAD": PREREG_AUTHORITY_HEAD,
            "REGISTRY_SHA256": REGISTRY_SHA256,
            "EPISODES_SHA256": EPISODES_SHA256,
            "DAILY_SHA256": DAILY_SHA256,
            "K_MAX": K_MAX,
            "OBSERVATION_END": OBSERVATION_END.isoformat(),
            "TOTAL_T0_N": TOTAL_T0_N,
            "ADMINISTRATIVE_NOT_FULLY_MATURE_N": admin_immature,
            "PRIMARY_EVENT_ROWS_N": len(primary),
            "EVENT_TIME_MATCH_N": int((primary["RECOMPUTED_EVENT_TIME"] == primary["days_since_anchor"]).sum()),
            "EVENT_TIME_MISMATCH_N": int((primary["RECOMPUTED_EVENT_TIME"] != primary["days_since_anchor"]).sum()),
            "MAX_ABS_DIFF": int(primary["_MAX_ABS_DIFF"].max()),
            "DUPLICATE_VIOLATION_N": 0,
            "LABEL_STAGE_MISMATCH_N": 0,
            "STAGE_PREREQUISITE_VIOLATION_N": 0,
            "STAGE_ORDER_VIOLATION_N": 0,
        }
    )

    # CSV outputs
    reg_out = reg[
        ["setup_id", "code", "anchor_date", "FOLLOWUP_SESSIONS_AVAILABLE", "FULL_WINDOW_MATURED"]
    ].sort_values(["anchor_date", "code", "setup_id"])
    reg_out.to_csv(OUT_DIR / "ttl-t0-transition-v01.csv", index=False)

    timing_rows = []
    for s in PRIMARY_LABELS:
        for k in range(1, K_MAX + 1):
            timing_rows.append(
                {
                    "STAGE": s,
                    "EVENT_TIME": k,
                    "EVENT_N": result["STAGES"][s]["EXACT_EVENT_N"][k],
                    "EVENT_RATE": result["STAGES"][s]["EXACT_EVENT_RATE"][k],
                    "BY_K_N": result["STAGES"][s]["BY_K_N"][k],
                    "BY_K_RATE": result["STAGES"][s]["BY_K_RATE"][k],
                }
            )
    timing = pd.DataFrame(timing_rows).sort_values(["STAGE", "EVENT_TIME"])
    timing.to_csv(OUT_DIR / "ttl-t0-transition-timing-v01.csv", index=False)

    # SHA256 of outputs
    result["OUTPUT_CSV_SHA256"] = sha256(OUT_DIR / "ttl-t0-transition-v01.csv")
    result["OUTPUT_TIMING_CSV_SHA256"] = sha256(OUT_DIR / "ttl-t0-transition-timing-v01.csv")

    (OUT_DIR / "ttl-t0-transition-v01.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "ttl-t0-transition-v01-report.md").write_text(
        render_report(result), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def render_report(r: dict) -> str:
    lines = [
        "# TTL T0 FIXED-COHORT TRANSITION RESULT V01 — 结构性 transition timing",
        "",
        f"- PREREG_AUTHORITY_HEAD = {r['PREREG_AUTHORITY_HEAD']}；BASE_HEAD = {r['BASE_HEAD']}",
        f"- REGISTRY_SHA256 = {r['REGISTRY_SHA256']}；EPISODES_SHA256 = {r['EPISODES_SHA256']}；DAILY_SHA256 = {r['DAILY_SHA256']}",
        f"- TOTAL_T0_N = {r['TOTAL_T0_N']}；FIXED_MATURED_N = {r['FIXED_MATURED_N']}；"
        f"ADMINISTRATIVE_NOT_FULLY_MATURE_N = {r['ADMINISTRATIVE_NOT_FULLY_MATURE_N']}",
        f"- K_MAX = {r['K_MAX']}（frozen observability boundary，非 validated TTL）",
        f"- PRIMARY_EVENT_ROWS_N = {r['PRIMARY_EVENT_ROWS_N']}；EVENT_TIME_MATCH_N = {r['EVENT_TIME_MATCH_N']}；"
        f"EVENT_TIME_MISMATCH_N = {r['EVENT_TIME_MISMATCH_N']}；MAX_ABS_DIFF = {r['MAX_ABS_DIFF']}",
        f"- DUPLICATE_VIOLATION_N = {r['DUPLICATE_VIOLATION_N']}；LABEL_STAGE_MISMATCH_N = {r['LABEL_STAGE_MISMATCH_N']}；"
        f"STAGE_PREREQUISITE_VIOLATION_N = {r['STAGE_PREREQUISITE_VIOLATION_N']}；STAGE_ORDER_VIOLATION_N = {r['STAGE_ORDER_VIOLATION_N']}",
        "",
    ]
    for s in ("B1_READY", "B2_READY", "B2_CONFIRMED"):
        st = r["STAGES"][s]
        lines += [
            f"## {s}",
            f"- BY_T9_N = {st['BY_T9_N']}；BY_T9_RATE = {st['BY_T9_RATE']}；"
            f"NO_EVENT_BY_T9_N = {st['NO_EVENT_BY_T9_N']}；NO_EVENT_BY_T9_RATE = {st['NO_EVENT_BY_T9_RATE']}",
            f"- PEAK_FIRST_EVENT_T = T+{st['PEAK_FIRST_EVENT_T']}",
            "| k | BY_K_N | BY_K_RATE | EXACT_EVENT_N | EXACT_EVENT_RATE |",
            "| --- | --- | --- | --- | --- |",
        ]
        for k in range(1, r["K_MAX"] + 1):
            lines.append(
                f"| {k} | {st['BY_K_N'][k]} | {st['BY_K_RATE'][k]} | "
                f"{st['EXACT_EVENT_N'][k]} | {st['EXACT_EVENT_RATE'][k]} |"
            )
    lines += [
        "",
        "## INTERPRETATION LIMIT（DESCRIPTIVE ONLY）",
        "- 以上全部为 structural transition timing / cumulative transition rates / exact first-event timing /",
        "  never-reached-stage-by-T9 fraction（fixed-matured cohort）",
        "- 允许描述明显的 timing concentration / decay，但仅属 DESCRIPTIVE",
        "- 不得解读为：VALIDATED TTL、交易买点规则、T+5 expiry rule、profitability 结论",
        "- F_STAGE(k) != Kaplan-Meier survival / alive probability / win rate / P(profit|B2) / validated TTL cutoff",
        f"- OUTPUT_CSV_SHA256 = {r['OUTPUT_CSV_SHA256']}；OUTPUT_TIMING_CSV_SHA256 = {r['OUTPUT_TIMING_CSV_SHA256']}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
