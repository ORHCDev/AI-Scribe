"""Unit tests for the pure retrieval metrics (run anywhere, no heavy deps)."""

import math

import pytest


def test_recall_and_precision(metrics_mod):
    retrieved = ["a", "b", "c", "d"]
    relevant = {"b", "d"}
    assert metrics_mod.recall_at_k(retrieved, relevant, 2) == 0.5
    assert metrics_mod.recall_at_k(retrieved, relevant, 4) == 1.0
    assert metrics_mod.precision_at_k(retrieved, relevant, 2) == 0.5
    assert metrics_mod.precision_at_k(retrieved, relevant, 4) == 0.5


def test_reciprocal_rank(metrics_mod):
    assert metrics_mod.reciprocal_rank(["a", "b", "c"], {"b"}) == 0.5
    assert metrics_mod.reciprocal_rank(["b", "a"], {"b"}) == 1.0
    assert metrics_mod.reciprocal_rank(["a", "c"], {"b"}) == 0.0


def test_hit_rate(metrics_mod):
    assert metrics_mod.hit_rate_at_k(["a", "b"], {"b"}, 1) == 0.0
    assert metrics_mod.hit_rate_at_k(["a", "b"], {"b"}, 2) == 1.0


def test_ndcg_matches_manual_calculation(metrics_mod):
    retrieved = ["a", "b", "c", "d"]
    relevant = {"b", "d"}  # ranks 2 and 4
    dcg = 1.0 / math.log2(3) + 1.0 / math.log2(5)
    ideal = 1.0 / math.log2(2) + 1.0 / math.log2(3)
    assert metrics_mod.ndcg_at_k(retrieved, relevant, 4) == pytest.approx(dcg / ideal)


def test_perfect_ranking_scores_one(metrics_mod):
    retrieved = ["b", "d", "a", "c"]
    relevant = {"b", "d"}
    assert metrics_mod.recall_at_k(retrieved, relevant, 2) == 1.0
    assert metrics_mod.reciprocal_rank(retrieved, relevant) == 1.0
    assert metrics_mod.ndcg_at_k(retrieved, relevant, 4) == pytest.approx(1.0)


def test_empty_relevant_is_zero_not_crash(metrics_mod):
    assert metrics_mod.recall_at_k(["a"], set(), 5) == 0.0
    assert metrics_mod.ndcg_at_k(["a"], set(), 5) == 0.0
    assert metrics_mod.reciprocal_rank(["a"], set()) == 0.0


def test_aggregate_averages_across_queries(metrics_mod):
    q1 = metrics_mod.evaluate_query(["a", "b"], {"a"}, ks=(1, 2))
    q2 = metrics_mod.evaluate_query(["x", "y"], {"y"}, ks=(1, 2))
    agg = metrics_mod.aggregate([q1, q2])
    # recall@1: q1 hits (1.0), q2 misses (0.0) -> mean 0.5
    assert agg["recall@1"] == pytest.approx(0.5)
    assert agg["recall@2"] == pytest.approx(1.0)
    assert agg["mrr"] == pytest.approx((1.0 + 0.5) / 2)
