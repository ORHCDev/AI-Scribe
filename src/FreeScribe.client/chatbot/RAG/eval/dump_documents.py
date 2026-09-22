"""
Inspect documents in the pgvector store (document_chunks) -- to find real cases
for the FTS probe gold and to eyeball mislabels. Pure SQL, no model/Oscar.
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import yaml

from chatbot.RAG.VectorSearch import VectorDB

CONFIG = "configs/config.yaml"


def main():
    ap = argparse.ArgumentParser(description="Inspect documents in document_chunks.")
    ap.add_argument("--patient", help="demographic_no to list documents for.")
    ap.add_argument("--type", default="", help="Filter by document_type (ILIKE substring).")
    ap.add_argument("--find-patients", action="store_true",
                    help="Instead of listing docs, list patients who have --type.")
    ap.add_argument("--k", type=int, default=25, help="Max rows.")
    ap.add_argument("--full", action="store_true", help="Print full text instead of a snippet.")
    args = ap.parse_args()

    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]
    db = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    cur = db.cursor

    if args.find_patients:
        cur.execute("""
            SELECT demographic_no, COUNT(DISTINCT document_id) AS n
            FROM document_chunks
            WHERE document_type ILIKE %s
            GROUP BY demographic_no
            ORDER BY n DESC
            LIMIT %s;
        """, (f"%{args.type}%", args.k))
        print(f"patients with document_type ILIKE '%{args.type}%':")
        for demo, n in cur.fetchall():
            print(f"  demo={demo}  docs={n}")
        db.cleanup()
        return

    if not args.patient:
        print("Provide --patient <demo_no> (or --find-patients --type ...).")
        db.cleanup()
        return

    filters = ["demographic_no = %s"]
    params = [args.patient]
    if args.type:
        filters.append("document_type ILIKE %s")
        params.append(f"%{args.type}%")
    where = " AND ".join(filters)

    cur.execute(f"""
        SELECT document_id, document_type, observation_date,
               string_agg(chunk_text, ' ' ORDER BY chunk_index) AS full_text
        FROM document_chunks
        WHERE {where}
        GROUP BY document_id, document_type, observation_date
        ORDER BY observation_date DESC
        LIMIT %s;
    """, params + [args.k])

    rows = cur.fetchall()
    print(f"patient {args.patient}: {len(rows)} document(s)"
          + (f" of type ~'{args.type}'" if args.type else ""))
    for doc_id, dtype, obs, text in rows:
        text = text or ""
        body = text if args.full else " ".join(text.split())[:200]
        print(f"\n--- doc_id={doc_id} [{dtype}] {obs} (len={len(text)}) ---")
        print(f"  {body}")

    db.cleanup()


if __name__ == "__main__":
    main()
