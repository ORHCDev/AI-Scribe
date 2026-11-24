"""
Evidence workflow: answers medical recommendation questions from the local
library of randomized controlled trial (RCT) study PDFs using agentic search.

The LLM iteratively calls the evidence tools (list studies, keyword search,
read passages, read sections), reviews what comes back, and refines its
searches until it has enough evidence to answer, at which point a final
prompt synthesizes an evidence-based recommendation with citations.
"""

import inspect
import json
import logging

from chatbot.Workflows.Workflow import Workflow, WorkflowContext, WorkflowResult, workflow
from chatbot.rct_library import DEFAULT_LIBRARY_DIR, get_rct_library


# How many rounds of tool calling the agent gets before it must answer.
MAX_SEARCH_ROUNDS = 4

# Ceiling on the evidence text carried into the final answer prompt.
MAX_EVIDENCE_CHARS = 24000

# Ceiling on the patient letter text carried into the prompts.
MAX_PATIENT_CONTEXT_CHARS = 8000


DEFAULT_EVIDENCE_TOOL_PROTOCOL = """\
JSON format:
[
  {
    "tool_name": "<tool_name>",
    "args": {
      "<parameter>": "<value>"
    }
  }
]

Respond with a JSON array containing the next tool call(s), or [] (an empty
array) when you have gathered enough evidence and no more tools are needed.
"""


DEFAULT_EVIDENCE_SEARCH_PROMPT = """\
You are a medical evidence research assistant. Your task is to gather
evidence from a local library of randomized controlled trial (RCT) study PDFs
to answer a clinician's question, by iteratively calling the search tools.

AVAILABLE STUDIES
{studies}

AVAILABLE TOOLS
{tools}

TOOLS ALREADY CALLED (do not repeat an identical call)
{history}

USER QUESTION
"{user_input}"

PATIENT CONTEXT (most recent letter from the selected patient's chart, or
"(no patient context)" when no patient is selected)
{patient_context}

HOW TO SEARCH
1. Start with search_rct_studies using specific clinical keywords for the
   question (intervention, comparator, outcome, population).
2. Review the returned passages. When a snippet is cut off or you need the
   surrounding context, call read_rct_passages with its chunk_ids. To review
   a whole part of one trial (e.g. its full methods or conclusions), call
   get_rct_study_section.
3. If the results are off-topic or empty, search again with different,
   broader, or alternate clinical terms before giving up.
4. Stop (return []) once the evidence answers the question, or after
   exhausting reasonable searches.
5. When patient context is provided, use the patient's relevant conditions,
   medications, prior events, and risk factors to choose search terms and to
   judge which trial populations fit the patient.

Respond ONLY with a JSON array of tool calls (or []):
{tool_protocol}
"""


DEFAULT_EVIDENCE_FOLLOWUP = """\
You are a medical advisor specializing in cardiology, answering a clinician's
question using ONLY the evidence retrieved from the local library of trial
PDFs.

RULES
- Base the answer ONLY on the retrieved evidence below. Do not add external
  medical knowledge unless you clearly mark it as general knowledge.
- If the evidence does not answer the question, say so plainly and describe
  what was searched.
- Cite the supporting study for each claim (study title or filename, and
  section when helpful).
- When patient context is provided, tailor the recommendation to that patient
  (comorbidities, medications, prior events, contraindications) and say how
  well the trial populations fit. Do not invent patient details that are not
  in the context.

ANSWER STRUCTURE
- Direct answer or recommendation first.
- Key evidence: for each relevant trial, the design, population, intervention
  vs comparator, the primary outcome with its effect size (RR/HR/OR, absolute
  and relative risk change, NNT when available), confidence interval, p-value,
  and sample size as reported in the evidence.
- Caveats: population fit, limitations, and what the evidence does not cover.
- Keep it concise and clinically useful.

USER QUESTION
"{user_input}"

PATIENT CONTEXT (most recent letter from the selected patient's chart, or
"(no patient context)" when no patient is selected)
{patient_context}

RETRIEVED EVIDENCE
{context}
"""


@workflow(
    name="evidence_search",
    description=(
        "Medical evidence and recommendation questions answered from the local library "
        "of randomized controlled trial (RCT) study PDFs and clinical guidelines, e.g. "
        "'what is the evidence for drug X in condition Y', 'what do the trials show "
        "about...', 'which treatment does the evidence support', effect sizes, outcomes, "
        "or comparisons between treatments. Use for evidence-based recommendations and "
        "trial results — NOT for patient-specific chart data or patient documents."
    ),
    keywords=[
        "evidence", "rct", "randomized", "randomised", "controlled trial",
        "trial", "trials", "clinical trial", "efficacy", "effectiveness",
        "recommendation", "recommendations", "guideline", "guidelines",
        "literature", "meta-analysis", "outcome", "hazard ratio",
    ],
)
class EvidenceWorkflow(Workflow):
    def _resolve_query(self, user_input: str, context: WorkflowContext) -> str:
        """Rewrites follow-up questions into standalone ones using history."""
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
                logging.info(f"Query resolution: {user_input!r} -> {resolved_query!r}")
                return resolved_query
        except json.JSONDecodeError:
            logging.warning(f"Could not parse resolved query: {response}")

        return user_input

    def _evidence_tools(self, context: WorkflowContext) -> list:
        """The registry tools in the evidence category (the RCT library tools)."""
        return [t for t in context.tools.list() if t.category == "evidence"]

    def _studies_summary(self) -> str:
        library = get_rct_library()
        studies = library.list_studies()
        if not studies:
            return "(no studies indexed)"
        lines = []
        for study in studies:
            bits = [f"- {study.display_name} (file: {study.filename})"]
            if study.year:
                bits.append(str(study.year))
            if study.study_design:
                bits.append(study.study_design)
            if study.sample_size:
                bits.append(f"n={study.sample_size}")
            if study.tags:
                bits.append(", ".join(study.tags[:6]))
            lines.append(" | ".join(bits))
        return "\n".join(lines)

    def _patient_context(self, context: WorkflowContext) -> str:
        """The selected patient's most recent 0letter text"""
        demo_no = str(context.curr_demo or "").strip()
        if not demo_no.isdigit() or context.db_conn is None or context.oscar is None:
            return ""

        try:
            rows = context.db_conn.query_database(f"""
                SELECT fdid, form_name, form_date
                FROM eform_data
                WHERE demographic_no = {int(demo_no)}
                  AND form_name LIKE '%letter%'
                ORDER BY form_date DESC, fdid DESC
                LIMIT 1;
            """)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Could not look up the patient's letters: %s", e)
            return ""
        if not rows:
            return ""

        letter = rows[0]
        try:
            text = context.oscar.get_0letter_text(letter.get("fdid"))
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Could not read the patient's latest letter: %s", e)
            return ""
        text = (text or "").strip()
        if not text:
            return ""

        if len(text) > MAX_PATIENT_CONTEXT_CHARS:
            text = text[:MAX_PATIENT_CONTEXT_CHARS] + "\n[letter truncated]"
        header = "Most recent letter"
        if letter.get("form_date"):
            header += f" ({letter['form_date']})"
        return f"{header}:\n{text}"

    def _parse_tool_calls(self, response: str) -> list[dict] | None:
        """Parses the LLM's JSON array of tool calls; None when unparseable."""
        cleaned = (
            response
            .replace("```json", "")
            .replace("```", "")
            .replace("**JSON only**", "")
            .strip()
        )
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Some models wrap the array in text; try to slice it out.
            start, end = cleaned.find("["), cleaned.rfind("]")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
        if not isinstance(parsed, list):
            return None
        return [c for c in parsed if isinstance(c, dict)]

    def _execute_call(self, call: dict, context: WorkflowContext) -> tuple[str, list]:
        """Runs one tool call, returning (result text, sources).

        Errors are returned as text so the agent can correct itself on the
        next round instead of the workflow failing.
        """
        name = call.get("tool_name")
        args = call.get("args") or {}
        allowed = {t.name for t in self._evidence_tools(context)}
        if name not in allowed:
            return (f"Error: '{name}' is not an evidence tool. "
                    f"Available: {', '.join(sorted(allowed))}."), []
        try:
            tool_obj = context.tools.get(name)
            sig = inspect.signature(tool_obj.func).parameters
            if "db_conn" in sig:
                args["db_conn"] = context.db_conn
            if "vec_search" in sig:
                args["vec_search"] = context.vec_search
            if "oscar" in sig:
                args["oscar"] = context.oscar
            res = context.tools.execute_tool(name, **args)
            sources = res.sources or []
            return f"{res.label}\n{res.query_results}", sources
        except Exception as e:
            logging.getLogger(__name__).warning("Evidence tool %s failed: %s", name, e)
            return f"Error calling {name}: {e}", []

    def run(self, user_input: str, context: WorkflowContext) -> WorkflowResult:
        """
        Agentic search over the RCT PDF library.

        Workflow
        --------
        1. Resolve ambiguous input using recent conversation history.
        2. Pull the selected patient's latest 0letter, when a patient is selected.
        3. Show the agent the study inventory, patient context and evidence tools.
        4. Loop: the LLM picks tool calls (search / read / section), the
           calls run, and their results are fed back for the next round.
        5. Once the LLM stops requesting tools, answer the question from the
           accumulated evidence with the evidence followup prompt.
        """
        if not user_input.strip():
            return WorkflowResult(response="")

        resolved_input = self._resolve_query(user_input, context)

        # Index the library now (first call parses the PDFs; later ones hit
        # the in-memory index). An empty library short-circuits with guidance.
        library = get_rct_library()
        if not library.list_studies():
            return WorkflowResult(
                response=(
                    "No study PDFs are indexed yet. Place the RCT / trial / "
                    f"guideline PDFs in the '{DEFAULT_LIBRARY_DIR}' folder and "
                    "ask again; they are indexed automatically."
                )
            )

        # Selected patient's latest letter, so recommendations fit this patient.
        patient_context = self._patient_context(context)

        # ---------------- Agentic search loop ---------------- #
        evidence_tools = self._evidence_tools(context)
        tool_str = ""
        for t in evidence_tools:
            tool_str += f"Tool: {t.name}\nDescription: {t.description}\nParameters: {t.parameters}\n\n"

        evidence_text = ""
        sources: list = []
        tools_tried: list[str] = []
        called: set[str] = set()

        for round_no in range(1, MAX_SEARCH_ROUNDS + 1):
            search_prompt = (context.prompts.get("evidence_search_prompt")
                             or DEFAULT_EVIDENCE_SEARCH_PROMPT).format(
                studies=self._studies_summary(),
                tools=tool_str,
                history="\n".join(tools_tried) or "None",
                user_input=resolved_input,
                patient_context=patient_context or "(no patient context)",
                tool_protocol=(context.prompts.get("evidence_tool_protocol")
                               or DEFAULT_EVIDENCE_TOOL_PROTOCOL),
            )
            response = context.ai_conn.send_message(search_prompt)
            calls = self._parse_tool_calls(response)

            if calls is None:
                logging.getLogger(__name__).warning(
                    "Evidence agent round %d returned unparseable output: %r",
                    round_no, response[:200])
                break
            if not calls:
                break  # agent is done gathering evidence

            for call in calls:
                key = json.dumps(call, sort_keys=True)
                if key in called:
                    evidence_text += (
                        f"Tool: {call.get('tool_name')} (skipped: identical call "
                        f"already made)\n\n")
                    continue
                called.add(key)
                name = call.get("tool_name")
                result_text, call_sources = self._execute_call(call, context)
                evidence_text += f"Tool: {name}\n{result_text}\n\n"
                sources.extend(call_sources)
                tools_tried.append(f"{name}({call.get('args') or {}})")

        if not evidence_text:
            evidence_text = "No tools were called."

        if len(evidence_text) > MAX_EVIDENCE_CHARS:
            evidence_text = (
                "[earlier evidence truncated]\n" + evidence_text[-MAX_EVIDENCE_CHARS:])

        # ---------------- Final answer ---------------- #
        if context.conversation_history and context.memory_needed:
            history = "\n".join(context.conversation_history)
            convo_history = f"Conversation History:\n{history}\n\nQuestion: {resolved_input}"
        else:
            convo_history = resolved_input

        followup_prompt = (context.prompts.get("evidence_followup")
                           or DEFAULT_EVIDENCE_FOLLOWUP).format(
            user_input=convo_history,
            patient_context=patient_context or "(no patient context)",
            context=evidence_text,
        )
        logging.getLogger(__name__).info("Evidence followup prompt length: %d", len(followup_prompt))
        resp = context.ai_conn.send_message(followup_prompt)

        metadata_context = evidence_text[:8000]
        if patient_context:
            metadata_context = (f"PATIENT CONTEXT:\n{patient_context[:2000]}\n\n"
                                f"EVIDENCE:\n{evidence_text[:6000]}")

        return WorkflowResult(
            response=resp,
            sources=sources,
            metadata={"tools_tried": tools_tried, "context": metadata_context},
        )
