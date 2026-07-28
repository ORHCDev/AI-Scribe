import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from RAG.VectorSearch import VectorDB
from RAG.embedder import EmbeddingEngine
from AIConnect import AIConnect
from SeleniumOscarQuery import SOQ
import time
from datetime import datetime, timedelta

from SSHTunnel import OscarDB
from Oscar import Oscar
import yaml
import requests

# Compared date
# datetime.now() for today's date
# (datetime.now().date() - timedelta(days=1)) for previous day's date
# datetime(YYYY, MM, DD) for specific date
DATE = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
# Date operator for comparison
# '=' : will upload documents with same date as above
# '>' : will upload documents that have entry date > date above. '>=' for inclusive.
# '<' : will upload documents that have entry daet < date above. '<=' for inclusive.
DATE_OP = "="
# Delay between each uploaded chunk (in seconds).
DELAY = 5
# Vectorization batch size. How much of the chunk is vectorized at once. 
# Default for embedding model is 32. 
BATCH_SIZE = 8

def initialize_oscardb(config) -> SOQ | OscarDB:
    """
    Initializes connection to the Oscar EMR database.
    """
    # Oscar credentials
    oscar_login = config["OscarLogin"]
    user = oscar_login["user"]
    passw = oscar_login["passw"]
    pin = oscar_login["pin"]
    oscar_url = oscar_login["url"]
    oscar_version = oscar_login["version"]

    # Driver path
    driver_path = config["Selenium"]["geckodriver_path"]

    # Query choice
    query_choice = config["query_choice"]

    # Initialize Oscar Session
    oscar = Oscar(user, passw, pin, oscar_url, driver_path, headless=True, oscar_version=oscar_version)
    oscar.run()

    if query_choice == "ssh":
        # SSH Credentials
        ssh = config["SSH"]
        ssh_host = ssh["ssh_host"]
        ssh_port = ssh["ssh_port"]
        ssh_user = ssh["ssh_user"]
        ssh_password = ssh["ssh_passw"]
        db_host = ssh["db_host"]
        db_port = ssh["db_port"]
        local_bind_port = ssh["local_bind_port"]
        db_user = ssh["db_user"]
        db_password = ssh["db_passw"]
        db_name = ssh["db_name"]

        session = requests.session()
        oscar.pass_cookies(session)

        db_conn = OscarDB(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            session=session,
            oscar_url=oscar_url,
            db_host=db_host,
            db_port=db_port,
            local_bind_port=local_bind_port
        )
        db_conn.connect()
    else:
        db_conn = SOQ(user, passw, pin, oscar_url, driver_path, True)
        db_conn.run()

    oscar.cleanup()

    return db_conn


def initialize_vectordb(config) -> VectorDB:
    """
    Initializes connection to the vector database.
    """
    vdb_creds = config["VectorDB"]
    vector_db = VectorDB(
        host        = vdb_creds["host"],
        port        = vdb_creds["port"],
        dbname      = vdb_creds["dbname"],
        user        = vdb_creds["user"],
        password    = vdb_creds["password"]
    )

    return vector_db


def initialize_aiconn(config) -> AIConnect:
    """
    Initializes connection to the LLM.
    """
    return AIConnect(config["AIConnection"]["endpoint"])


if __name__ == "__main__":
    
    # Load credential info
    with open("./configs/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    oscar_db = None
    vector_db = None
    ai_conn = None
    
    try:
        oscar_db = initialize_oscardb(config)
        vector_db = initialize_vectordb(config)
        ai_conn = initialize_aiconn(config)


        embedder = EmbeddingEngine(oscar_db, vector_db, ai_conn, batch_size=BATCH_SIZE)
        
        print(f"Upserting Documents for {DATE}")
        embedder.upsert_documents(
            date=DATE, 
            date_op=DATE_OP, 
            delay=DELAY, 
            skip_exists=True, 
            summarize=False
        )

        time.sleep(10)
        print(f"Upserting measurements for {DATE}")
        embedder.upsert_measurements(
            date=DATE, 
            date_op=DATE_OP, 
            delay=DELAY, 
            skip_exists=True
        )


    finally:
        if oscar_db is not None:
            oscar_db.cleanup()
        if vector_db is not None:
            vector_db.cleanup()