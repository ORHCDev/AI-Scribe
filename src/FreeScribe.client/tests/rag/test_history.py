import json, sys, yaml
from pathlib import Path
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2])
)
from chatbot.Workflows.Workflow import WorkflowContext
from chatbot.AIConnect import AIConnect

with open(r".\configs\config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

ai_config = config["AIConnection"]
ai_conn = AIConnect(
    ai_config["endpoint"],
    api_key=ai_config["api_key"],
    headers=ai_config.get("headers", {}),
    top_p=0.25,
    top_k=20
)
example_history = [
    "User: list LDL measurements for patient 29452",
    "Chatbot: - 2026-04-06: 2.67\n"
    "- 2025-09-12: 2.04\n"
    "- 2025-02-06: 2.30\n"
    "- 2023-06-19: 2.32\n"
    "- 2023-06-13: 2.32",
    "User: plot the measurements",
    "Chatbot: No matching records were found to plot.",
    "User: plot the measurements for LDL for patient 29452",
    "Chatbot: I cannot create a plot, but here are the LDL measurements for patient 29452:\n"
    "\n"
    "- 2026-04-06: 2.67\n"
    "- 2025-09-12: 2.04\n"
    "- 2025-02-06: 2.30\n"
    "- 2023-06-19: 2.32\n"
    "- 2023-06-13: 2.32",
    "User: list medication history for patient Joe Test",
    "Chatbot: - LITHIUM CARBONATE 600MG CAPSULE (2026-09-15)\n"
    "- ASA 80 (2016-06-06)",
    "User: hello",
    "Chatbot: Hello. How can I assist you today?"
]
example_context = WorkflowContext(
    ai_conn=ai_conn,
    db_conn=None,
    oscar=None,
    vec_search=None,
    tools=None,
    conversation_history=example_history,
    curr_demo=None,
    prompts={},
    memory_needed=True
)

def history_to_json(context: WorkflowContext):
    if not context.conversation_history:
        return None

    history = "\n".join(context.conversation_history)

    prompt = f"""
    Review the following chatbot conversation history and extract the key
    information that may be useful for continuing the conversation.

    Return JSON only, using exactly this structure:

    {{
        "patient_id": null,
        "patient_name": null,
        "most_recent_topic": null,
        "key_details": []
    }}

    Rules:
    - patient_id: the most recently referenced patient demographic number, if one
    is explicitly mentioned. Otherwise null.
    - patient_name: the most recently referenced patient name, if one is
    explicitly mentioned. Otherwise null.
    - key_details: a list of other important facts from the conversation that
    may be relevant to future questions.
    - Do not invent or infer information that is not explicitly present.
    - If there are multiple patients, use the patient referenced most recently.
    - Keep key_details concise.

    Conversation history:
    {history}
    """

    response = context.ai_conn.send_message(prompt)

    response = (
        response
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        print(f"Could not parse history JSON: {response}")
        return None

result = history_to_json(example_context)
print(json.dumps(result, indent=2))