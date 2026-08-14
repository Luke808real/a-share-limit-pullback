"""Independent self-review of the daily-run (read-only).

The sanctioned terminal state for 2026-08-07: daily step OK (formal pointers
advanced, sentinels all match), trade-plan step fail-closed at the frozen
STRATEGY_SEMANTIC_REVIEW_PENDING gate, and NO plan/brief/watchlist artifacts
(the chain must stop before producing them). Anything else is a defect.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("data")
SESSION = "2026-08-07"
RUN_DIR = ROOT / "tmp" / "daily-run-20260807"
CATCHUP = ROOT / "tmp" / f"canonical-catchup-{SESSION}"
GATE = "STRATEGY_SEMANTIC_REVIEW_PENDING"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ops_status() -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "limit_pullback.ops", "status"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT.parent,
    )
    return json.loads(out.stdout)


def promotion_records() -> list[dict]:
    import duckdb

    con = duckdb.connect(str(ROOT / "warehouse.duckdb"), read_only=True)
    try:
        rows = con.execute(
            "SELECT * FROM snapshot_promotion_records WHERE snapshot_id LIKE ? "
            "ORDER BY promoted_at",
            [f"snap-{SESSION}%"],
        ).fetchall()
        cols = [d[0] for d in con.description]
        return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        con.close()


def main() -> int:
    report: dict = {"checks": [], "artifacts": {}}
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})

    # 1. timing.json chain shape
    timing = read_json(RUN_DIR / "timing.json")
    report["timing"] = timing
    check("timing status FAILED (expected: gate stop)", timing.get("status") == "FAILED")
    check("completed == [daily]", timing.get("completed") == ["daily"], str(timing.get("completed")))
    steps = {s["name"]: s for s in timing.get("steps", [])}
    check("daily step ok", bool(steps.get("daily", {}).get("ok")))
    tp = steps.get("trade-plan")
    check("trade-plan step recorded", tp is not None)
    if tp is not None:
        check(
            "trade-plan blocked by frozen semantic gate",
            GATE in str(tp.get("detail", "")),
            str(tp.get("detail")),
        )
    check("no steps after trade-plan", "news-brief" not in steps and "reconcile" not in steps)

    # 2. daily-summary statuses, sentinels, staging, hashes
    summary = read_json(CATCHUP / "daily-summary.json")
    report["daily_summary_core"] = {
        k: summary.get(k) for k in ("snapshot", "generation", "staging", "provider", "fast_path_stats")
    }
    check("snapshot SCREEN_READY", summary["snapshot"]["status"] == "SCREEN_READY")
    check("pointer_before == 08-06", summary["snapshot"]["pointer_before"] == "snap-2026-08-06-e798f88ff67b")
    check("generation ACTIVE", summary["generation"]["status"] == "ACTIVE")
    check("state_n == 3191", summary["generation"]["state_n"] == 3191)
    check(
        "staging conflicted == 0",
        summary["staging"]["conflicted_n"] == 0,
        str(summary["staging"]),
    )
    check(
        "preclose continuity mismatch == 0",
        summary["staging"]["preclose_continuity_mismatch_n"] == 0,
    )
    check("provider retries == 0", summary["provider"]["retry_codes"] == 0)
    check(
        "incomplete_n == 1 (documented)",
        summary["staging"]["incomplete_n"] == 1,
        str(summary["staging"]["incomplete_n"]),
    )
    sentinels = summary.get("sentinel_checks") or []
    report["sentinels"] = [
        {k: s.get(k) for k in ("code", "match", "fast_stage", "replay_stage", "fast_last_processed")}
        for s in sentinels
    ]
    check("sentinels all match", all(s.get("match") is True for s in sentinels))
    check("staging hash present", bool(summary["staging"].get("staging_hash")))
    check("generation semantic root present", bool(summary["generation"].get("semantic_root")))

    # 3. formal pointers now point at the new artifacts
    status = ops_status()
    fp = status.get("formal_snapshot_pointer")
    fp_id = fp[0] if isinstance(fp, list) and fp else fp
    check("formal snapshot pointer == new", fp_id == summary["snapshot"]["id"], f"{fp_id}")
    check(
        "formal state pointer == new",
        status.get("formal_state_pointer") == summary["generation"]["id"],
        str(status.get("formal_state_pointer")),
    )

    # 4. fetch summary hashes
    fetch = read_json(CATCHUP / "fetch-summary.json")
    report["fetch_summary"] = fetch
    check(
        "fetch failures == 0",
        fetch.get("tdx_failure_n") == 0 and fetch.get("tencent_failure_n") == 0,
        f"tdx={fetch.get('tdx_failure_n')} tencent={fetch.get('tencent_failure_n')}",
    )
    check("tdx rows > 0", (fetch.get("tdx_row_n") or 0) > 0)
    check("tencent rows > 0", (fetch.get("tencent_row_n") or 0) > 0)
    check("fetch sha256 present", bool(fetch.get("tdx_full_sha256")) and bool(fetch.get("tencent_full_sha256")))

    # 5. promotion records in warehouse metadata
    recs = promotion_records()
    report["snapshot_promotion_records"] = [
        {k: str(v) for k, v in r.items() if k in ("snapshot_id", "from_status", "to_status")} for r in recs
    ]
    check("promotion record exists for new snapshot", len(recs) >= 1, str(len(recs)))

    # 6. fail-closed artifact absence after the gate
    for name in ("plan.json", "brief.md", "watchlist.md"):
        p = RUN_DIR / name
        report["artifacts"][name] = "ABSENT" if not p.exists() else str(p)
        check(f"{name} absent after gate (fail-closed)", not p.exists())
    report["artifacts"]["timing.json"] = str(RUN_DIR / "timing.json")
    report["artifacts"]["daily-summary.json"] = str(CATCHUP / "daily-summary.json")
    report["artifacts"]["fetch-summary.json"] = str(CATCHUP / "fetch-summary.json")
    report["artifacts"]["console-round2.log"] = str(ROOT / "tmp" / "daily-run-20260807-console-round2.log")

    report["ok"] = ok
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
