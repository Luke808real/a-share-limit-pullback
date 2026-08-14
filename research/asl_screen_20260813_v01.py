"""ASL-lake-driven advance screen: 2026-08-13 -> watchlist for 2026-08-14.

Data source: the ASL lake DuckDB (asl-shared), per user instruction
"数据库用ASL那个仓库". Strategy engine: V flash frozen code (screen engine +
fast path). Seeds states from the 2026-08-06 ACTIVE generation; advances the
five sessions 08-07..08-13 in one bounded window pass.

Pipeline contract mirrors run_screen_fast: previous ACTIVE state + new
canonical bars -> evaluate new bars only, with the same fallback semantics.
preclose is derived as the sequential previous valid close with corporate
action (ex-date) adjustments from ASL corporate_actions. Limit-up pool =
canonical pool (through 08-06) + derived PRICE_ONLY events for 08-07..08-13
(same derivation the product uses for the newest session).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import duckdb
import pyarrow.parquet as pq

from limit_pullback.config import load_strategy_config
from limit_pullback.derived_limit_event import build_derived_limit_events
from limit_pullback.models.market import DailyBar, LimitUpRecord
from limit_pullback.screen.canonical import FIXED_FETCHED_AT, load_canonical_metadata
from limit_pullback.screen.fast_path import FastPathStats, run_screen_fast
from limit_pullback.screen.runner import _git_head
from limit_pullback.universe import phase2d0_universe_from_snapshot
from limit_pullback.warehouse.layout import WarehouseLayout
from limit_pullback.warehouse.metadata import WarehouseMetadata
from limit_pullback.warehouse.snapshot import resolve_formal_screen_ready_snapshot

ASL_DB = Path("/Users/luke808/AI/asl-shared/duckdb/ashare-lake.duckdb")
AS_OF = date(2026, 8, 13)
SESSIONS = (
    date(2026, 8, 7),
    date(2026, 8, 10),
    date(2026, 8, 11),
    date(2026, 8, 12),
    date(2026, 8, 13),
)
SEED_STATES = Path(
    "data/screen/generations/stategen-2026-08-06-a846075a5ac7/states"
)
PREVIOUS_COMMIT = "02d4cb05b82f2879919048a6dffd4ddfbbdc5649"
BUILD_ROOT = Path("data/tmp/asl-screen-20260813")
WINDOW_DAYS = 400
LOAD_SINCE = AS_OF - timedelta(days=WINDOW_DAYS + 40)

layout = WarehouseLayout(Path("data"))
STRATEGY_CONFIG = Path("config/strategy.yaml")


def _symbol_of(code: str) -> str:
    return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"


def _code_of(symbol: str) -> str:
    return symbol.split(".")[0]


def _bar_hash(code: str, d: date, o: float, h: float, l: float, c: float,
              pc: Decimal, v: float, a: float) -> str:
    payload = f"{code}|{d.isoformat()}|{o}|{h}|{l}|{c}|{pc}|{v}|{a}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _log(msg: str) -> None:
    print(f"[{time.time()-STARTED:8.1f}s] {msg}", flush=True)


STARTED = time.time()


def main() -> int:
    import os as _os

    phase = _os.environ.get("ASL_PHASE", "screen")
    slice_i = int(_os.environ.get("ASL_SLICE_I", "0"))
    slice_n = int(_os.environ.get("ASL_SLICE_N", "1"))
    _log(f"start phase={phase} slice={slice_i}/{slice_n}")
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    states_root = BUILD_ROOT / "states"
    states_root.mkdir(parents=True, exist_ok=True)
    if phase == "screen":
        # Seed only for the screen phase; merge/report must NOT re-copy
        # seeds over freshly written states.
        for path in SEED_STATES.glob("[0-9]*.json"):
            shutil.copy2(path, states_root / path.name)
        _log(f"seeded states: {len(list(states_root.glob('[0-9]*.json')))}")

    with WarehouseMetadata(layout.duckdb_path, read_only=True) as md:
        snap = resolve_formal_screen_ready_snapshot(md)
    universe = phase2d0_universe_from_snapshot(layout, snap)
    _log(f"snapshot={snap.snapshot_id} universe_n={universe.member_n}")
    if phase == "screen" and slice_n > 1:
        from types import SimpleNamespace

        members = tuple(
            c for i, c in enumerate(universe.members) if i % slice_n == slice_i
        )
        universe = SimpleNamespace(
            members=members,
            member_n=len(members),
            contract_version=universe.contract_version,
            member_hash=universe.member_hash,
        )
        _log(f"slice universe_n={universe.member_n}")
    elif phase != "screen":
        # merge/report: no-op screen pass (empty universe, slice 99 artifacts)
        from types import SimpleNamespace

        universe = SimpleNamespace(
            members=(),
            member_n=universe.member_n,
            contract_version=universe.contract_version,
            member_hash=universe.member_hash,
        )
        slice_i = 99

    con = duckdb.connect(str(ASL_DB), read_only=True)
    con.execute("SET threads=4")

    # --- names ---
    try:
        name_rows = con.execute(
            "SELECT symbol, name FROM instruments WHERE name IS NOT NULL"
        ).fetchall()
        names = {_code_of(str(s)): str(n) for s, n in name_rows}
    except Exception:
        names = {}
    _log(f"instrument names: {len(names)}")

    # --- corporate actions (ex-date adjustments) ---
    actions = {}
    for symbol, ex, cash, bonus, transfer in con.execute(
        "SELECT symbol, ex_date, cash_dividend, bonus_ratio, transfer_ratio "
        "FROM corporate_actions WHERE ex_date > ? AND ex_date <= ?",
        [LOAD_SINCE - timedelta(days=60), AS_OF],
    ).fetchall():
        key = (_code_of(str(symbol)), ex)
        actions[key] = (
            Decimal(str(cash)) if cash is not None else Decimal("0"),
            Decimal(str(bonus)) if bonus is not None else Decimal("0"),
            Decimal(str(transfer)) if transfer is not None else Decimal("0"),
        )
    _log(f"corporate actions loaded: {len(actions)}")

    # --- bars ---
    symbols = tuple(_symbol_of(c) for c in universe.members)
    raw = con.execute(
        "SELECT symbol, trade_date, open, high, low, close, volume, amount "
        "FROM daily_bars WHERE symbol IN (SELECT unnest(?::VARCHAR[])) "
        "AND trade_date > ? AND trade_date <= ? ORDER BY symbol, trade_date",
        [symbols, LOAD_SINCE, AS_OF],
    ).fetchall()
    _log(f"bar rows loaded: {len(raw)}")

    # anchor close before window (for first-bar preclose)
    anchor_close = {}
    for symbol, d, c in con.execute(
        "SELECT symbol, trade_date, close FROM daily_bars "
        "WHERE trade_date <= ? AND symbol IN (SELECT unnest(?::VARCHAR[])) "
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) = 1",
        [LOAD_SINCE, symbols],
    ).fetchall():
        anchor_close[_code_of(str(symbol))] = (d, Decimal(str(c)))

    # --- trading status for the 5 sessions ---
    status_rows = con.execute(
        "SELECT symbol, trade_date, is_trading FROM trading_status "
        "WHERE trade_date >= ? AND trade_date <= ? AND "
        "symbol IN (SELECT unnest(?::VARCHAR[]))",
        [SESSIONS[0], SESSIONS[-1], symbols],
    ).fetchall()
    non_trading = {(str(s), d) for s, d, t in status_rows if not t}
    _log(f"trading_status rows: {len(status_rows)}, non-trading: {len(non_trading)}")
    con.close()

    # --- build per-code bars with derived preclose ---
    rows_by_code: dict[str, list] = {}
    for symbol, d, o, h, l, c, v, a in raw:
        rows_by_code.setdefault(_code_of(str(symbol)), []).append(
            (d, o, h, l, c, v, a)
        )
    covered_days: dict[str, set] = {}
    window_bars_by_code: dict[str, tuple] = {}
    for code, rows in rows_by_code.items():
        rows.sort(key=lambda r: r[0])
        bars = []
        prev_close = None
        prev_date = None
        if code in anchor_close:
            prev_date, prev_close = anchor_close[code]
        for d, o, h, l, c, v, a in rows:
            preclose = prev_close
            if prev_date is not None and preclose is not None:
                adj = actions.get((code, d))
                if adj is not None:
                    cash, bonus, transfer = adj
                    denom = Decimal("1") + bonus + transfer
                    preclose = (preclose - cash) / denom if denom else preclose
            if preclose is None or preclose <= 0:
                # First bar without a predecessor close: seed the frozen
                # price chain with FIRST_VALID_CLOSE (the bar's own close).
                preclose = Decimal(str(c))
            try:
                bar = DailyBar(
                    trade_date=d,
                    code=code,
                    open=Decimal(str(o)),
                    high=Decimal(str(h)),
                    low=Decimal(str(l)),
                    close=Decimal(str(c)),
                    preclose=preclose,
                    volume=Decimal(str(v)),
                    amount=Decimal(str(a)),
                    pct_change=(
                        (Decimal(str(c)) / preclose - Decimal("1")).quantize(
                            Decimal("0.0001")
                        )
                    ),
                    trade_status=True,
                    is_st=None,
                    source="ASL_LAKE",
                    fetched_at=FIXED_FETCHED_AT,
                )
            except Exception:
                continue
            bars.append(bar)
            prev_close = Decimal(str(c))
            prev_date = d
        window_bars_by_code[code] = tuple(bars)
        covered_days[code] = {b.trade_date for b in bars}

    missing_from_asl = set(universe.members) - set(rows_by_code)
    _log(f"codes with bars: {len(rows_by_code)}, missing from ASL: {len(missing_from_asl)}")

    # --- verified no-trade per session ---
    verified: list[tuple[str, date]] = []
    unexplained: list[tuple[str, date]] = []
    for d in SESSIONS:
        for code in universe.members:
            if code in covered_days and d in covered_days[code]:
                continue
            if (code, d) in non_trading:
                verified.append((code, d))
            else:
                unexplained.append((code, d))
    _log(f"verified_no_trade: {len(verified)}, unexplained: {len(unexplained)}")
    if unexplained:
        _log(f"unexplained sample: {unexplained[:10]}")

    # --- pool: canonical through 08-06 + derived events 08-07..08-13 ---
    _, pool_records, pool_status = load_canonical_metadata(
        layout, snapshot_id=snap.snapshot_id
    )
    config = load_strategy_config(STRATEGY_CONFIG)
    derived_rows = []
    for code, bars in window_bars_by_code.items():
        for bar in bars:
            if bar.trade_date > snap.as_of:
                derived_rows.append(
                    {
                        "code": code,
                        "trade_date": bar.trade_date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "preclose": bar.preclose,
                        "source_daily_hash": _bar_hash(
                            code, bar.trade_date,
                            float(bar.open), float(bar.high), float(bar.low),
                            float(bar.close), bar.preclose,
                            float(bar.volume), float(bar.amount),
                        ),
                    }
                )
    events = build_derived_limit_events(
        derived_rows,
        source_id="ASL_SCREEN_20260813",
        config=config,
        universe_members=set(universe.members),
    )
    derived_pool = tuple(
        LimitUpRecord(
            trade_date=event.trade_date,
            code=event.code,
            name=event.code,
            limit_price=event.theoretical_limit_price,
            first_seal_time=None,
            last_seal_time=None,
            open_count=None,
            consecutive_count=None,
            turnover_rate=None,
            float_market_cap=None,
            total_market_cap=None,
            industry=None,
            source="CANONICAL_DERIVED",
            fetched_at=FIXED_FETCHED_AT,
        )
        for event in events
    )
    pool_all = tuple(sorted(
        list(pool_records) + list(derived_pool),
        key=lambda r: (r.code, r.trade_date),
    ))
    for event in events:
        pool_status[(event.code, event.trade_date)] = "CONFIRMED"
    _log(f"pool: canonical {len(pool_records)} + derived {len(derived_pool)}")

    def full_bars_loader(code: str) -> tuple:
        con2 = duckdb.connect(str(ASL_DB), read_only=True)
        con2.execute("SET threads=2")
        rows = con2.execute(
            "SELECT trade_date, open, high, low, close, volume, amount "
            "FROM daily_bars WHERE symbol = ? AND trade_date <= ? "
            "ORDER BY trade_date",
            [_symbol_of(code), AS_OF],
        ).fetchall()
        con2.close()
        # fallback full history: preclose derived from previous raw close only
        out = []
        prev_close = None
        for d, o, h, l, c, v, a in rows:
            if prev_close is None:
                prev_close = Decimal(str(c))
            try:
                out.append(
                    DailyBar(
                        trade_date=d, code=code,
                        open=Decimal(str(o)), high=Decimal(str(h)),
                        low=Decimal(str(l)), close=Decimal(str(c)),
                        preclose=prev_close,
                        volume=Decimal(str(v)), amount=Decimal(str(a)),
                        pct_change=(
                            (Decimal(str(c)) / prev_close - Decimal("1")).quantize(
                                Decimal("0.0001")
                            )
                        ),
                        trade_status=True, is_st=None,
                        source="ASL_LAKE", fetched_at=FIXED_FETCHED_AT,
                    )
                )
            except Exception:
                pass
            prev_close = Decimal(str(c))
        return tuple(out)

    _log("bars built; entering screen loop")
    commit = _git_head()
    config_hash = hashlib.sha256(
        STRATEGY_CONFIG.read_bytes()
    ).hexdigest()
    generated_at = datetime.combine(AS_OF, dtime(23, 59, 59), tzinfo=timezone.utc)
    processed_at = datetime.now(timezone.utc)

    stats = FastPathStats()
    t0 = time.time()
    manifest = run_screen_fast(
        layout=layout,
        snapshot=snap,
        universe=universe,
        as_of=AS_OF,
        config_path=STRATEGY_CONFIG,
        config=config,
        commit=commit,
        config_hash=config_hash,
        states_root=states_root,
        spool_path=BUILD_ROOT / f"rows-s{slice_i}.jsonl",
        manifest_path=BUILD_ROOT / f"manifest-s{slice_i}.json",
        compact_output_path=BUILD_ROOT / f"screen-output-s{slice_i}.parquet",
        generated_at=generated_at,
        processed_at=processed_at,
        pool_mode="formal",
        window_calendar_days=WINDOW_DAYS,
        verified_no_trade=verified,
        previous_commit=PREVIOUS_COMMIT,
        stats=stats,
        window_bars_by_code=window_bars_by_code,
        full_bars_loader=full_bars_loader,
        pool_override=pool_all,
        pool_status_override=pool_status,
        progress_cb=lambda done, total: _log(f"screen progress {done}/{total}"),
    )
    screen_wall = time.time() - t0
    _log(f"screen wall: {screen_wall:.1f}s")
    if phase == "screen":
        _log(f"screen phase done slice={slice_i}")
        return 0
    _log(
        "fast stats: "
        + json.dumps(
            {
                k: getattr(stats, k)
                for k in (
                    "fast_path_n",
                    "targeted_fallback_n",
                    "full_fallback_n",
                    "rows_scanned",
                    "rows_materialized",
                )
            }
        )
    )
    _log("fallback reasons: " + json.dumps(dict(stats.fallback_reasons)))
    _log("status counts: " + json.dumps(manifest["status_counts"]))

    if phase == "merge":
        import limit_pullback.screen.runner as _runner

        # Per-slice spools were unlinked after compact write; rebuild the
        # merged spool from the per-slice compact parquet payload column.
        # payload strings are identical to the original spool lines, so the
        # merged output hash equals the concatenated spool hash.
        merged_spool = BUILD_ROOT / "rows.jsonl"
        with merged_spool.open("w", encoding="utf-8") as out:
            for p in sorted(BUILD_ROOT.glob("screen-output-s[0-9].parquet")):
                table = pq.read_table(p)
                for batch in table.to_batches():
                    payloads = batch["payload"].to_pylist()
                    for payload in payloads:
                        out.write(payload + "\n")
        manifests = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(BUILD_ROOT.glob("manifest-s[0-9].json"))
        ]
        base = dict(manifests[0])
        merged_counts: dict[str, int] = {}
        rows_count = 0
        codes_all: list[str] = []
        notes_all: set[str] = set()
        for m in manifests:
            for k, v in (m.get("status_counts") or {}).items():
                merged_counts[k] = merged_counts.get(k, 0) + int(v)
            rows_count += int(m.get("rows_count") or 0)
            codes_all.extend(m.get("codes") or ())
            notes_all.update(m.get("notes") or ())
        base["status_counts"] = dict(sorted(merged_counts.items()))
        base["rows_count"] = rows_count
        base["codes"] = tuple(codes_all)
        base["universe_size"] = len(codes_all)
        base["notes"] = sorted(notes_all)
        base["output_hash"] = _runner._spool_output_hash(merged_spool)
        _runner._write_compact_output(
            metadata=base,
            spool_path=merged_spool,
            compact_output_path=BUILD_ROOT / "screen-output.parquet",
            output_path=BUILD_ROOT / "manifest.json",
        )
        merged_spool.unlink(missing_ok=True)
        _log("merge done")
        return 0

    # --- state summary ---
    stage_counts: dict[str, int] = {}
    last_processed_as_of = 0
    for path in states_root.glob("[0-9]*.json"):
        state = json.loads(path.read_text(encoding="utf-8"))
        signal = json.loads(state.get("signal_json") or "{}")
        stage = signal.get("setup_stage", "?")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        if state.get("last_processed_date") == AS_OF.isoformat():
            last_processed_as_of += 1
    _log("stage counts: " + json.dumps(stage_counts))
    _log(f"states processed through {AS_OF}: {last_processed_as_of}")

    # --- candidates ---
    cand_rows = []
    table = pq.read_table(BUILD_ROOT / "screen-output.parquet")
    for batch in table.to_batches():
        for i in range(batch.num_rows):
            code = str(batch["code"][i].as_py())
            d = batch["trade_date"][i].as_py()
            payload = json.loads(batch["payload"][i].as_py())
            cand_rows.append((code, d, payload))
    last_rows: dict[str, dict] = {}
    for code, d, payload in cand_rows:
        key = payload.get("trade_date") or str(d)
        if d <= AS_OF and (
            code not in last_rows
            or key > (last_rows[code].get("trade_date") or "")
        ):
            last_rows[code] = payload
    _log(f"compact rows: {len(cand_rows)}, codes with last row: {len(last_rows)}")

    # Authoritative stage comes from the frozen state signal; the latest row
    # payload carries the execution-level detail. Entry candidates rank ahead
    # of non-entry setups within the same watch priority.
    state_stage: dict[str, str] = {}
    for path in states_root.glob("[0-9]*.json"):
        st = json.loads(path.read_text(encoding="utf-8"))
        sig = json.loads(st.get("signal_json") or "{}")
        if sig.get("setup_stage"):
            state_stage[st["code"]] = str(sig["setup_stage"])

    def _priority(code: str, p: dict) -> tuple:
        entry = bool(p.get("is_entry_candidate"))
        if state_stage.get(code) == "LAUNCH_READY":
            return (0, entry, 0)
        if state_stage.get(code) == "B2_READY" and entry:
            return (1, entry, 0)
        if state_stage.get(code) == "B1_READY":
            return (2, entry, 0)
        if state_stage.get(code) == "B2_READY":
            return (3, entry, 0)
        if state_stage.get(code) == "PREPOSITION":
            return (4, entry, 0)
        if state_stage.get(code) == "B2_CONFIRMED" and entry:
            return (5, entry, 0)
        return (99, entry, 0)

    watchable = []
    for code, p in last_rows.items():
        if _priority(code, p)[0] == 99:
            continue
        watchable.append((code, p))
    watchable.sort(
        key=lambda item: (
            _priority(item[0], item[1])[0],
            -int(bool(item[1].get("is_entry_candidate"))),
            -(float(item[1].get("entry_quality_score") or 0)
              if item[1].get("entry_quality_score") is not None else 0),
            -float(item[1].get("setup_quality_score") or 0),
        )
    )
    top = watchable[:5]
    out = []
    for code, p in top:
        rec = {
            "code": code,
            "name": names.get(code, code),
            "setup_stage": state_stage.get(code, p.get("setup_stage")),
            "is_entry_candidate": p.get("is_entry_candidate"),
            "setup_quality_score": str(p.get("setup_quality_score")),
            "entry_quality_score": (
                str(p["entry_quality_score"])
                if p.get("entry_quality_score") is not None else None
            ),
            "entry_room_state": p.get("entry_room_state"),
            "risk_reward_ratio": str(p.get("risk_reward_ratio"))
            if p.get("risk_reward_ratio") is not None else None,
            "invalid_price": str(p.get("invalid_price"))
            if p.get("invalid_price") is not None else None,
            "entry_reference_price": str(p.get("entry_reference_price"))
            if p.get("entry_reference_price") is not None else None,
            "b2_trigger": (
                str(p["b2_trigger_snapshot"]["trigger_price"])
                if p.get("b2_trigger_snapshot")
                and p["b2_trigger_snapshot"].get("trigger_price") is not None
                else None
            ),
            "target_s1": (
                {
                    "low": str(p["target_s1"]["s1_low"]),
                    "high": str(p["target_s1"]["s1_high"]),
                }
                if p.get("target_s1")
                and p["target_s1"].get("s1_low") is not None
                else None
            ),
            "support": (
                str(p["support_snapshot"]["support_center"])
                if p.get("support_snapshot")
                and p["support_snapshot"].get("support_center") is not None
                else None
            ),
            "event_flags": [str(f) for f in p.get("event_flags", [])],
            "primary_pattern": p.get("primary_pattern"),
        }
        out.append(rec)
    (BUILD_ROOT / "candidates-20260814.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2)
    )
    total_wall = time.time() - STARTED
    summary = {
        "as_of": AS_OF.isoformat(),
        "watch_date": "2026-08-14",
        "universe_n": universe.member_n,
        "screen_wall_seconds": round(screen_wall, 2),
        "total_wall_seconds": round(total_wall, 2),
        "fast_path_n": stats.fast_path_n,
        "targeted_fallback_n": stats.targeted_fallback_n,
        "full_fallback_n": stats.full_fallback_n,
        "states_through_as_of": last_processed_as_of,
        "missing_from_asl_n": len(missing_from_asl),
        "unexplained_n": len(unexplained),
        "candidates": out,
    }
    (BUILD_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    _log("DONE " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
