"""Daily orchestration entry (REF-R7).

The full-market daily orchestration lives in `limit_pullback.screen.runner`;
this module re-exports it so the runtime surface stays stable while the
per-code loop is unified with Replay through `runtime.common.evaluate_day`.
"""

from limit_pullback.screen.runner import run_screen

__all__ = ["run_screen"]
