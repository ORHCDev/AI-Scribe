from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser

@tool(
    category="medication",
    description=(
        "Returns the patient's current medications from the EMR measurement entries (type = 'MEDS'). "
        "The result contains the medication text entries and their observation dates for the most recent "
        "MEDS snapshot recorded for the given patient demographic number. "
        "Each row represents an active medication entry and includes the medication text and the date it was "
        "observed, as stored in the Oscar EMR measurements table. "
        "This tool is most relevant when answering questions about a patient's current treatment regimen, "
        "active medications, medication reconciliation, drug interactions, or confirming whether a patient is presently "
        "on a specific medication."
    ),
    context="Active and ongoing medications for a patient",
    parameters={
        "demo_no": "Patient demographic number used to identify the patient in the EMR",
    }
)
def get_current_medications(db_conn, demo_no : str):
    """
    Queries the Oscar EMR database for the patients current medication information.

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
        m.type AS "Type",
        m.dataField AS "Medication",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    JOIN (
        SELECT MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE demographicNo = {demo_no}
        AND type = 'MEDS'
    ) latest
        ON m.dateObserved = latest.maxDate
    WHERE m.demographicNo = {demo_no}
    AND m.type = 'MEDS'
    GROUP BY m.type, m.dataField, DATE(m.dateObserved)
    ORDER BY m.dateObserved DESC;
    """
    res = db_conn.query_database(query)
    return tr(
        label="Current Medications",
        send_to_ai=True,
        query_results=res, 
        save_results=res
    )

@tool(
    category="medication",
    description=(
        "Returns the patient's medication history from the EMR measurement entries (type = 'MEDS'). "
        "Results are ordered by most recent observation date first and include up to the 10 most recent medication "
        "entries. Each record corresponds to a medication entry and includes the medication text and the date it was "
        "observed, as stored in the Oscar EMR measurements table. "
        "This tool is most relevant when reviewing prior therapies, understanding medication changes over time, "
        "investigating adverse reactions, assessing treatment effectiveness, or answering questions about what medications "
        "a patient has taken in the past."
    ),
    context="Historical patient medications",
    parameters={
        "demo_no": "Patient demographic number used to identify the patient in the EMR",
    }
)
def get_medication_history(db_conn, demo_no : str):
    """
    Queries the Oscar EMR database for the patients past medication history information.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection to Oscar EMR

    demo_no : str
        String of numbers that makes up the patients demographic number

    Returns
    -------
    Dataframe containing the queried results
    """

    query = f"""
    SELECT
        m.type AS "Type",
        m.dataField AS "Medication",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    WHERE m.demographicNo = {demo_no}
    AND m.type = 'MEDS'
    GROUP BY m.type, m.dataField, DATE(m.dateObserved)
    ORDER BY m.dateObserved DESC
    LIMIT 10;
    """
    res = db_conn.query_database(query)
    return tr(
        label="Medication History",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )
    
@tool(
    category="medication",
    description=(
        "Returns medication records for a specific medication name for the given patient from the EMR measurement "
        "entries (type = 'MEDS'). The search performs a case-insensitive partial match against the medication text "
        "entry, allowing flexible matching even when naming varies across entries. Results are ordered by observation "
        "date in descending order and include up to the 10 most recent matching entries. Each row represents a "
        "medication entry and includes the medication text and the date it was observed. "
        "This tool is most relevant when determining whether a patient is or was ever prescribed a particular medication, "
        "checking medication continuity, reviewing historical use of a drug, or confirming prior exposure to a specific therapy."
    ),
    context="Medication history filtered by a specific drug name",
    parameters={
        "demo_no": "Patient demographic number used to identify the patient in the EMR",
        "drug_name": "Drug name or partial drug name to search for (brand, generic, or custom name)",
    }
)
def get_prescription_by_drug(db_conn, demo_no : str, drug_name : str):
    """
    Queries the Oscar EMR database for the patients past medication history information.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection to Oscar EMR

    demo_no : str
        String of numbers that makes up the patients demographic number

    drug_name : str
        Strig of characters that makes up the drug name

    Returns
    -------
    Dataframe containing the queried results
    """

    query = f"""
    SELECT
        m.type AS "Type",
        m.dataField AS "Medication",
        DATE(m.dateObserved) AS "Date Observed"
    FROM measurements m
    WHERE m.demographicNo = {demo_no}
    AND m.type = 'MEDS'
    AND LOWER(m.dataField) LIKE LOWER('%{drug_name}%')
    GROUP BY m.type, m.dataField, DATE(m.dateObserved)
    ORDER BY m.dateObserved DESC
    LIMIT 10;
    """
    res = db_conn.query_database(query)
    return tr(
        label=f"Prescription for {drug_name}",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )


@tool(
    category="medication",
    description=(
        "Returns a report of active patients who have medication entries matching one or more specified drug names "
        "within a defined recent time period. The tool searches medication-related measurement entries (type = 'MEDS') "
        "and aggregates medication text entries and observation dates for each patient. Results include patient identifiers "
        "(first and last name), provider number, medication entry text, and corresponding observation dates, grouped by patient. "
        "Only active patients are included, and only medication entries recorded on or after the calculated start date "
        "based on the provided period are considered. "
        "This tool is most relevant for population-level medication audits, cohort identification, quality improvement initiatives, "
        "clinical reporting, or identifying patients currently or recently documented as taking specific medications."
    ),
    context="Population-level lookup of patients associated with specific medications over a recent time window",
    parameters={
        "meds": "List of medication names or partial names to search for in medication measurement entries",
        "period": "Required. Time window to search within, expressed as a duration such as '6m', '30d', or '1y'",
    }
)
def medication_lookup(db_conn, meds : list[str], period : str):
    """
    Queries and returns a report of patients that are on the given medications.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    meds : list[str]
        List of medications to use to find patients that are on them.

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """

    date = period_parser(period)

    med_filter = " OR ".join(f"m.dataField LIKE '%{med}%'" for med in meds)

    print(f"MED FILTER: {med_filter}")

    query = f"""
    SELECT DISTINCT
        d.last_name,
        d.first_name,
        m.type,
        GROUP_CONCAT(CONCAT('new entry: ', m.dataField) ORDER BY m.dateObserved SEPARATOR '\n') AS medication_entries,
        GROUP_CONCAT(CONCAT('new entry: ', m.dateObserved) ORDER BY m.dateObserved SEPARATOR '\n') AS date_entries,
        d.provider_no
    FROM measurements m
    JOIN demographic d
        ON m.demographicNo = d.demographic_no
    WHERE m.type = 'MEDS'
    AND d.patient_status = 'AC'
    AND m.dateObserved >= '{date}'
    AND (
        {med_filter}
        )
    GROUP BY
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no,
        m.type
    ORDER BY
        d.last_name,
        d.first_name
    LIMIT 10;
    """

    res = db_conn.query_database(query)
    return tr(
        label=f"Patients' on at least one of {meds}",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )