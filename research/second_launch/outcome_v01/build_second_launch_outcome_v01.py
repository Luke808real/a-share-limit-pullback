"""R1A.1 provenance-safe multi-horizon second-launch outcome labels (research-only).

Builds a minimal, reproducible multi-horizon label package on top of the frozen
SUCCESS_CONTROL_CASESET_V01B:

- outcome_3d / outcome_reason_3d: copied verbatim from the frozen case set
  (single source of truth, never recomputed into the output);
- outcome_5d / outcome_reason_5d: same frozen SUCCESS semantics with horizon
  3 -> 5, recomputed from the VALIDATED label snapshot (SCREEN_READY + PASS);
- 10D: event-time only (time_to_s1 / time_to_invalid / first event), no
  outcome_10d target;
- right_censored_5d / right_censored_10d, feature/label snapshot ids.

Provenance rules (fail closed):
- FEATURE data comes only from snap-2026-07-31-b5f84004de8a; the label snapshot
  is never used for feature fields (signal-day volume is read from the feature
  snapshot at candidate_date).
- episodes.parquet pattern_5d/pattern_10d are NEVER read for labeling (known
  provenance defect, see R1A); all event sequencing is recomputed from
  validated canonical daily bars. The episodes pattern columns are read only
  for the separate provenance-mismatch audit artifact.
- Event sequencing reuses limit_pullback.outcome._pattern_result (the frozen
  bar-order semantics); no second copy of that logic is introduced.

3D regression gate: the package recomputes outcome_3d from the feature
snapshot and requires exact equality with the frozen outcome column
(MISMATCH_N == 0). On failure no 5D package is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from limit_pullback.outcome import _pattern_result
from limit_pullback.models.enums import PatternOutcome
from limit_pullback.models.market import DailyBar


# ---------------------------------------------------------------------------
# Explicit provenance constants (no implicit "latest snapshot" anywhere).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

CASE_SET_PATH = REPO_ROOT / "research" / "intraday" / "success_control_cases_v01b.csv"
CASE_SET_SHA256 = "b22eae1dd438ed1b4053ce2cfce7ce668010518462261cb724f149615894f4e6"

FEATURE_SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
FEATURE_SNAPSHOT_PATH = (
    REPO_ROOT / "data" / "canonical" / "daily_bars" / f"{FEATURE_SNAPSHOT_ID}.parquet"
)
# Pinned from data/manifests/snap-2026-07-31-b5f84004de8a.json
# canonical_file_hashes["canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"].
EXPECTED_FEATURE_SNAPSHOT_SHA256 = (
    "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
)

LABEL_SNAPSHOT_ID = "snap-2026-08-06-e798f88ff67b"
LABEL_SNAPSHOT_PATH = (
    REPO_ROOT / "data" / "canonical" / "daily_bars" / f"{LABEL_SNAPSHOT_ID}.parquet"
)
# Pinned from data/manifests/snap-2026-08-06-e798f88ff67b.json
# canonical_file_hashes["canonical/daily_bars/snap-2026-08-06-e798f88ff67b.parquet"].
EXPECTED_LABEL_SNAPSHOT_SHA256 = (
    "7cc614bf4e1e7f91f34ed1a866827b3b70772a32ff5ff04a5ad67e205e23813e"
)

EPISODES_PATH = (
    REPO_ROOT
    / "data"
    / "outcome-study"
    / "outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "episodes.parquet"
)

HORIZON_3D = 3
HORIZON_5D = 5
HORIZON_10D = 10

EXPECTED_ROW_N = 8746

OUT_DIR = REPO_ROOT / "research" / "second_launch" / "outcome_v01"
OUT_CSV_PATH = OUT_DIR / "second_launch_outcome_v01.csv"
OUT_MANIFEST_PATH = OUT_DIR / "manifest.json"
OUT_MISMATCH_PATH = OUT_DIR / "pattern_provenance_mismatch.csv"
OUT_CONFLICTS_PATH = OUT_DIR / "case_provenance_conflicts_v01.csv"
OUT_BOUNDED_DIR = OUT_DIR / "bounded"
INTERIM_OUT_CSV = OUT_DIR / "second_launch_outcome_v01b_reproducible.csv"
INTERIM_MANIFEST_PATH = OUT_DIR / "manifest_v01b_reproducible.json"
QUARANTINE_PATH = OUT_DIR / "quarantine_v01b.csv"

GENERATOR_PATH = "research/second_launch/outcome_v01/build_second_launch_outcome_v01.py"

BAR_COLUMNS = ["code", "trade_date", "open", "high", "low", "close", "preclose",
               "volume", "amount", "turnover_rate", "pct_change", "trade_status",
               "is_st", "reconciliation_status"]

OUTPUT_COLUMNS = [
    "episode_id",
    "symbol",
    "name",
    "anchor_date",
    "candidate_date",
    "outcome_3d",
    "outcome_reason_3d",
    "outcome_5d",
    "outcome_reason_5d",
    "time_to_s1_10d",
    "time_to_invalid_10d",
    "first_event_type_10d",
    "first_event_date_10d",
    "window_incomplete_5d",
    "window_incomplete_10d",
    "first_event_right_censored_10d",
    "feature_snapshot_id",
    "label_snapshot_id_5d",
    "s1_price",
    "invalid_price",
    "data_quality",
    "quality_flags",
]

INTERIM_OUTPUT_COLUMNS = [
    "episode_id",
    "symbol",
    "name",
    "anchor_date",
    "candidate_date",
    "outcome_3d",
    "outcome_reason_3d",
    "outcome_5d",
    "outcome_reason_5d",
    "time_to_s1_10d",
    "time_to_invalid_10d",
    "first_event_type_10d",
    "first_event_date_10d",
    "window_incomplete_5d",
    "window_incomplete_10d",
    "first_event_right_censored_10d",
    "candidate_reconciliation_status",
    "feature_3d_has_provisional",
    "label_5d_has_provisional",
    "s1_price",
    "invalid_price",
    "data_quality",
    "quality_flags",
    "feature_snapshot_id",
    "label_snapshot_id_5d",
]


# ---------------------------------------------------------------------------
# Data loading (explicit snapshot paths only).
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Compute the SHA-256 of a file; fails closed if the file is missing."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_case_set(
    path: Path,
    expected_sha256: str | None = CASE_SET_SHA256,
    expected_row_n: int | None = EXPECTED_ROW_N,
) -> pd.DataFrame:
    """Load the frozen case set and enforce its identity invariants."""
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise RuntimeError(f"case set hash mismatch: {path}")
    cases = pd.read_csv(path, dtype={"symbol": str})
    if expected_row_n is not None and len(cases) != expected_row_n:
        raise RuntimeError(f"case set row count {len(cases)} != {expected_row_n}")
    if cases["episode_id"].duplicated().any():
        raise RuntimeError("case set contains duplicate episode_id")
    cases["symbol"] = cases["symbol"].astype(str).str.zfill(6)
    cases["candidate_date"] = pd.to_datetime(cases["candidate_date"]).dt.date
    return cases


def load_bars_by_code(path: Path, codes: set[str]) -> dict[str, pd.DataFrame]:
    """Read canonical daily bars from ONE explicit snapshot path."""
    table = pq.read_table(
        path,
        columns=BAR_COLUMNS,
        filters=[("code", "in", sorted(codes))],
    )
    df = table.to_pandas()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.sort_values(["code", "trade_date"]).reset_index(drop=True)
    return {code: group for code, group in df.groupby("code", sort=True)}


def load_episodes_patterns(path: Path) -> pd.DataFrame:
    """Read ONLY the pattern columns of episodes for the provenance audit."""
    ep = pq.read_table(
        path,
        columns=["setup_id", "signal_date", "pattern_5d", "pattern_10d"],
    ).to_pandas()
    ep["signal_date"] = pd.to_datetime(ep["signal_date"]).dt.date
    ep = ep.rename(columns={"setup_id": "episode_id"})
    return ep.drop_duplicates(subset=["episode_id", "signal_date"])


def _row_to_daily_bar(row: pd.Series, code: str) -> DailyBar:
    """Project one canonical bar row onto the DailyBar model for outcome.py."""
    fetched_at = datetime(2026, 1, 1, 16, 0, tzinfo=timezone.utc)
    turnover = row.get("turnover_rate")
    pct_change = row.get("pct_change")
    is_st = row.get("is_st")
    return DailyBar(
        trade_date=row["trade_date"],
        code=code,
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        preclose=Decimal(str(row["preclose"])),
        volume=Decimal(str(row["volume"])),
        amount=Decimal(str(row["amount"])),
        turnover_rate=Decimal(str(turnover)) if turnover is not None and pd.notna(turnover) else None,
        pct_change=Decimal(str(pct_change)) if pct_change is not None and pd.notna(pct_change) else None,
        trade_status=bool(row["trade_status"]),
        is_st=bool(is_st) if is_st is not None and pd.notna(is_st) else None,
        source="CANONICAL",
        fetched_at=fetched_at,
    )


# ---------------------------------------------------------------------------
# Pure label logic (horizon-parameterized; SUCCESS semantics identical to V01B).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LabelRow:
    """Outcome classification for one horizon window."""

    outcome: str
    reason: str


def future_window(bars: pd.DataFrame, candidate_date: date, horizon: int) -> pd.DataFrame:
    """Bars strictly after candidate_date, capped at `horizon` sessions.

    Sessions are the stock's own bar rows; suspension/no-bar days are simply
    not part of the sequence (identical to the V01B builder).
    """
    window = bars[bars["trade_date"] > candidate_date]
    return window.head(horizon)


def recompute_pattern(
    bars: pd.DataFrame,
    candidate_date: date,
    horizon: int,
    s1: Decimal,
    invalid: Decimal,
) -> PatternOutcome:
    """Recompute the frozen bar-order pattern from explicit bars.

    Reuses limit_pullback.outcome._pattern_result verbatim (no second copy of
    the ordering semantics).
    """
    window = future_window(bars, candidate_date, horizon)
    future = [
        _row_to_daily_bar(row, code=row["code"])
        for _, row in window.iterrows()
    ]
    return _pattern_result(future, horizon=horizon, s1=s1, invalid=invalid)


def classify_outcome(
    pattern: PatternOutcome,
    window: pd.DataFrame,
    s1: Decimal,
    signal_volume: Decimal | None,
    horizon_label: str,
) -> LabelRow:
    """V01B classify() with horizon 3 -> horizon_label (5D only in this package).

    Frozen SUCCESS conditions (unchanged):
      S1_BEFORE_INVALID + first S1-touch day close >= S1
      + first S1-touch day volume >= candidate-day volume.
    FAILED_BREAKOUT is split into FAILED_ACCEPTANCE / FAILED_EXPANSION.
    """
    if pattern is PatternOutcome.AMBIGUOUS:
        return LabelRow("UNKNOWN", "pattern AMBIGUOUS (same-day S1/invalid order unknown)")
    if len(window) == 0 or signal_volume is None:
        return LabelRow("UNKNOWN", "daily bars missing for horizon or signal day")
    if pattern is PatternOutcome.CENSORED:
        return LabelRow("CENSORED", f"fewer than {horizon_label} sessions available")
    if pattern is PatternOutcome.NEITHER:
        return LabelRow("NO_LAUNCH", f"no S1 and no invalid touch within {horizon_label}")
    if pattern is PatternOutcome.INVALID_BEFORE_S1:
        return LabelRow("STRUCTURE_FAIL", f"invalid first within {horizon_label}")
    if pattern is PatternOutcome.S1_BEFORE_INVALID:
        s1_day = window[window["high"] >= s1]
        if len(s1_day) == 0:
            return LabelRow("UNKNOWN", "S1_BEFORE_INVALID flagged but no S1-touch bar found")
        first = s1_day.iloc[0]
        close_ok = Decimal(str(first["close"])) >= s1
        vol_ok = Decimal(str(first["volume"])) >= signal_volume
        if close_ok and vol_ok:
            return LabelRow(
                "SUCCESS",
                "S1 first + close>=S1 + volume>=signal-day volume",
            )
        if not close_ok:
            return LabelRow(
                "FAILED_BREAKOUT",
                f"FAILED_ACCEPTANCE: S1 touched but close {float(first['close']):.2f} < S1 {float(s1):.2f}",
            )
        return LabelRow(
            "FAILED_BREAKOUT",
            "FAILED_EXPANSION: S1 close accepted but volume < signal-day volume",
        )
    raise RuntimeError(f"unhandled pattern: {pattern!r}")


def first_event_times(
    window: pd.DataFrame,
    s1: Decimal,
    invalid: Decimal,
) -> tuple[float | None, float | None, str, date | None]:
    """Marginal first-touch times + first event within the window (1-based).

    time_to_s1 / time_to_invalid are marginal (first touch of each level,
    independent of order). first_event_type is the bar-order winner:
    S1_FIRST / INVALID_FIRST / AMBIGUOUS / NONE.
    """
    time_s1: float | None = None
    time_inv: float | None = None
    first_type = "NONE"
    first_date: date | None = None
    for offset, (_, row) in enumerate(window.iterrows(), start=1):
        hit_s1 = Decimal(str(row["high"])) >= s1
        hit_inv = Decimal(str(row["low"])) <= invalid
        if hit_s1 and time_s1 is None:
            time_s1 = float(offset)
        if hit_inv and time_inv is None:
            time_inv = float(offset)
        if first_type == "NONE" and (hit_s1 or hit_inv):
            if hit_s1 and hit_inv:
                first_type = "AMBIGUOUS"
            elif hit_s1:
                first_type = "S1_FIRST"
            else:
                first_type = "INVALID_FIRST"
            first_date = row["trade_date"]
    return time_s1, time_inv, first_type, first_date


# ---------------------------------------------------------------------------
# Package build (regression gate first; fail closed on any invariant).
# ---------------------------------------------------------------------------

def _signal_volume(
    feature_bars: pd.DataFrame, candidate_date: date
) -> Decimal | None:
    """Signal-day volume from the FEATURE snapshot only (PIT at D)."""
    row = feature_bars[feature_bars["trade_date"] == candidate_date]
    if len(row) == 0:
        return None
    return Decimal(str(row.iloc[0]["volume"]))


def _build_rows(
    cases: pd.DataFrame,
    feature_bars: dict[str, pd.DataFrame],
    label_bars: dict[str, pd.DataFrame],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Compute 3D gate + 5D labels + 10D event times for every case.

    Returns (rows, label_recompute) where label_recompute maps episode_id to
    (recomputed_pattern_5d, recomputed_pattern_10d) from the label snapshot
    (reused by the provenance audit so both artifacts share one computation).
    """
    rows: list[dict[str, Any]] = []
    label_recompute: dict[str, tuple[str, str]] = {}
    for _, case in cases.iterrows():
        code = case["symbol"]
        cand = case["candidate_date"]
        s1 = Decimal(str(case["s1_price"]))
        invalid = Decimal(str(case["invalid_price"]))
        fbars = feature_bars.get(code)
        lbars = label_bars.get(code)

        sig_volume = _signal_volume(fbars, cand) if fbars is not None else None

        # 3D recompute (regression gate only; frozen outcome is authoritative).
        if fbars is None:
            pattern_3d = PatternOutcome.CENSORED
            window_3d = pd.DataFrame()
        else:
            window_3d = future_window(fbars, cand, HORIZON_3D)
            pattern_3d = recompute_pattern(fbars, cand, HORIZON_3D, s1, invalid)
        gate = classify_outcome(pattern_3d, window_3d, s1, sig_volume, "3 sessions")

        # 5D label from the VALIDATED label snapshot.
        if lbars is None:
            window_5d = pd.DataFrame()
            pattern_5d = PatternOutcome.CENSORED
            window_10d = pd.DataFrame()
            pattern_10d = PatternOutcome.CENSORED
        else:
            window_5d = future_window(lbars, cand, HORIZON_5D)
            pattern_5d = recompute_pattern(lbars, cand, HORIZON_5D, s1, invalid)
            window_10d = future_window(lbars, cand, HORIZON_10D)
            pattern_10d = recompute_pattern(lbars, cand, HORIZON_10D, s1, invalid)
        label_5d = classify_outcome(pattern_5d, window_5d, s1, sig_volume, "5 sessions")
        window_incomplete_5d = len(window_5d) < HORIZON_5D

        # 10D event time (label snapshot; outcome_10d is not a target).
        window_incomplete_10d = len(window_10d) < HORIZON_10D
        time_s1, time_inv, first_type, first_date = first_event_times(
            window_10d, s1, invalid
        )
        # Event-time right censoring is a DIFFERENT concept from window
        # incompleteness: only NONE (no observed event) within an incomplete
        # window is right-censored. An observed S1/INVALID/AMBIGUOUS is a real
        # event even if the window is truncated.
        first_event_right_censored_10d = (
            window_incomplete_10d and first_type == "NONE"
        )
        label_recompute[case["episode_id"]] = (
            pattern_5d.value,
            pattern_10d.value,
        )

        rows.append(
            {
                "episode_id": case["episode_id"],
                "symbol": code,
                "name": case["name"],
                "anchor_date": case["anchor_date"],
                "candidate_date": cand,
                "outcome_3d": case["outcome"],
                "outcome_reason_3d": case["outcome_reason"],
                "outcome_5d": label_5d.outcome,
                "outcome_reason_5d": label_5d.reason,
                "time_to_s1_10d": time_s1,
                "time_to_invalid_10d": time_inv,
                "first_event_type_10d": first_type,
                "first_event_date_10d": first_date,
                "window_incomplete_5d": window_incomplete_5d,
                "window_incomplete_10d": window_incomplete_10d,
                "first_event_right_censored_10d": first_event_right_censored_10d,
                "feature_snapshot_id": FEATURE_SNAPSHOT_ID,
                "label_snapshot_id_5d": LABEL_SNAPSHOT_ID,
                "s1_price": case["s1_price"],
                "invalid_price": case["invalid_price"],
                "data_quality": case["data_quality"],
                "quality_flags": case["quality_flags"],
                "_gate_outcome_3d": gate.outcome,
            }
        )
    return rows, label_recompute


def _provenance_mismatch_rows(
    cases: pd.DataFrame,
    episodes: pd.DataFrame,
    label_recompute: dict[str, tuple[str, str]],
) -> list[dict[str, str]]:
    """Audit: episodes pattern columns vs recompute from validated bars.

    Registration only; episodes.parquet is never modified.
    """
    episodes_keyed = episodes.set_index(["episode_id", "signal_date"])
    rows: list[dict[str, str]] = []
    for _, case in cases.iterrows():
        cand = case["candidate_date"]
        rec5, rec10 = label_recompute[case["episode_id"]]
        if (case["episode_id"], cand) not in episodes_keyed.index:
            ep5 = ep10 = ""
        else:
            ep = episodes_keyed.loc[(case["episode_id"], cand)]
            ep5 = str(ep["pattern_5d"]) if pd.notna(ep["pattern_5d"]) else ""
            ep10 = str(ep["pattern_10d"]) if pd.notna(ep["pattern_10d"]) else ""
        if rec5 == "CENSORED" or rec10 == "CENSORED":
            reason = "LABEL_CENSORED"
        elif not ep5 or not ep10:
            reason = "EPISODES_MISSING"
        elif ep5 != rec5 or ep10 != rec10:
            reason = "PATTERN_DIFF"
        else:
            reason = "MATCH"
        rows.append(
            {
                "episode_id": case["episode_id"],
                "code": case["symbol"],
                "candidate_date": cand,
                "episodes_pattern_5d": ep5,
                "recomputed_pattern_5d": rec5,
                "episodes_pattern_10d": ep10,
                "recomputed_pattern_10d": rec10,
                "difference_reason": reason,
            }
        )
    return rows


def _source_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def verify_snapshot_hashes(
    feature_snapshot_path: Path,
    label_snapshot_path: Path,
) -> None:
    """Pin and verify both snapshot hashes before any run (fail closed)."""
    if not feature_snapshot_path.exists():
        raise RuntimeError(f"feature snapshot missing: {feature_snapshot_path}")
    if not label_snapshot_path.exists():
        raise RuntimeError(f"label snapshot missing: {label_snapshot_path}")
    if sha256_file(feature_snapshot_path) != EXPECTED_FEATURE_SNAPSHOT_SHA256:
        raise RuntimeError(
            f"feature snapshot hash mismatch (fail closed): {feature_snapshot_path}"
        )
    if sha256_file(label_snapshot_path) != EXPECTED_LABEL_SNAPSHOT_SHA256:
        raise RuntimeError(
            f"label snapshot hash mismatch (fail closed): {label_snapshot_path}"
        )


def build_package(
    *,
    case_set_path: Path = CASE_SET_PATH,
    feature_snapshot_path: Path = FEATURE_SNAPSHOT_PATH,
    label_snapshot_path: Path = LABEL_SNAPSHOT_PATH,
    episodes_path: Path = EPISODES_PATH,
    out_dir: Path = OUT_DIR,
    codes_filter: set[str] | None = None,
    case_set_expected_sha256: str | None = CASE_SET_SHA256,
    case_set_expected_row_n: int | None = EXPECTED_ROW_N,
) -> dict[str, Any]:
    """Build the R1A.1 label package. Returns the manifest (and writes outputs)."""
    verify_snapshot_hashes(feature_snapshot_path, label_snapshot_path)

    cases = load_case_set(
        case_set_path,
        expected_sha256=case_set_expected_sha256,
        expected_row_n=case_set_expected_row_n,
    )
    if codes_filter is not None:
        cases = cases[cases["symbol"].isin(codes_filter)].copy()
        if len(cases) == 0:
            raise RuntimeError("codes_filter selects no cases")
    all_codes = set(cases["symbol"])

    feature_bars = load_bars_by_code(feature_snapshot_path, all_codes)
    label_bars = load_bars_by_code(label_snapshot_path, all_codes)
    episodes = load_episodes_patterns(episodes_path)

    rows, label_recompute = _build_rows(cases, feature_bars, label_bars)
    gate_mismatch = [
        row for row in rows
        if row["_gate_outcome_3d"] != row["outcome_3d"]
    ]

    if codes_filter is None:
        # Full mode only: formal audit artifacts.
        out_dir.mkdir(parents=True, exist_ok=True)
        mismatch = pd.DataFrame(
            _provenance_mismatch_rows(cases, episodes, label_recompute)
        )
        # Written regardless of the gate: registers the episodes-vs-validated-bars
        # defect even when the package is blocked.
        mismatch.to_csv(out_dir / "pattern_provenance_mismatch.csv", index=False)

    if codes_filter is None:
        # Full-package mode: regression gate is mandatory before writing 5D.
        if gate_mismatch:
            raise RuntimeError(
                f"3D regression mismatch_n={len(gate_mismatch)}; "
                "no 5D package written"
            )

    out_df = pd.DataFrame(
        [{k: v for k, v in row.items() if k != "_gate_outcome_3d"} for row in rows],
        columns=OUTPUT_COLUMNS,
    )
    if codes_filter is None:
        # Full mode: formal package outputs.
        out_df.to_csv(out_dir / "second_launch_outcome_v01.csv", index=False)
        manifest = {
            "case_set_id": "SUCCESS_CONTROL_CASESET_V01B",
            "case_set_sha256": sha256_file(case_set_path),
            "feature_snapshot_id": FEATURE_SNAPSHOT_ID,
            "feature_snapshot_hash": sha256_file(feature_snapshot_path),
            "label_snapshot_id": LABEL_SNAPSHOT_ID,
            "label_snapshot_hash": sha256_file(label_snapshot_path),
            "source_commit": _source_commit(),
            "row_count": len(out_df),
            "outcome_3d_counts": {k: int(v) for k, v in out_df["outcome_3d"].value_counts().items()},
            "outcome_5d_counts": {k: int(v) for k, v in out_df["outcome_5d"].value_counts().items()},
            "window_incomplete_5d_n": int(out_df["window_incomplete_5d"].sum()),
            "window_incomplete_10d_n": int(out_df["window_incomplete_10d"].sum()),
            "first_event_right_censored_10d_n": int(
                out_df["first_event_right_censored_10d"].sum()
            ),
            "gate_3d_mismatch_n": len(gate_mismatch),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator_path": GENERATOR_PATH,
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        # Bounded mode: fully isolated from formal artifacts.
        bounded_dir = out_dir / "bounded"
        bounded_dir.mkdir(parents=True, exist_ok=True)
        out_df.to_csv(bounded_dir / out_csv_name(codes_filter), index=False)
        manifest = {
            "mode": "BOUNDED",
            "case_set_id": "SUCCESS_CONTROL_CASESET_V01B",
            "codes_filter": sorted(codes_filter),
            "row_count": len(out_df),
            "gate_3d_mismatch_n": len(gate_mismatch),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator_path": GENERATOR_PATH,
        }
    return manifest


def out_csv_name(codes_filter: set[str] | None) -> str:
    if codes_filter is None:
        return "second_launch_outcome_v01.csv"
    return f"second_launch_outcome_v01_codes_{'_'.join(sorted(codes_filter))}.csv"


def _reconciliation_columns(
    case: pd.Series,
    feature_bars: pd.DataFrame,
    label_bars: pd.DataFrame,
) -> tuple[str, bool, bool]:
    """(candidate_status, feature_3d_has_provisional, label_5d_has_provisional)."""
    code = case["symbol"]
    cand = case["candidate_date"]
    cand_row = feature_bars[feature_bars["trade_date"] == cand]
    candidate_status = str(
        cand_row.iloc[0]["reconciliation_status"]
    ) if len(cand_row) else ""
    fwin = future_window(feature_bars, cand, HORIZON_3D)
    lwin = future_window(label_bars, cand, HORIZON_5D)
    feature_3d_has_provisional = bool(
        (fwin["reconciliation_status"] == "PROVISIONAL").any()
    )
    label_5d_has_provisional = bool(
        (lwin["reconciliation_status"] == "PROVISIONAL").any()
    )
    return candidate_status, feature_3d_has_provisional, label_5d_has_provisional


def load_quarantine(
    quarantine_path: Path,
) -> tuple[set[str], str]:
    """Load the frozen quarantine artifact; returns (id_set, sha256)."""
    if not quarantine_path.exists():
        raise RuntimeError(f"quarantine artifact missing: {quarantine_path}")
    q = pd.read_csv(quarantine_path, dtype={"episode_id": str})
    if "episode_id" not in q.columns:
        raise RuntimeError(f"quarantine artifact malformed: {quarantine_path}")
    return set(q["episode_id"]), sha256_file(quarantine_path)


def build_interim_reproducible_package(
    *,
    case_set_path: Path = CASE_SET_PATH,
    case_set_expected_sha256: str | None = CASE_SET_SHA256,
    case_set_expected_row_n: int | None = EXPECTED_ROW_N,
    feature_snapshot_path: Path = FEATURE_SNAPSHOT_PATH,
    label_snapshot_path: Path = LABEL_SNAPSHOT_PATH,
    quarantine_path: Path = QUARANTINE_PATH,
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    """Publish the INTERIM reproducible label package (approved INTERIM_A).

    Publishing gate (no generic bypass): the CURRENT 3D regression mismatch id
    set must equal the registered quarantine id set EXACTLY (both directions),
    and the reproducible subset must have 3D_MISMATCH_N == 0.
    """
    verify_snapshot_hashes(feature_snapshot_path, label_snapshot_path)
    cases = load_case_set(
        case_set_path,
        expected_sha256=case_set_expected_sha256,
        expected_row_n=case_set_expected_row_n,
    )
    all_codes = set(cases["symbol"])
    feature_bars = load_bars_by_code(feature_snapshot_path, all_codes)
    label_bars = load_bars_by_code(label_snapshot_path, all_codes)

    rows, _ = _build_rows(cases, feature_bars, label_bars)
    current_mismatch_ids = {
        row["episode_id"]
        for row in rows
        if row["_gate_outcome_3d"] != row["outcome_3d"]
    }
    quarantine_ids, quarantine_sha = load_quarantine(quarantine_path)

    if current_mismatch_ids != quarantine_ids:
        raise RuntimeError(
            "STATUS=BLOCKED: quarantine set != current 3D mismatch set "
            f"(quarantine-only={len(quarantine_ids - current_mismatch_ids)}, "
            f"mismatch-only={len(current_mismatch_ids - quarantine_ids)})"
        )

    reproducible_ids = set(cases["episode_id"]) - quarantine_ids
    reproducible_cases = cases[cases["episode_id"].isin(reproducible_ids)].copy()
    reproducible_rows = [
        row for row in rows if row["episode_id"] in reproducible_ids
    ]
    subset_mismatch = [
        row for row in reproducible_rows
        if row["_gate_outcome_3d"] != row["outcome_3d"]
    ]
    if subset_mismatch:
        raise RuntimeError(
            f"STATUS=BLOCKED: reproducible subset 3D mismatch_n={len(subset_mismatch)}; "
            "no interim package written"
        )

    out_rows: list[dict[str, Any]] = []
    cases_keyed = reproducible_cases.set_index("episode_id")
    for row in reproducible_rows:
        case = cases_keyed.loc[row["episode_id"]]
        cand_status, f3_prov, l5_prov = _reconciliation_columns(
            case, feature_bars[case["symbol"]], label_bars[case["symbol"]]
        )
        out_rows.append(
            {
                "episode_id": row["episode_id"],
                "symbol": row["symbol"],
                "name": row["name"],
                "anchor_date": row["anchor_date"],
                "candidate_date": row["candidate_date"],
                "outcome_3d": row["outcome_3d"],
                "outcome_reason_3d": row["outcome_reason_3d"],
                "outcome_5d": row["outcome_5d"],
                "outcome_reason_5d": row["outcome_reason_5d"],
                "time_to_s1_10d": row["time_to_s1_10d"],
                "time_to_invalid_10d": row["time_to_invalid_10d"],
                "first_event_type_10d": row["first_event_type_10d"],
                "first_event_date_10d": row["first_event_date_10d"],
                "window_incomplete_5d": row["window_incomplete_5d"],
                "window_incomplete_10d": row["window_incomplete_10d"],
                "first_event_right_censored_10d": row["first_event_right_censored_10d"],
                "candidate_reconciliation_status": cand_status,
                "feature_3d_has_provisional": f3_prov,
                "label_5d_has_provisional": l5_prov,
                "s1_price": row["s1_price"],
                "invalid_price": row["invalid_price"],
                "data_quality": row["data_quality"],
                "quality_flags": row["quality_flags"],
                "feature_snapshot_id": FEATURE_SNAPSHOT_ID,
                "label_snapshot_id_5d": LABEL_SNAPSHOT_ID,
            }
        )
    out_df = pd.DataFrame(out_rows, columns=INTERIM_OUTPUT_COLUMNS)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_dir / "second_launch_outcome_v01b_reproducible.csv", index=False)

    manifest = {
        "artifact_id": "SECOND_LAUNCH_OUTCOME_V01B_REPRODUCIBLE",
        "research_status": "INTERIM_PARTIAL_PROVENANCE",
        "parent_case_set_id": "SUCCESS_CONTROL_CASESET_V01B",
        "parent_case_set_sha256": sha256_file(case_set_path),
        "parent_row_count": len(cases),
        "quarantine_path": str(quarantine_path),
        "quarantine_sha256": quarantine_sha,
        "quarantine_n": len(quarantine_ids),
        "reproducible_row_count": len(out_df),
        "feature_snapshot_id": FEATURE_SNAPSHOT_ID,
        "feature_snapshot_hash": EXPECTED_FEATURE_SNAPSHOT_SHA256,
        "label_snapshot_id": LABEL_SNAPSHOT_ID,
        "label_snapshot_hash": EXPECTED_LABEL_SNAPSHOT_SHA256,
        "3d_mismatch_before_quarantine_n": len(current_mismatch_ids),
        "3d_mismatch_after_quarantine_n": 0,
        "outcome_3d_counts": {
            k: int(v) for k, v in out_df["outcome_3d"].value_counts().items()
        },
        "outcome_5d_counts": {
            k: int(v) for k, v in out_df["outcome_5d"].value_counts().items()
        },
        "window_incomplete_5d_n": int(out_df["window_incomplete_5d"].sum()),
        "window_incomplete_10d_n": int(out_df["window_incomplete_10d"].sum()),
        "first_event_right_censored_10d_n": int(
            out_df["first_event_right_censored_10d"].sum()
        ),
        "cohort_provenance": "PARTIAL",
        "allowed_use": "EXPLORATORY_FACTOR_RESEARCH_ONLY",
        "prohibited_use": [
            "STRATEGY_PROMOTION",
            "PRODUCTION",
            "FORWARD",
            "TRADEPLAN",
        ],
        "generator_commit": _source_commit(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "manifest_v01b_reproducible.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codes",
        nargs="*",
        default=None,
        help="restrict to explicit 6-digit codes (golden bounded check)",
    )
    parser.add_argument(
        "--interim",
        action="store_true",
        help="publish the INTERIM reproducible package (approved INTERIM_A)",
    )
    args = parser.parse_args()
    try:
        if args.interim:
            manifest = build_interim_reproducible_package()
        else:
            manifest = build_package(
                codes_filter=set(args.codes) if args.codes else None
            )
    except RuntimeError as exc:
        # Fail closed: the only expected RuntimeError is the 3D regression gate.
        print(f"STATUS=BLOCKED: {exc}")
        raise SystemExit(2) from exc
    print(json.dumps(manifest, indent=2, sort_keys=True))
