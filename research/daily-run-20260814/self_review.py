"""Independent self-review of one daily-run session (read-only).

Usage: python self_review.py SESSION [--expect FULL|GATE]
  FULL: daily + trade-plan + news-brief + watchlist + reconcile all ok
  GATE: daily ok, trade-plan fail-closed at the frozen semantic gate
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("data")
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


def main() -> int:
    session = sys.argv[1]
    expect = sys.argv[2] if len(sys.argv) > 2 else "FULL"
    run_dir = ROOT / "tmp" / f"daily-run-{session.replace('-', '')}"
    catchup = ROOT / "tmp" / f"canonical-catchup-{session}"
    report: dict = {"session": session, "expect": expect, "checks": []}
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})

    timing = read_json(run_dir / "timing.json")
    report["timing"] = timing
    steps = {s["name"]: s for s in timing.get("steps", [])}
    check("daily ok", bool(steps.get("daily", {}).get("ok")))
    if expect == "FULL":
        check("timing status OK", timing.get("status") == "OK")
        check(
            "all five steps ok",
            all(steps.get(n, {}).get("ok") for n in ("daily", "trade-plan", "news-brief", "watchlist", "reconcile")),
            str([n for n in ("daily", "trade-plan", "news-brief", "watchlist", "reconcile") if not steps.get(n, {}).get("ok")]),
        )
        plan = read_json(run_dir / "plan.json")
        report["plan_summary"] = {
            k: plan.get(k)
            for k in ("plan_date", "for_trade_date", "snapshot_id", "watch_count",
                      "b1_prep_count", "b1_ready_count", "b2_ready_count",
                      "b2_confirmed_count", "actionable_count", "universe")
        }
        check("plan.json exists", True)
        check("watchlist.md exists", (run_dir / "watchlist.md").exists())
        if plan.get("plans"):
            check("brief.md exists", (run_dir / "brief.md").exists())
            brief = read_json(run_dir / "brief.json")
            report["brief_summary"] = {
                "symbols_requested": brief.get("symbols_requested"),
                "symbols_matched": brief.get("symbols_matched"),
                "availability": brief.get("availability"),
            }
        else:
            check("brief.md absent on NO_TRADE day (valid)", not (run_dir / "brief.md").exists())
    else:
        check("timing status FAILED (gate stop)", timing.get("status") == "FAILED")
        tp = steps.get("trade-plan")
        check("trade-plan blocked by gate", tp is not None and GATE in str(tp.get("detail", "")))
        check("no steps after trade-plan", "news-brief" not in steps and "reconcile" not in steps)
        for name in ("plan.json", "brief.md", "watchlist.md"):
            check(f"{name} absent (fail-closed)", not (run_dir / name).exists())

    summary = read_json(catchup / "daily-summary.json")
    check("snapshot SCREEN_READY", summary["snapshot"]["status"] == "SCREEN_READY")
    check("generation ACTIVE", summary["generation"]["status"] == "ACTIVE")
    check("state_n == 3191", summary["generation"]["state_n"] == 3191)
    check("staging conflicted == 0", summary["staging"]["conflicted_n"] == 0)
    check("preclose mismatch == 0", summary["staging"]["preclose_continuity_mismatch_n"] == 0)
    check("provider retries == 0", summary["provider"]["retry_codes"] == 0)
    sentinels = summary.get("sentinel_checks") or []
    check("sentinels all match", all(s.get("match") is True for s in sentinels))
    report["sentinel_codes"] = [s.get("code") for s in sentinels]
    report["fast_path_stats"] = summary.get("fast_path_stats")

    status = ops_status()
    fp = status.get("formal_snapshot_pointer")
    fp_id = fp[0] if isinstance(fp, list) and fp else fp
    check("formal snapshot pointer == new", fp_id == summary["snapshot"]["id"], f"{fp_id}")
    check("formal state pointer == new", status.get("formal_state_pointer") == summary["generation"]["id"])

    fetch = read_json(catchup / "fetch-summary.json")
    check("fetch failures == 0", fetch.get("tdx_failure_n") == 0 and fetch.get("tencent_failure_n") == 0)
    check("tdx rows > 0", (fetch.get("tdx_row_n") or 0) > 0)
    check("tencent rows > 0", (fetch.get("tencent_row_n") or 0) > 0)

    report["ok"] = ok
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
