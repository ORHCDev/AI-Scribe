import json, logging
from chatbot.Workflows.Workflow import WorkflowContext
from chatbot.Tools.Tool import tool, ToolReturn as tr

def correct_patient_name(patient_name: str, context: WorkflowContext):
    correction_prompt = context.prompts.get(
        "patient_name_correction"
    ).format(
        patient_name=patient_name
    )

    correction_resp = context.ai_conn.send_message(correction_prompt)

    correction_resp = (
        correction_resp
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:
        correction = json.loads(correction_resp)
    except json.JSONDecodeError:
        logging.warning(
            f"Could not parse patient name correction response: "
            f"{correction_resp}"
        )
        return None

    corrected_name = correction.get("corrected_name")

    if not corrected_name:
        return None

    corrected_name = corrected_name.strip()

    if corrected_name.lower() == patient_name.lower():
        return None
    else:
        return corrected_name

def get_patient_by_name(patient_name: str, context: WorkflowContext):
    db_conn = context.db_conn

    # Normalize the user's input
    patient_name = patient_name.strip()
    search_name = patient_name.lower().replace(",", " ")
    search_parts = search_name.split()

    if len(search_parts) < 2:
        return []

    # Exact match
    query = f"""
    SELECT
        demographic_no,
        first_name,
        last_name
    FROM demographic
    WHERE CONCAT(first_name, ' ', last_name) = '{patient_name}'
    OR CONCAT(last_name, ', ', first_name) = '{patient_name}'
    LIMIT 10;
    """

    exact_matches = db_conn.query_database(query)

    if exact_matches:
        return exact_matches

    # Middle-name-omitted match
    first_name = search_parts[0]
    last_name = search_parts[-1]

    query = f"""
    SELECT
        demographic_no,
        first_name,
        last_name
    FROM demographic
    WHERE
        (
            first_name LIKE '{first_name}%'
            AND last_name = '{last_name}'
        )
        OR
        (
            first_name LIKE '{last_name}%'
            AND last_name = '{first_name}'
        )
    LIMIT 10;
    """

    middle_name_matches = db_conn.query_database(query)

    if middle_name_matches:
        return middle_name_matches

    # LLM call to fix typos
    corrected_name = correct_patient_name(patient_name, context)

    if not corrected_name:
        return []

    logging.info(
        f"Trying corrected patient name: "
        f"'{patient_name}' -> '{corrected_name}'"
    )

    corrected_query = f"""
    SELECT
        demographic_no,
        first_name,
        last_name
    FROM demographic
    WHERE CONCAT(first_name, ' ', last_name) = '{corrected_name}'
    OR CONCAT(last_name, ', ', first_name) = '{corrected_name}'
    LIMIT 10;
    """

    corrected_matches = db_conn.query_database(corrected_query)

    if corrected_matches:
        return corrected_matches
    else:
        return []

def get_demo_num_from_history(context: WorkflowContext):
    if not context.conversation_history:
        return None

    history = "\n".join(context.conversation_history)

    prompt = f"""
    Review the conversation history below and identify the most recently
    referenced patient demographic number.

    Return JSON only in this format:
    {{
        "patient_id": "12345"
    }}

    Rules:
    - Return the demographic number of the most recently referenced patient.
    - If multiple patients were discussed, use the patient referenced most recently.
    - Do not guess or infer a demographic number.
    - If no demographic number is explicitly referenced, return null.

    Conversation history:
    {history}
    """

    response = context.ai_conn.send_message(prompt)

    response = (
        response
        .replace("```json", "")
        .replace("```", "")
        .replace("**JSON only**", "")
        .strip()
    )

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        logging.warning(
            f"Could not parse patient ID from conversation history: {response}"
        )
        return None

    patient_id = result.get("patient_id")

    if patient_id is None:
        return None

    return str(patient_id)

def get_demo_num(user_input: str, context: WorkflowContext):
    identifier_prompt = context.prompts.get("patient_identifier").format(
        user_input=user_input
    )

    identifier_resp = context.ai_conn.send_message(identifier_prompt)

    identifier_resp = (
        identifier_resp
        .replace("```json", "")
        .replace("```", "")
        .replace("**JSON only**", "")
        .strip()
    )

    try:
        identifier = json.loads(identifier_resp)
    except json.JSONDecodeError:
        logging.warning(
            f"Could not parse patient identifier response: {identifier_resp}"
        )
        identifier = {
            "patient_id": None,
            "patient_name": None
        }

    patient_id = identifier.get("patient_id")
    patient_name = identifier.get("patient_name")
    patient_relevant = identifier.get("patient_relevant", False)

    if patient_relevant and patient_id:
        logging.info(f"Patient resolved from ID: {patient_id}")
        return str(patient_id), None
    
    elif patient_relevant and patient_name:
        matches = get_patient_by_name(patient_name, context)

        # No matches
        if len(matches) == 0:
            logging.warning(f"No patient found with name: {patient_name}")

            return None, (
                f"I could not find a patient named '{patient_name}'. "
                "Please check the patient's name and try again."
            )

        # One match
        if len(matches) == 1:
            demo_no = matches[0]["demographic_no"]

            logging.info(
                f"Patient resolved from name '{patient_name}': {demo_no}"
            )

            return str(demo_no), None

        # Multiple matches
        logging.warning(
            f"Multiple patients found for '{patient_name}': {matches}"
        )

        patient_list = "\n".join(
            f"- {m['first_name']} {m['last_name']} "
            f"(demographic number: {m['demographic_no']})"
            for m in matches
        )

        return None, (
            f"I found multiple patients matching '{patient_name}'. "
            "Please specify which patient you mean:\n"
            f"{patient_list}"
        )
        
    history_demo_no = get_demo_num_from_history(context)

    if history_demo_no:
        logging.info(
            f"Patient resolved from conversation history: {history_demo_no}"
        )
        return history_demo_no, None

    return None, None

def demo_number_required(user_input: str, context: WorkflowContext):
    prompt = context.prompts.get("patient_requirement_prompt").format(user_input=user_input)
    response = context.ai_conn.send_message(prompt)
    response = (
        response
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:
        result = json.loads(response)
        result_bool = result.get("patient_required", True)
        logging.info(f"Specific patient required={'True' if result_bool else 'False'}")
        return result_bool

    except (json.JSONDecodeError, TypeError):
        logging.warning(f"Could not parse patient requirement response: {response}")
        return True

'''@tool(
    category="patientinfo",
    description=(
        "Returns only the demographic number of a specific patient."
        "This tool is relevant when the user asks specifically and exclusively for the "
        "ID or demographic number of a specific patient."
    ),
    context="Patient demographic number:",
    parameters={
        "demo_no": "Patient demographic number used to uniquely identify the patient in the EMR"
    }
)'''
def get_patient_demographic_number(demo_no : str):
    """
    Returns the demographic number
    """
    return tr(
        label="Demographic Number",
        send_to_ai=False,
        query_results=demo_no,
        save_results=demo_no,
    )