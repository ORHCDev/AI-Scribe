from chatbot.Tools.Tool import tool, ToolReturn as tr
from datetime import datetime
from chatbot.Tools.utils import period_parser


@tool(
    category="appointments",
    description=(
        "Returns a list of all future-scheduled appointments for a specific patient, "
        "filtered to appointments occurring on or after the current date. "
        "Each result typically includes appointment date, time, provider, location, "
        "status, and appointment type. "
        "This tool is most relevant when answering questions about a patient's "
        "next visits, upcoming care plans, scheduling reminders, or near-term follow-up."
    ),
    context="Here are the patients upcoming appointments, summarize them in a concise format:",
    parameters={
        "demo_no": "Patient demographic number"
    }
)
def get_upcoming_appointments(db_conn, demo_no : str):
    """
    Queries the Oscar EMR database for a patient's upcoming appointments.
    """

    today = datetime.today().strftime("%Y-%m-%d")

    query = f"""
    SELECT *
    FROM appointment
    WHERE demographic_no = {demo_no}
      AND appointment_date >= '{today}'
    """

    res = db_conn.query_database(query)
    return tr(
        label="Upcoming Appointments",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )



@tool(
    category="appointments",
    description=(
        "Returns a limited history of a patient's past appointments that occurred "
        "before the current date, ordered by recency. "
        "Results typically include appointment dates, providers, visit statuses, "
        "and appointment types. "
        "This tool is relevant when summarizing prior visits, reviewing past care, "
        "understanding visit frequency, or providing historical context for current complaints."
    ),
    context="Here are the patients past appointments, summarize them in a concise format:",
    parameters={
        "demo_no": "Patient demographic number"
    }
)
def get_appointment_history(db_conn, demo_no : str):
    """
    Queries the Oscar EMR database for a patient's past appointments.
    """

    today = datetime.today().strftime("%Y-%m-%d")

    query = f"""
    SELECT *
    FROM appointment
    WHERE demographic_no = {demo_no}
      AND appointment_date < '{today}'
    LIMIT 10;
    """

    res = db_conn.query_database(query)
    return tr(
        label="Appointment History",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )

@tool(
    category="appointments",
    description=(
        "Returns a list of upcoming appointments assigned to a specific provider, "
        "filtered to future dates only. "
        "Each record typically contains patient identifiers, appointment date and time, "
        "visit status, and appointment type. "
        "This tool is most relevant for provider schedule reviews, workload planning, "
        "clinic flow management, or answering questions about a provider's upcoming day or week."
    ),
    context="Here are the providers upcoming appointments, summarize them in a concise format:",
    parameters={
        "provider_id": "Provider ID"
    }
)
def get_appointments_by_provider(db_conn, provider_id : str):
    """
    Queries the Oscar EMR database for a provider's upcoming appointments
    """
    
    today = datetime.today().strftime("%Y-%m-%d")
    
    query = f"""
    SELECT *
    FROM appointment
    WHERE provider_no = {provider_id}
      AND appointment_date > '{today}'
    LIMIT 10;
    """

    res = db_conn.query_database(query)
    return tr(
        label=f"Appointments for Provider {provider_id}",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="appointments",
    description=(
        "Returns a list of active patients who have not completed a valid appointment "
        "within a specified time period (days, months, or years). "
        "Patients with cancelled, no-show, or rescheduled visits within the period are excluded. "
        "Results typically include patient demographic identifiers and assigned provider. "
        "This tool is especially relevant for patient outreach, recall programs, "
        "preventive care tracking, and identifying patients lost to follow-up."
    ),
    context="Here are the patient's who haven't been seen recently:",
    parameters={
        "period": (
            "An integer followed by one of 'd', 'm', or 'y' representing days, months, or years "
            "(e.g., '6m' for six months)."
        )
    }
)"""
def patients_not_seen(db_conn, period : str = "2y") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have not been seen for X days/months/years.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.

    Returns
    -------
    A list of dictionaries of patient's that have not been seen for X days/months/years.
    """

    date = period_parser(period)

    # Status':
    # b: Booked
    # a: Exam Room 2
    # i: Arrived
    # c: Completed
    # E: Echo Room 1
    # d: Rescheduled
    # e: Exam Room 1
    # G: Holter Booked
    # R: Exam Room 3
    # j: Stress Echo Room
    # H: EST Room
    # N: No Show
    # C: Cancelled
    # B: Billed

    query = f"""
    SELECT 
        d.demographic_no AS "demoNo",
        d.last_name AS "LastName",
        d.first_name AS "FirstName",
        d.provider_no AS "ProviderNo"
    FROM demographic d
    WHERE d.patient_status = 'AC'

    # Exclude patient's who have had appointments within period
    AND NOT EXISTS (
        SELECT 1
        FROM appointment a
        WHERE a.demographic_no = d.demographic_no
        AND a.demographic_no <> 0
        AND a.status NOT IN ('d', 'N', 'C')
        AND a.appointment_date > '{date}'
    )

    # Only include patient's who have had at least 1 appointment registered
    AND EXISTS (
        SELECT 1
        FROM appointment a2
        WHERE a2.demographic_no = d.demographic_no
          AND a2.demographic_no <> 0
    )
    """

    res = db_conn.query_database(query)
    return tr(
        label=f"Patient's Not Seen since {date}",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="appointments",
    description=(
        "Returns a list of active patients who have never had an appointment recorded "
        "in the system. "
        "Results typically include patient identifiers and assigned provider information. "
        "This tool is relevant for identifying inactive or unengaged patients, "
        "data quality audits, onboarding follow-ups, or outreach to patients who "
        "have never been seen despite being registered."
    ),
    context="Here are the patient's who haven't had appointments:",
    parameters={}
)"""
def patients_with_no_appointments(db_conn) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have not had any appointments scheduled.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.
    """

    query = f"""
    SELECT 
        d.demographic_no AS "demoNo",
        d.last_name AS "LastName",
        d.first_name AS "FirstName",
        d.provider_no AS "ProviderNo"
    FROM demographic d
    WHERE d.patient_status = 'AC'

    # Only include patient's who have not had any appointments registered
    AND NOT EXISTS (
        SELECT 1
        FROM appointment a
        WHERE a.demographic_no = d.demographic_no
          AND a.demographic_no <> 0
    )
    """

    res = db_conn.query_database(query)
    return tr(
        label=f"Patient's with no appointments",
        send_to_ai=False,
        query_results=res,
        save_results=res
    )


"""@tool(
    category="appointments",
    description=(
        "Returns patients who have missed one or more appointments within a specified time period "
        "and do not currently have a future appointment scheduled. "
        "Missed appointments may include no-shows or unattended visits depending on status rules. "
        "Results are useful for identifying patients requiring rebooking, outreach, "
        "or follow-up after missed care."
    ),
    context="Here are the patients with missed appointments and no rescheduled visits:",
    parameters={
        "period": "An integer followed by 'd', 'm', or 'y' (e.g., '6m' for six months)."
    }
)"""
def missed_appointments(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have had missed appointments and new appointments
    have yet to be scheduled.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  
