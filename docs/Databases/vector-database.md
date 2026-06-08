# Vector Database
The vector database used to store measurement and document embeddings is a Postgres database with the pgvector extension. 

The vector database stores vectorized embeddings of document chunks (along with document metadata like type, observation date, patient demographic number, ...) and grouped measurements (some measurments of the same type are stored in separate entries, so they are grouped together to form a measurement chunk). These document and measurement chunks are stored in the `document_chunks` and `measurement_chunks` tables respectively. 


## Database Table Schema

### Document Table
```sql
CREATE TABLE document_chunks (
    -- Identity
    id BIGSERIAL PRIMARY KEY,

    demographic_no BIGINT NOT NULL,            -- patient id
    document_id BIGINT NOT NULL,               -- EMR document identifier
    document_type TEXT,                        -- document type (i.e. HOLTER, EST, ...)
    chunk_index INTEGER NOT NULL,              -- position within document

    -- Temporal context
    observation_date TIMESTAMP WITH TIME ZONE, -- date document was observed
    entry_date TIMESTAMP WITH TIME ZONE,       -- date document was uploaded to EMR

    -- Canonical content
    chunk_text TEXT NOT NULL,                  -- chunk text
    chunk_summary TEXT,                        -- LLM-generated clinical summary

    -- Embeddings (pgvector)
    embedding_raw VECTOR(768) NOT NULL,        -- vectorized chunk_text
    embedding_summary VECTOR(768),             -- vectorized chunk_summary

    -- Safety / provenance
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

    -- Constraints
    UNIQUE (document_id, chunk_index)
);
```

### Document Table Indexing
```sql
-- ANN index on raw embedding - primary semantic search target
CREATE INDEX idx_document_embedding_raw
    ON document_chunks
    USING hnsw (embedding_raw vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Only create this if you actually query embedding_summary separately
CREATE INDEX idx_document_embedding_summary
    ON document_chunks
    USING hnsw (embedding_summary vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- For filtering by demographic no
CREATE INDEX idx_document_demographic_no
    ON document_chunks (demographic_no);

-- Useful if you query by document (e.g. "all chunks for doc X")
CREATE INDEX idx_document_document_id
    ON document_chunks (document_id);

-- If you filter by date range alongside vector search
CREATE INDEX idx_document_observation_date
    ON document_chunks (observation_date);

CREATE INDEX idx_document_entry_date
    ON document_chunks (entry_date);

-- Document type filter
CREATE INDEX idx_document_type
    ON document_chunks (document_type);
```


### Measurement Table
```sql
CREATE TABLE measurement_chunks (
    -- Identity
    id BIGSERIAL PRIMARY KEY,

    demographic_no BIGINT NOT NULL,              -- patient_id
    measurement_ids TEXT NOT NULL,               -- grouped measurement ids
    measurement_type TEXT,                       -- measurement type (i.e. CARD, CATH, ...)
    chunk_index INTEGER NOT NULL,                -- chunk position (will likely be 0 for all measurements)

    -- Temporal context
    observation_date TIMESTAMP WITH TIME ZONE,   -- date the measurement was observed
    entry_date TIMESTAMP WITH TIME ZONE,         -- date the measurement was uploaded to EMR

    -- Canonical content
    chunk_text TEXT NOT NULL,                    -- chunk text

    -- Embeddings (pgvector)
    embedding_raw VECTOR(768) NOT NULL,          -- vectorized chunk_text

    -- Safety / provenance
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

    -- measurement_ids
    UNIQUE (measurement_ids, chunk_index)
);
```

### Measurement Table Indexing
```sql
-- ANN index on raw embedding — your primary semantic search target
CREATE INDEX idx_measurement_embedding_raw
    ON measurement_chunks
    USING hnsw (embedding_raw vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Almost certainly your most common filter
CREATE INDEX idx_measurement_demographic_no
    ON measurement_chunks (demographic_no);

-- Useful if you query by document (e.g. "all chunks for doc X")
CREATE INDEX idx_measurement_ids
    ON measurement_chunks (measurement_ids);

-- If you filter by date range alongside vector search
CREATE INDEX idx_measurement_observation_date
    ON measurement_chunks (observation_date);

CREATE INDEX idx_measurement_entry_date
    ON measurement_chunks (entry_date);

-- Document type filter
CREATE INDEX idx_measurement_type
    ON measurement_chunks (measurement_type);
```



## Setup
Follow this to setup a local Postgres database with the pgvector extension on Docker.

1. Install Docker Desktop here: https://www.docker.com/products/docker-desktop/
 * Can verify it has been installed using `docker --version` in command prompt.
2. Start PostgreSQL + pgvector container.
```bash
docker run -d --name pgvector -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=emr -p 5432:5432 -v pgvector_data:/var/lib/postgresql/data ankane/pgvector
```
 * You can change the user, password, database name, and port by changing the values above or just leave it as is.
 * This image will run PostgreSQL, has pgvector pre-installed, and is production-grade.
 * Can verify that this container is running using `docker ps`

3. You can connect to the database to use psql by typing
```bash
docker exec -it pgvector psql -U <user> -d <database_name>
```
If you left the default values, should be
```bash
docker exec -it pgvector psql -U postgres -d emr
```

4. Once inside psql, add the vector extension
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
Verify
```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

5. Navigate to the `..\AI-Scribe\src\FreeScribe.client\chatbot` directory and run `create_tables.py` to create the `document_chunks` and `measurement_chunks` tables.
 - You will need to add your vector database credentials to the config file (`..\AI-Scribe\src\FreeScribe.client\configs\config.yaml`) for this to work.
 - You could also manually copy-paste the tables + desired indexes above (the `create_tables.py` creates all indexes so manually copy-pasting will allow you to choose which ones you want)

6. Your vector database is now setup!

### Upserting Document and Measurement Chunks
1. Navigate to the `..\AI-Scribe\src\FreeScribe.client\chatbot` directory.
2. For uploading all documents and measurements for specific patients, use `patient_uploader.py`
 - Modify params at top of `patient_uploader.py` to choose which patients to upload, delay between upsertions, and batch size.
3. For uploading documents and measurements for a specific date or date range, use `daily_uploader.py`
 - This program was designed to be called by a batch file to automatically upload newly added documents to the EMR everyday.
4. If you want to add documents or measurements that are not in the EMR, look at `RAG\chunker.py` and `RAG\embedder.py` for chunking documents, creating embeddings, and upserting. 
