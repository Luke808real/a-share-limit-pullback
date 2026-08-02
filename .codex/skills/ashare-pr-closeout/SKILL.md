---
name: ashare-pr-closeout
description: "PR closeout workflow for the a-share-limit-pullback repo: validation audit, blocker audit, PR body final-state update, ready-for-review, and merge only on explicit user request. Use when the user asks to close out / 收口 a Draft PR, verify before merge, mark a PR ready, or merge a PR. Never auto-merge; never squash, rebase, or force-push."
---

# A-share PR Closeout

## Workflow

1. **Verify**: branch, local HEAD == origin == PR head, base main, worktree clean,
   PR `OPEN / Draft / MERGEABLE`, and no new conflicting main commits since review.
2. **Validation audit** (once): `pytest -q`, `python -m compileall -q src tests`,
   `git diff --check`; compare with expected test counts.
3. **Blocker audit**: fix only the human-review blockers listed; do not expand scope.
4. **PR body**: keep final facts, mark historical sections; keep Draft until approval.
5. **Mark Ready** only after human approval and green checks.
6. **Merge ONLY on explicit user request** ("merge"):
   `gh pr merge <n> --merge --subject "Merge PR #<n>: <title>"`.
   No squash / rebase / force push.
7. **Post-merge**: `MERGED=true`, main contains the head commit, worktree clean,
   origin synced; quick `git diff HEAD^1..HEAD --stat`; no strategy/config drift.
8. **KB update**: minimal record in `05_Codex/CURRENT_PHASE.md` and
   `05_Codex/IMPLEMENTATION_LOG.md` (KB repo: `~/AI/a-share-strategy-brain`), commit + push.
9. Keep research PRs Draft / unmerged (identify them from the user or
   `gh pr list --state open`; do not hardcode numbers).

## Guardrails

- Default is **never auto-merge**; Draft stays Draft until human review.
- Research/perf PRs do not promote research to production.
- No strategy or config changes inside closeout rounds unless the review explicitly lists them.
