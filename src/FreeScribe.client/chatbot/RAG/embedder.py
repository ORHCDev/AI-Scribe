from Tools.utils import pdf_image_to_text
from RAG.chunker import Chunker
import pandas as pd
from sentence_transformers import SentenceTransformer
import yaml
import time
import gc

SUMMARY_PROMPT = """
You are a clinical documentation assistant summarizing a fragment of an electronic medical record.

Your task is to produce a concise, factual summary of the clinically important information in the provided text.

Follow these rules strictly:
- Do NOT add interpretations, conclusions, or diagnoses not explicitly stated.
- Preserve uncertainty (e.g., "possible", "rule out", "cannot exclude").
- Preserve negations and negative findings.
- Retain all numeric values, units, dates, and times.
- Retain medication names, dosages, routes, and frequencies if present.
- Retain test names and key results.
- Retain symptoms and findings with their qualifiers.
- Do NOT remove temporal context or progression.
- Do NOT infer relationships or causality.
- Do NOT restate boilerplate, headers, or administrative text.

Output requirements:
- Use clear, compact sentences or bullet points.
- Use neutral clinical language.
- Do NOT exceed 120 tokens.
- If the text contains no clinically meaningful information, output: "No clinically relevant information in this chunk."
"""

class EmbeddingEngine:
    """
    Pulls documents and measurements from Oscar EMR, chunks them, creates embeddings 
    and uploads them to a database.
    """
    _model = None

    def __init__(
        self, 
        oscar_db, 
        vector_db, 
        ai_conn,
        model : str="abhinand/MedEmbed-base-v0.1", 
        desc_path : str=r".\RAG\measurement_descriptions.yaml",
        batch_size : int=8
    ):
        self.oscar_db = oscar_db
        self.vector_db = vector_db
        self.ai_conn = ai_conn
        self.batch_size = batch_size

        try:
            with open(desc_path, "r", encoding="utf-8") as f:
                self.descriptions = yaml.safe_load(f)
        except:
            self.descriptions = None

        if EmbeddingEngine._model is None:
            EmbeddingEngine._model = SentenceTransformer(model)
        self.model = EmbeddingEngine._model

        self.chunker = Chunker()

        # Measurement types
        self.mtypes_dict = {
            "CARD" : ["CARD", "CARD1"],
            "CATH" : ["CATH", "CATH1"],
            "ECG" : ["ECG", "ECGe"],
            "ECHO" : ["ECHO", "ECHO1", "ECHO2", "ECHOQ"],
            "CONC" : ["CONC"],
            "CS" : ["CS", "CS2", "CS3"],
            "EST" : ["EST"],
            "EXAM" : ["EXAM"],
            "FImp" : ["FImp"],
            "HOL" : ["HOL1", "HOL2", "HOL3", "HOL4"],
            "HOLT" : ["HOLT", "HOLT1", "HOLT2"],
            "HPI" : ["HPI", "HPIO", "HPIT"],
            "MEDS" : ["MEDS", "MEDS1"],
            "PLAN" : ["MPLAN", "PLAN"],
            "OTHE" : ["OTHE"],
            "RISK" : ["RISK"],
            "RV" : ["RV"],
            "SECHO" : ["SECHO", "SECHO1", "SECHOC", "SEIND", "SES", "SLAP"],
            "SOCH" : ["SOCH"],
            "THR" : ["THR"],
            "VA" : ["VA", "VA2"],
        }

        self.mtype_vals = []
        for val in self.mtypes_dict.values():
            self.mtype_vals += val

        self.mtype_str = "'" + "', '".join(self.mtype_vals) + "'"


    def _initialize_connections(self):
        pass


    def _read_measurements(
        self,
        patient_id : str | None = None,
        date : str | None = None,
        date_op : str = "="
    ):
        
        # Filters
        filters = []
        if patient_id:
            filters.append(f"AND demographicNo = '{patient_id}'")
        if date:
            filters.append(f"AND DATE(dateEntered) {date_op} '{date}'")
        filter_str = "\n".join(filters)

        query = f"""
        SELECT 
            id,
            type,
            demographicNo,
            providerNo,
            dataField,
            measuringInstruction,
            comments,
            DATE(dateObserved) as dateObserved,
            DATE(dateEntered) as dateEntered,
            appointmentNo
        FROM measurements
        WHERE type IN ({self.mtype_str})
            {filter_str}
        ORDER BY type, dateObserved;
        """

        res = self.oscar_db.query_database(query)

        if not res: return pd.DataFrame()

        df = pd.DataFrame(res)
        emb_df = df[['id', 'type', 'demographicNo', 'dataField', 'dateObserved', 'dateEntered']].copy()

        reverse_map = {v: k for k, vals in self.mtypes_dict.items() for v in vals}

        emb_df["type_group"] = emb_df["type"].map(reverse_map)

        emb_df = emb_df.drop_duplicates(subset=["type", "dateObserved", "dataField", "demographicNo"])

        results = (
            emb_df.groupby(["type_group", "dateObserved", "dateEntered", "demographicNo"])
            .agg({
                "dataField": "\n\n".join,
                "id": lambda x: "\n\n".join(x.astype(str))
            })
            .reset_index()
        )

        return results


    def upsert_measurements(
        self, 
        patient_id      : str | None = None, 
        date            : str | None = None,
        date_op         : str = "=",
        skip_exists     : bool = False,
        delay           : float = 0.5,
        collect_after   : int = 10
    ):
        """
        Inserts or updates grouped measurements from Oscar EMR to the vector database.
        Will read, group, vectorize, and then insert or update a measurement.

        Params
        ------
        patient_id : str | None
            Filter parameter, that if provided will filter and upsert only documents
            for this patient.

        date : str | None
            Filter parameter, that if provided will filter results to upsert only documents
            past or equal to the provided date. Date format must be 'YYYY-MM-DD'. 
            For example, if given date is '2024-01-01', will upsert all documents that have been 
            uploaded after '2024-01-01' (like '2024-01-02').

        date_op : str
            One of '=', '>', '<', '>=', '<=' that is used when comparing the EMR entry date with the
            passed date. For example, if given date is '2024-01-01' and date_op is '>', then will upsert
            all documents that have entry date > '2024-01-01'.

        delay : float
            Amount of delay to have between upserts.

        skip_exists : bool
            If True, will skip documents that already exist in the vector database.
        """

        exists_query = """
        SELECT EXISTS (
            SELECT 1
            FROM measurement_chunks
            WHERE measurement_ids = %s
        );
        """

        measurements = self._read_measurements(patient_id=patient_id, date=date, date_op=date_op)
        if measurements.empty:
            print(f"No measurements for {patient_id} | {date}")
            return 
        
        ctr = 1
        print(f"Found {len(measurements)} to upsert")
        for idx, row in measurements.iterrows():

            data = row["dataField"]
            obs_date = row["dateObserved"]
            type_group = row["type_group"]
            ids = row["id"]
            demo_no = row["demographicNo"]

            # Skip if already exists in vector database
            if skip_exists:
                self.vector_db.cursor.execute(exists_query, (ids,))
                exists = self.vector_db.cursor.fetchone()[0]
                if exists:
                    print(f"{ids} already has an entry, skipping")
                    continue


            # Append descriptions to make vector search better
            if self.descriptions:
                data = f"Type:{type_group}\nDate Observed:{obs_date}\nDescription:{self.descriptions[type_group]}\nContent:{data}"

            vector = self.model.encode(
                data, 
                normalize_embeddings=True, 
                batch_size=self.batch_size
            ).tolist()
            chunk = {
                "demographic_no"        : demo_no,
                "measurement_ids"       : ids,
                "measurement_type"      : type_group,
                "chunk_index"           : 0,
                "chunk_text"            : data,
                "embedding_raw"         : vector,
                "observation_date"      : obs_date,
                "entry_date"            : row["dateEntered"],
            }

            self.vector_db.insert_measurement_chunk(chunk.copy())

            if ctr % collect_after == 0:
                gc.collect()
            
            ctr += 1
            time.sleep(delay)


    def upsert_documents(
        self, 
        patient_id      : str | None = None, 
        date            : str | None = None,
        date_op         : str = '=',
        delay           : float = 0.5, 
        skip_types      : list[str]=[],
        skip_exists     : bool = False,
        summarize       : bool = False,
        collect_after   : int = 10
    ):
        """
        Inserts or updates documents from Oscar EMR to the vector database.
        Will OCR, chunk, vectorize, and then insert or update document. 

        Params
        ------
        patient_id : str | None
            Filter parameter, that if provided will filter and upsert only documents
            for this patient.

        date : str | None
            Filter parameter, that if provided will filter results to upsert only documents
            past or equal to the provided date. Date format must be 'YYYY-MM-DD'. 
            For example, if given date is '2024-01-01', will upsert all documents that have been 
            uploaded after '2024-01-01' (like '2024-01-02').

        date_op : str
            One of '=', '>', '<', '>=', '<=' that is used when comparing the EMR entry date with the
            passed date. For example, if given date is '2024-01-01' and date_op is '>', then will upsert
            all documents that have entry date > '2024-01-01'.

        delay : float
            Amount of delay to have between upserts.

        skip_types : List[str]
            Document types to be skipped.
            I.e. skip_types=['LAB'] will skip documents that are labeled with 'LAB'

        skip_exists : bool
            If True, will skip documents that already exist in the vector database.

        summarize : bool
            If True, will query LLM via ai_conn to summarize text chunk. This summary along with a vectorized
            version of it will be upserted (will slow down upsert speed by a bit).
        """
        # Filters
        filters = []
        if patient_id:
            filters.append(f"AND cd.module_id = '{patient_id}'")
        if date:
            filters.append(f"AND DATE(d.contentdatetime) {date_op} '{date}'")

        filter_str = "\n".join(filters)

        exists_query = """
        SELECT EXISTS (
            SELECT 1
            FROM document_chunks
            WHERE document_id = %s
        );
        """

        query = f"""
            SELECT 
                cd.document_no,
                cd.module_id AS patient_id,
                d.doctype,
                d.docdesc,
                d.observationdate,
                d.contentdatetime
            FROM ctl_document AS cd
            LEFT JOIN document AS d
            ON cd.document_no = d.document_no
            WHERE cd.module = "demographic"
                {filter_str}
            ORDER BY observationdate DESC
        """

        docs = self.oscar_db.query_database(query)
        print(f"Found {len(docs)} to upsert")
        # Iterate over returned documents
        for i, row in enumerate(docs):
            doc_no = row["document_no"]
            doc_type = row["doctype"]
            obs_date = row["observationdate"]
            entry_date = row["contentdatetime"]
            demo_no = row["patient_id"]

            # Skip if doc type is in to skip list 
            if doc_type in skip_types: 
                print(f"Skipping {doc_type}")
                continue

            # Skip if already exists in vector database
            if skip_exists:
                self.vector_db.cursor.execute(exists_query, (doc_no,))
                exists = self.vector_db.cursor.fetchone()[0]
                if exists:
                    print(f"{doc_no} already has entries, skipping")
                    continue


            # Read document text
            try:
                doc_bytes = self.oscar_db.get_doc_bytes(doc_no=doc_no)
                text = pdf_image_to_text(pdf_bytes=doc_bytes, last_page=4)
            except:
                print(f"Unable to read {doc_no}")
                continue

            # Chunk document
            chunks = self.chunker.chunk_medical_document(text)
            ctr = 1
            # Vectorize and upsert each chunk
            try:
                for idx, chunk in enumerate(chunks):
                    vector = self.model.encode(
                        chunk,
                        normalize_embeddings=True,
                        batch_size=self.batch_size
                    ).tolist()
                    time.sleep(delay)

                    # Summarize text chunk using LLM
                    summary = None
                    summary_vector = None
                    if summarize:
                        summary = self.ai_conn.send_message(chunk, pre_prompt=SUMMARY_PROMPT)
                        summary_vector = self.model.encode(
                            summary,
                            normalize_embeddings=True,
                            batch_size=self.batch_size
                        ).tolist()
                        time.sleep(delay)

                    data = {
                        "demographic_no"    : demo_no,
                        "document_id"       : doc_no,
                        "document_type"     : doc_type,
                        "chunk_index"       : idx,
                        "chunk_text"        : chunk,
                        "chunk_summary"     : summary,
                        "embedding_raw"     : vector,
                        "embedding_summary" : summary_vector,
                        "observation_date"  : obs_date,
                        "entry_date"        : entry_date,
                    }

                    self.vector_db.insert_document_chunk(data, commit=False)

                    if ctr % collect_after == 0:
                        gc.collect()

                    ctr += 1

                # Commit all chunks for this document at once so a killed run never leaves a partially-uploaded document
                self.vector_db.conn.commit()
            except Exception as e:
                print(f"Error upserting {doc_no}, rolling back: {e}")
                self.vector_db.conn.rollback()

            print(f"Completed {doc_no} | Docs done so far: {i+1}")




