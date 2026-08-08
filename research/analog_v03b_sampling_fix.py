"""ANALOG_V03B_SAMPLING_FIX (research-only; fixes V03A sampling bug).

V03A bug: per_year stored ABSOLUTE recs indices, but sample_year() returned
positions within the year list; q_indices used those internal positions as
absolute recs indices.

Fix: for each stage/year, take year_indices (absolute), sort by recs[idx]["T"],
select deterministic evenly-spaced POSITIONS in the year, then map back to
year_indices[selected_position]. Hard audit + asserts included.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from research.historical_analog_engine_v02 import build_library_and_candidates
from research.analog_v03a_strict_pit import (
    eval_query_strict,
    first_passage_5d,
    realized_mfe_mae,
    rank_corr,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "runs" / "ANALOG_V03_OOS_CALIBRATION"
MAX_PER_YEAR = 500


def sample_year_abs(year_indices, recs):
    year_indices = sorted(year_indices, key=lambda i: recs[i]["T"])
    n = len(year_indices)
    if n <= MAX_PER_YEAR:
        return year_indices
    positions = sorted({round(p * (n - 1) / (MAX_PER_YEAR - 1)) for p in range(MAX_PER_YEAR)})
    return [year_indices[p] for p in positions]


def sampling_audit(recs, per_year, q_indices):
    audit = {}
    total_selected = 0
    for year in sorted(per_year):
        selected = sample_year_abs(per_year[year], recs)
        total_selected += len(selected)
        selected_T = sorted(recs[i]["T"] for i in selected)
        audit[str(year)] = {
            "available_n": len(per_year[year]),
            "selected_n": len(selected),
            "min_selected_T": selected_T[0] if selected_T else None,
            "max_selected_T": selected_T[-1] if selected_T else None,
            "duplicate_query_count": len(selected) - len(set(selected)),
            "wrong_year_count": sum(1 for i in selected if recs[i]["T"][:4] != str(year)),
        }
        assert len(selected) <= MAX_PER_YEAR
        assert audit[str(year)]["duplicate_query_count"] == 0
        assert audit[str(year)]["wrong_year_count"] == 0
        if len(per_year[year]) > MAX_PER_YEAR:
            all_T = sorted(recs[i]["T"] for i in per_year[year])
            assert selected_T[0] == all_T[0] and selected_T[-1] == all_T[-1]
    assert total_selected == len(q_indices)
    return audit


def main():
    library, _, _ = build_library_and_candidates()
    lib = [r for r in library if r.get("fwd")]
    stages = sorted({r["stage"] for r in lib})
    results = {}
    audits = {}
    for stage in stages:
        recs = [r for r in lib if r["stage"] == stage]
        per_year = defaultdict(list)
        for i, r in enumerate(recs):
            per_year[int(r["T"][:4])].append(i)
        q_indices = sorted(
            {
                idx
                for year in per_year.values()
                for idx in sample_year_abs(year, recs)
            }
        )
        audits[stage] = sampling_audit(recs, per_year, q_indices)
        out = {"RAW": [], "BAL": []}
        masks = {
            "A": ["price_shape"],
            "B": ["price_shape", "price_state"],
            "C": ["price_shape", "price_state", "vol_shape"],
            "D": ["price_shape", "vol_shape", "price_state", "technical"],
        }
        ablation = {name: [] for name in masks}
        abl_indices = q_indices[::3][:400]
        for qi in q_indices:
            qrec = recs[qi]
            lab5, _, _ = first_passage_5d(qrec)
            r3 = realized_mfe_mae(qrec, 3)
            r5 = realized_mfe_mae(qrec, 5)
            for variant in ("RAW", "BAL"):
                row = eval_query_strict(qi, recs, None, variant)
                if row is not None:
                    row.update(
                        {
                            "realized_lab5": lab5,
                            "realized_mfe3": r3[0],
                            "realized_mae3": r3[1],
                            "realized_mfe5": r5[0],
                            "realized_mae5": r5[1],
                            "query_T": qrec["T"],
                            "query_year": int(qrec["T"][:4]),
                        }
                    )
                out[variant].append(row)
        for qi in abl_indices:
            qrec = recs[qi]
            lab5, _, _ = first_passage_5d(qrec)
            r5 = realized_mfe_mae(qrec, 5)
            for name, m in masks.items():
                row = eval_query_strict(qi, recs, None, "RAW", blocks_mask=m)
                if row is not None:
                    row.update(
                        {
                            "realized_lab5": lab5,
                            "realized_mfe5": r5[0],
                            "realized_mae5": r5[1],
                            "query_T": qrec["T"],
                            "query_year": int(qrec["T"][:4]),
                        }
                    )
                    ablation[name].append(row)
        results[stage] = {"queries": len(q_indices), "RAW": out["RAW"], "BAL": out["BAL"], "ablation": ablation}
        print("stage", stage, "queries", len(q_indices), flush=True)

    summary = {}
    for stage, sd in results.items():
        summary[stage] = {}
        for variant in ("RAW", "BAL"):
            rows = [r for r in sd[variant] if r and r.get("realized_lab5") is not None]
            if not rows:
                continue
            summary[stage][variant] = {
                "n": len(rows),
                "brier_s1": round(statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in rows), 4),
                "brier_inv": round(statistics.fmean((r["inv_rate"] - (1 if r["realized_lab5"] == "INVALID_FIRST" else 0)) ** 2 for r in rows), 4),
                "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in rows), 4),
                "mean_abs_err_mae5": round(statistics.fmean(abs(r["mae5"] - r["realized_mae5"]) for r in rows), 4),
                "corridor_coverage_mfe_p25_75": round(statistics.fmean(1 if r["p25mfe5"] <= r["realized_mfe5"] <= r["p75mfe5"] else 0 for r in rows), 4),
                "corridor_coverage_mae_p10_90": round(statistics.fmean(1 if r["p10mae5"] <= r["realized_mae5"] <= r["p90mae5"] else 0 for r in rows), 4),
                "rank_corr_mfe5": round(rank_corr([r["mfe5"] for r in rows], [r["realized_mfe5"] for r in rows]), 3),
                "rank_corr_s1": round(rank_corr([r["s1_rate"] for r in rows], [1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in rows]), 3),
                "periods": {
                    p: {
                        "n": len(sub),
                        "brier_s1": round(statistics.fmean((r["s1_rate"] - (1 if r["realized_lab5"] == "S1_FIRST" else 0)) ** 2 for r in sub), 4),
                        "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in sub), 4),
                        "realized_s1_first_rate": round(statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in sub), 4),
                    }
                    for p, sub in (
                        ("DISCOVERY", [r for r in rows if r["query_T"] < "2025-07-01"]),
                        ("VALIDATION", [r for r in rows if r["query_T"] >= "2025-07-01"]),
                        ("2024", [r for r in rows if r["query_year"] == 2024]),
                        ("2025", [r for r in rows if r["query_year"] == 2025]),
                        ("2026", [r for r in rows if r["query_year"] == 2026]),
                    )
                },
                "unique_anchors_mean": round(statistics.fmean(r["unique_anchors"] for r in rows), 1),
                "unique_stocks_mean": round(statistics.fmean(r["unique_stocks"] for r in rows), 1),
                "same_stock_share_mean": round(statistics.fmean(r["same_stock_share"] for r in rows), 4),
            }
        abl = {}
        for name, rws in sd["ablation"].items():
            rows = [x for x in rws if x]
            abl[name] = {
                "n": len(rows),
                "neighbor_s1_rate_mean": round(statistics.fmean(r["s1_rate"] for r in rows), 4) if rows else None,
                "realized_s1_first_rate": round(statistics.fmean(1 if r["realized_lab5"] == "S1_FIRST" else 0 for r in rows), 4) if rows else None,
                "mean_abs_err_mfe5": round(statistics.fmean(abs(r["mfe5"] - r["realized_mfe5"]) for r in rows), 4) if rows else None,
            }
        summary[stage]["ABLATION"] = abl

    payload = {
        "RUN_ID": "ANALOG_V03B_SAMPLING_FIX",
        "SAMPLING_AUDIT": audits,
        "summary": summary,
        "results": results,
    }
    (OUT_DIR / "metrics_v03b.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    Path("data/tmp/analog-v03b-oos-calibration/queries.json").parent.mkdir(parents=True, exist_ok=True)
    Path("data/tmp/analog-v03b-oos-calibration/queries.json").write_text(
        json.dumps({"RUN_ID": payload["RUN_ID"], "results": results}, ensure_ascii=False), encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    main()
