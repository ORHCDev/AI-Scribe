from chatbot.Tools.Tool import tool, ToolReturn as tr


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
        "reviewing clinical data such as medications, documents, or encounters."
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




