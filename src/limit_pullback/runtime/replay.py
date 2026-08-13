"""Replay orchestration entry (REF-R7).

The single-stock replay orchestration lives in `limit_pullback.replay`; this
module re-exports it so the runtime surface stays stable while the loop body
is unified with Daily through `runtime.common.evaluate_day`.
"""

from limit_pullback.replay import replay_stock

__all__ = ["replay_stock"]
