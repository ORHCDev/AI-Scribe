"""
Rule-based auto-eval for measurement retrieval (recall stage only, no LLM/tools).

Expected ids come from a SQL rule over type+date (latest / all), not from labels
or AI. Each question is run with its primary query plus every phrasing. A per-case
diagnostic line is written to REPORT for drill-down.
"""

import json
import yaml
import psycopg2
from sentence_transformers import SentenceTransformer

CONFIG = "configs/config.yaml"
MODEL = "abhinand/MedEmbed-base-v0.1"
GOLD = "chatbot/RAG/eval/gold_set.example.yaml"
PATIENTS = [18931]        # demographic_no list; None -> auto-pick AUTO_PICK_N
AUTO_PICK_N = 10
TOP_K = 10
REPORT = "auto_eval_report.jsonl"   # PHI -- gitignored


def _vec_literal(vec):
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


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


def _retrieve(cur, patient, query_vec, k):
    cur.execute(
        "WITH candidate AS MATERIALIZED ("
        "  SELECT measurement_ids, measurement_type, observation_date, embedding_raw "
        "  FROM measurement_chunks WHERE demographic_no = %s"
        ") "
        "SELECT measurement_ids, measurement_type, observation_date "
        "FROM candidate ORDER BY embedding_raw <=> %s::vector LIMIT %s;",
        (patient, _vec_literal(query_vec), k),
    )
    return cur.fetchall()


def _recall(expected_ids, retrieved_ids):
    exp = set(expected_ids)
    return len(exp & set(retrieved_ids)) / len(exp) if exp else 0.0


def _first_hit_rank(expected_ids, retrieved_ids):
    exp = set(expected_ids)
    for i, r in enumerate(retrieved_ids, start=1):
        if r in exp:
            return i
    return None


def _miss_reason(expected, retrieved):
    exp_ids = {r[0] for r in expected}
    got_ids = {r[0] for r in retrieved}
    missed = exp_ids - got_ids
    if not missed:
        return "all expected ids retrieved"
    exp_types = {r[1] for r in expected}
    got_types = {r[1] for r in retrieved}
    if not (exp_types & got_types):
        return (f"expected type(s) {sorted(exp_types)} absent from top-k; "
                f"top-k types were {sorted(got_types)}")
    return (f"{len(missed)}/{len(exp_ids)} expected ids missing from top-k "
            f"(right type retrieved but wrong/older rows ranked higher)")


def _pick_patients(cur, n):
    cur.execute(
        "SELECT demographic_no FROM measurement_chunks "
        "GROUP BY demographic_no ORDER BY COUNT(*) DESC LIMIT %s;",
        (n,),
    )
    return [r[0] for r in cur.fetchall()]


def _fmt_rows(rows):
    return [{"measurement_ids": r[0], "type": r[1], "date": str(r[2])} for r in rows]


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]
    with open(GOLD, "r", encoding="utf-8") as f:
        questions = [q for q in yaml.safe_load(f) if q.get("target_types")]

    print(f"Loading model '{MODEL}' ...")
    model = SentenceTransformer(MODEL)

    conn = psycopg2.connect(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    cur = conn.cursor()

    patients = PATIENTS if PATIENTS else _pick_patients(cur, AUTO_PICK_N)
    print(f"Patients: {patients}\n")

    results = {q["id"]: {} for q in questions}
    n_eval = n_skip = 0

    with open(REPORT, "w", encoding="utf-8") as log:
        for patient in patients:
            for q in questions:
                expected = _expected_rows(cur, patient, q["target_types"], q.get("auto_rule", "latest"))
                if not expected:
                    n_skip += 1
                    continue
                exp_ids = [r[0] for r in expected]
                k = max(TOP_K, len(exp_ids)) if q.get("auto_rule") == "all" else TOP_K

                for phrasing in [q["query"]] + (q.get("phrasings") or []):
                    retrieved = _retrieve(cur, patient, model.encode(phrasing), k)
                    got_ids = [r[0] for r in retrieved]
                    rec = _recall(exp_ids, got_ids)
                    hit = _first_hit_rank(exp_ids, got_ids)
                    rr = (1.0 / hit) if hit else 0.0

                    results[q["id"]].setdefault(phrasing, []).append((rec, rr))
                    n_eval += 1

                    log.write(json.dumps({
                        "patient": patient,
                        "question_id": q["id"],
                        "phrasing": phrasing,
                        "auto_rule": q.get("auto_rule", "latest"),
                        "k": k,
                        "recall": round(rec, 3),
                        "mrr": round(rr, 3),
                        "first_hit_rank": hit,
                        "expected": _fmt_rows(expected),
                        "retrieved": [
                            {**row, "rank": i}
                            for i, row in enumerate(_fmt_rows(retrieved), start=1)
                        ],
                        "miss_reason": None if rec == 1.0 else _miss_reason(expected, retrieved),
                    }) + "\n")

    conn.close()

    print("=" * 74)
    print(f"{'question':22s} {'n':>3s} {'recall':>7s} {'mrr':>6s}  worst phrasing (recall)")
    print("-" * 74)
    all_rec, all_rr = [], []
    for q in questions:
        by_phrasing = results[q["id"]]
        if not by_phrasing:
            print(f"{q['id']:22s}   0    (no patient had this data)")
            continue
        flat = [pair for lst in by_phrasing.values() for pair in lst]
        recs = [p[0] for p in flat]
        rrs = [p[1] for p in flat]
        all_rec += recs
        all_rr += rrs
        worst_phr = min(by_phrasing, key=lambda p: sum(r for r, _ in by_phrasing[p]) / len(by_phrasing[p]))
        worst_rec = sum(r for r, _ in by_phrasing[worst_phr]) / len(by_phrasing[worst_phr])
        print(f"{q['id']:22s} {len(flat):>3d} {sum(recs)/len(recs):>7.3f} "
              f"{sum(rrs)/len(rrs):>6.3f}  {worst_rec:.2f}  \"{worst_phr}\"")
    print("-" * 74)
    if all_rec:
        print(f"{'OVERALL':22s} {len(all_rec):>3d} {sum(all_rec)/len(all_rec):>7.3f} "
              f"{sum(all_rr)/len(all_rr):>6.3f}")
    print("=" * 74)
    print(f"evaluated {n_eval} cases; skipped {n_skip}; diagnostics in {REPORT}")


if __name__ == "__main__":
    main()
