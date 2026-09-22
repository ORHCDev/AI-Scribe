"""
One-time migration: add a GIN full-text index on document_chunks.chunk_text so
the SQL/FTS document path (VectorDB.fetch_documents / the get_documents tool)
runs fast. Idempotent -- safe to run more than once.

  cd src/FreeScribe.client
  python -m chatbot.RAG.add_document_fts_index

Reads only the VectorDB section of config.yaml. No Oscar / SSH / model needed.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import yaml

from chatbot.RAG.VectorSearch import VectorDB

CONFIG = "configs/config.yaml"

# 'english' regconfig makes to_tsvector IMMUTABLE, so it is indexable.
INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_document_chunks_fts "
    "ON document_chunks USING gin (to_tsvector('english', chunk_text));"
)


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        creds = yaml.safe_load(f)["VectorDB"]

    db = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    print("Creating FTS index on document_chunks.chunk_text (idempotent) ...")
    db.cursor.execute(INDEX_SQL)
    db.conn.commit()
    print("Done. idx_document_chunks_fts is ready.")
    db.cleanup()


if __name__ == "__main__":
    main()
