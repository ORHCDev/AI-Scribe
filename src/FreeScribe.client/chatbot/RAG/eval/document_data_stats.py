"""
Data-quality prevalence stats over document_chunks, per document_type. No LLM,
no Oscar -- just the pgvector store. Tells you how big the two problems that FTS
CANNOT fix are, before deciding how much to invest:

  - empty_pct:    documents with no usable extracted text (image-only / OCR gave
                  nothing) -- FTS can never find these by content.
  - avg_len:      average characters of extracted text per document.
  - dup_pct:      redundant documents (same patient + identical full text).
  - has_date_pct: of documents whose text quotes an explicit date, the share
                  that do (a real exam date often sits in the report header).
  - mismatch_pct: of those, how many quote a YEAR != the record's
                  observation_date year (observation_date is the filing date,
                  not the event date).

Chunks are aggregated back into whole documents first. Output is aggregate only
(no text, no ids) -- safe to keep.

  cd src/FreeScribe.client
  python -m chatbot.RAG.eval.document_data_stats
"""

import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import yaml

from chatbot.RAG.VectorSearch import VectorDB

CONFIG = "configs/config.yaml"
EMPTY_THRESHOLD = 20  # a document with < this many chars of text = "no content"

# Date patterns whose YEAR we can trust as a real date reference.
_DATE_PATTERNS = [
    re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b"),                       # 2024-08-20
    re.compile(r"\b\d{1,2}/\d{1,2}/((?:19|20)\d{2})\b"),              # 20/08/2024
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"\d{1,2},?\s+((?:19|20)\d{2})\b",
        re.IGNORECASE,
    ),                                                                # Aug 20, 2024
]


def _years(text):
    years = set()
    if not text:
        return years
    for m in _DATE_PATTERNS[0].finditer(text):
        years.add(int(m.group(0)[:4]))
    for pat in _DATE_PATTERNS[1:]:
        for m in pat.finditer(text):
            years.add(int(m.group(1)))
    return years


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]
    db = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    cur = db.cursor

    # One row per document: type, patient, date, text length, content hash, head.
    cur.execute("""
        SELECT COALESCE(document_type, '(none)') AS document_type,
               demographic_no, observation_date, length(full_text) AS len,
               md5(full_text) AS h, LEFT(full_text, 1500) AS head
        FROM (
            SELECT document_id,
                   MAX(document_type)   AS document_type,
                   MAX(demographic_no)  AS demographic_no,
                   MAX(observation_date) AS observation_date,
                   string_agg(chunk_text, ' ' ORDER BY chunk_index) AS full_text
            FROM document_chunks
            GROUP BY document_id
        ) d;
    """)

    # Aggregate per type in Python (mirrors measurement_data_stats).
    stats = {}          # type -> dict of counters
    seen = {}           # type -> {(demo, hash): count}  for dup detection
    for dtype, demo, obs_date, ln, h, head in cur.fetchall():
        s = stats.setdefault(dtype, {
            "docs": 0, "empty": 0, "len_sum": 0, "has_date": 0, "mismatch": 0,
        })
        s["docs"] += 1
        s["len_sum"] += int(ln or 0)
        if (ln or 0) < EMPTY_THRESHOLD:
            s["empty"] += 1

        years = _years(head)
        if years:
            s["has_date"] += 1
            if obs_date is not None and obs_date.year not in years:
                s["mismatch"] += 1

        key = (demo, h)
        d = seen.setdefault(dtype, {})
        d[key] = d.get(key, 0) + 1

    db.cleanup()

    rows = []
    for dtype, s in stats.items():
        docs = s["docs"]
        redundant = sum(c - 1 for c in seen.get(dtype, {}).values() if c > 1)
        rows.append((
            dtype,
            docs,
            100.0 * s["empty"] / docs if docs else 0.0,
            int(s["len_sum"] / docs) if docs else 0,
            100.0 * redundant / docs if docs else 0.0,
            100.0 * s["has_date"] / docs if docs else 0.0,
            100.0 * s["mismatch"] / s["has_date"] if s["has_date"] else 0.0,
        ))

    rows.sort(key=lambda r: r[1], reverse=True)

    print("=" * 84)
    print(f"{'type':22s} {'docs':>6s} {'empty%':>7s} {'avg_len':>8s} "
          f"{'dup%':>6s} {'has_date%':>10s} {'mismatch%':>10s}")
    print("-" * 84)
    for r in rows:
        print(f"{str(r[0])[:22]:22s} {r[1]:>6d} {r[2]:>7.1f} {r[3]:>8d} "
              f"{r[4]:>6.1f} {r[5]:>10.1f} {r[6]:>10.1f}")
    print("=" * 84)

    total_docs = sum(r[1] for r in rows)
    total_empty = sum(s["empty"] for s in stats.values())
    total_red = sum(
        sum(c - 1 for c in d.values() if c > 1) for d in seen.values()
    )
    print(f"total documents {total_docs}; "
          f"empty {total_empty} ({100.0*total_empty/total_docs:.1f}%); "
          f"redundant {total_red} ({100.0*total_red/total_docs:.1f}%); "
          f"types {len(rows)}")


if __name__ == "__main__":
    main()
