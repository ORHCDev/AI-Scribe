"""Reranking math tests -- need real numpy, else the module is skipped."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

HAS_REAL_NUMPY = hasattr(np, "log1p")

pytestmark = pytest.mark.skipif(not HAS_REAL_NUMPY, reason="needs real numpy")


class _FakeCrossEncoder:
    def __init__(self, scores):
        self._scores = list(scores)

    def predict(self, pairs, batch_size=8):
        return self._scores[: len(pairs)]


def _make_vs(vectorsearch_mod, scores):
    VectorSearch = vectorsearch_mod.VectorSearch
    vs = VectorSearch.__new__(VectorSearch)
    vs.cross_encoder = _FakeCrossEncoder(scores)
    vs.model = None
    return vs


# Regression for former BUG #4: log-normalize must survive negative logits.
def test_log_normalize_survives_negative_scores(vectorsearch_mod):
    vs = _make_vs(vectorsearch_mod, scores=[])
    out = np.asarray(vs._normalize_scores([-2.0, -0.5, 3.0], method="log"), dtype=float)
    assert np.isfinite(out).all()
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert list(out) == sorted(out)


def test_normalize_handles_all_equal_scores(vectorsearch_mod):
    vs = _make_vs(vectorsearch_mod, scores=[])
    for method in ("log", "min-max"):
        out = np.asarray(vs._normalize_scores([0.5, 0.5, 0.5], method=method), dtype=float)
        assert np.isfinite(out).all()


# Regression for former BUG #3: date_rank must return the boost-sorted list.
def test_date_rank_returns_boost_sorted(vectorsearch_mod):
    # Doc 0 is more relevant but old; doc 1 less relevant but recent -> recency
    # boost should flip the order, so the result must be descending by boost.
    vs = _make_vs(vectorsearch_mod, scores=[0.90, 0.85])
    now = datetime.now(timezone.utc)
    docs = [
        {"text": "older but slightly more relevant", "obs_date": now - timedelta(days=3000)},
        {"text": "recent and almost as relevant", "obs_date": now - timedelta(days=2)},
    ]
    out = vs.date_rank("query", docs, text_key="text", date_key="obs_date",
                       recency_method="recent", batch_size=2)
    boosts = [row[0] for row in out]
    assert boosts == sorted(boosts, reverse=True)
