from RAG.VectorSearch import VectorDB
import yaml

# Load credential info
with open(r"..\configs\config.yaml", "r") as f:
    config = yaml.safe_load(f)

vdb_creds = config["VectorDB"]
vector_db = None
try:
    vector_db = VectorDB(
        host        = vdb_creds["host"],
        port        = vdb_creds["port"],
        dbname      = vdb_creds["dbname"],
        user        = vdb_creds["user"],
        password    = vdb_creds["password"]
    )


    vector_db.create_document_table()
    vector_db.create_measurement_table()

finally:
    if vector_db is not None:
        vector_db.cleanup()