"""
Count stored measurement chunks that exceed the embedding token limit (i.e. that
were silently truncated at embed time). Standalone: psycopg2 + transformers.
"""

import yaml
import psycopg2
from transformers import AutoTokenizer

CONFIG = "configs/config.yaml"
MODEL = "abhinand/MedEmbed-base-v0.1"
LIMIT = 512
PATIENT = None            # demographic_no to scope, or None for all
TOP_OFFENDERS = 15


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]

    conn = psycopg2.connect(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    cur = conn.cursor()
    if PATIENT is None:
        cur.execute("SELECT measurement_ids, measurement_type, chunk_text FROM measurement_chunks;")
    else:
        cur.execute(
            "SELECT measurement_ids, measurement_type, chunk_text "
            "FROM measurement_chunks WHERE demographic_no = %s;",
            (PATIENT,),
        )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("measurement_chunks has no rows for this scope.")
        return

    print(f"Loading tokenizer '{MODEL}' ...")
    tok = AutoTokenizer.from_pretrained(MODEL)

    lengths, over = [], []
    for mids, mtype, text in rows:
        n = len(tok(text or "", truncation=False, add_special_tokens=True)["input_ids"])
        lengths.append(n)
        if n > LIMIT:
            over.append((n, mtype, mids))

    total = len(rows)
    n_over = len(over)
    print()
    print(f"measurement chunks scanned   : {total}")
    print(f"token limit (encode cutoff)  : {LIMIT}")
    print(f"chunks OVER the limit        : {n_over} ({100.0 * n_over / total:.1f}%)")
    print(f"max token length seen        : {max(lengths)}")
    print(f"mean token length            : {sum(lengths) / total:.0f}")

    if over:
        over.sort(reverse=True)
        print(f"\nlongest {min(TOP_OFFENDERS, len(over))} (tokens | type | measurement_ids):")
        for n, mtype, mids in over[:TOP_OFFENDERS]:
            print(f"  {n:6d} | {mtype} | {mids!r}")


if __name__ == "__main__":
    main()
