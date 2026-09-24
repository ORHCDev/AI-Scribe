"""
List every measurement chunk stored for one patient (id, type, date, preview).
Use it to build gold-set cases. Standalone: psycopg2 + pyyaml.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CLIENT_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_CLIENT_ROOT), str(_CLIENT_ROOT / "chatbot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dump a patient's measurement chunks")
    ap.add_argument("--config", required=True)
    ap.add_argument("--patient", required=True)
    ap.add_argument("--type", default="", help="Filter by measurement_type (ILIKE substring, e.g. ECG).")
    args = ap.parse_args(argv)

    import yaml
    from chatbot.RAG.VectorSearch import VectorDB

    with open(args.config, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]

    db = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    sql = (
        "SELECT measurement_ids, measurement_type, observation_date, "
        "left(chunk_text, 200) AS preview "
        "FROM measurement_chunks WHERE demographic_no = %s "
    )
    params = [args.patient]
    if args.type:
        sql += "AND measurement_type ILIKE %s "
        params.append(f"%{args.type}%")
    sql += "ORDER BY observation_date DESC;"

    try:
        db.cursor.execute(sql, params)
        rows = db.cursor.fetchall()
    finally:
        db.cleanup()

    if not rows:
        print(f"No measurement chunks for demographic_no={args.patient} "
              f"(not ingested into the vector DB yet).")
        return

    print(f"{len(rows)} measurement chunk(s) for demographic_no={args.patient}:\n")
    for mids, mtype, obs_date, preview in rows:
        preview = " ".join((preview or "").split())
        print(f"- measurement_ids : {mids!r}")
        print(f"  type            : {mtype}")
        print(f"  observation_date: {obs_date}")
        print(f"  preview         : {preview}\n")


if __name__ == "__main__":
    main()
