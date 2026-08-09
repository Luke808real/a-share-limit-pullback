"""Lightweight static checks for the Agent/Skill governance refresh V02.

Checks only the governance files touched by this refresh; no repo-wide scan.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
GOV_FILES = [
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "docs" / "agent-context.md",
    REPO_ROOT / ".codex" / "agents" / "data-reader.toml",
    REPO_ROOT / ".codex" / "agents" / "adversarial-reviewer.toml",
    REPO_ROOT / ".codex" / "agents" / "code-reader.toml",
    REPO_ROOT / ".codex" / "skills" / "ashare-research-cycle" / "SKILL.md",
    REPO_ROOT / ".codex" / "skills" / "ashare-prospective-validation" / "SKILL.md",
    REPO_ROOT / ".codex" / "skills" / "ashare-premarket-review" / "SKILL.md",
    REPO_ROOT / ".codex" / "skills" / "ashare-pr-closeout" / "SKILL.md",
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agents_two_planes_and_authority_matrix():
    t = _text(REPO_ROOT / "AGENTS.md")
    assert "PRODUCTION PLANE" in t
    assert "RESEARCH PLANE" in t
    assert "Authority Matrix" in t
    assert "Frozen KB overrides only frozen strategy semantics" in t
    assert "SUPPORTED != VALIDATED != PROMOTED" in t
    assert "DEVELOPMENT_STABILITY" in t


def test_research_skill_not_clean_oos():
    t = _text(REPO_ROOT / ".codex" / "skills" / "ashare-research-cycle" / "SKILL.md")
    assert "DEVELOPMENT_STABILITY" in t
    assert "CHRONOLOGICAL_VALIDATION" not in t
    assert "2025-06-30" not in t and "2025-07-01" not in t
    assert "66d5943" not in t
    assert "OBSERVE_ONLY" not in t and "REJECT" not in t  # legacy taxonomy
    assert "clean OOS" not in t.lower() or "not clean OOS" in t.lower()


def test_prospective_skill_gate():
    t = _text(REPO_ROOT / ".codex" / "skills" /
              "ashare-prospective-validation" / "SKILL.md")
    assert "PRE_R9_STATUS" in t
    assert "PROTOCOL_FREEZE" in t
    assert "OOS_START" in t
    assert "no refit" in t.lower()
    assert "no checkpoint switching" in t.lower()


def test_agent_context_pointer_not_stale():
    t = _text(REPO_ROOT / "docs" / "agent-context.md")
    assert "PROJECT_STATE_SNAPSHOT" in t
    assert "Phase 2C.2C" not in t
    assert "PR #7" not in t
    assert "2026-07-31" not in t


def test_no_user_absolute_paths_in_governance_docs():
    for p in GOV_FILES + [REPO_ROOT / "docs" / "AGENT_GOVERNANCE_REFRESH_V02.md"]:
        if not p.exists():
            continue
        assert "/Users/luke808" not in _text(p), p


def test_adversarial_reviewer_covers_bias():
    t = _text(REPO_ROOT / ".codex" / "agents" / "adversarial-reviewer.toml")
    assert "label circularity" in t
    assert "population construction" in t
    assert "GO_WITH_CONDITIONS" in t


def test_data_reader_row_order_and_units():
    t = _text(REPO_ROOT / ".codex" / "agents" / "data-reader.toml")
    assert "row order" in t
    assert "timestamp" in t
    assert "volume / amount units" in t
    assert "NEVER assume parquet physical row order is" in t
    assert "chronological" in t


def test_premarket_readiness_gate():
    t = _text(REPO_ROOT / ".codex" / "skills" /
              "ashare-premarket-review" / "SKILL.md")
    assert "READINESS GATE" in t
    assert "WATCHLIST_NOT_READY" in t
    assert "not the normal path" in t.lower()
    # rebuild removed from the DEFAULT production-screen step
    marker = "2. **Production screen**"
    step2 = t.split(marker)[1].split("3. **")[0]
    assert "--rebuild" not in step2


def test_kb_governance_if_available():
    """KB checks run only when the sibling strategy-brain repo is present."""
    kb = REPO_ROOT.parent / "a-share-strategy-brain"
    if not kb.is_dir():
        pytest.skip("KB_UNAVAILABLE: no sibling strategy-brain repo")
    agents = (kb / "AGENTS.md")
    snap = (kb / "PROJECT_STATE_SNAPSHOT.md")
    phase = (kb / "05_Codex" / "CURRENT_PHASE.md")
    if not (agents.exists() and snap.exists() and phase.exists()):
        pytest.skip("KB governance files not present (not yet audited)")
    ta = agents.read_text(encoding="utf-8")
    ts = snap.read_text(encoding="utf-8")
    tp = phase.read_text(encoding="utf-8")
    assert "Authority Matrix" in ta
    assert "PROJECT_STATE_SNAPSHOT" in ts
    assert "HISTORICAL IMPLEMENTATION LOG" in tp
    assert "A_SHARE_STRATEGY_BRAIN_ROOT" in ta or "../a-share-strategy-brain" in ta
