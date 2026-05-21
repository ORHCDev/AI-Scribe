import json
import logging
from datetime import datetime, timedelta, timezone

from chatbot.Workflows.Workflow import Workflow, WorkflowContext, WorkflowResult, workflow


@workflow(
    name="rag_search",
    description="Patient-specific clinical queries requiring search of documents, labs, measurements, or clinical history",
    keywords=["search", "query", "find", "lab values", "lab results", "lab documents", "documents"]
)
class RAGWorkflow(Workflow):

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
            user_input=user_input
        )
        rag_str = context.ai_conn.send_message(rag_prompt)
        rag_str = rag_str.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
        rag_json = json.loads(rag_str)

        rstr = rag_json["RAG"]
        date = rag_json["date"]

        #self._write_out(rag_prompt, "#")
        #self._write_out(rag_str, "$")


        demo_no = context.curr_demo

        # Perform RAG search on tool embeddings and documents
        date_rank = False
        if date == 'old' or date == 'recent':
            date_rank = True
            embeddings = context.vec_search.search(
                query=rag_str,
                patient_id=demo_no,
                top_k=10,
                to_dict=True
            )
        else:
            embeddings = context.vec_search.search(
                query=rag_str,
                patient_id=demo_no,
                top_k=10,
                date=date,
                to_dict=True
            )

        tool_embds = embeddings["tools"]
        doc_embds = embeddings["documents"]
        msr_embds = embeddings["measurements"]


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
        tools = [elem[1] for elem in top_k if elem[1]["is_tool"]]

        # Generating sources array
        sources = []

        tool_context = ""
        if tools:
            tool_str = ""
            for t in tools:
                tool_str += f"{t}\n" 
            tool_prompt = context.prompts.get("rag_tool_prompt").format(
                tool_protocol=context.prompts.get("rag_tool_protocol"),
                demo_no=demo_no,
                user_input=user_input,
                tools=tool_str,
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
                    args = tool.get("args")
                    args["db_conn"] = context.db_conn
                    res = context.tools.execute_tool(name, **args)
                    tool_context += f"Tool: {name}\nResults: {res}\n\n"

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
        if context.conversation_history:
            history = '\n'.join(context.conversation_history)
            convo_history = f"Conversation History:{history}\nInput:{user_input}\n"
        else:
            convo_history = user_input

        followup_prompt = context.prompts.get("followup").format(
            user_input=convo_history,
            context=context_str
        )
        logging.info(f"Followup: {followup_prompt}")
        resp = context.ai_conn.send_message(followup_prompt)

        # self._write_out(followup_prompt, "#")
        # self._write_out(resp, "$")

        return WorkflowResult(response=resp, sources=sources)
