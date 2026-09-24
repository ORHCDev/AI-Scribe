import inspect, json, logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from chatbot.Workflows.Workflow import Workflow, WorkflowContext, WorkflowResult, workflow
from chatbot.Tools.demonumber import get_demo_num, demo_number_required

# When set to False, document and measurement search skips the RAG vector database 
# and instead relies on the documents.py and measurements.py tools
USE_RAG_VECTORS = False

@workflow(
    name="rag_search",
    description="Patient-specific clinical queries requiring search of documents, labs, measurements, or clinical history",
    keywords=["search", "query", "find", "lab values", "lab results", "lab documents", "documents"]
)
class RAGWorkflow(Workflow):
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

    def run(self, user_input: str, context: WorkflowContext) -> WorkflowResult:
        """
        Chains multiple LLM calls together augmenting original user input with patient context.

        Workflow
        --------
        1. Gets LLM to generate keyword string that will be used for vector search from user input.
        2. Does a vector search to retrieve closest matching documents, measurements, and tools.
        3. Organizes returned chunks and re-ranks.
        4. If any tools are selected, execute tool(s) and save returned results.
        5. Iterate over documents and measurements, appending chunks until maximum context is reached.
        6. Send follow up to LLM to answer User's input with the attached context. 
        7. Return LLM response to follow up.
        """

        if not user_input.strip(): return WorkflowResult(response="")
        resolved_input = self._resolve_query(user_input, context)

        today = datetime.now()

        # Get AI to generate RAG search string
        rag_prompt = context.prompts.get("date_rag_prompt").format(
            resp_format=context.prompts.get("resp_format"),
            year=today.year,
            month=today.month,
            today=today.date(),
            yesterday=(today - timedelta(days=1)).date(),
            last_week=(today - timedelta(weeks=1)).date(),
            last_month=(today - timedelta(days=30)).date(),
            last_year=(datetime(year=(today.year - 1), month=today.month, day=1)).date(),
            user_input=resolved_input
        )
        rag_str = context.ai_conn.send_message(rag_prompt)
        rag_str = rag_str.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
        rag_json = json.loads(rag_str)

        rstr = rag_json["RAG"]
        date = rag_json["date"]
        intent = {
            "category": rag_json.get("category", "general"),
            "types": rag_json.get("types") or [],
            "mode": rag_json.get("mode", "none"),
        }

        #self._write_out(rag_prompt, "#")
        #self._write_out(rag_str, "$")

        demo_no = context.curr_demo
        if demo_number_required(resolved_input, context):
            logging.info(
                f"RAG PATIENT DEBUG: original demo_no={demo_no!r}, "
                f"isdigit={demo_no and demo_no.isdigit()}"
            )

            if demo_no and demo_no.isdigit():
                logging.info("RAG PATIENT DEBUG: final demo_no unchanged")
            else:
                demo_no, patient_error = get_demo_num(resolved_input, context)
                logging.info(
                    f"RAG PATIENT DEBUG: final demo_no={demo_no!r}, "
                    f"isdigit={demo_no and demo_no.isdigit()}"
                )
                if patient_error:
                    return WorkflowResult(response=patient_error)
                elif not demo_no:
                    return WorkflowResult(response="No patient was specified. Please state which patient.")
        else:
            logging.info("Demo number deemed unnecessary for this prompt")

        # Perform RAG search on tool embeddings and documents
        date_rank = False
        if date == 'old' or date == 'recent':
            date_rank = True
            embeddings = context.vec_search.search(
                query=rstr,
                patient_id=demo_no,
                top_k=10,
                to_dict=True
            )
        else:
            embeddings = context.vec_search.search(
                query=rstr,
                patient_id=demo_no,
                top_k=10,
                date=date,
                to_dict=True
            )

        tool_embds = embeddings["tools"]
        doc_embds = embeddings["documents"] if USE_RAG_VECTORS else []
        msr_embds = embeddings["measurements"] if USE_RAG_VECTORS else []

        if not USE_RAG_VECTORS:
            logging.info("skipping vector DB document and measurement search (retrieval delegated to documents.py and measurements.py tools).")

        # Combine for reranking
        chunks = []

        for t in tool_embds:
            data = {
                "tool_name" : t["tool_name"],
                "text" : t["description"],
                "obs_date" : datetime.now(timezone.utc),
                "args" : t["metadata"]["params"],
                "is_tool" : True
            }
            chunks.append(data)

        for d in doc_embds:
            data = {
                "id" : d["document_id"],
                "type" : d["document_type"],
                "obs_date" : d["observation_date"],
                "text" : d["chunk_text"],
                "is_tool" : False,
                "source_type" : "document"
            }
            chunks.append(data)

        for m in msr_embds:
            data = {
                "id" : m["measurement_ids"],
                "type" : m["measurement_type"],
                "obs_date" : m["observation_date"],
                "text" : m["chunk_text"],
                "is_tool" : False,
                "source_type" : "measurement"
            }
            chunks.append(data)

        # Re-rank and take top results
        if date_rank:
            reranked = context.vec_search.date_rank(rstr, chunks, text_key="text", date_key="obs_date", recency_method=date, batch_size=8)
        else:
            reranked = context.vec_search.rank(rstr, chunks, key="text", batch_size=8)
        top_k = reranked[:10]
        logging.info(f"Top results: {top_k}")
        #
        # Extract tools and prompt LLM
        rag_tools = [elem[1] for elem in top_k if elem[1]["is_tool"]]

        # On a retry let the LLM choose from the full tool registry instead
        retrying = bool(context.verification_feedback or context.excluded_tools)
        if retrying:
            logging.info("Retry detected: offering full tool registry to the LLM instead of RAG candidates")
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
        else:
            tools = rag_tools

        # Withhold tools that a previous verification attempt already failed
        # with so a retry is forced to consider an alternative.
        if context.excluded_tools:
            tools = [t for t in tools if t["tool_name"] not in context.excluded_tools]
            logging.info(f"Excluding previously failed tools: {context.excluded_tools}")

        # Generating sources array
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

            #self._write_out(tool_prompt, "#")
            #self._write_out(tool_resp, "$")
            
            # Execute any tools the AI selected and append results as context
            
            tool_select = tool_resp.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
            if tool_select.startswith("["):
                # Load tool
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
                    res = context.tools.execute_tool(name, **args)
                    tools_tried.append(name)
                    instruction = f"{tool_obj.context}\n" if tool_obj.context else ""
                    tool_context += f"Tool: {name}\n{instruction}Results: {res}\n\n"

                    sources.append({
                        "source_type": "tool",
                        "id": name, # the tool name
                        "data_type": None,
                        "obs_date": None,
                        "score": None
                    })

        MAX_LEN = 15000
        cur_len = len(context.prompts.get("followup")) + len(tool_context)

        # Generate context string
        doc_context = ""
        for elem in top_k:
            chunk = elem[1]
            if not chunk["is_tool"]:
                sources.append({
                    "source_type": chunk["source_type"],
                    "id": chunk["id"],
                    "data_type": chunk["type"],
                    "obs_date": chunk["obs_date"],
                    "score": float(elem[0])
                })

                doc_context += f"Date Observed: {chunk['obs_date'].strftime('%Y-%m-%d')}\nDocument ID: {chunk['id']}\nContent:{chunk['text']}\n\n"
                if len(doc_context) + cur_len > MAX_LEN:
                    break

        # Combine tool and document
        if not tool_context:
            context_str = f"Document Context:\n{doc_context}"
            logging.info("No tools selected")
        else:
            context_str = f"Document Context:\n{doc_context}\n\nTool Context:\n{tool_context}"

        #print(f"{'$'*50}\nDOCUMENT CONTEXT:{doc_context}\n{'$'*50}")
        #print(f"{'&'*50}\nTOOL CONTEXT: {tool_context}\n{'&'*50}")

        # Get AI followup response for User question with provided context
        if context.conversation_history and context.memory_needed:
            history = '\n'.join(context.conversation_history)
            convo_history = f"Conversation History:{history}\nInput:{resolved_input}\n"
        else:
            convo_history = resolved_input

        followup_prompt = context.prompts.get("followup").format(
            user_input=convo_history,
            context=context_str
        )
        logging.info(f"Followup: {followup_prompt}")
        resp = context.ai_conn.send_message(followup_prompt)

        # self._write_out(followup_prompt, "#")
        # self._write_out(resp, "$")

        return WorkflowResult(
            response=resp,
            sources=sources,
            metadata={"tools_tried": tools_tried, "context": context_str},
        )
