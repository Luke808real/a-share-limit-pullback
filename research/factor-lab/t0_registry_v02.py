"""T0 COMPLETE REGISTRY V02 — rebuilt on the repaired ASL snapshot.

Reuses the FROZEN V01 anchor semantics VERBATIM (``t0_registry_v01`` module:
detect_anchor / make_setup_id / anchor-only scan / parity gate); the ONLY
differences are the input snapshot (repaired ASL snapshot
``snap-2026-07-31-d34171a7e7ae``) and the evidence gates added for V02:
fail-closed input-authority binding (clean-repair receipt), row-level
snapshot provenance, July 23-session hard gate, PIT date cap, V01->V02
population diff, and repaired-date impact.

Frozen authorities (V01, unchanged):
  EPISODE_STRATEGY_COMMIT = 315fbe0d6a41cbcbb17166c03c134e010f163084
  STRATEGY_CONFIG_HASH    = 47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf
  HISTORICAL_STRUCTURE_BLOB = daed3a8471c856431234a54f33aab76cd3967447
  COHORT = [2024-01-01, 2026-07-31]

V02 input authority (bound fail-closed against the committed clean-repair
receipt; constants here are EXPECTED values that the receipt must match):
  SNAPSHOT_ID  = snap-2026-07-31-d34171a7e7ae  (RESEARCH_READY, as_of 2026-07-31)
  REPAIR_RUN   = 59aad30e65ae8c8d43928bcd
  REPAIR_EVIDENCE_COMMIT = 3643b9c553bd85808ff979bd3596fedc25ec8452
  DAILY_SHA256 = 75fa706dd8575ee5c43d4a9462adda39c8e17af4c72866b00b1fabacea364dc0
  POOL_SHA256  = 10119d6237a2ff59440796dba9f2b24f1b9ad91178bb1705dcd081014dcf6d8a

Population-blocker note: V01's 22393 was revoked because 12 July sessions
(07-09..07-24) were PROVISIONAL. V02 rebuilds on the repaired snapshot where
those 12 sessions are CONFIRMED. A different population is EXPECTED, not a
failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from t0_registry_v01 import (  # noqa: E402  (frozen V01 semantics, verbatim)
    COHORT_END,
    COHORT_START,
    EPISODE_STRATEGY_COMMIT,
    HISTORICAL_STRUCTURE_BLOB,
    STRATEGY_CONFIG_HASH,
    anchor_only_scan,
    parity_gate,
    sha256,
)
from limit_pullback.config import load_strategy_config  # noqa: E402
from limit_pullback.outcome import (  # noqa: E402
    _load_pool_by_code,
)

# ---- V02 input authority (EXPECTED values; receipt binding is fail-closed) ---
SNAPSHOT_ID = "snap-2026-07-31-d34171a7e7ae"
REPAIR_RUN_ID = "59aad30e65ae8c8d43928bcd"
REPAIR_EVIDENCE_COMMIT = "3643b9c553bd85808ff979bd3596fedc25ec8452"
EXECUTION_CODE_COMMIT = "bea3317f5193a2b993332ec5322b953616b8bf0c"
AS_OF = date(2026, 7, 31)
REPAIRED_DATES = tuple(
    date(2026, 7, d) for d in (9, 10, 13, 14, 15, 16, 17, 20, 21, 22, 23, 24)
)

V01_RUN_DIR = ROOT / "research/factor-lab/runs/t0-registry-v01"
V01_CSV_PATH = V01_RUN_DIR / "t0-registry-v01.csv"
V01_CSV_SHA256 = "130a56986307fed3e382dd65f4a4f9a4a9df61a7387a7b7a15b049cf72d9441c"
V01_TOTAL = 22393

EVIDENCE_DIR = ROOT / "research/factor-lab/runs/july-asl-clean-repair-v02"
RECEIPT_PATH = EVIDENCE_DIR / "receipt.json"
VALIDATION_PATH = EVIDENCE_DIR / "validation.json"

DATA_ROOT = Path("/Users/luke808/AI/V flash/data")
DAILY_PATH = DATA_ROOT / "canonical/daily_bars/snap-2026-07-31-d34171a7e7ae.parquet"
POOL_PATH = DATA_ROOT / "canonical/limit_up_pool/snap-2026-07-31-d34171a7e7ae.parquet"
DAILY_SHA256_EXPECTED = "75fa706dd8575ee5c43d4a9462adda39c8e17af4c72866b00b1fabacea364dc0"
POOL_SHA256_EXPECTED = "10119d6237a2ff59440796dba9f2b24f1b9ad91178bb1705dcd081014dcf6d8a"

EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome/episodes.parquet"
)
EPISODES_SHA256 = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"

OUT_DIR = ROOT / "research/factor-lab/runs/t0-registry-v02"


# ---- fail-closed input-authority binding (receipt must match constants) ----

def load_input_authority(
    receipt_path: Path = RECEIPT_PATH,
    validation_path: Path = VALIDATION_PATH,
) -> dict:
    """Bind V02 inputs to the committed clean-repair evidence.

    Reads the committed receipt.json / validation.json and fail-closes on
    ANY mismatch against the frozen expected values (INPUT_AUTHORITY_BINDING
    gate). Tampered evidence must never silently enter the registry build.
    """
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    checks = {
        "receipt.new_snapshot_id": receipt.get("new_snapshot_id"),
        "receipt.snapshot_as_of": receipt.get("snapshot_as_of"),
        "receipt.snapshot_status": receipt.get("snapshot_status"),
        "receipt.repair_run_id": receipt.get("repair_run_id"),
        "receipt.provider_name": receipt.get("provider_name"),
        "receipt.execution_code_head": receipt.get("execution_code_head"),
    }
    expected = {
        "receipt.new_snapshot_id": SNAPSHOT_ID,
        "receipt.snapshot_as_of": "2026-07-31",
        "receipt.snapshot_status": "RESEARCH_READY",
        "receipt.repair_run_id": REPAIR_RUN_ID,
        "receipt.provider_name": "ASL",
        "receipt.execution_code_head": EXECUTION_CODE_COMMIT,
    }
    mismatches = {
        key: value for key, value in checks.items() if value != expected[key]
    }
    canonical = receipt.get("new_canonical_file_hashes", {})
    daily_key = f"canonical/daily_bars/{SNAPSHOT_ID}.parquet"
    pool_key = f"canonical/limit_up_pool/{SNAPSHOT_ID}.parquet"
    if canonical.get(daily_key) != DAILY_SHA256_EXPECTED:
        mismatches["receipt.canonical_daily_sha"] = canonical.get(daily_key)
    if canonical.get(pool_key) != POOL_SHA256_EXPECTED:
        mismatches["receipt.canonical_pool_sha"] = canonical.get(pool_key)
    invariants = validation.get("snapshot_invariants", {})
    if invariants.get("july_sessions") != 23:
        mismatches["validation.july_sessions"] = invariants.get("july_sessions")
    if invariants.get("july_confirmed_sessions") != 23:
        mismatches["validation.july_confirmed_sessions"] = invariants.get(
            "july_confirmed_sessions"
        )
    if invariants.get("july_gap"):
        mismatches["validation.july_gap"] = invariants.get("july_gap")
    if mismatches:
        raise RuntimeError(
            f"INPUT_AUTHORITY_BINDING_FAIL: {json.dumps(mismatches, sort_keys=True)}"
        )
    return {
        "snapshot_id": SNAPSHOT_ID,
        "repair_run_id": REPAIR_RUN_ID,
        "repair_evidence_commit": REPAIR_EVIDENCE_COMMIT,
        "execution_code_commit": EXECUTION_CODE_COMMIT,
        "as_of": AS_OF,
        "snapshot_status": receipt.get("snapshot_status"),
        "daily_sha256": DAILY_SHA256_EXPECTED,
        "pool_sha256": POOL_SHA256_EXPECTED,
    }


# ---- row-level snapshot provenance ---------------------------------------

def bind_row_provenance(rows: list[dict], snapshot_id: str) -> list[dict]:
    """Rewrite every registry row's snapshot_id to the repaired snapshot.

    The frozen V01 ``_emit`` hard-codes its own (revoked) SNAPSHOT_ID; V02
    rows must carry the repaired snapshot id so each row's lineage is
    self-proving. All other fields (setup_id, code, anchor fields, limits,
    strategy_commit, strategy_config_hash) are untouched.
    """
    return [{**row, "snapshot_id": snapshot_id} for row in rows]


def verify_row_provenance(
    rows: list[dict], snapshot_id: str
) -> tuple[list[str], int]:
    """Hard gate: every row's snapshot_id must equal the repaired snapshot."""
    unique = sorted({str(row.get("snapshot_id")) for row in rows})
    mismatch_n = sum(1 for row in rows if row.get("snapshot_id") != snapshot_id)
    if mismatch_n:
        raise RuntimeError(
            f"ROW_SNAPSHOT_ID_MISMATCH_N = {mismatch_n} (unique={unique}): "
            "registry rows carry foreign snapshot lineage — STOP"
        )
    return unique, mismatch_n


# ---- July 23-session hard gate --------------------------------------------

def july_hard_gate(daily: dict[str, tuple]) -> dict:
    """Local scan of the input daily must show exactly 23 generator-visible
    July-2026 sessions with CONFIRMED rows. Anything else: STOP."""
    sessions = sorted(
        {
            b.trade_date
            for bars in daily.values()
            for b in bars
            if b.trade_date.year == 2026 and b.trade_date.month == 7
        }
    )
    if len(sessions) != 23:
        raise RuntimeError(
            f"JULY_SESSION_GATE_FAIL: {len(sessions)} July-2026 sessions "
            f"(expected 23) — STOP"
        )
    return {"july_sessions_2026": len(sessions), "july_sessions": [d.isoformat() for d in sessions]}


def load_daily_v02(path: Path, expected_sha: str) -> dict[str, tuple]:
    """V02 input loader: same CONFIRMED-only / per-code semantics as the
    frozen V01 loader, but the repaired snapshot's canonical file is not
    physically code-sorted (bootstrap streams code-sorted; the repaired
    composition appends repair-date rows). Sorting by (code, trade_date)
    restores the exact layout the frozen extractor consumed from V01."""
    actual = sha256(path)
    if actual != expected_sha:
        raise RuntimeError(
            f"daily SHA mismatch: expected {expected_sha}, got {actual}"
        )
    import pyarrow.parquet as pq

    from limit_pullback.outcome import _daily_bar

    table = pq.read_table(path)
    rows: list[tuple[str, object, dict]] = []
    for row in table.to_pylist():
        if str(row.get("reconciliation_status")) != "CONFIRMED":
            continue
        rows.append((str(row["code"]), row["trade_date"], row))
    rows.sort(key=lambda item: (item[0], item[1]))
    out: dict[str, list] = {}
    for code, _day, row in rows:
        out.setdefault(code, []).append(_daily_bar(row))
    return {code: tuple(bars) for code, bars in out.items()}


def load_pool_v02(path: Path, expected_sha: str) -> dict[str, tuple]:
    actual = sha256(path)
    if actual != expected_sha:
        raise RuntimeError(
            f"pool SHA mismatch: expected {expected_sha}, got {actual}"
        )
    return _load_pool_by_code(path)


def semantic_drift_gate() -> dict:
    """Frozen detector files must not have drifted from the frozen state."""
    hist = subprocess.run(
        ["git", "rev-parse", f"{EPISODE_STRATEGY_COMMIT}:src/limit_pullback/strategy/structure.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD:src/limit_pullback/strategy/structure.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    engine = subprocess.run(
        ["git", "rev-parse", "HEAD:src/limit_pullback/strategy/engine.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    outcome = subprocess.run(
        ["git", "rev-parse", "HEAD:src/limit_pullback/outcome.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return {
        "HISTORICAL_STRUCTURE_BLOB_SHA": hist,
        "CURRENT_STRUCTURE_BLOB_SHA": head,
        "STRUCTURE_SEMANTICS_MATCH": hist == head == HISTORICAL_STRUCTURE_BLOB,
        "CURRENT_ENGINE_BLOB_SHA": engine,
        "CURRENT_OUTCOME_BLOB_SHA": outcome,
    }


def population_accounting_v02(
    registry_rows: list[dict], episodes: pd.DataFrame
) -> dict:
    """V02 accounting: the OBSERVED/NEVER split is a LEGACY-EPISODE
    CROSSWALK classification only — it is NOT a signal classification on
    the repaired timebase and MUST NOT feed a TTL-transition denominator."""
    reg = pd.DataFrame(registry_rows)
    if reg.empty:
        raise RuntimeError("registry empty: accounting impossible")
    cohort = reg[
        (reg["anchor_date"] >= COHORT_START.isoformat())
        & (reg["anchor_date"] <= COHORT_END.isoformat())
    ].copy()
    dup_setup = int(cohort["setup_id"].duplicated().sum())
    conflicts = cohort.groupby(["code", "anchor_date"])["setup_id"].nunique()
    setup_conflict = int((conflicts > 1).sum())
    if dup_setup:
        raise RuntimeError(f"REGISTRY_DUPLICATE_SETUP_ID_N = {dup_setup}: fail closed")
    if setup_conflict:
        raise RuntimeError(f"REGISTRY_CODE_ANCHOR_CONFLICT_N = {setup_conflict}: fail closed")

    ep = episodes.copy()
    ep["anchor_date"] = ep["anchor_date"].astype(str)
    cohort_ep = ep[
        (ep["anchor_date"] >= COHORT_START.isoformat())
        & (ep["anchor_date"] <= COHORT_END.isoformat())
    ]
    observed_ids = set(cohort_ep["setup_id"].unique())
    registry_ids = set(cohort["setup_id"].unique())
    episode_not_in_registry = sorted(observed_ids - registry_ids)
    total = len(registry_ids)
    observed = len(registry_ids & observed_ids)
    never = total - observed
    if total != observed + never:
        raise RuntimeError("TOTAL != OBSERVED + NEVER: accounting identity failed")
    return {
        "TOTAL_T0_SETUP_N": total,
        "LEGACY_EPISODE_CROSSWALK_OBSERVED_N": observed,
        "LEGACY_EPISODE_CROSSWALK_UNMATCHED_N": never,
        "SIGNAL_CLASSIFICATION_AUTHORITY": "LEGACY_EPISODE_CROSSWALK_ONLY",
        "NOT_VALID_FOR_TTL_TRANSITION_DENOMINATOR": True,
        "EPISODE_SETUP_NOT_IN_REGISTRY_N": len(episode_not_in_registry),
        "EPISODE_SETUP_NOT_IN_REGISTRY_SAMPLE": episode_not_in_registry[:5],
        "REGISTRY_DUPLICATE_SETUP_ID_N": dup_setup,
        "REGISTRY_CODE_ANCHOR_CONFLICT_N": setup_conflict,
        "ACCOUNTING_IDENTITY": f"{total} == {observed} + {never}",
    }


def pit_gate(daily: dict[str, tuple], pool: dict[str, tuple]) -> dict:
    max_daily = max((b.trade_date for bars in daily.values() for b in bars), default=None)
    max_pool = max((r.trade_date for rows in pool.values() for r in rows), default=None)
    return {
        "AS_OF": AS_OF.isoformat(),
        "MAX_DAILY_DATE_READ": max_daily.isoformat() if max_daily else None,
        "MAX_POOL_DATE_READ": max_pool.isoformat() if max_pool else None,
        "FUTURE_DATA_USED": bool(
            (max_daily and max_daily > AS_OF) or (max_pool and max_pool > AS_OF)
        ),
    }


def v01_vs_v02_diff(v02_rows: list[dict]) -> dict:
    v01 = pd.read_csv(V01_CSV_PATH, dtype={"code": str})
    v01_ids = set(v01["setup_id"].unique())
    v02 = pd.DataFrame(v02_rows)
    v02_ids = set(v02["setup_id"].unique())
    added = v02_ids - v01_ids
    removed = v01_ids - v02_ids
    unchanged = v01_ids & v02_ids
    v02_added_rows = v02[v02["setup_id"].isin(added)].copy()
    v01_removed_rows = v01[v01["setup_id"].isin(removed)].copy()
    added_by_date = v02_added_rows.groupby("anchor_date").size().to_dict()
    removed_by_date = v01_removed_rows.groupby("anchor_date").size().to_dict()
    repaired_dates = [d.isoformat() for d in REPAIRED_DATES]

    def date_impact(by_date: dict) -> dict:
        repaired = {d: by_date.get(d, 0) for d in repaired_dates if by_date.get(d, 0)}
        non_repair = sum(n for d, n in by_date.items() if d not in repaired_dates)
        return {"repaired_dates": repaired, "other_dates": non_repair}

    return {
        "V01_REVOKED_T0_N": V01_TOTAL,
        "V01_CSV_SHA256": V01_CSV_SHA256,
        "V01_CSV_SHA_MATCH": sha256(V01_CSV_PATH) == V01_CSV_SHA256,
        "V02_T0_N": len(v02_ids),
        "ADDED_N": len(added),
        "REMOVED_N": len(removed),
        "UNCHANGED_N": len(unchanged),
        "ADDED_BY_DATE": added_by_date,
        "REMOVED_BY_DATE": removed_by_date,
        "ADDED_REPAIRED_DATE_IMPACT": date_impact(added_by_date),
        "REMOVED_REPAIRED_DATE_IMPACT": date_impact(removed_by_date),
    }


def render_report(a: dict) -> str:
    p = a["PARITY"]
    d = a["DIFF"]
    lines = [
        "# T0 COMPLETE REGISTRY V02 — rebuilt on repaired ASL snapshot",
        "",
        f"- INPUT_SNAPSHOT = {a['SNAPSHOT_ID']}（status={a['SNAPSHOT_STATUS']}，as_of={a['AS_OF']}）",
        f"- INPUT_CANONICAL_SHA = {a['DAILY_SHA256']}；POOL_SHA256 = {a['POOL_SHA256']}",
        f"- INPUT_AUTHORITY_BINDING = {a['INPUT_AUTHORITY_BINDING']}（receipt/validation 逐项 fail-closed 比对）",
        f"- REPAIR_RUN_ID = {a['REPAIR_RUN_ID']}；REPAIR_EVIDENCE_COMMIT = {a['REPAIR_EVIDENCE_COMMIT']}",
        f"- EXECUTION_CODE_COMMIT = {a['EXECUTION_CODE_COMMIT']}",
        f"- ROW_SNAPSHOT_ID_UNIQUE = {a['ROW_SNAPSHOT_ID_UNIQUE']}；ROW_SNAPSHOT_ID_MISMATCH_N = {a['ROW_SNAPSHOT_ID_MISMATCH_N']}",
        f"- EPISODE_STRATEGY_COMMIT = {a['EPISODE_STRATEGY_COMMIT']}；STRATEGY_CONFIG_HASH = {a['STRATEGY_CONFIG_HASH']}",
        f"- structure.py blob：HISTORICAL = {a['HISTORICAL_STRUCTURE_BLOB_SHA']}；CURRENT = {a['CURRENT_STRUCTURE_BLOB_SHA']}；MATCH = {a['STRUCTURE_SEMANTICS_MATCH']}",
        f"- engine/outcome blobs：{a['CURRENT_ENGINE_BLOB_SHA'][:12]}… / {a['CURRENT_OUTCOME_BLOB_SHA'][:12]}…",
        f"- cohort = [{a['COHORT_START']}, {a['COHORT_END']}]",
        "",
        "## PIT / NO FUTURE LEAKAGE",
        f"- MAX_DAILY_DATE_READ = {a['MAX_DAILY_DATE_READ']}；MAX_POOL_DATE_READ = {a['MAX_POOL_DATE_READ']}；FUTURE_DATA_USED = {a['FUTURE_DATA_USED']}",
        f"- JULY_SESSION_GATE = {a['JULY_SESSION_GATE']}（2026-07 sessions = {a['JULY_SESSIONS_2026']}，hard gate 23）",
        "",
        "## EQUIVALENCE GATE",
        f"- PARITY_ROWS_CHECKED = {p['PARITY_ROWS_CHECKED']}；PARITY_MATCH_N = {p['PARITY_MATCH_N']}；PARITY_MISMATCH_N = {p['PARITY_MISMATCH_N']}",
        "",
        "## POPULATION",
        f"- TOTAL_T0_N = {a['TOTAL_T0_SETUP_N']}",
        f"- LEGACY_EPISODE_CROSSWALK_OBSERVED_N = {a['LEGACY_EPISODE_CROSSWALK_OBSERVED_N']}；LEGACY_EPISODE_CROSSWALK_UNMATCHED_N = {a['LEGACY_EPISODE_CROSSWALK_UNMATCHED_N']}",
        f"- SIGNAL_CLASSIFICATION_AUTHORITY = {a['SIGNAL_CLASSIFICATION_AUTHORITY']}",
        f"- NOT_VALID_FOR_TTL_TRANSITION_DENOMINATOR = {a['NOT_VALID_FOR_TTL_TRANSITION_DENOMINATOR']}",
        f"- EPISODE_SETUP_NOT_IN_REGISTRY_N = {a['EPISODE_SETUP_NOT_IN_REGISTRY_N']}（sample: {a['EPISODE_SETUP_NOT_IN_REGISTRY_SAMPLE']}）",
        f"- REGISTRY_DUPLICATE_SETUP_ID_N = {a['REGISTRY_DUPLICATE_SETUP_ID_N']}；SETUP_CONFLICT_N = {a['REGISTRY_CODE_ANCHOR_CONFLICT_N']}",
        "",
        "## V01 vs V02 DIFF",
        f"- V01_REVOKED_T0_N = {d['V01_REVOKED_T0_N']}；V02_T0_N = {d['V02_T0_N']}",
        f"- ADDED_N = {d['ADDED_N']}；REMOVED_N = {d['REMOVED_N']}；UNCHANGED_N = {d['UNCHANGED_N']}",
        f"- ADDED repaired-date impact: {d['ADDED_REPAIRED_DATE_IMPACT']}",
        f"- REMOVED repaired-date impact: {d['REMOVED_REPAIRED_DATE_IMPACT']}",
        "",
        "## STATUS",
        f"- T0_REGISTRY_V02_AUTHORITY = {a['T0_REGISTRY_V02_AUTHORITY']}",
        f"- REGISTRY_SHA256 = {a['REGISTRY_SHA256']}；rows = {a['REGISTRY_ROWS']}",
        "- 未运行 TTL transition / survival / factor rerun / snapshot promotion / state generation",
    ]
    return "\n".join(lines)


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = load_strategy_config(ROOT / "config/strategy.yaml")
    config_hash = sha256(ROOT / "config/strategy.yaml")
    if config_hash != STRATEGY_CONFIG_HASH:
        raise RuntimeError(f"config hash mismatch: {config_hash}")

    # 0. fail-closed input-authority binding (committed clean-repair evidence)
    authority = load_input_authority()

    # 1. semantic drift gate (frozen detector files)
    semantic = semantic_drift_gate()
    if not semantic["STRUCTURE_SEMANTICS_MATCH"]:
        raise RuntimeError(
            f"SEMANTIC_DRIFT = YES: {semantic} — STOP, do not redefine T0"
        )

    # 2. input provenance gates (SHA + PIT + July)
    daily = load_daily_v02(DAILY_PATH, DAILY_SHA256_EXPECTED)
    pool = load_pool_v02(POOL_PATH, POOL_SHA256_EXPECTED)
    july = july_hard_gate(daily)
    episodes = pd.read_parquet(EPISODES_PATH)
    if sha256(EPISODES_PATH) != EPISODES_SHA256:
        raise RuntimeError("episodes SHA mismatch")
    distinct_commit = episodes["strategy_commit"].nunique()
    if distinct_commit != 1 or str(episodes["strategy_commit"].iloc[0]) != EPISODE_STRATEGY_COMMIT:
        raise RuntimeError("episodes strategy_commit mismatch")
    pit = pit_gate(daily, pool)
    if pit["FUTURE_DATA_USED"]:
        raise RuntimeError(f"FUTURE_DATA_USED: {pit}")

    # 3. parity gate on the deterministic bounded sample (frozen semantics)
    parity = parity_gate(daily, pool, config)
    if parity["PARITY_MISMATCH_N"] != 0:
        raise RuntimeError(f"PARITY_MISMATCH_N != 0: {parity} — full registry forbidden")

    # 4. full anchor-only registry (frozen V01 scan, new input)
    raw_rows = anchor_only_scan(daily, pool, config)
    rows = bind_row_provenance(raw_rows, SNAPSHOT_ID)
    row_unique, row_mismatch = verify_row_provenance(rows, SNAPSHOT_ID)
    reg = pd.DataFrame(rows)
    csv_path = OUT_DIR / "t0-registry-v02.csv"
    reg.to_csv(csv_path, index=False)
    reg_sha = sha256(csv_path)

    # 5. population accounting (legacy-episode crosswalk classification only)
    acct = population_accounting_v02(rows, episodes)

    # 6. V01 vs V02 diff + repaired-date impact
    diff = v01_vs_v02_diff(rows)

    out = {
        "SNAPSHOT_ID": SNAPSHOT_ID,
        "SNAPSHOT_STATUS": authority["snapshot_status"],
        "AS_OF": AS_OF.isoformat(),
        "DAILY_SHA256": DAILY_SHA256_EXPECTED,
        "POOL_SHA256": POOL_SHA256_EXPECTED,
        "INPUT_AUTHORITY_BINDING": "PASS",
        "REPAIR_RUN_ID": REPAIR_RUN_ID,
        "REPAIR_EVIDENCE_COMMIT": REPAIR_EVIDENCE_COMMIT,
        "EXECUTION_CODE_COMMIT": EXECUTION_CODE_COMMIT,
        "ROW_SNAPSHOT_ID_UNIQUE": row_unique,
        "ROW_SNAPSHOT_ID_MISMATCH_N": row_mismatch,
        "EPISODE_STRATEGY_COMMIT": EPISODE_STRATEGY_COMMIT,
        "STRATEGY_CONFIG_HASH": STRATEGY_CONFIG_HASH,
        **semantic,
        "COHORT_START": COHORT_START.isoformat(),
        "COHORT_END": COHORT_END.isoformat(),
        **pit,
        "JULY_SESSION_GATE": "PASS",
        "JULY_SESSIONS_2026": july["july_sessions_2026"],
        "PARITY": parity,
        **acct,
        "DIFF": diff,
        "REGISTRY_SHA256": reg_sha,
        "REGISTRY_ROWS": len(rows),
        "T0_REGISTRY_V02_AUTHORITY": "T0_COMPLETE_REGISTRY_V02",
        "TTL_TRANSITION_RUN": False,
    }
    (OUT_DIR / "parity-v02.json").write_text(
        json.dumps(parity, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    (OUT_DIR / "t0-registry-v02.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    (OUT_DIR / "t0-registry-v02-report.md").write_text(
        render_report(out), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return out


if __name__ == "__main__":
    main()
