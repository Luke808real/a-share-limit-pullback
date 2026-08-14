from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_vflash_has_one_non_authoritative_current_state_pointer() -> None:
    markdown_files = list(REPO_ROOT.glob("*.md")) + list(
        (REPO_ROOT / "docs").rglob("*.md")
    )
    marker = "CURRENT_STATE_POINTER=true"
    marked = [path for path in markdown_files if marker in path.read_text()]

    assert marked == [REPO_ROOT / "docs" / "CURRENT_STATE.md"]

    pointer = marked[0].read_text()
    assert "Luke808real/a-share-strategy-brain" in pointer
    assert "00_Project/CURRENT_STATE.md" in pointer
    assert "00_Project/AGENT_HANDOFF.md" in pointer
    assert "2b15b44a4d2b586199e3824b817220f9fdfa281f" in pointer
    assert "CANONICAL_CURRENT_STATE=true" not in pointer
    assert "## Evidence snapshot" not in pointer
    assert "## Gate registry snapshot" not in pointer


def test_readme_and_agent_context_route_to_current_state() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    agent_context = (REPO_ROOT / "docs" / "agent-context.md").read_text()

    assert "docs/CURRENT_STATE.md" in readme
    assert "[CURRENT_STATE.md](CURRENT_STATE.md)" in agent_context

    stale_context = (
        "feature/phase-2c2c-trade-plan",
        "#7 Add post-close B-point trade plans",
        "22c7f79f22a68770c7000495493c514acc2867e1",
    )
    for stale_value in stale_context:
        assert stale_value not in agent_context

    assert "HUMAN EXECUTION" not in readme
    assert "0-2 实际交易" not in readme
