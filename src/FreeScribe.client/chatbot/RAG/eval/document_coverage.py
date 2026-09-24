"""
For each patient, compare how many documents OSCAR has vs how
many are in the pgvector store (document_chunks). Shows what the ingestion has
pulled and what is still MISSING -- run it after a backfill to see how much got
pulled and what remains.
"""

import os
import sys
import argparse


_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

import yaml

from chatbot.daily_uploader import initialize_oscardb
from chatbot.RAG.VectorSearch import VectorDB
from chatbot.Tools.utils import pdf_image_to_text

CONFIG = "configs/config.yaml"
EMPTY_THRESHOLD = 20  # OCR text shorter than this = "blank" (unreadable, can't be ingested)


def _ocr_len(db_conn, doc_no):
    # OCR a document and return its text length; 0 if it can't be read (blank).
    try:
        pdf_bytes = db_conn.get_doc_bytes(doc_no=doc_no)
        return len(pdf_image_to_text(pdf_bytes=pdf_bytes, last_page=4) or "")
    except Exception:
        return 0


def _oscar_doc_ids(db_conn, demo):
    # All of a patient's documents in Oscar -> {document_no: (doctype, observationdate)}.
    query = f"""
        SELECT cd.document_no, d.doctype, d.observationdate
        FROM ctl_document AS cd
        LEFT JOIN document AS d ON cd.document_no = d.document_no
        WHERE cd.module = "demographic" AND cd.module_id = {int(demo)}
    """
    rows = db_conn.query_database(query)
    out = {}
    for r in rows:
        no = r.get("document_no")
        if no is not None:
            out[int(no)] = (r.get("doctype"), r.get("observationdate"))
    return out


def _store_doc_ids(cur, demo):
    # A patient's distinct document ids already ingested into the store.
    cur.execute(
        "SELECT DISTINCT document_id FROM document_chunks WHERE demographic_no = %s;",
        (demo,),
    )
    return {int(r[0]) for r in cur.fetchall()}


def main():
    ap = argparse.ArgumentParser(description="Oscar vs store document coverage.")
    ap.add_argument("--patients", default="", help="Comma-separated demographic_no.")
    ap.add_argument("--n", type=int, default=0,
                    help="Use the N patients with the most docs already in the store.")
    ap.add_argument("--list-missing", action="store_true",
                    help="Print each missing document's type + date.")
    ap.add_argument("--check-content", action="store_true",
                    help="OCR each MISSING document to split blank (unreadable) from real (has text).")
    args = ap.parse_args()

    with open(CONFIG, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    creds = config["VectorDB"]

    vdb = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    cur = vdb.cursor

    if args.patients:
        patients = [p.strip() for p in args.patients.split(",") if p.strip()]
    elif args.n:
        cur.execute(
            "SELECT demographic_no, COUNT(DISTINCT document_id) AS n "
            "FROM document_chunks GROUP BY demographic_no ORDER BY n DESC LIMIT %s;",
            (args.n,),
        )
        patients = [str(r[0]) for r in cur.fetchall()]
    else:
        print("Provide --patients 1,2,3 or --n 20.")
        vdb.cleanup()
        return

    print("Connecting to Oscar (this can take a moment) ...")
    db_conn = initialize_oscardb(config)

    check = args.check_content
    if check:
        print("--check-content: OCR-ing each missing document to detect blanks (slow) ...")
    hdr = f"\n{'patient':>10s} {'oscar':>6s} {'store':>6s} {'missing':>8s}"
    hdr += (f" {'blank':>6s} {'real':>6s} {'realcov%':>8s}" if check else f" {'cover%':>7s}")
    print(hdr)
    width = 60 if check else 44
    print("-" * width)

    tot_oscar = tot_store = tot_missing = tot_blank = tot_real = 0
    missing_detail = []

    for demo in patients:
        oscar = _oscar_doc_ids(db_conn, demo)
        store = _store_doc_ids(cur, demo)
        missing = sorted(set(oscar) - store)
        o, s, m = len(oscar), len(store & set(oscar)), len(missing)

        blank = real = 0
        for doc_no in missing:
            tag = "?"
            if check:
                if _ocr_len(db_conn, doc_no) < EMPTY_THRESHOLD:
                    blank += 1
                    tag = "blank"
                else:
                    real += 1
                    tag = "content"
            if args.list_missing:
                dtype, dt = oscar[doc_no]
                missing_detail.append((demo, doc_no, dtype, dt, tag))

        tot_oscar += o
        tot_store += s
        tot_missing += m
        tot_blank += blank
        tot_real += real

        if check:
            readable = o - blank
            realcov = 100.0 * (readable - real) / readable if readable else 0.0
            print(f"{str(demo):>10s} {o:>6d} {s:>6d} {m:>8d} {blank:>6d} {real:>6d} {realcov:>7.1f}%")
        else:
            cov = 100.0 * (o - m) / o if o else 0.0
            print(f"{str(demo):>10s} {o:>6d} {s:>6d} {m:>8d} {cov:>6.1f}%")

    print("-" * width)
    if check:
        readable = tot_oscar - tot_blank
        realcov = 100.0 * (readable - tot_real) / readable if readable else 0.0
        print(f"{'TOTAL':>10s} {tot_oscar:>6d} {tot_store:>6d} {tot_missing:>8d} "
              f"{tot_blank:>6d} {tot_real:>6d} {realcov:>7.1f}%")
        print(f"\nof {tot_missing} missing: {tot_blank} blank (unreadable -- cannot be "
              f"ingested), {tot_real} REAL (have text -> a backfill will pull these).")
    else:
        cov = 100.0 * (tot_oscar - tot_missing) / tot_oscar if tot_oscar else 0.0
        print(f"{'TOTAL':>10s} {tot_oscar:>6d} {tot_store:>6d} {tot_missing:>8d} {cov:>6.1f}%")
        print(f"\n{tot_missing} document(s) in Oscar are NOT in the store "
              f"({100.0 - cov:.1f}% missing). Add --check-content to split blank vs real.")

    if args.list_missing and missing_detail:
        print("\nMissing documents (in Oscar, not in store):")
        print(f"  {'patient':>10s} {'doc_no':>10s}  {'tag':8s} {'type':20s} date")
        for demo, doc_no, dtype, dt, tag in missing_detail:
            print(f"  {str(demo):>10s} {doc_no:>10d}  {tag:8s} {str(dtype)[:20]:20s} {dt}")

    db_conn.cleanup()
    vdb.cleanup()


if __name__ == "__main__":
    main()
