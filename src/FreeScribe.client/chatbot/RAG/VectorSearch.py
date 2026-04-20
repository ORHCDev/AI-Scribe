import psycopg2
from sentence_transformers import SentenceTransformer, CrossEncoder
from chatbot.Tools.Tool import ToolEmbeddings
from datetime import datetime, timezone
from dataclasses import dataclass
import numpy as np
import gc


class VectorDB:
    def __init__(self, host, port, dbname, user, password):

        # Connect to database
        self.conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password
        )
        self.cursor = self.conn.cursor()

        
    def cleanup(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    
    def search(
        self, 
        table_name      : str,
        columns         : list[str],
        vector_col      : str,
        query_vec       : np.ndarray[786] | list[786], 
        patient_filter  : dict[str, str] | None=None, 
        date_filter     : dict[str, str] | None=None,
        top_k           : int=5,
        to_dict         : bool=False
    ):
        """
        Searches a table in the vector database filtering by patient and date if provided.

        Params
        ------
        table_name : str
            Name of table in database to search.

        columns : list[str]
            List of columns to include in the output.

        vector_col : str
            Name of the column that stores the vector embedding.

        query_vec : np.ndarray[786] | list[786]
            Query vector that is used to search the database. 

        patient_filter : dict[str, str] | None
            Requires a dictionary of the format:
            "{
                'column' : [Column in table that stores patient id],
                'value'  : [Value to filter by]
            }"
            
            For example:
            "{
                'column' : 'demographic_no',
                'value'  : '4'
            }"

        date_filter : dict[str, str] | None
            Requires a dictionary of the format:
            "{
                'column' : [Column in table that stores patient id],
                'value'  : [Date to filter by in format 'YYYY-MM-DD'],
                'delta'  : [Optional (int). Can include to search around the provided date. I.e. delta of 3 will include dates 3 days below and above provided date]
            }"

            For example:
            "{
                'column' : 'observation_date',
                'value'  : '2024-01-01',
            }"

            Can include the optional date delta field that is used to include x dates above and below that provided date string.
            For example, if date is '2024-01-04' and date delta is 3, then will filter for dates
            between '2024-01-01' and '2024-01-07' (inclusive). Date delta of 0 is exact date and is default. 

        top_k : int
            Number of results to return.

        to_dict : bool
            If True, will return dictionary rows where the keys are the given columns.

        Returns
        -------
        Returns a list of tuples, where each tuple is a row in in same order as given columns with
        the last value being the vector distance. If to_dict is True, will return a list of dictionaries,
        where the keys are the passed columns and the values are the tuple values. 
        """

        # If ndarray convert to list
        if type(query_vec) == np.ndarray:
            query_vec = query_vec.tolist()

        # Explicitly cast as a string
        query_vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"  

        # Create filter strings for filtering table
        filters = []
        if patient_filter is not None:
            if patient_filter["value"] is not None:
                filters.append(
                    f"{patient_filter['column']} = {patient_filter['value']}"
                )
        if date_filter is not None:
            if date_filter["value"] is not None:
                filters.append(
                    f"{date_filter['column']} = '{date_filter['value']}'"
                )
        filter_str = ""
        if filters:
            filter_str = "WHERE " + " \nAND ".join(filters)
        
        column_str = ",\n".join(columns)

        # Create SQL query
        sql = f"""
        SELECT 
            {column_str},
            {vector_col} <=> '{query_vec_str}'::vector AS distance
        FROM {table_name}
        {filter_str}
        ORDER BY distance
        LIMIT {top_k};
        """

        # Execute query 
        self.cursor.execute(sql)
        res = self.cursor.fetchall()

        if to_dict:
            # Convert tuple rows to dictionary rows
            rows = []
            columns.append("score")
            # Iterate over rows
            for r in res:
                row = {}
                # Store col : val in dict
                for col, val in zip(columns, r):
                    row[col] = val
                # Append row
                rows.append(row)
            return rows
        else:
            # Return tuple rows
            return res


    def document_search(
        self, 
        query_vec   : np.ndarray[768] | list[768], 
        patient_id  : str | None=None, 
        date        : str | None=None,
        date_delta  : int=0,
        top_k       : int=5,
        to_dict     : bool=False
    ):
        """
        Searches the document table in the vector database filtering by patient_id and date if provided.

        Params
        ------
        query_vec : np.ndarray[768] | list[768]
            Query vector that is used to search the database. 

        patient_id : str | None
            Patient's demographic number (id) for filtering database.

        date : str | None
            Date string in format 'YYYY-MM-DD' for filtering database.

        date_delta : int 
            Date delta that is used to include x dates above and below that provided date string.
            For example, if date is '2024-01-04' and date delta is 3, then will filter for dates
            between '2024-01-01' and '2024-01-07' (inclusive). Date delta of 0 is exact date. 

        top_k : int
            Number of results to return.

        to_dict : bool
            If True, will return dictionary rows instead of tuple rows. 

        Returns
        -------
        Returns a list of tuples, where each tuple is a row in format:
            (document_id, document_type, observation_date, chunk_text, chunk_summary, score) 
        """
        cols = ['document_id', 'document_type', 'demographic_no', 'observation_date', 'chunk_text']
        res = self.search(
            table_name     = "document_chunks",
            columns        = cols,
            vector_col     = 'embedding_raw',
            query_vec      = query_vec,
            patient_filter = {'column': 'demographic_no', 'value': patient_id},
            date_filter    = {'column': 'observation_date', 'value': date, 'delta': date_delta},
            top_k          = top_k,
            to_dict        = to_dict
        )

        return res



    def measurement_search(
        self, 
        query_vec   : np.ndarray[768] | list[768], 
        patient_id  : str | int | None=None,
        date        : str | None=None,
        date_delta  : int=3,
        top_k       : int=5,
        to_dict     : bool=False
    ):
        """
        Searches the document table in the vector database filtering by patient_id and date if provided.

        Params
        ------
        query_vec : np.ndarray[768] | list[768]
            Query vector that is used to search the database. 

        patient_id : str | None
            Patient's demographic number (id) for filtering database.

        date : str | None
            Date string in format 'YYYY-MM-DD' for filtering database.

        date_delta : int 
            Date delta that is used to include x dates above and below that provided date string.
            For example, if date is '2024-01-04' and date delta is 3, then will filter for dates
            between '2024-01-01' and '2024-01-07' (inclusive). Date delta of 0 is exact date. 

        top_k : int
            Number of results to return.

        to_dict : bool
            If True, will return dictionary rows instead of tuple rows. 

        Returns
        -------
        Returns a list of tuples, where each tuple is a row in format:
            ('measurement_ids', 'measurement_type', 'demographic_no', 'observation_date', 'chunk_text') 
        Or a list of dictionaries if to_dict is True. 
        """
        
        cols = ['measurement_ids', 'measurement_type', 'demographic_no', 'observation_date', 'chunk_text']
        res = self.search(
            table_name     = "measurement_chunks",
            columns        = cols,
            vector_col     = 'embedding_raw',
            query_vec      = query_vec,
            patient_filter = {'column': 'demographic_no', 'value': patient_id},
            date_filter    = {'column': 'observation_date', 'value': date, 'delta': date_delta},
            top_k          = top_k,
            to_dict        = to_dict
        )

        return res


    def insert_measurement_chunk(self, chunk):
        query = """
        INSERT INTO measurement_chunks (
            demographic_no,
            measurement_ids,
            measurement_type,
            chunk_index,
            observation_date,
            entry_date,
            chunk_text,
            embedding_raw
        ) VALUES (
            %(demographic_no)s,
            %(measurement_ids)s,
            %(measurement_type)s,
            %(chunk_index)s,
            %(observation_date)s,
            %(entry_date)s,
            %(chunk_text)s,
            %(embedding_raw)s::vector
        )
        ON CONFLICT (measurement_ids, chunk_index)
            DO UPDATE SET
                demographic_no    = EXCLUDED.demographic_no,
                measurement_type  = EXCLUDED.measurement_type,
                observation_date  = EXCLUDED.observation_date,
                entry_date        = EXCLUDED.entry_date,
                chunk_text        = EXCLUDED.chunk_text,
                embedding_raw     = EXCLUDED.embedding_raw,
                updated_at        = now()
        RETURNING id;
        """

        self.cursor.execute(query, chunk)
        row_id: int = self.cursor.fetchone()[0]
        self.conn.commit()
        print("Upserted measurement chunk row id=%d", row_id)
        return row_id


    def insert_document_chunk(self, chunk):
        query = """
        INSERT INTO document_chunks (
            demographic_no,
            document_id,
            document_type,
            chunk_index,
            observation_date,
            entry_date,
            chunk_text,
            chunk_summary,
            embedding_raw,
            embedding_summary
        ) VALUES (
            %(demographic_no)s,
            %(document_id)s,
            %(document_type)s,
            %(chunk_index)s,
            %(observation_date)s,
            %(entry_date)s,
            %(chunk_text)s,
            %(chunk_summary)s,
            %(embedding_raw)s::vector,
            %(embedding_summary)s::vector
        )
        ON CONFLICT (document_id, chunk_index)
            DO UPDATE SET
                demographic_no    = EXCLUDED.demographic_no,
                document_type     = EXCLUDED.document_type,
                observation_date  = EXCLUDED.observation_date,
                entry_date        = EXCLUDED.entry_date,
                chunk_text        = EXCLUDED.chunk_text,
                chunk_summary     = EXCLUDED.chunk_summary,
                embedding_raw     = EXCLUDED.embedding_raw,
                embedding_summary = EXCLUDED.embedding_summary,
                updated_at        = now()
        RETURNING id;
        """

        self.cursor.execute(query, chunk)
        row_id: int = self.cursor.fetchone()[0]
        self.conn.commit()
        print("Upserted document chunk row id=%d", row_id)
        return row_id


    def create_document_table(self):
        table_query = """
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
        """

        # Indexes
        idx1 = """
        CREATE INDEX idx_document_embedding_raw
            ON document_chunks
            USING hnsw (embedding_raw vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """
        idx2 = """
        CREATE INDEX idx_document_embedding_summary
            ON document_chunks
            USING hnsw (embedding_summary vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """
        idx3 = """
        CREATE INDEX idx_document_demographic_no
            ON document_chunks (demographic_no);
        """
        idx4 = """
        CREATE INDEX idx_document_document_id
            ON document_chunks (document_id);
        """
        idx5 = """
        CREATE INDEX idx_document_observation_date
            ON document_chunks (observation_date);
        """
        idx6 = """
        CREATE INDEX idx_document_entry_date
            ON document_chunks (entry_date);
        """
        idx7 = """
        CREATE INDEX idx_document_type
            ON document_chunks (document_type);
        """
        indexes = [idx1, idx2, idx3, idx4, idx5, idx6, idx7]


        # Create table
        self.cursor.execute(table_query)
        self.conn.commit()

        # Add indexes
        for idx in indexes:
            self.cursor.execute(idx)
        self.conn.commit()


    def create_measurement_table(self):
        table_query = """
        CREATE TABLE measurement_chunks (
            -- Identity
            id BIGSERIAL PRIMARY KEY,

            demographic_no BIGINT NOT NULL,              -- demographic / MRN surrogate
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
        """
        # Indexes
        idx1 = """
        CREATE INDEX idx_measurement_embedding_raw
            ON measurement_chunks
            USING hnsw (embedding_raw vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """
        idx2 = """
        CREATE INDEX idx_measurement_demographic_no
            ON measurement_chunks (demographic_no);
        """
        idx3 = """
        CREATE INDEX idx_measurement_ids
            ON measurement_chunks (measurement_ids);
        """
        idx4 = """
        CREATE INDEX idx_measurement_observation_date
            ON measurement_chunks (observation_date);
        """
        idx5 = """
        CREATE INDEX idx_measurement_entry_date
            ON measurement_chunks (entry_date);
        """
        idx6 = """
        CREATE INDEX idx_measurement_type
            ON measurement_chunks (measurement_type);
        """
        indexes = [idx1, idx2, idx3, idx4, idx5, idx6]


        # Create table
        self.cursor.execute(table_query)
        self.conn.commit()

        # Add indexes
        for idx in indexes:
            self.cursor.execute(idx)
        self.conn.commit()



class VectorSearch:

    _model = None
    _cross_encoder = None

    def __init__(
        self, 
        ragdb : VectorDB, 
        tool_embds : ToolEmbeddings, 
        embedding_model : str="abhinand/MedEmbed-base-v0.1"
                 
    ):
        self.ragdb = ragdb
        self.tool_embds = tool_embds

        if VectorSearch._model is None:
            VectorSearch._model = SentenceTransformer(embedding_model)
        
        if VectorSearch._cross_encoder is None:
            VectorSearch._cross_encoder = CrossEncoder("ncbi/MedCPT-cross-encoder")

        self.model = VectorSearch._model
        self.cross_encoder = VectorSearch._cross_encoder


    def cleanup(self):
        if self.ragdb:
            self.ragdb.cleanup()
            self.ragdb = None


    def tool_search(self, query_vec=None, query : str | None=None, top_k : int=3):
        """
        Performs a vector search on the tool embeddings, return the top_k results.

        Params
        ------
        query : str
            Search query.

        top_k : int
            Number of results to return (default is 3).
        """
        if query_vec is None:
            query_vec = self.model.encode(query)
        res = self.tool_embds.search_tools(query_vec, top_k=3)
        return res
    

    def ragdb_search(
        self, 
        query_vec=None, 
        query : str | None=None, 
        patient_id : str | None=None,
        date : str | None=None, 
        top_k : int=3, 
        batch_size : int=8,
        date_delta : int=3,
        to_dict : bool=False,
    ):
        """
        Performs a vector search on the Postgres DB that holds the vectoriced document embeddings.

        Params
        ------
        query : str
            Search query.

        patient_id : str
            String of digits that represents patient's id in the database. Used to filter documents
            for more relevant return results.

        top_k : int
            Number of results to return (default is 3).
        """
        if query_vec is None:
            query_vec = self.model.encode(query, batch_size=batch_size)
        docs = self.ragdb.document_search(query_vec, patient_id=patient_id, date=date, top_k=top_k, to_dict=to_dict)
        measurements = self.ragdb.measurement_search(query_vec, patient_id=patient_id, date=date, top_k=top_k, to_dict=to_dict)
        return (docs, measurements)


    def search(
        self, 
        query : str, 
        patient_id : str | None=None, 
        date : str | None=None,
        top_k : int=3, 
        batch_size : int=8,
        to_dict : bool = False
    ):
        """
        Performs a vector search on the tool embeddings and Postgres DB that holds the 
        vectoriced document embeddings.

        Params
        ------
        query : str
            Search query.

        patient_id : str
            String of digits that represents patient's id in the database. Used to filter documents
            for more relevant return results.

        top_k : int
            Number of results to return (default is 3).
        """
        query_vec = self.model.encode(query, batch_size=batch_size)
        tool_res = None
        if self.tool_embds:
            tool_res = self.tool_search(
                query_vec=query_vec, 
                top_k=top_k
            )
        db_res = self.ragdb_search(
            query_vec=query_vec, 
            patient_id=patient_id, 
            date=date,
            top_k=top_k,
            to_dict=to_dict
        )

        return {
            "tools" : tool_res,
            "documents" : db_res[0],
            "measurements" : db_res[1],
        }
    


    def _normalize_scores(self, scores : list[float], method : str="log") -> np.ndarray:
        """
        Normalizes scores using log scaling or min-max scaling

        Params
        ------
        scores : list[float]
            Scores to be normalized.

        method : str
            Method to use: 
                - 'log' for log scaling
                - 'min-max' for min-max scaling

        Returns
        -------
        Returns a np.ndarray of normalized scores.
        """
        if method == "log":
            return np.log1p(scores) / np.max(np.log1p(scores))
        else:
            s = np.array(scores)
            return (s - s.min()) / (s.max() - s.min())


    def _days_old(self, date : datetime) -> int:
        """Calulates how many days away the given date is from today"""
        now = datetime.now(timezone.utc)
        return (now - date).days


    def _recency_weight(self, age_days : int, tau : float=365*3, method : str='recent') -> np.float64:
        """
        Gives a score based on how old (in days) the document is.

        Params
        ------
        age_days : int
            How old something is from today in days.

        tau : float
            Controls how fast things decay. Larger tau = weaker recency bias.

        method : str
            Method of recency weighing:
             - 'recent' will weigh dates higher if newer.
             - 'old' will weigh dates higher if older. 

        Returns
        -------
        Returns a score based on how old/recent it is. 
        """
        if method == 'recent':
            return np.exp(-age_days / tau)
        else:
            return 1 - np.exp(-age_days / tau)


    def _multiplicative_boost(self, scores, date_weights, beta = 0.2, method = 'mult'):
        """
        Applies a multiplicative boost to the given scores based on the date_weights.

        Params
        ------
        scores : list[float]
            List of scores.

        date_weights : list[float]
            List of date_weight scores.

        beta : float
            Multiplicative scaler.

        method : str
            One of:
             - 'mult' for linear multiplicative boost
             - 'exp' for exponential boost
        """
        rescored = []
        if method == "exp":
            for s, dw in zip(scores, date_weights):
                rescored.append(
                    s * np.exp(beta * dw)
                )
        else:
            for s, dw in zip(scores, date_weights):
                rescored.append(
                    s * (1 + beta * dw)
                )

        return rescored


    def date_rank(
        self, 
        query           : str, 
        docs            : list[dict],
        text_key        : str, 
        date_key        : str,
        recency_method  : str = 'recent', 
        norm_method     : str = 'log',
        mult_method     : str = 'exp',
        beta            : float = 0.2,
        batch_size      : int = 8,
        to_dict         : bool = False
    ):
        """
        Ranks the documents and then re-scores based on date relevance.
        """

        # Rank documents
        ranked = self.rank(query, docs, key=text_key, batch_size=batch_size)

        # Get scores and recency weights
        scores = []
        recency_weights = []
        original_rank = []
        for idx, r in enumerate(ranked):
            scores.append(r[0])
            days_old = self._days_old(r[1][date_key])
            recency_weights.append(
                self._recency_weight(days_old, method=recency_method)
            )
            original_rank.append(idx)

        # Normalize
        norm_scores = self._normalize_scores(scores, method=norm_method)

        # Apply multiplicative boost
        boosted_scores = self._multiplicative_boost(
            scores       =norm_scores,
            date_weights =recency_weights,
            beta         =beta,
            method       =mult_method
        )

        # Combine with metadata
        ctr = 0
        combined = []
        for norm, boost, orig, rank in zip(norm_scores, boosted_scores, original_rank, ranked):
            if to_dict:
                combined.append(
                    {
                        "norm" : norm,
                        "boost" : boost,
                        "orig" : orig,
                        "orig score" : rank[0],
                        "metadata" : rank[1]
                    }
                )
            else:
                combined.append(
                    (boost, rank[1])
                )

        reranked = sorted(
            combined, 
            key=lambda x: x[0], 
            reverse=True
        )

        return combined


    def rank(
        self, 
        query       : str, 
        docs        : list[dict], 
        key         : str, 
        batch_size  : int = 8
    ):
        """
        Ranks given documents on how similar they are to the given query.

        Params
        ------
        query : str
            Query string.

        docs : list[dict]
            List of dictionaries where one element contains the text that is to be compared with the query string.

        key : str
            Dictionary key that maps to the document text.

        batch_size : int, Optional
            Batch size for encoding.
        """
        # Prepare pairs for scoring
        pairs = [(query, doc[key]) for doc in docs]

        # Score each document for relevance
        scores = self.cross_encoder.predict(pairs, batch_size=batch_size)

        # Sort by score (descending)
        reranked_docs = sorted(
            zip(scores, docs), 
            key=lambda x: x[0], 
            reverse=True
        )

        # print("Reranked Documents:")
        # for score, doc in reranked_docs:
        #     print(score, doc)

        return reranked_docs


