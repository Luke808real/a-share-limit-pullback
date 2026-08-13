"""REF-R7 runtime package.

Replay and Daily are orchestration modes over the same domain core
(features -> state -> selection). `runtime/common` exposes the shared per-day
evaluation seam; `runtime/replay` and `runtime/daily` re-export the existing
orchestration entries; `runtime/live` is interface reservation only.
"""

from limit_pullback.runtime.common import evaluate_day

__all__ = ["evaluate_day"]
