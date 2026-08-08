"""R3A.1 statistical correctness tests (Mann-Whitney ties, BH-FDR)."""

from __future__ import annotations

import itertools
import math
from pathlib import Path
import sys

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "research" / "second_launch" / "factors_v01"))

import r3a_univariate_screen_v01 as r3a  # noqa: E402


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i:j + 1]] = avg
        i = j + 1
    return ranks


def _identity_oracle_p(values: np.ndarray, labels: np.ndarray) -> float:
    """Independent tie-corrected MWU p via rank-variance identity:
    Var(U) = n1*n0 * sum((r - r_bar)^2) / (N*(N-1))."""
    pos = values[labels == 1]
    neg = values[labels == 0]
    n1, n0 = len(pos), len(neg)
    pooled = np.concatenate([pos, neg])
    ranks = _rankdata(pooled)
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2.0
    n = n1 + n0
    centered = ranks - ranks.mean()
    var_u = n1 * n0 * float(np.sum(centered ** 2)) / (n * (n - 1))
    if var_u <= 0:
        return 1.0 if abs(u - n1 * n0 / 2.0) <= 1e-12 else float("nan")
    z = (u - n1 * n0 / 2.0) / math.sqrt(var_u)
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def _exact_permutation_p(values: np.ndarray, labels: np.ndarray) -> float:
    """Exact two-sided p by enumerating label permutations (small n).

    Two-sided: accumulate permutations with |U_perm - mu| >= |U_obs - mu|.
    """
    n1 = int(labels.sum())
    n = len(labels)
    u_obs = r3a.binary_auc(values, labels) * n1 * (n - n1)
    mu = n1 * (n - n1) / 2.0
    obs_dev = abs(u_obs - mu)
    total = 0
    extreme = 0
    for combo in itertools.combinations(range(n), n1):
        total += 1
        mask = np.zeros(n, dtype=bool)
        mask[list(combo)] = True
        ranks = _rankdata(values)
        u = ranks[mask].sum() - n1 * (n1 + 1) / 2.0
        if abs(u - mu) >= obs_dev - 1e-12:
            extreme += 1
    return extreme / total


def test_no_tie_p_matches_identity_oracle_and_manual():
    values = np.arange(1.0, 9.0)
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    p_new = r3a.auc_pvalue(values, labels)
    p_oracle = _identity_oracle_p(values, labels)
    assert p_new == pytest.approx(p_oracle, abs=1e-12)
    # Manual no-tie value: U=16, var=12, z=(16-8)/sqrt(12)
    z = (16.0 - 8.0) / math.sqrt(12.0)
    p_manual = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
    assert p_new == pytest.approx(p_manual, abs=1e-12)
    # Old (no-tie) formula would equal the new one here (no ties present).
    assert r3a.binary_auc(values, labels) == pytest.approx(1.0)


def test_heavy_tie_p_matches_identity_oracle_and_exact():
    # Heavy-tie count-like factor.
    values = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0])
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1, 0, 1])
    p_new = r3a.auc_pvalue(values, labels)
    p_oracle = _identity_oracle_p(values, labels)
    assert p_new == pytest.approx(p_oracle, abs=1e-9)
    # Exact permutation reference (n=10 -> 252 perms). The asymptotic
    # approximation deviates from the exact p at small n (gap ~0.07 here);
    # this is a loose sanity bound, NOT the correctness oracle. The tight
    # oracle is the independent tie-corrected variance identity above.
    p_exact = _exact_permutation_p(values, labels)
    assert abs(p_new - p_exact) <= 0.15


def test_all_equal_values():
    values = np.full(12, 5.0)
    labels = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
    assert r3a.binary_auc(values, labels) == pytest.approx(0.5)
    assert r3a.auc_pvalue(values, labels) == pytest.approx(1.0)


def test_direction_not_flipped():
    pos = np.array([1.0, 2.0, 3.0, 4.0])
    neg = np.array([5.0, 6.0, 7.0, 8.0])
    values = np.concatenate([pos, neg])
    labels = np.array([1, 1, 1, 1, 0, 0, 0, 0])
    auc = r3a.binary_auc(values, labels)
    assert auc == pytest.approx(0.0)
    assert auc < 0.5
    p = r3a.auc_pvalue(values, labels)
    z = (0.0 - 8.0) / math.sqrt(12.0)
    p_manual = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    assert p == pytest.approx(p_manual, abs=1e-12)


def test_bh_fdr_reference_values():
    pvalues = {
        "a": 0.001, "b": 0.01, "c": 0.02, "d": 0.2, "e": 0.3,
    }
    q = r3a.bh_fdr(pvalues)
    expected = {
        "a": 0.005, "b": 0.025, "c": 1.0 / 30.0, "d": 0.25, "e": 0.3,
    }
    for k, v in expected.items():
        assert q[k] == pytest.approx(v, abs=1e-12)
    # Monotone nondecreasing in p and capped at 1.
    order = sorted(q.keys(), key=lambda k: pvalues[k])
    qs = [q[k] for k in order]
    assert all(b >= a - 1e-12 for a, b in zip(qs, qs[1:]))
    assert all(v <= 1.0 + 1e-12 for v in q.values())


def test_exact_permutation_two_sided_deviation():
    """Fixed helper accumulates |U_perm - mu| >= |U_obs - mu| (not only
    exact-equal/mirror U values)."""
    v = np.arange(1.0, 7.0)
    # pos values 2,4,6 -> U=6, mu=4.5, dev=1.5; U<=3 or U>=6 -> 14/20.
    labels_mid = np.array([0, 1, 0, 1, 0, 1])
    assert _exact_permutation_p(v, labels_mid) == pytest.approx(14.0 / 20.0)
    # Extreme case: U=9 (dev 4.5) -> only U=0 and U=9 -> 2/20.
    labels_extreme = np.array([0, 0, 0, 1, 1, 1])
    assert _exact_permutation_p(v, labels_extreme) == pytest.approx(2.0 / 20.0)
