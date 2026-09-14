"""
RAG retrieval-quality evaluation runner (MEASUREMENTS ONLY).

Scope: this harness evaluates retrieval of Oscar *measurements* (the
measurement_chunks table). Documents and chatbot tools are intentionally out of
scope. Pipeline exercised: MedEmbed bi-encoder + pgvector search, optionally the
MedCPT cross-encoder rerank, scored against a hand-labeled gold set with
recall / precision / MRR / nDCG.

This script needs the RAG runtime and is meant to run on the clinic / server
machine, NOT on a dev laptop:
  * Python deps: numpy, psycopg2, sentence-transformers, pyyaml
  * a populated pgvector database (measurement_chunks)
  * the embedding + cross-encoder models (downloaded on first run)

It only reads the Postgres vector DB; it does NOT touch Oscar EMR, so no SSH
tunnel or EMR credentials are required.

Usage
-----
    cd src/FreeScribe.client
    python -m chatbot.RAG.eval.run_eval \
        --config /path/to/config.yaml \
        --gold   chatbot/RAG/eval/gold_set.yaml \
        --top-k 10 --rerank --out eval_report.json

`--config` must be a YAML file with a `VectorDB` section:

    VectorDB:
      host: ...
      port: 5432
      dbname: ...
      user: ...
      password: ...
    # optional:
    RAG:
      embedding_model: abhinand/MedEmbed-base-v0.1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make `chatbot...` importable no matter where this is launched from.
_CLIENT_ROOT = Path(__file__).resolve().parents[3]  # src/FreeScribe.client
for _p in (str(_CLIENT_ROOT), str(_CLIENT_ROOT / "chatbot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chatbot.RAG.eval import metrics as M  # noqa: E402


DEFAULT_EMBEDDING_MODEL = "abhinand/MedEmbed-base-v0.1"


def _load_yaml(path):
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _retrieve_measurements(vs, query, patient_id, date, top_k):
    """Run the raw measurement vector search; return dict rows ordered by distance."""
    query_vec = vs.model.encode(query)
    return vs.ragdb.measurement_search(
        query_vec, patient_id=patient_id, date=date, top_k=top_k, to_dict=True
    )


def _ranked_ids(rows):
    """measurement_ids in rank order, first occurrence wins (rows are distance-sorted)."""
    seen, out = set(), []
    for r in rows:
        rid = r["measurement_ids"]
        if rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


def _reranked_ids(vs, query, rows):
    """Cross-encoder rerank of the measurement chunk pool, mirroring RAGWorkflow."""
    chunks = [{"id": r["measurement_ids"], "text": r["chunk_text"]} for r in rows]
    if not chunks:
        return []
    ranked = vs.rank(query, chunks, key="text")  # [(score, chunk), ...] desc
    seen, out = set(), []
    for _score, chunk in ranked:
        if chunk["id"] not in seen:
            seen.add(chunk["id"])
            out.append(chunk["id"])
    return out


def run(config_path, gold_path, top_k, do_rerank, ks):
    from chatbot.RAG.VectorSearch import VectorDB, VectorSearch

    config = _load_yaml(config_path)
    creds = config["VectorDB"]
    model_name = (config.get("RAG") or {}).get("embedding_model", DEFAULT_EMBEDDING_MODEL)

    gold = _load_yaml(gold_path)
    if not gold:
        raise SystemExit(f"Gold set {gold_path} is empty.")

    ragdb = VectorDB(
        host=creds["host"],
        port=creds["port"],
        dbname=creds["dbname"],
        user=creds["user"],
        password=creds["password"],
    )
    # tool_embds=None: measurement retrieval only, no tool embeddings involved.
    vs = VectorSearch(ragdb=ragdb, tool_embds=None, embedding_model=model_name)

    vector_scores, rerank_scores, per_case = [], [], []
    try:
        for case in gold:
            gold_ids = set(case.get("relevant_measurement_ids") or [])
            if not gold_ids:
                print(f"[skip] case {case.get('id')} has no relevant_measurement_ids")
                continue

            rows = _retrieve_measurements(
                vs, case["query"], str(case.get("patient_id") or "") or None,
                case.get("date"), top_k,
            )

            vec_metrics = M.evaluate_query(_ranked_ids(rows), gold_ids, ks=ks)
            vector_scores.append(vec_metrics)

            row = {"id": case.get("id"), "query": case.get("query"),
                   "n_relevant": len(gold_ids), "vector": vec_metrics}

            if do_rerank:
                rr_metrics = M.evaluate_query(_reranked_ids(vs, case["query"], rows), gold_ids, ks=ks)
                rerank_scores.append(rr_metrics)
                row["reranked"] = rr_metrics

            per_case.append(row)
            print(f"[ok] {case.get('id')}: "
                  f"recall@{top_k}={vec_metrics.get(f'recall@{top_k}', 0):.3f}")
    finally:
        vs.cleanup()

    report = {
        "scope": "measurements",
        "config": os.path.basename(config_path),
        "gold_set": os.path.basename(gold_path),
        "top_k": top_k,
        "n_cases": len(per_case),
        "vector": M.aggregate(vector_scores),
        "reranked": M.aggregate(rerank_scores) if do_rerank else None,
        "per_case": per_case,
    }
    return report


def _print_summary(report):
    def fmt(agg):
        if not agg:
            return "  (none)"
        return "\n".join(f"    {k:14s} {v:.3f}" for k, v in sorted(agg.items()))

    print("\n" + "=" * 60)
    print(f"Measurement retrieval | cases: {report['n_cases']}  (top_k={report['top_k']})")
    print("\nVector search (pre-rerank):")
    print(fmt(report["vector"]))
    if report["reranked"] is not None:
        print("\nCross-encoder rerank:")
        print(fmt(report["reranked"]))
    print("=" * 60)


def main(argv=None):
    ap = argparse.ArgumentParser(description="RAG measurement retrieval-quality eval")
    ap.add_argument("--config", required=True, help="YAML config with a VectorDB section")
    ap.add_argument("--gold", required=True, help="YAML gold set (see gold_set.example.yaml)")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--rerank", action="store_true", help="also score the cross-encoder rerank")
    ap.add_argument("--ks", default="1,3,5,10", help="comma-separated k values for @k metrics")
    ap.add_argument("--out", default=None, help="write full JSON report to this path")
    args = ap.parse_args(argv)

    ks = tuple(int(x) for x in args.ks.split(",") if x.strip())
    report = run(args.config, args.gold, args.top_k, args.rerank, ks)
    _print_summary(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nWrote report to {args.out}")


if __name__ == "__main__":
    main()
