"""Targeted PIT ST closure evidence — 59-code cohort only (no full-market run).

Re-runs production screen_code (PRICE_ONLY, AS_OF=2026-08-06) for exactly the
decision-relevant ST-unknown codes against the lake now carrying official
baostock historical ST facts, and produces the decision-relevant outputs:

* AS_OF final signatures before (previous full-run artifact) vs after
* candidate-date success/control signatures
* episode recomputation with ST-resolution classes
* intersection with the 25 AS_OF counterfactual-unknown codes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from limit_pullback.config import load_strategy_config  # noqa: E402
from shadow import (  # noqa: E402
    HISTORY_START,
    AS_OF,
    WINDOW_START,
    aggregate_success_control,
    classify_code_inputs,
    load_legacy_canonical,
    process_code,
    read_success_control_cases,
)
from shadow import _load_asl_recursive, load_ca_ex_dates  # noqa: E402

ST_COVERAGE_UNKNOWN = "ST_COVERAGE_UNKNOWN"
PIT_ST_DATA_UPGRADE = "PIT_ST_DATA_UPGRADE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-snapshot", required=True, type=Path)
    parser.add_argument("--asl-root", required=True, type=Path)
    parser.add_argument("--config", default="config/strategy.yaml", type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--full-artifact", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    codes = summary["st_coverage"]["decision_relevant_st_unknown_codes"]
    previous = json.loads(args.full_artifact.read_text(encoding="utf-8"))
    config = load_strategy_config(args.config)

    # Previous-run ASL final signatures (before ST) from counterfactual records.
    before_finals = {
        cf["code"]: cf.get("asl_final_signature")
        for cf in previous.get("counterfactuals", [])
    }
    legacy_finals_prev = {
        cf["code"]: cf.get("legacy_final_signature")
        for cf in previous.get("counterfactuals", [])
    }

    legacy = load_legacy_canonical(args.legacy_snapshot, set(codes), HISTORY_START, AS_OF)
    asl, errors, explained, coverage = _load_asl_recursive(
        args.asl_root, codes, HISTORY_START, AS_OF, legacy
    )
    if asl is None:
        asl = {}
    ca = load_ca_ex_dates(args.asl_root, set(codes))

    frozen_cases = [
        case
        for case in read_success_control_cases(
            Path("research/intraday/success_control_cases_v01b.csv"), set(codes)
        )
    ]
    case_map: dict[str, list] = {}
    for case in frozen_cases:
        case_map.setdefault(case["code"], []).append(case["candidate_date"])

    # Reconstruct the PRE-ST state by stripping the trusted status facts
    # (before the targeted backfill the adapter emitted is_st=None for every
    # row).  Used only for honest before/after episode resolution counts.
    asl_before: dict[str, list[dict]] = {}
    for code in codes:
        asl_before[code] = [
            {**row, "is_st": None, "asl_status_trust": None}
            for row in asl.get(code, [])
        ]

    results: dict[str, dict] = {}
    results_before: dict[str, dict] = {}
    for code in codes:
        results[code] = process_code(
            code,
            legacy.get(code, []),
            asl.get(code, []),
            config,
            ca,
            case_map.get(code, []),
        )
        results_before[code] = process_code(
            code,
            legacy.get(code, []),
            asl_before.get(code, []),
            config,
            ca,
            case_map.get(code, []),
        )

    # AS_OF candidate table for the six previously unresolved candidates.
    asof_six = [
        "000826", "002528", "600730", "603398", "002512", "600082"
    ]
    asof_table = []
    for code in asof_six:
        r = results[code]
        before = before_finals.get(code)
        after = r["final_asl"]
        asof_table.append(
            {
                "code": code,
                "legacy_asof_stage": r["final_legacy"][0] if r["final_legacy"] else None,
                "asl_before_st_stage": before[0] if before else None,
                "asl_after_pit_st_stage": after[0] if after else None,
                "is_entry_candidate_before": before[7] if before else None,
                "is_entry_candidate_after": after[7] if after else None,
                "asl_st_unknown_after": r["associated_class_at_asof"]
                == ST_COVERAGE_UNKNOWN,
                "pit_st_evidence_rows": sum(
                    1
                    for row in asl.get(code, [])
                    if row.get("asl_status_trust") == "BAOSTOCK_ST"
                ),
            }
        )

    # Top20 pair eligibility change (no full-market rerank).
    top20_pair = []
    for code in ("002512", "600082"):
        r = results[code]
        before = before_finals.get(code)
        after = r["final_asl"]
        top20_pair.append(
            {
                "code": code,
                "legacy_asof_stage": r["final_legacy"][0] if r["final_legacy"] else None,
                "asl_before_st_stage": before[0] if before else None,
                "asl_after_pit_st_stage": after[0] if after else None,
                "entry_candidate_before": before[7] if before else None,
                "entry_candidate_after": after[7] if after else None,
                "top20_membership_before": code in summary["screen_20260806"]["ASL_ONLY_TOP20"]
                or code in summary["screen_20260806"]["LEGACY_ONLY_TOP20"]
                or code
                in set(summary["screen_20260806"]["legacy"]["top20"])
                | set(summary["screen_20260806"]["asl"]["top20"]),
                "remains_eligible_after": after is not None
                and after[7] is True,
            }
        )

    # Episodes: before-ST vs after-ST per cohort code.
    def episode_key(ep: dict) -> tuple:
        return (ep["anchor_date"], ep.get("side") or "BOTH", ep["start_date"])

    before_rows = {
        (code, episode_key(ep)): ep
        for code in codes
        for ep in results_before[code]["episode_details"]
    }
    after_rows = {
        (code, episode_key(ep)): ep
        for code in codes
        for ep in results[code]["episode_details"]
    }
    episode_keys = sorted(set(before_rows) | set(after_rows))
    episode_rows = []
    for key in episode_keys:
        before = before_rows.get(key)
        after = after_rows.get(key)
        episode_rows.append(
            {
                "code": key[0],
                "anchor_date": key[1][0],
                "side": key[1][1],
                "start_date": key[1][2],
                "associated_class_before": before["associated_class"]
                if before else None,
                "bucket_before": before["bucket"] if before else None,
                "associated_class_after": after["associated_class"]
                if after else None,
                "bucket_after": after["bucket"] if after else None,
            }
        )
    was_st_unknown = [
        ep for ep in episode_rows
        if ep["bucket_before"] == "ST_COVERAGE_UNKNOWN_EPISODE"
        or ep["associated_class_before"] == ST_COVERAGE_UNKNOWN
    ]
    # Resolved: the episode difference existed before with an ST-unknown
    # association and the trusted ST evidence either removed the episode
    # (ASL anchor sat on a trusted ST day -> gone) or the start window is
    # now explained by trusted ST.
    resolved = [
        ep for ep in was_st_unknown
        if ep["bucket_after"] is None
        or ep["associated_class_after"] in (PIT_ST_DATA_UPGRADE, "TRUSTED_ASL_ST")
    ]
    still_unknown = [
        ep for ep in episode_rows
        if ep["associated_class_after"] == ST_COVERAGE_UNKNOWN
    ]
    unchanged = [
        ep for ep in episode_rows
        if ep not in was_st_unknown
        and ep["associated_class_after"]
        not in (ST_COVERAGE_UNKNOWN,)
    ]
    episode_summary = {
        "cohort_episode_row_keys_n": len(episode_keys),
        "previous_st_coverage_unknown_episode_n": len(was_st_unknown),
        "resolved_by_trusted_st_n": len(resolved),
        "unchanged_despite_st_evidence_n": len(unchanged),
        "st_still_unknown_episode_n": len(still_unknown),
    }

    # Success/control at candidate_date for cohort cases.
    success = aggregate_success_control(frozen_cases, results)
    success_rows = success.get("cases", [])
    explained_by_pit = sum(
        1
        for row in success_rows
        if row["associated_class"] in (PIT_ST_DATA_UPGRADE, "TRUSTED_ASL_ST")
    )
    still_unknown_cases = sum(
        1 for row in success_rows if row["associated_class"] == ST_COVERAGE_UNKNOWN
    )
    changed = sum(
        1
        for row in success_rows
        if row["legacy_sig"] != row["asl_sig"]
    )
    success_summary = {
        "frozen_case_n": len(frozen_cases),
        "compared_case_n": len(success_rows),
        "changed_signature_n": changed,
        "explained_by_pit_st_n": explained_by_pit,
        "still_unknown_n": still_unknown_cases,
    }

    # Intersection with the 25 counterfactual-unknown codes.
    unknown25 = set(summary["as_of_causal_attribution"]["unknown_root_cause_codes"])
    intersection = sorted(unknown25 & set(codes))
    intersection_rows = []
    for code in intersection:
        r = results[code]
        intersection_rows.append(
            {
                "code": code,
                "legacy_final_stage": r["final_legacy"][0] if r["final_legacy"] else None,
                "asl_after_st_stage": r["final_asl"][0] if r["final_asl"] else None,
                "asl_after_st_entry": r["final_asl"][7] if r["final_asl"] else None,
                "asl_after_st_unknown": r["associated_class_at_asof"] == ST_COVERAGE_UNKNOWN,
            }
        )

    evidence = {
        "contract": "VFLASH_P1B_TARGETED_ST_EVIDENCE_V1",
        "target_st_code_n": len(codes),
        "as_of": AS_OF.isoformat(),
        "status_provenance_cohort": coverage,
        "adapter_trusted_baostock_row_n": coverage.get("trusted_baostock_n", 0),
        "as_of_six_candidates": asof_table,
        "top20_pair": top20_pair,
        "episode_summary": episode_summary,
        "episode_rows": episode_rows,
        "success_control": success_summary,
        "success_control_rows": success_rows,
        "intersection_with_25": {
            "count": len(intersection),
            "codes": intersection,
            "rows": intersection_rows,
        },
        "per_code_st_unknown_eval_dates_after": {
            code: results[code]["st_unknown_eval_dates"]
            for code in codes
            if results[code]["st_unknown_eval_dates"]
        },
        "per_code_final_after": {
            code: {
                "legacy": results[code]["final_legacy"],
                "asl_before_st": results_before[code]["final_asl"],
                "asl_after_st": results[code]["final_asl"],
                "asl_class_at_asof_after": results[code]["associated_class_at_asof"],
            }
            for code in codes
        },
        "data_errors": errors,
        "explained_absences": explained,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
