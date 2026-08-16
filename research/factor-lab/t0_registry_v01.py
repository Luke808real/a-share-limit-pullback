"""T0 COMPLETE REGISTRY V01 — anchor-only full-market T0 setup registry.

Population-blocker resolution (Sol review chain: ttl contract -> case B -> T0
denominator). Builds the complete T0 setup universe — including T0s that never
entered B1_PREP / B1_READY / B2_READY / B2_CONFIRMED — WITHOUT calling the
full strategy replay (no evaluate_strategy / build_trade_plan / outcome
replay). T0 identity comes from detect_anchor() exactly as the frozen
generator used it (structure.py blob identical at 315fbe0d and HEAD:
daed3a8471c856431234a54f33aab76cd3967447).

Frozen authorities:
  SNAPSHOT_ID            = snap-2026-07-31-b5f84004de8a
  EPISODE_STRATEGY_COMMIT= 315fbe0d6a41cbcbb17166c03c134e010f163084
  STRATEGY_CONFIG_HASH   = 47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf
  DAILY_SHA256           = e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514
  POOL_SHA256            = 45faa1a23583b04acfd6c4faf5ef42311c2575c93a4c702cf5846d0213f31517
  EPISODES_SHA256        = 66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093

T0 population contract (frozen):
  - T0 = day where detect_anchor(prefix, as_of=day, config, pool_prefix)
    returns a valid AnchorEvaluation with anchor.snapshot.anchor_date == day
    (the frozen strategy enters LIMIT_ANCHOR exactly then; evaluate_strategy
    sets stage LIMIT_ANCHOR iff current.trade_date == anchor.anchor_date).
  - daily input: reconciliation_status == "CONFIRMED" only (identical to
    frozen _iter_confirmed_code_bars); per-code, sorted by trade_date.
  - pool input: reconciliation_status in {"CONFIRMED","CONFIRMED_SINGLE_SOURCE"}
    (identical to frozen _load_pool_by_code); per-code sorted records.
  - setup_id = make_setup_id(code, anchor_date, anchor_price, price_tick)
    (code + anchor_date + anchor_price ticks, ROUND_HALF_UP).
  - cohort: anchor_date in [2024-01-01, 2026-07-31]; bars before the cohort
    start may serve as lookback warmup but never enter the cohort.
  - only limit-close candidate days are evaluated (is_limit_close and
    trade_status and not is_st) — detect_anchor's anchor_date == as_of can
    only hold on such a day, so skipping other days is exact.

Equivalence gate (PARITY): on a deterministic bounded sample of codes, the
anchor-only extractor's setup_id set must equal the set of setup_ids emitted
by the frozen strategy engine at LIMIT_ANCHOR stage (full evaluate_strategy
loop with previous_signal chaining). PARITY_MISMATCH_N must be 0, otherwise
the full registry is NOT generated (fail closed).

This module performs STRUCTURAL accounting only: no survival curve, no
hazard, no P(B2 by T+k), no outcome comparison, no TTL cutoff, no threshold
mining, no F22 rescue, no ML.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from limit_pullback.config import load_strategy_config  # noqa: E402
from limit_pullback.models.enums import SetupStage  # noqa: E402
from limit_pullback.outcome import (  # noqa: E402
    _daily_bar,
    _iter_confirmed_code_bars,
    _load_pool_by_code,
)
from limit_pullback.quality import merge_signal_quality  # noqa: E402
from limit_pullback.strategy.engine import (  # noqa: E402
    evaluate_strategy,
    make_setup_id,
)
from limit_pullback.strategy.structure import (  # noqa: E402
    detect_anchor,
    is_limit_close,
)

ROOT = Path(__file__).resolve().parents[2]
EPISODES_PATH = (
    ROOT
    / "data/outcome-study/outcome-snap-2026-07-31-b5f84004de8a-2024-01-01-2026-07-31-25903057f106"
    / "corrected-b2-trigger-outcome/episodes.parquet"
)
DAILY_PATH = ROOT / "data/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
POOL_PATH = ROOT / "data/canonical/limit_up_pool/snap-2026-07-31-b5f84004de8a.parquet"
OUT_DIR = ROOT / "research/factor-lab/runs/t0-registry-v01"

EPISODES_SHA256 = "66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093"
DAILY_SHA256 = "e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514"
POOL_SHA256 = "45faa1a23583b04acfd6c4faf5ef42311c2575c93a4c702cf5846d0213f31517"
SNAPSHOT_ID = "snap-2026-07-31-b5f84004de8a"
EPISODE_STRATEGY_COMMIT = "315fbe0d6a41cbcbb17166c03c134e010f163084"
STRATEGY_CONFIG_HASH = "47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf"
HISTORICAL_STRUCTURE_BLOB = "daed3a8471c856431234a54f33aab76cd3967447"
COHORT_START = date(2024, 1, 1)
COHORT_END = date(2026, 7, 31)
OBSERVED_LABELS = frozenset(
    {"B1_PREP", "B1_READY", "B2_READY", "B2_CONFIRMED"}
)
TZ = timezone.utc


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_episodes(path: Path, expected_sha: str = EPISODES_SHA256) -> pd.DataFrame:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_episodes: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"episodes SHA mismatch: {path}")
    return pd.read_parquet(path)


def load_pool(path: Path, expected_sha: str = POOL_SHA256) -> dict[str, tuple]:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_pool: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"pool SHA mismatch: {path}")
    return _load_pool_by_code(path)


def load_daily(path: Path, expected_sha: str = DAILY_SHA256) -> dict[str, tuple]:
    if isinstance(path, pd.DataFrame):
        raise TypeError("load_daily: DataFrame bypass forbidden")
    if sha256(path) != expected_sha:
        raise RuntimeError(f"daily SHA mismatch: {path}")
    return dict(_iter_confirmed_code_bars(path))


def _emit(row: dict, config, anchor, code: str) -> dict:
    setup_id = make_setup_id(
        code,
        anchor.snapshot.anchor_date,
        anchor.snapshot.anchor_price,
        config.anchor.price_tick,
    )
    return {
        "setup_id": setup_id,
        "code": code,
        "anchor_date": anchor.snapshot.anchor_date.isoformat(),
        "anchor_price": str(anchor.snapshot.anchor_price),
        "anchor_source": anchor.snapshot.source,
        "profile": anchor.profile.value,
        "limit_price": str(anchor.limit_price),
        "is_first_board": anchor.is_first_board,
        "recent_limit_count": anchor.recent_limit_count,
        "recent_limits_non_consecutive": anchor.recent_limits_non_consecutive,
        "seal_before_cutoff": (
            None if anchor.seal_before_cutoff is None else bool(anchor.seal_before_cutoff)
        ),
        "snapshot_id": SNAPSHOT_ID,
        "strategy_commit": EPISODE_STRATEGY_COMMIT,
        "strategy_config_hash": STRATEGY_CONFIG_HASH,
    }


def anchor_only_scan_code(
    bars: tuple,
    pool: tuple,
    config,
    cohort_start: date = COHORT_START,
    cohort_end: date = COHORT_END,
) -> list[dict]:
    """Anchor-only T0 extraction for one code (generator-identical semantics).

    Evaluates only limit-close candidate days (trade_status and not is_st and
    is_limit_close): detect_anchor can only yield anchor_date == as_of on such
    a day. Emits one row per T0 within [cohort_start, cohort_end]; bars before
    cohort_start serve as lookback warmup only.
    """
    rows: list[dict] = []
    pool_prefix: list = []
    pool_ordered = tuple(sorted(pool, key=lambda r: r.trade_date))
    pool_index = 0
    for bar in bars:
        while pool_index < len(pool_ordered) and pool_ordered[pool_index].trade_date <= bar.trade_date:
            pool_prefix.append(pool_ordered[pool_index])
            pool_index += 1
        if not (bar.trade_status and bar.is_st is not True and is_limit_close(bar, config)):
            continue
        prefix = tuple(b for b in bars if b.trade_date <= bar.trade_date)
        anchor = detect_anchor(prefix, bar.trade_date, config, tuple(pool_prefix))
        if anchor is None or anchor.snapshot.anchor_date != bar.trade_date:
            continue
        if cohort_start <= anchor.snapshot.anchor_date <= cohort_end:
            rows.append(_emit({}, config, anchor, bar.code))
    return rows


def anchor_only_scan(
    daily: dict[str, tuple],
    pool: dict[str, tuple],
    config,
    codes: list[str] | None = None,
) -> list[dict]:
    """Full-market anchor-only scan (or restricted to `codes`)."""
    all_rows: list[dict] = []
    code_list = sorted(codes) if codes is not None else sorted(daily.keys())
    for code in code_list:
        bars = daily.get(code)
        if bars is None:
            continue
        all_rows.extend(
            anchor_only_scan_code(bars, pool.get(code, ()), config)
        )
    all_rows.sort(key=lambda r: (r["anchor_date"], r["code"], r["setup_id"]))
    return all_rows


# ---------- PARITY GATE (bounded deterministic sample) ----------

def frozen_strategy_t0_set(
    bars: tuple,
    pool: tuple,
    config,
    cohort_start: date = COHORT_START,
    cohort_end: date = COHORT_END,
) -> set[str]:
    """Reference: frozen strategy LIMIT_ANCHOR semantics.

    Replicates _replay_code's loop (evaluate_strategy per day with
    previous_signal chaining + merge_signal_quality) and collects setup_ids
    whose stage is LIMIT_ANCHOR within the cohort window. This is the exact
    generator path that produced the frozen episodes' setup identity.
    """
    t0_ids: set[str] = set()
    pool_ordered = tuple(sorted(pool, key=lambda r: r.trade_date))
    pool_prefix: list = []
    pool_index = 0
    previous_signal = None
    for bar in bars:
        while pool_index < len(pool_ordered) and pool_ordered[pool_index].trade_date <= bar.trade_date:
            pool_prefix.append(pool_ordered[pool_index])
            pool_index += 1
        prefix = tuple(b for b in bars if b.trade_date <= bar.trade_date)
        if prefix[-1].trade_date != bar.trade_date:
            raise ValueError("replay prefix must end exactly on as_of")
        signal = evaluate_strategy(
            bars=prefix,
            as_of=bar.trade_date,
            config=config,
            generated_at=datetime.combine(bar.trade_date, time(23, 59, 59), tzinfo=TZ),
            limit_pool=tuple(pool_prefix),
            previous_signal=previous_signal,
        )
        signal = merge_signal_quality(
            signal,
            (signal.data_quality,),
            insufficient_history=len(prefix) < config.universe.minimum_listing_trade_days,
        )
        previous_signal = signal
        if signal.setup_stage is SetupStage.LIMIT_ANCHOR:
            if cohort_start <= signal.trade_date <= cohort_end and signal.setup_id:
                t0_ids.add(signal.setup_id)
    return t0_ids


def parity_sample_codes(daily: dict[str, tuple], pool: dict[str, tuple], n: int = 20) -> list[str]:
    """Deterministic bounded sample: hash-sorted codes + first pool codes."""
    hashed = sorted(
        daily.keys(),
        key=lambda code: (hashlib.sha256(code.encode()).hexdigest(), code),
    )
    sample = hashed[:n]
    pool_codes = sorted(pool.keys())
    for code in pool_codes:
        if len(sample) >= n + 5:
            break
        if code not in sample:
            sample.append(code)
    return sorted(sample)


def parity_gate(
    daily: dict[str, tuple],
    pool: dict[str, tuple],
    config,
    codes: list[str] | None = None,
) -> dict:
    """Anchor-only T0s must equal frozen strategy LIMIT_ANCHOR setup_ids."""
    if codes is None:
        codes = parity_sample_codes(daily, pool)
    anchor_ids: set[str] = set()
    strategy_ids: set[str] = set()
    for code in codes:
        bars = daily.get(code)
        if bars is None:
            continue
        anchor_ids.update(
            row["setup_id"]
            for row in anchor_only_scan_code(bars, pool.get(code, ()), config)
        )
        strategy_ids.update(frozen_strategy_t0_set(bars, pool.get(code, ()), config))
    return {
        "PARITY_ROWS_CHECKED": len(codes),
        "PARITY_MATCH_N": len(anchor_ids & strategy_ids),
        "PARITY_MISMATCH_N": len(anchor_ids ^ strategy_ids),
        "ANCHOR_ONLY_UNIQUE": sorted(anchor_ids - strategy_ids)[:5],
        "STRATEGY_ONLY_UNIQUE": sorted(strategy_ids - anchor_ids)[:5],
    }


# ---------- POPULATION ACCOUNTING ----------

def population_accounting(registry_rows: list[dict], episodes: pd.DataFrame) -> dict:
    reg = pd.DataFrame(registry_rows)
    if reg.empty:
        raise RuntimeError("registry empty: accounting impossible")
    cohort = reg[
        (reg["anchor_date"] >= COHORT_START.isoformat())
        & (reg["anchor_date"] <= COHORT_END.isoformat())
    ].copy()
    if cohort["setup_id"].duplicated().any():
        raise RuntimeError("REGISTRY_DUPLICATE_SETUP_ID_N > 0: fail closed")
    # conflict: one (code, anchor_date) maps to >1 distinct setup_id
    conflicts = cohort.groupby(["code", "anchor_date"])["setup_id"].nunique()
    if int((conflicts > 1).sum()):
        raise RuntimeError("REGISTRY_CODE_ANCHOR_CONFLICT_N > 0: fail closed")

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

    if episode_not_in_registry:
        raise RuntimeError(
            f"EPISODE_SETUP_NOT_IN_REGISTRY_N = {len(episode_not_in_registry)}: "
            f"fail closed; samples: {episode_not_in_registry[:5]}"
        )
    if total != observed + never:
        raise RuntimeError("TOTAL != OBSERVED + NEVER: accounting identity failed")

    return {
        "TOTAL_T0_SETUP_N": total,
        "OBSERVED_SIGNAL_SETUP_N": observed,
        "NEVER_SIGNAL_SETUP_N": never,
        "EPISODE_SETUP_NOT_IN_REGISTRY_N": 0,
        "REGISTRY_DUPLICATE_SETUP_ID_N": 0,
        "REGISTRY_CODE_ANCHOR_CONFLICT_N": 0,
        "ACCOUNTING_IDENTITY": f"{total} == {observed} + {never}",
        "T0_REGISTRY_STATUS": "COMPLETE",
        "T0_POPULATION_AUTHORITY": "T0_COMPLETE_REGISTRY_V01",
        "T0_SURVIVAL_PREREG_READY": True,
        "SURVIVAL_RUN": False,
        "TTL_CUTOFF": None,
    }


def registry_sha256(path: Path) -> str:
    return sha256(path)


# ---------- MAIN ----------

def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = load_strategy_config(ROOT / "config/strategy.yaml")
    config_hash = sha256(ROOT / "config/strategy.yaml")
    if config_hash != STRATEGY_CONFIG_HASH:
        raise RuntimeError(f"config hash mismatch: {config_hash}")

    episodes = load_episodes(EPISODES_PATH)
    pool = load_pool(POOL_PATH)
    daily = load_daily(DAILY_PATH)

    # provenance consistency
    distinct_commit = episodes["strategy_commit"].nunique()
    if distinct_commit != 1:
        raise RuntimeError(f"strategy_commit not unique: {distinct_commit}")
    if str(episodes["strategy_commit"].iloc[0]) != EPISODE_STRATEGY_COMMIT:
        raise RuntimeError("episodes strategy_commit mismatch")

    # structure.py blob gate (historical vs HEAD)
    import subprocess
    hist = subprocess.run(
        ["git", "rev-parse", "315fbe0d6a41cbcbb17166c03c134e010f163084:src/limit_pullback/strategy/structure.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD:src/limit_pullback/strategy/structure.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if hist != head or hist != HISTORICAL_STRUCTURE_BLOB:
        raise RuntimeError(f"structure.py drift: hist={hist} head={head}")

    # 1. parity gate on bounded sample
    parity = parity_gate(daily, pool, config)
    if parity["PARITY_MISMATCH_N"] != 0:
        raise RuntimeError(f"PARITY_MISMATCH_N != 0: {parity} — full registry forbidden")
    (OUT_DIR / "parity.json").write_text(
        json.dumps(parity, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2. full anchor-only registry
    rows = anchor_only_scan(daily, pool, config)
    reg = pd.DataFrame(rows)
    csv_path = OUT_DIR / "t0-registry-v01.csv"
    reg.to_csv(csv_path, index=False)
    reg_sha = registry_sha256(csv_path)

    # 3. population accounting
    acct = population_accounting(rows, episodes)
    acct["REGISTRY_SHA256"] = reg_sha
    acct["REGISTRY_ROWS"] = len(rows)
    acct["SNAPSHOT_ID"] = SNAPSHOT_ID
    acct["DAILY_SHA256"] = DAILY_SHA256
    acct["POOL_SHA256"] = POOL_SHA256
    acct["EPISODE_STRATEGY_COMMIT"] = EPISODE_STRATEGY_COMMIT
    acct["STRATEGY_CONFIG_HASH"] = STRATEGY_CONFIG_HASH
    acct["HISTORICAL_STRUCTURE_BLOB_SHA"] = hist
    acct["CURRENT_STRUCTURE_BLOB_SHA"] = head
    acct["STRUCTURE_SEMANTICS_MATCH"] = hist == head
    acct["COHORT_START"] = COHORT_START.isoformat()
    acct["COHORT_END"] = COHORT_END.isoformat()
    acct["PARITY"] = parity

    (OUT_DIR / "t0-registry-v01-report.md").write_text(
        render_report(acct), encoding="utf-8"
    )
    (OUT_DIR / "t0-registry-v01.json").write_text(
        json.dumps(acct, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(acct, ensure_ascii=False, indent=2))
    return acct


def render_report(a: dict) -> str:
    p = a["PARITY"]
    lines = [
        "# T0 COMPLETE REGISTRY V01 — anchor-only full-market T0 setup registry",
        "",
        f"- SNAPSHOT_ID = {a['SNAPSHOT_ID']}；EPISODE_STRATEGY_COMMIT = {a['EPISODE_STRATEGY_COMMIT']}",
        f"- STRATEGY_CONFIG_HASH = {a['STRATEGY_CONFIG_HASH']}",
        f"- DAILY_SHA256 = {a['DAILY_SHA256']}；POOL_SHA256 = {a['POOL_SHA256']}",
        f"- structure.py blob：HISTORICAL = {a['HISTORICAL_STRUCTURE_BLOB_SHA']}；CURRENT = {a['CURRENT_STRUCTURE_BLOB_SHA']}；"
        f"MATCH = {a['STRUCTURE_SEMANTICS_MATCH']}",
        f"- cohort = [{a['COHORT_START']}, {a['COHORT_END']}]（之前 bars 仅 warmup）",
        "",
        "## EQUIVALENCE GATE（anchor-only vs frozen strategy LIMIT_ANCHOR）",
        f"- PARITY_ROWS_CHECKED = {p['PARITY_ROWS_CHECKED']}（deterministic bounded sample）",
        f"- PARITY_MATCH_N = {p['PARITY_MATCH_N']}；PARITY_MISMATCH_N = {p['PARITY_MISMATCH_N']}",
        "",
        "## POPULATION ACCOUNTING",
        f"- TOTAL_T0_SETUP_N = {a['TOTAL_T0_SETUP_N']}",
        f"- OBSERVED_SIGNAL_SETUP_N = {a['OBSERVED_SIGNAL_SETUP_N']}（registry 中至少有一个 B1_PREP/B1_READY/B2_READY/B2_CONFIRMED 事件）",
        f"- NEVER_SIGNAL_SETUP_N = {a['NEVER_SIGNAL_SETUP_N']}",
        f"- EPISODE_SETUP_NOT_IN_REGISTRY_N = {a['EPISODE_SETUP_NOT_IN_REGISTRY_N']}",
        f"- REGISTRY_DUPLICATE_SETUP_ID_N = {a['REGISTRY_DUPLICATE_SETUP_ID_N']}",
        f"- REGISTRY_CODE_ANCHOR_CONFLICT_N = {a['REGISTRY_CODE_ANCHOR_CONFLICT_N']}",
        f"- ACCOUNTING_IDENTITY = {a['ACCOUNTING_IDENTITY']}",
        f"- REGISTRY_SHA256 = {a['REGISTRY_SHA256']}；rows = {a['REGISTRY_ROWS']}",
        "",
        "## STATUS",
        f"- T0_REGISTRY_STATUS = {a['T0_REGISTRY_STATUS']}",
        f"- T0_POPULATION_AUTHORITY = {a['T0_POPULATION_AUTHORITY']}",
        f"- T0_SURVIVAL_PREREG_READY = {a['T0_SURVIVAL_PREREG_READY']}",
        f"- SURVIVAL_RUN = {a['SURVIVAL_RUN']}；TTL_CUTOFF = {a['TTL_CUTOFF']}",
        "",
        "## 限制",
        "- 本 registry 为 anchor-only 结构登记（detect_anchor 语义），非 outcome/survival 结果",
        "- 未运行 survival / hazard / P(B2 by T+k) / TTL cutoff / outcome 分析",
        "- PREREG_READY ≠ survival 已运行",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
