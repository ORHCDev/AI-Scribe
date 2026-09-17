"""
End-to-end retrieval eval: mirror the RAGWorkflow retrieve + rerank stage and
check whether the rule-derived gold rows survive into the final top-N context
the LLM would see. Uses the real VectorSearch (measurement + document search,
cross-encoder rank, recency date_rank for 'latest' questions). There is no LLM
query generation or answer step -- the question text is used as the search
string, and auto_rule picks the rerank path (latest -> date_rank recent).
"""

import os
import sys
import json

# Make the FreeScribe.client root importable regardless of how this is launched.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import yaml

from chatbot.RAG.VectorSearch import VectorDB, VectorSearch

CONFIG = "configs/config.yaml"
GOLD = "chatbot/RAG/eval/gold_set.example.yaml"
PATIENTS = None          # demographic_no list; None -> auto-pick AUTO_PICK_N
AUTO_PICK_N = 10
RETRIEVE_K = 10          # per-source top_k, matches RAGWorkflow search(top_k=10)
FINAL_K = 10             # reranked[:10], matches RAGWorkflow
REPORT = "e2e_eval_report.jsonl"   # PHI -- gitignored


def _expected_rows(cur, patient, target_types, rule):
    placeholders = ",".join(["%s"] * len(target_types))
    if rule == "all":
        cur.execute(
            f"SELECT measurement_ids, measurement_type, observation_date "
            f"FROM measurement_chunks "
            f"WHERE demographic_no = %s AND measurement_type IN ({placeholders});",
            (patient, *target_types),
        )
        return cur.fetchall()
    cur.execute(
        f"SELECT measurement_ids, measurement_type, observation_date "
        f"FROM measurement_chunks "
        f"WHERE demographic_no = %s AND measurement_type IN ({placeholders}) "
        f"ORDER BY observation_date DESC LIMIT 1;",
        (patient, *target_types),
    )
    row = cur.fetchone()
    return [row] if row else []


def _pick_patients(cur, n):
    cur.execute(
        "SELECT demographic_no FROM measurement_chunks "
        "GROUP BY demographic_no ORDER BY COUNT(*) DESC LIMIT %s;",
        (n,),
    )
    return [r[0] for r in cur.fetchall()]


def _chunks_from(embeddings):
    # Mirror the document / measurement chunk shapes RAGWorkflow builds for rerank.
    chunks = []
    for d in embeddings["documents"]:
        chunks.append({
            "id": d["document_id"], "type": d["document_type"],
            "obs_date": d["observation_date"], "text": d["chunk_text"],
            "is_tool": False, "source_type": "document",
        })
    for m in embeddings["measurements"]:
        chunks.append({
            "id": m["measurement_ids"], "type": m["measurement_type"],
            "obs_date": m["observation_date"], "text": m["chunk_text"],
            "is_tool": False, "source_type": "measurement",
        })
    return chunks


def _recall(expected_ids, retrieved_ids):
    exp = set(expected_ids)
    return len(exp & set(retrieved_ids)) / len(exp) if exp else 0.0


def _first_hit_rank(expected_ids, ranked_ids):
    exp = set(expected_ids)
    for i, r in enumerate(ranked_ids, start=1):
        if r in exp:
            return i
    return None


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]
    with open(GOLD, "r", encoding="utf-8") as f:
        questions = [q for q in yaml.safe_load(f) if q.get("target_types")]

    ragdb = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    print("Loading models (embedder + MedCPT cross-encoder) ...")
    vs = VectorSearch(ragdb, tool_embds=None)
    cur = ragdb.cursor

    patients = PATIENTS if PATIENTS else _pick_patients(cur, AUTO_PICK_N)
    print(f"Patients: {patients}\n")

    results = {q["id"]: [] for q in questions}
    n_eval = n_skip = 0

    with open(REPORT, "w", encoding="utf-8") as log:
        for patient in patients:
            for q in questions:
                rule = q.get("auto_rule", "latest")
                expected = _expected_rows(cur, patient, q["target_types"], rule)
                if not expected:
                    n_skip += 1
                    continue
                exp_ids = [r[0] for r in expected]

                # Deterministic tool path: what get_measurements would deliver
                # (SQL by type + date), independent of the query phrasing.
                tool_mode = "all" if rule == "all" else "latest"
                tool_rows = vs.ragdb.fetch_measurements(
                    patient_id=str(patient), types=q["target_types"],
                    mode=tool_mode, top_k=max(FINAL_K, len(exp_ids)), to_dict=True,
                )
                tool_ids = [r["measurement_ids"] for r in tool_rows]
                tool_rec = _recall(exp_ids, tool_ids)

                for phrasing in [q["query"]] + (q.get("phrasings") or []):
                    embeddings = vs.search(
                        query=phrasing, patient_id=str(patient),
                        top_k=RETRIEVE_K, to_dict=True,
                    )
                    chunks = _chunks_from(embeddings)

                    # 'latest' questions carry recency intent -> date_rank recent;
                    # 'all' (trend / changes) use the plain cross-encoder rank.
                    if rule == "latest":
                        reranked = vs.date_rank(
                            phrasing, chunks, text_key="text", date_key="obs_date",
                            recency_method="recent", batch_size=8,
                        )
                    else:
                        reranked = vs.rank(phrasing, chunks, key="text", batch_size=8)

                    top = reranked[:FINAL_K]
                    ranked_ids = [
                        elem[1]["id"] for elem in top
                        if elem[1].get("source_type") == "measurement"
                    ]
                    rec = _recall(exp_ids, ranked_ids)
                    hit = _first_hit_rank(exp_ids, ranked_ids)
                    rr = (1.0 / hit) if hit else 0.0
                    results[q["id"]].append((rec, rr, tool_rec))
                    n_eval += 1

                    log.write(json.dumps({
                        "patient": patient,
                        "question_id": q["id"],
                        "phrasing": phrasing,
                        "auto_rule": rule,
                        "recall": round(rec, 3),
                        "tool_recall": round(tool_rec, 3),
                        "mrr": round(rr, 3),
                        "first_hit_rank": hit,
                        "expected": [
                            {"measurement_ids": r[0], "type": r[1], "date": str(r[2])}
                            for r in expected
                        ],
                        "final_topN": [
                            {"id": e[1]["id"], "type": e[1]["type"],
                             "date": str(e[1]["obs_date"]),
                             "source": e[1]["source_type"], "score": float(e[0])}
                            for e in top
                        ],
                    }) + "\n")

    ragdb.cleanup()

    print("=" * 74)
    print(f"{'question':22s} {'n':>3s} {'vec_rec':>8s} {'tool_rec':>9s} {'mrr':>6s}")
    print("-" * 74)
    all_rec, all_rr, all_tool = [], [], []
    for q in questions:
        flat = results[q["id"]]
        if not flat:
            print(f"{q['id']:22s}   0")
            continue
        recs = [p[0] for p in flat]
        rrs = [p[1] for p in flat]
        tools = [p[2] for p in flat]
        all_rec += recs
        all_rr += rrs
        all_tool += tools
        print(f"{q['id']:22s} {len(flat):>3d} {sum(recs)/len(recs):>8.3f} "
              f"{sum(tools)/len(tools):>9.3f} {sum(rrs)/len(rrs):>6.3f}")
    print("-" * 74)
    if all_rec:
        print(f"{'OVERALL':22s} {len(all_rec):>3d} {sum(all_rec)/len(all_rec):>8.3f} "
              f"{sum(all_tool)/len(all_tool):>9.3f} {sum(all_rr)/len(all_rr):>6.3f}")
    print("=" * 74)
    print(f"evaluated {n_eval} cases; skipped {n_skip}; diagnostics in {REPORT}")


if __name__ == "__main__":
    main()
