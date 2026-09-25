import inspect, json, logging
from datetime import datetime, timezone

from chatbot.Workflows.Workflow import Workflow, WorkflowContext, WorkflowResult, workflow
from chatbot.Tools.demonumber import get_demo_num, demo_number_required


@workflow(
    name="oscar_search",
    description=(
        "Patient-specific clinical queries that require structured EMR data such as "
        "measurements, laboratory results, vitals, trends, medications, appointments, "
        "demographics, or population lookups. Does not search document text."
    ),
    keywords=[
        "measurement", "measurements", "lab values", "lab results", "vitals",
        "trend", "medication", "appointment", "demographics", "patients"
    ]
)
class OscarWorkflow(Workflow):
    def _resolve_query(self, user_input: str, context: WorkflowContext) -> str:
        if not context.conversation_history or not context.memory_needed:
            return user_input

        history = "\n".join(context.conversation_history[-5:])

        prompt = context.prompts.get("query_resolution_prompt").format(
            history=history,
            user_input=user_input
        )

        response = context.ai_conn.send_message(prompt)

        response = (
            response
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        try:
            result = json.loads(response)
            resolved_query = result.get("resolved_query")

            if resolved_query:
                logging.info(
                    f"Query resolution: {user_input!r} -> {resolved_query!r}"
                )
                return resolved_query

        except json.JSONDecodeError:
            logging.warning(
                f"Could not parse resolved query: {response}"
            )

        return user_input

    def _build_intent(self, user_input: str, context: WorkflowContext) -> dict:
        """
        Asks the LLM to classify what kind of data the question needs so tool
        selection can be guided by category, types, and mode.
        """
        try:
            prompt = context.prompts.get("oscar_intent_prompt").format(
                user_input=user_input
            )
            response = context.ai_conn.send_message(prompt)
            response = (
                response
                .replace("```json", "")
                .replace("```", "")
                .replace("**JSON only**", "")
                .strip()
            )
            parsed = json.loads(response)
            return {
                "category": parsed.get("category", "general"),
                "types": parsed.get("types") or [],
                "mode": parsed.get("mode", "none"),
            }
        except (json.JSONDecodeError, AttributeError):
            logging.warning("Could not parse oscar intent response, defaulting to general")
            return {"category": "general", "types": [], "mode": "none"}

    def run(self, user_input: str, context: WorkflowContext) -> WorkflowResult:
        """
        Selects and executes tools from the full tool registry, then answers the
        user's question from the returned results.

        Workflow
        --------
        1. Resolve ambiguous input using recent conversation history.
        2. Identify the patient demographic number when required.
        3. Classify the question into a data category, types, and mode.
        4. Offer the full tool registry to the LLM and execute the selected tools.
        5. Send a follow up to the LLM to answer the question with the tool results.
        6. Return the LLM response.
        """

        if not user_input.strip():
            return WorkflowResult(response="")

        resolved_input = self._resolve_query(user_input, context)

        demo_no = context.curr_demo
        if demo_number_required(resolved_input, context):
            logging.info(
                f"OSCAR PATIENT DEBUG: original demo_no={demo_no!r}, "
                f"isdigit={demo_no and demo_no.isdigit()}"
            )

            if demo_no and demo_no.isdigit():
                logging.info("OSCAR PATIENT DEBUG: final demo_no unchanged")
            else:
                demo_no, patient_error = get_demo_num(resolved_input, context)
                logging.info(
                    f"OSCAR PATIENT DEBUG: final demo_no={demo_no!r}, "
                    f"isdigit={demo_no and demo_no.isdigit()}"
                )
                if patient_error:
                    return WorkflowResult(response=patient_error)
                elif not demo_no:
                    return WorkflowResult(response="No patient was specified. Please state which patient.")
        else:
            logging.info("Demo number deemed unnecessary for this prompt")

        intent = self._build_intent(resolved_input, context)

        # No vector search: offer the full tool registry to the LLM.
        tools = [
            {
                "tool_name": t.name,
                "text": t.description,
                "obs_date": datetime.now(timezone.utc),
                "args": t.parameters,
                "is_tool": True,
            }
            for t in context.tools.list()
        ]

        # Withhold tools that a previous verification attempt already failed with
        # so a retry is forced to consider an alternative.
        if context.excluded_tools:
            tools = [t for t in tools if t["tool_name"] not in context.excluded_tools]
            logging.info(f"Excluding previously failed tools: {context.excluded_tools}")

        sources = []
        tool_context = ""
        tools_tried = []
        if tools:
            tool_str = ""
            for t in tools:
                tool_str += f"{t}\n"
            tool_prompt = context.prompts.get("rag_tool_prompt").format(
                tool_protocol=context.prompts.get("rag_tool_protocol"),
                demo_no=demo_no,
                user_input=resolved_input,
                tools=tool_str,
                verification_feedback=context.verification_feedback or "None",
                intent=intent,
            )
            tool_resp = context.ai_conn.send_message(tool_prompt)

            tool_select = tool_resp.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
            if tool_select.startswith("["):
                tool_call = json.loads(tool_select)
                for tool in tool_call:
                    logging.info(f"Calling tool: {tool}")
                    name = tool.get("tool_name")
                    args = tool.get("args") or {}
                    if name in context.excluded_tools:
                        logging.warning(f"Skipping previously failed tool returned by LLM: {name}")
                        continue
                    if name not in context.tools.keys():
                        logging.warning(f"Skipping unknown tool returned by LLM: {name}")
                        continue
                    tool_obj = context.tools.get(name)
                    sig = inspect.signature(tool_obj.func).parameters
                    if "db_conn" in sig:
                        args["db_conn"] = context.db_conn
                    if "vec_search" in sig:
                        args["vec_search"] = context.vec_search
                    if "oscar" in sig:
                        args["oscar"] = context.oscar
                    res = context.tools.execute_tool(name, **args)
                    tools_tried.append(name)
                    instruction = f"{tool_obj.context}\n" if tool_obj.context else ""
                    tool_context += f"Tool: {name}\n{instruction}Results: {res}\n\n"

                    sources.append({
                        "source_type": "tool",
                        "id": name,  # the tool name
                        "data_type": None,
                        "obs_date": None,
                        "score": None
                    })

        if tool_context:
            context_str = f"Tool Context:\n{tool_context}"
        else:
            context_str = "Tool Context:\nNo tools were selected."
            logging.info("No tools selected")

        # Get AI followup response for User question with provided context
        if context.conversation_history and context.memory_needed:
            history = '\n'.join(context.conversation_history)
            convo_history = f"Conversation History:{history}\nInput:{resolved_input}\n"
        else:
            convo_history = resolved_input

        followup_prompt = context.prompts.get("oscar_followup").format(
            user_input=convo_history,
            context=context_str
        )
        logging.info(f"Followup: {followup_prompt}")
        resp = context.ai_conn.send_message(followup_prompt)

        return WorkflowResult(
            response=resp,
            sources=sources,
            metadata={"tools_tried": tools_tried, "context": context_str},
        )
