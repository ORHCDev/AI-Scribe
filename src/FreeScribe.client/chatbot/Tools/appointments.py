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
        "Returns a list of upcoming appointments assigned to a specific healthcare provider, "
        "filtered to future dates only. The provider should be identified by name. "
        "The provider name may be given with or without a professional title such as "
        "'Dr.'. This tool is relevant when the user asks for the upcoming appointments or schedule "
        "associated with a particular individual, who is assumed to be a doctor, provider or clinician."
    ),
    context=(
        "Here are the upcoming appointments for the requested provider or doctor. "
        "Summarize them in a concise format:"
    ),
    parameters={
        "provider_name": "Name of the provider whose upcoming appointments should be retrieved"
    }
)
def get_appointments_by_provider(db_conn, provider_name: str):
    """
    Queries the Oscar EMR database for a provider's upcoming appointments.
    """

    provider_query = f"""
    SELECT
        provider_no,
        first_name,
        last_name,
        provider_type,
        specialty,
        email
    FROM provider
    WHERE CONCAT(first_name, ' ', last_name) = '{provider_name}'
    OR CONCAT('Dr. ', first_name, ' ', last_name) = '{provider_name}'
    ORDER BY provider_no;
    """

    providers = db_conn.query_database(provider_query)

    today = datetime.today().strftime("%Y-%m-%d")

    if not providers:
        return tr(
            label=f"Provider not found: {provider_name}",
            send_to_ai=True,
            query_results=[],
            save_results=[]
        )

    if len(providers) > 1:
        providers_with_appointments = []

        for provider in providers:
            provider_id = provider["provider_no"]

            query = f"""
            SELECT *
            FROM appointment
            WHERE provider_no = {provider_id}
            AND appointment_date >= '{today}'
            ORDER BY appointment_date
            LIMIT 15;
            """

            appointments = db_conn.query_database(query)

            if appointments:
                providers_with_appointments.append({
                    "provider": provider,
                    "appointments": appointments
                })

        if len(providers_with_appointments) == 0:
            return tr(
                label=f"No upcoming appointments for {provider_name}",
                send_to_ai=True,
                query_results=[],
                save_results=[]
            )

        if len(providers_with_appointments) > 1:
            return tr(
                label=f"Multiple providers found: {provider_name}",
                send_to_ai=True,
                query_results=[
                    {
                        "provider_no": item["provider"]["provider_no"],
                        "first_name": item["provider"]["first_name"],
                        "last_name": item["provider"]["last_name"],
                        "specialty": item["provider"]["specialty"],
                        "appointments": item["appointments"]
                    }
                    for item in providers_with_appointments
                ],
                save_results=providers_with_appointments
            )

        # Exactly one matching provider has appointments
        res = providers_with_appointments[0]["appointments"]

    else:
        provider_id = providers[0]["provider_no"]

        query = f"""
        SELECT *
        FROM appointment
        WHERE provider_no = {provider_id}
        AND appointment_date >= '{today}'
        ORDER BY appointment_date
        LIMIT 15;
        """

        res = db_conn.query_database(query)

    provider_id = providers[0]["provider_no"]

    query = f"""
    SELECT *
    FROM appointment
    WHERE provider_no = {provider_id}
      AND appointment_date >= '{today}'
    ORDER BY appointment_date
    LIMIT 15;
    """

    res = db_conn.query_database(query)

    return tr(
        label=f"Appointments for {provider_name}",
        send_to_ai=True,
        query_results=res,
        save_results=res
    )


@tool(
    category="appointments",
    description=(
        "Returns a list of active patients who have not completed a valid appointment "
        "within a specified time period (days, months, or years). "
        "Patients with cancelled, no-show, or rescheduled visits within the period are excluded. "
        "Results typically include patient demographic identifiers and assigned provider. "
        "The search may optionally be filtered to a specific provider by name. "
        "The provider name may be given with or without a professional title such as 'Dr.'. "
        "This tool is especially relevant for patient outreach, recall programs, "
        "preventive care tracking, and identifying patients lost to follow-up."
    ),
    context=(
        "Here is a list of patients who have not been seen within the specified period. "
        "Return the patients as a simple list using the patient's FirstName and LastName. "
        "Do not summarize, analyze, group, or describe the dataset. "
        "Do not provide an overview, demographic breakdown, sample entries, or table. "
        "Include every patient in the results."
    ),
    parameters={
        "period": (
            "An integer followed by one of 'd', 'm', or 'y' representing days, months, or years "
            "(e.g., '6m' for six months). Optional; defaults to 2 years."
        ),
        "provider_name": (
            "Optional name of the provider to filter patients by. "
            "The name may be given with or without 'Dr.' "
        )
    }
)
def patients_not_seen(
    db_conn,
    period: str = "2y",
    provider_name: str = None
) -> list[dict]:
    """
    Queries and returns a list of active patients that have not been seen
    within the specified period, optionally filtered by provider.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months,
        or years respectively. E.g. '6m' indicates six months.

    provider_name : str
        Optional provider name used to filter the results.
    """

    date = period_parser(period)

    provider_filter = ""

    if provider_name:
        provider_query = f"""
        SELECT provider_no
        FROM provider
        WHERE CONCAT(first_name, ' ', last_name) = '{provider_name}'
           OR CONCAT('Dr. ', first_name, ' ', last_name) = '{provider_name}'
        """

        providers = db_conn.query_database(provider_query)

        if not providers:
            return tr(
                label=f"Provider not found: {provider_name}",
                send_to_ai=True,
                query_results=[],
                save_results=[]
            )

        provider_ids = [str(provider["provider_no"]) for provider in providers]

        provider_filter = f"""
        AND d.provider_no IN ({','.join(provider_ids)})
        """

    query = f"""
    SELECT 
        d.demographic_no AS "demoNo",
        d.last_name AS "LastName",
        d.first_name AS "FirstName",
        d.provider_no AS "ProviderNo",
        MAX(a.appointment_date) AS "LastAppointment"
    FROM demographic d
    JOIN appointment a
        ON a.demographic_no = d.demographic_no
    WHERE d.patient_status = 'AC'
    AND a.demographic_no <> 0
    AND a.status NOT IN ('d', 'N', 'C')

    {provider_filter}

    GROUP BY
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no

    HAVING MAX(a.appointment_date) <= '{date}'

    ORDER BY MAX(a.appointment_date) ASC

    LIMIT 15;
    """

    res = db_conn.query_database(query)

    label = f"Patients Not Seen since {date}"

    if provider_name:
        label += f" for {provider_name}"

    return tr(
        label=label,
        send_to_ai=True,
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
