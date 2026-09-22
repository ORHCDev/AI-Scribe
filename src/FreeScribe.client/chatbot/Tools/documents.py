from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import pdf_image_to_text
from datetime import datetime

import logging


@tool(
    category="documents",
    description=(
        "Searches a patient's clinical documents by content and/or type using a direct "
        "database full-text search (no vector similarity), and returns the matching document "
        "text with its type and date. Provide `query` with clinical keywords to find documents "
        "that mention them (e.g. 'angiogram', 'ejection fraction', 'atrial fibrillation'), "
        "and/or `doc_type` to restrict to a kind of document (e.g. 'discharge summary', "
        "'consult', 'echo report'). Leave `query` empty to list the most recent documents. "
        "Most relevant when the user asks what a report / consult note / discharge summary / "
        "angiogram says, or to pull up a specific document."
    ),
    context="Here is the content of the matching patient document(s):",
    parameters={
        "demo_no": "Patient's demographic number",
        "query": "Clinical keywords to search document text for (optional; empty = most recent documents)",
        "doc_type": "Preferred document type, e.g. 'discharge summary' (optional; used as a ranking hint on the content search, NOT a hard filter, so mislabeled documents can still be found by content)",
        "limit": "Maximum number of documents to return. Defaults to 5.",
    },
)
def get_documents(vec_search, demo_no : str, query : str = "", doc_type : str = "", limit : int = 5):
    """
    SQL/FTS document retrieval over the pre-parsed document_chunks table (the
    non-RAG path). Searches document CONTENT via Postgres full-text search plus
    optional type filter, so a document mislabeled in Oscar can still be found by
    what it actually says. Does not re-OCR and does not use vector similarity.
    """
    rows = vec_search.ragdb.fetch_documents(
        patient_id=str(demo_no),
        query=query or None,
        doc_type=doc_type or None,
        top_k=int(limit),
        to_dict=True,
    )

    text = ""
    for r in rows:
        text += (
            f"DOCUMENT TYPE: {r['document_type']}\n"
            f"Observation Date: {r['observation_date']}\n\n"
            f"{r['full_text']}\n\n"
        )
    if not text:
        text = "No matching documents were found for this patient."

    label = "Document search"
    if doc_type:
        label += f" [{doc_type}]"
    if query:
        label += f": {query}"
    return tr(
        label=label,
        send_to_ai=True,
        query_results=text,
        save_results=text,
    )


"""@tool(
    category="documents",
    description=(
        "Retrieves and returns OCR-extracted text from a patient's most recently uploaded "
        "clinical documents, ordered by recency. The output is a concatenated text stream "
        "that may include document type, observation date, content date, and scanned clinical "
        "content such as consult notes, test results, referral letters, or imaging reports. "
        "This tool is most relevant when the user asks about recent findings, recent reports, "
        "latest documentation, or wants a high-level summary of newly added patient documents."
    ),
    context="Here is the scanned text from the most recent documents, provide a concise summary:",
    parameters={
        "demo_no": "Patient's demographic number",
        "limit": "Maximum number of recent documents to retrieve and scan"
    }
)"""
def get_recent_documents(db_conn, demo_no : str, limit = 5):
    """
    Queries the Oscar EMR database to find and scan a patient's most recent documents.

    Params
    ------
    db_conn : SOQ | OscarDB
        Oscar EMR database connection

    demo_no : str
        Patient's demographic number

    limit : int
        Number of documents to scan

    Returns
    -------
    The concatenation of OCRd text from scanned patient documents.
    """
    
    query = f"""
    SELECT 
        cd.module,
        cd.module_id,
        cd.document_no,
        d.doctype,
        d.docfilename,
        d.contenttype,
        d.docClass,
        d.docSubClass,
        d.observationdate,
        d.contentdatetime
    FROM ctl_document AS cd
    LEFT JOIN document AS d
    ON cd.document_no = d.document_no
    WHERE cd.module = "demographic"
        AND cd.module_id = {demo_no}
    ORDER BY document_no DESC
    LIMIT {int(limit)};
    """

    res = db_conn.query_database(query)
    logging.info(f"'[Recent Document]': {res}")

    text = ""
    for row in res:
        doc_no = row.get("document_no")
        doc_name = row.get("docfilename")
        doc_type = row.get("doctype")
        doc_observationdate = row.get("observationdate")
        doc_contentdatetime = row.get("contentdatetime")
        if doc_no:
            pdf_bytes = db_conn.get_doc_bytes(doc_no=doc_no)
            text += f"DOCUMENT TYPE:{doc_type}\nObservation Date:{doc_observationdate}\nContent Date Time:{doc_contentdatetime}\n\n{pdf_image_to_text(pdf_bytes=pdf_bytes, last_page=3)}\n"

    return tr(
        label="Scan of Recent Documents",
        send_to_ai=True,
        query_results=text,
        save_results=text
    )



"""@tool(
    category="documents",
    description=(
        "Retrieves OCR-extracted text from a specific patient document based on document type "
        "or description, optionally narrowed to a date closest to a user-specified time. "
        "The returned text includes scanned clinical content along with associated metadata "
        "such as observation date and content timestamp. "
        "This tool is most relevant when the user explicitly asks about a particular document "
        "type (e.g., echo report, referral letter, stress test, consult note) or references "
        "information from a specific report or date."
    ),
    context="Here is the scanned text from the specified document:",
    parameters={
        "demo_no": "Patient's demographic number",
        "doc_type": "Document type or description keyword to search for (e.g., 'Echo', 'Referral')",
        "date": (
            "Optional. Date in YYYY-MM-DD format used to select the document closest in time. "
            "Only include if the user specifies a date."
        )
    }
)"""
def get_specific_document(db_conn, demo_no : str, doc_type : str, date : str = ""):
    """
    Fetches and returns the scanned text from a specified document.
    """
    doc_type = doc_type.strip()
    print(f"Doctype: {doc_type}")
    print(f"Demo: {demo_no}")

    query = f"""
    SELECT 
        cd.module,
        cd.module_id,
        cd.document_no,
        d.doctype,
        d.docdesc,
        d.docfilename,
        d.contenttype,
        d.docClass,
        d.docSubClass,
        d.observationdate,
        d.contentdatetime
    FROM ctl_document AS cd
    LEFT JOIN document AS d
    ON cd.document_no = d.document_no
    WHERE cd.module = "demographic"
        AND cd.module_id = {demo_no}
        AND (d.doctype LIKE "%{doc_type}%" OR d.docdesc LIKE "%{doc_type}%")
    ORDER BY document_no DESC
    """

    res = db_conn.query_database(query)
    print(res)
    logging.info(f"'[Specific Document]': {res}")

    if not date:
        row = res[0]
    else:
        target_dt = datetime.strptime(date, "%Y-%m-%d")
        date_dts = [datetime.strptime(d["observationdate"], "%Y-%m-%d") for d in res]

        closest = min(date_dts, key=lambda d: abs(d - target_dt))
        closest = closest.strftime("%Y-%m-%d")

        row = [r for r in res if r["observationdate"] == closest][0]
        
    print(row)
    text = ""
    #for row in rows:
    doc_no = row.get("document_no")
    doc_name = row.get("docfilename")
    doc_type = row.get("doctype")
    doc_observationdate = row.get("observationdate")
    doc_contentdatetime = row.get("contentdatetime")
    if doc_no:
        pdf_bytes = db_conn.get_doc_bytes(doc_no=doc_no)
        text += f"Observation Date:{doc_observationdate}\nContent Date Time:{doc_contentdatetime}\n\n{pdf_image_to_text(pdf_bytes=pdf_bytes, last_page=3)}\n"

    return tr(
        label=f"Scan of {doc_type} Document",
        send_to_ai=True,
        query_results=text,
        save_results=text
    )
"""
@tool(
    category="documents",
    description=(
        "Retrieves and returns structured or scanned content from a specific electronic form "
        "(eForm) completed for a patient. The results may include form responses, timestamps, "
        "and associated clinical data depending on form structure. "
        "This tool is most relevant when the user asks about intake forms, questionnaires, "
        "risk assessments, consent forms, or named eForms completed by the patient."
    ),
    context="Here is the content from the specified patient eForm:",
    parameters={
        "demo_no": "Patient's demographic number",
        "eform_name": "Name or partial name of the eForm to retrieve"
    }
)"""
def get_specific_eform(db_conn, demo_no : str, eform_name : str):
    pass