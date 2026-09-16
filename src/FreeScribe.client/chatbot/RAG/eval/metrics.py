"""
Retrieval metrics. Pure, dependency-free. Each takes an ordered `retrieved` id
sequence (best first) and a `relevant` id set; ids must be same-typed hashables.
"""

from __future__ import annotations

import math
from typing import Hashable, Sequence


def _top_k(retrieved: Sequence[Hashable], k: int) -> list:
    return list(retrieved)[:k]


def hit_rate_at_k(retrieved: Sequence[Hashable], relevant, k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    return 1.0 if any(r in rel for r in _top_k(retrieved, k)) else 0.0


def recall_at_k(retrieved: Sequence[Hashable], relevant, k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    found = len({r for r in _top_k(retrieved, k)} & rel)
    return found / len(rel)


def precision_at_k(retrieved: Sequence[Hashable], relevant, k: int) -> float:
    rel = set(relevant)
    topk = _top_k(retrieved, k)
    if not topk:
        return 0.0
    found = sum(1 for r in topk if r in rel)
    return found / len(topk)


def reciprocal_rank(retrieved: Sequence[Hashable], relevant) -> float:
    rel = set(relevant)
    for i, r in enumerate(retrieved, start=1):
        if r in rel:
            return 1.0 / i
    return 0.0


def dcg_at_k(retrieved: Sequence[Hashable], relevant, k: int) -> float:
    rel = set(relevant)
    dcg = 0.0
    for i, r in enumerate(_top_k(retrieved, k), start=1):
        if r in rel:
            dcg += 1.0 / math.log2(i + 1)
    return dcg


def ndcg_at_k(retrieved: Sequence[Hashable], relevant, k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(rel), k) + 1))
    if ideal == 0:
        return 0.0
    return dcg_at_k(retrieved, relevant, k) / ideal


def evaluate_query(retrieved, relevant, ks=(1, 3, 5, 10)) -> dict:
    out = {"mrr": reciprocal_rank(retrieved, relevant)}
    for k in ks:
        out[f"recall@{k}"] = recall_at_k(retrieved, relevant, k)
        out[f"precision@{k}"] = precision_at_k(retrieved, relevant, k)
        out[f"hit@{k}"] = hit_rate_at_k(retrieved, relevant, k)
        out[f"ndcg@{k}"] = ndcg_at_k(retrieved, relevant, k)
    return out


def aggregate(per_query: list) -> dict:
    if not per_query:
        return {}
    keys = per_query[0].keys()
    n = len(per_query)
    return {k: sum(q.get(k, 0.0) for q in per_query) / n for k in keys}
