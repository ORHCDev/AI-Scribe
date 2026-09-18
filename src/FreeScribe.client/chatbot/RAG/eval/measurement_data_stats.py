"""
Data-quality prevalence stats over measurement_chunks. No LLM, no Oscar.
Quantifies, per measurement_type across ALL patients:
  - dup_pct:      redundant rows (same patient + identical chunk_text repeated)
  - avg_len:      average chunk_text length (narrative blobs run long)
  - has_date_pct: of the latest record per patient, how many quote an explicit
                  YYYY-MM-DD in the text (a back-reference to another event)
  - mismatch_pct: of those, how many quote a year != the record's observation_date
                  year (observation_date is the filing date, not the event date)
Output is aggregate only (no chunk_text, no ids) -- safe to keep/commit.
"""

import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import yaml

from chatbot.RAG.VectorSearch import VectorDB

CONFIG = "configs/config.yaml"
DATE_RE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]
    db = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    cur = db.cursor

    cur.execute("""
        WITH g AS (
            SELECT measurement_type, demographic_no, chunk_text, COUNT(*) AS c
            FROM measurement_chunks
            GROUP BY 1, 2, 3
        )
        SELECT measurement_type, SUM(c) AS total, SUM(c) - COUNT(*) AS redundant
        FROM g GROUP BY 1;
    """)
    redund = {r[0]: (int(r[1]), int(r[2])) for r in cur.fetchall()}

    cur.execute("""
        SELECT measurement_type, COUNT(*), COUNT(DISTINCT demographic_no),
               ROUND(AVG(LENGTH(chunk_text)))
        FROM measurement_chunks GROUP BY 1;
    """)
    vol = {r[0]: (int(r[1]), int(r[2]), int(r[3])) for r in cur.fetchall()}

    cur.execute("""
        SELECT DISTINCT ON (demographic_no, measurement_type)
               measurement_type, observation_date, chunk_text
        FROM measurement_chunks
        ORDER BY demographic_no, measurement_type, observation_date DESC;
    """)
    latest_n, has_date, mismatch = {}, {}, {}
    for mtype, obs_date, text in cur.fetchall():
        latest_n[mtype] = latest_n.get(mtype, 0) + 1
        years = {int(m.group(0)[:4]) for m in DATE_RE.finditer(text or "")}
        if years:
            has_date[mtype] = has_date.get(mtype, 0) + 1
            if obs_date is not None and obs_date.year not in years:
                mismatch[mtype] = mismatch.get(mtype, 0) + 1

    db.cleanup()

    rows = []
    for mtype in vol:
        total, pats, avglen = vol[mtype]
        red = redund.get(mtype, (total, 0))[1]
        dup_pct = 100.0 * red / total if total else 0.0
        ln = latest_n.get(mtype, 0)
        hd = has_date.get(mtype, 0)
        mm = mismatch.get(mtype, 0)
        has_pct = 100.0 * hd / ln if ln else 0.0
        mm_pct = 100.0 * mm / hd if hd else 0.0
        rows.append((mtype, pats, total, dup_pct, avglen, ln, has_pct, mm_pct))

    rows.sort(key=lambda x: x[3], reverse=True)

    print("=" * 92)
    print(f"{'type':8s} {'patients':>8s} {'rows':>7s} {'dup%':>6s} {'avg_len':>7s} "
          f"{'latest_n':>8s} {'has_date%':>9s} {'mismatch%':>9s}")
    print("-" * 92)
    for r in rows:
        print(f"{str(r[0]):8s} {r[1]:>8d} {r[2]:>7d} {r[3]:>6.1f} {r[4]:>7d} "
              f"{r[5]:>8d} {r[6]:>9.1f} {r[7]:>9.1f}")
    print("=" * 92)
    tot_rows = sum(r[2] for r in rows)
    tot_red = sum(redund.get(r[0], (0, 0))[1] for r in rows)
    print(f"total rows {tot_rows}; redundant {tot_red} "
          f"({100.0*tot_red/tot_rows:.1f}% overall dup); types {len(rows)}")


if __name__ == "__main__":
    main()
