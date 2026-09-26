from chatbot.Tools.Tool import tool, ToolReturn as tr
from utils.read_files import pdf_image_to_text

def get_patient_mh(db_conn, oscar, demo_no : str):
    query = f"""
    SELECT 
        cd.document_no,
        d.doctype,
        d.docdesc,
        d.observationdate
    FROM ctl_document AS cd
    LEFT JOIN document AS d
        ON cd.document_no = d.document_no
    WHERE cd.module = "demographic"
        AND cd.module_id = {demo_no}
    ORDER BY d.observationdate DESC;
    """

    res = db_conn.query_database(query)

    # Use default document types
    doc_names = ["DC summary", "CATH"]

    # Find most recent matching document of each requested type
    doc_nos = []
    doc_data = {}

    for doc in doc_names:
        for row in res:
            row_type = row.get("doctype")
            doc_no = row.get("document_no")
            obs_date = row.get("observationdate")

            if row_type and doc.lower() == row_type.lower():
                if doc_no not in doc_nos:
                    doc_nos.append(doc_no)
                    doc_data[doc_no] = (row_type, obs_date)
                    break

    text = ""

    # Extract document text
    for doc_no in doc_nos:
        try:
            pdf_bytes = oscar.get_document_bytes(doc_no)
            doc_text = pdf_image_to_text(
                pdf_bytes=pdf_bytes,
                last_page=3
            )

            doc_type, obs_date = doc_data[doc_no]

            text += (
                f"DOCUMENT TYPE: {doc_type}\n"
                f"OBSERVATION DATE: {obs_date}\n"
                f"{doc_text}\n"
            )

        except Exception as e:
            print(f"Error when reading text from {doc_no}: {e}")

    # Get most recent 0letter
    query = f"""
    SELECT
        fdid,
        fid,
        form_name,
        form_date,
        demographic_no
    FROM eform_data
    WHERE demographic_no = {demo_no}
      AND form_name LIKE '%letter%'
    ORDER BY form_date DESC
    LIMIT 1;
    """

    res = db_conn.query_database(query)

    if res:
        fdid = res[0]["fdid"]
        date = res[0]["form_date"]

        letter_text = oscar.get_0letter_text(fdid)

        text += (
            f"LETTER\n"
            f"LETTER DATE: {date}\n"
            f"{letter_text}\n"
        )

    return text

@tool(
    category="patientinfo",
    description="Summarizes a specific patient.",
    context="Summary of patient",
    parameters={
        "demo_no": "Patient demographic number used to uniquely identify the patient in the EMR"
    }
)
def get_patient_summary(db_conn, oscar, demo_no : str):
    text = get_patient_mh(db_conn, oscar, demo_no)
    return tr(
        label="Patient Summary",
        send_to_ai=True,
        query_results=text,
        save_results=text,
        followup_prompt="Summarize the following information into two sentences: {text}"
    )

@tool(
    category="patientinfo",
    description="Gets a specific patient's active cardiac issues.",
    context="Patient's cardiac issues",
    parameters={
        "demo_no": "Patient demographic number used to uniquely identify the patient in the EMR"
    }
)
def get_patient_cardiac_issues(db_conn, oscar, demo_no : str):
    text = get_patient_mh(db_conn, oscar, demo_no)
    return tr(
        label="Patient Summary",
        send_to_ai=True,
        query_results=text,
        save_results=text,
        followup_prompt=(
            """
            Extract the patient's active cardiac issues from the following text.
            Do not use any markdown formatting, bolding, or italics.
            Do not use asterisks (*) in the final output.
            
            {text}
            """
        )
    )

@tool(
    category="patientinfo",
    description="Gets a specific patient's full cardiac history.",
    context="Patient's cardiac history",
    parameters={
        "demo_no": "Patient demographic number used to uniquely identify the patient in the EMR"
    }
)
def get_patient_cardiac_history(db_conn, oscar, demo_no : str):
    text = get_patient_mh(db_conn, oscar, demo_no)
    return tr(
        label="Patient Summary",
        send_to_ai=True,
        query_results=text,
        save_results=text,
        followup_prompt=(
            """
            Extract the patient's full cardiac history from the following text.
            Do not use any markdown formatting, bolding, or italics.
            Do not use asterisks (*) in the final output.
            
            {text}
            """
        )
    )

@tool(
    category="patientinfo",
    description=(
        "Returns the complete demographic profile for a specific patient as recorded in the Oscar EMR demographic table. "
        "The result typically includes identifying and administrative fields such as the patient's name, date of birth, sex, "
        "contact information, address, health card or identifier fields, assigned provider number, patient status, and other "
        "registration-level attributes stored for the patient. Each row represents a single patient record matched by "
        "demographic number. "
        "This tool is most relevant when answering questions about who the patient is, confirming identity details, "
        "verifying demographic attributes, retrieving contact information, or establishing patient context prior to "
        "reviewing clinical data such as medications, documents, or encounters. "
    ),
    context="Patient demographic and registration-level information",
    parameters={
        "demo_no": "Patient demographic number used to uniquely identify the patient in the EMR"
    }
)
def get_patient_demographic(db_conn, demo_no : str):
    """
    Queries the Oscar EMR database for the patients demographic information.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection to Oscar EMR

    demo_no : str
        String of numbers that makes up the patients demographic number

    Returns
    -------
    Dataframe containing the queried results.
    """

    query = f"""
    SELECT *
    FROM demographic
    WHERE demographic_no = {demo_no}
    """
    res = db_conn.query_database(query)
    return tr(
        label="Demographic Information",
        send_to_ai=True,
        query_results=res,
        save_results=res,
    )


@tool(
    category="patientinfo",
    description=(
        "Returns information about the patient's assigned primary provider by joining the demographic record with the "
        "provider table. The result includes the provider's unique identifier, name, provider type, specialty, and "
        "available contact details such as phone number and email address. Each result represents the clinician or provider "
        "currently designated as responsible for the patient's care in the EMR. "
        "This tool is most relevant when determining who the patient's main provider is, routing clinical questions, "
        "understanding care ownership, coordinating follow-up, or answering administrative or workflow-related questions "
        "about provider responsibility."
    ),
    context="Primary care provider associated with a patient",
    parameters={
        "demo_no": "Patient demographic number used to identify the patient whose primary provider is being requested"
    }
)
def get_patient_primary_provider(db_conn, demo_no : str):
    """
    Queries and returns patient primary provider number.
    
    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection to Oscar EMR

    demo_no : str
        String of numbers that makes up the patients demographic number

    Returns
    -------
    Dataframe containing the queried results.
    """

    query = f"""
    SELECT
        p.provider_no,
        p.last_name,
        p.first_name,
        p.provider_type,
        p.specialty,
        p.phone,
        p.email
    FROM provider AS p
    LEFT JOIN demographic AS d
    ON p.provider_no = d.provider_no
    WHERE demographic_no = {demo_no};
    """

    res = db_conn.query_database(query)
    return tr(
        label="Primary Provider",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )




