"""
Bug-level tests for the reranking math in chatbot/RAG/VectorSearch.py::VectorSearch.

These exercise real numeric behavior, so they need the real numpy. On machines
without the RAG runtime installed, a tiny numpy stub is used for imports only and
the whole module is skipped (detected via ``hasattr(np, "log1p")``).
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

HAS_REAL_NUMPY = hasattr(np, "log1p")

pytestmark = pytest.mark.skipif(
    not HAS_REAL_NUMPY,
    reason="reranking math needs the real numpy (RAG runtime deps not installed here)",
)


class _FakeCrossEncoder:
    """Returns caller-supplied scores aligned to the (query, text) pairs order."""

    def __init__(self, scores):
        self._scores = list(scores)

    def predict(self, pairs, batch_size=8):
        return self._scores[: len(pairs)]


def _make_vs(vectorsearch_mod, scores):
    VectorSearch = vectorsearch_mod.VectorSearch
    vs = VectorSearch.__new__(VectorSearch)  # skip __init__ -> no model download
    vs.cross_encoder = _FakeCrossEncoder(scores)
    vs.model = None
    return vs


# --- Regression for former BUG #4: log-normalize must handle negative scores ---
# (Previously _normalize_scores('log') did np.log1p(scores) directly; MedCPT
# cross-encoder logits can be <= -1, producing nan/-inf. Fixed by shifting the
# scores to be non-negative before log1p.)
def test_log_normalize_survives_negative_scores(vectorsearch_mod):
    vs = _make_vs(vectorsearch_mod, scores=[])
    scores = [-2.0, -0.5, 3.0]
    out = np.asarray(vs._normalize_scores(scores, method="log"), dtype=float)
    # no nan/inf, stays in [0, 1], and preserves the input ordering
    assert np.isfinite(out).all()
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert list(out) == sorted(out)  # inputs were ascending, so outputs must be too


def test_normalize_handles_all_equal_scores(vectorsearch_mod):
    vs = _make_vs(vectorsearch_mod, scores=[])
    for method in ("log", "min-max"):
        out = np.asarray(vs._normalize_scores([0.5, 0.5, 0.5], method=method), dtype=float)
        assert np.isfinite(out).all()


# --- Regression for former BUG #3: date_rank must return the boost-sorted list ---
# (Previously it computed `reranked = sorted(...)` but returned the unsorted
# `combined`, so recency weighting never reordered the results. Fixed to return
# `reranked`.)
def test_date_rank_returns_boost_sorted(vectorsearch_mod):
    # Doc 0 is slightly more relevant but ~8 years old; doc 1 is a touch less
    # relevant but 2 days old. Recency boost makes doc 1's final score the higher
    # one, so a correct rerank must return them in descending boost order.
    vs = _make_vs(vectorsearch_mod, scores=[0.90, 0.85])
    now = datetime.now(timezone.utc)
    docs = [
        {"text": "older but slightly more relevant", "obs_date": now - timedelta(days=3000)},
        {"text": "recent and almost as relevant", "obs_date": now - timedelta(days=2)},
    ]
    out = vs.date_rank(
        "query",
        docs,
        text_key="text",
        date_key="obs_date",
        recency_method="recent",
        batch_size=2,
    )
    boosts = [row[0] for row in out]
    assert boosts == sorted(boosts, reverse=True)
