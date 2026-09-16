"""
Hermetic orchestration tests for RAGWorkflow.run: LLM / retrieval / tools / DB
are all fakes injected via WorkflowContext.
"""

from datetime import datetime, timezone

import pytest

# Templates have no {placeholders}; the markers let FakeAI tell the stages apart.
_PROMPTS = {
    "date_rag_prompt": "RAGSTAGE",
    "resp_format": "",
    "rag_tool_prompt": "TOOLSTAGE",
    "rag_tool_protocol": "",
    "followup": "FOLLOWUP",
}


class FakeAI:
    def __init__(self, rag, tool_response=None, final="FINAL ANSWER"):
        self.rag = rag
        self.tool_response = tool_response
        self.final = final
        self.prompts_seen = []

    def send_message(self, prompt, pre_prompt=None):
        self.prompts_seen.append(prompt)
        if "TOOLSTAGE" in prompt:
            return self.tool_response
        if "FOLLOWUP" in prompt:
            return self.final
        return self.rag


class FakeVecSearch:
    def __init__(self, tools=(), documents=(), measurements=()):
        self._payload = {
            "tools": list(tools),
            "documents": list(documents),
            "measurements": list(measurements),
        }
        self.search_calls = []
        self.rank_called = False
        self.date_rank_called = False

    def search(self, query=None, patient_id=None, date=None, top_k=3, to_dict=False, **kw):
        self.search_calls.append({"query": query, "patient_id": patient_id, "date": date})
        return self._payload

    def rank(self, query, docs, key="text", batch_size=8):
        self.rank_called = True
        return [(1.0 - i * 0.01, d) for i, d in enumerate(docs)]

    def date_rank(self, query, docs, text_key="text", date_key="obs_date",
                  recency_method="recent", batch_size=8):
        self.date_rank_called = True
        return [(1.0 - i * 0.01, d) for i, d in enumerate(docs)]


class FakeTools:
    def __init__(self):
        self.calls = []

    def execute_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return f"RESULT[{name}]"


def _ctx(mod, ai, vec, tools=None, demo="123", history=None):
    return mod.WorkflowContext(
        ai_conn=ai, db_conn="DB", oscar=None, vec_search=vec,
        tools=tools if tools is not None else FakeTools(),
        conversation_history=history or [], curr_demo=demo,
        prompts=dict(_PROMPTS),
    )


def _doc(i, text="doc text"):
    return {
        "document_id": 1000 + i,
        "document_type": "ECHO",
        "observation_date": datetime(2024, 1, (i % 27) + 1, tzinfo=timezone.utc),
        "chunk_text": text,
    }


def _msr(i, text="measurement text"):
    return {
        "measurement_ids": str(2000 + i),
        "measurement_type": "CARD",
        "observation_date": datetime(2024, 2, (i % 27) + 1, tzinfo=timezone.utc),
        "chunk_text": text,
    }


def _tool():
    return {
        "tool_name": "get_recent_lab_results",
        "description": "recent labs",
        "metadata": {"params": {"demo_no": "Patient's demographic number"}},
    }


def test_empty_input_returns_empty(ragworkflow_mod):
    wf = ragworkflow_mod.RAGWorkflow()
    res = wf.run("   ", _ctx(ragworkflow_mod, FakeAI('{"RAG":"x","date":"none"}'), FakeVecSearch()))
    assert res.response == ""


def test_parses_fenced_json_and_runs_search(ragworkflow_mod):
    wf = ragworkflow_mod.RAGWorkflow()
    ai = FakeAI('```json\n{"RAG": "echo ejection fraction", "date": "2024-01-04"}\n```')
    vec = FakeVecSearch(documents=[_doc(1)])
    res = wf.run("how is the echo", _ctx(ragworkflow_mod, ai, vec))

    assert vec.search_calls, "expected a vector search"
    call = vec.search_calls[0]
    assert call["patient_id"] == "123"
    assert call["date"] == "2024-01-04"
    assert vec.rank_called and not vec.date_rank_called
    assert res.response == "FINAL ANSWER"


# Regression for former BUG #6: recall must use the extracted RAG query, not the
# raw JSON envelope that search() used to receive.
def test_vector_search_uses_extracted_query_not_raw_json(ragworkflow_mod):
    wf = ragworkflow_mod.RAGWorkflow()
    ai = FakeAI('{"RAG": "echo ejection fraction", "date": "none"}')
    vec = FakeVecSearch(documents=[_doc(1)])
    wf.run("how is the echo", _ctx(ragworkflow_mod, ai, vec))
    assert vec.search_calls[0]["query"] == "echo ejection fraction"


def test_recent_date_uses_date_rank_and_drops_date_filter(ragworkflow_mod):
    wf = ragworkflow_mod.RAGWorkflow()
    ai = FakeAI('{"RAG": "recent labs", "date": "recent"}')
    vec = FakeVecSearch(measurements=[_msr(1)])
    wf.run("recent labs", _ctx(ragworkflow_mod, ai, vec))

    assert vec.date_rank_called and not vec.rank_called
    assert vec.search_calls[0]["date"] is None


def test_sources_include_tool_documents_and_measurements(ragworkflow_mod):
    wf = ragworkflow_mod.RAGWorkflow()
    ai = FakeAI(
        rag='{"RAG": "labs", "date": "none"}',
        tool_response='[{"tool_name": "get_recent_lab_results", "args": {"demo_no": "123"}}]',
    )
    ftools = FakeTools()
    vec = FakeVecSearch(tools=[_tool()], documents=[_doc(1)], measurements=[_msr(1)])
    res = wf.run("labs", _ctx(ragworkflow_mod, ai, vec, tools=ftools))

    kinds = {s["source_type"] for s in res.sources}
    assert {"tool", "document", "measurement"} <= kinds
    assert ftools.calls and ftools.calls[0][0] == "get_recent_lab_results"
    assert ftools.calls[0][1].get("db_conn") == "DB"


def test_maxlen_truncates_document_context(ragworkflow_mod):
    wf = ragworkflow_mod.RAGWorkflow()
    ai = FakeAI('{"RAG": "q", "date": "none"}')
    big = "X" * 2500
    vec = FakeVecSearch(documents=[_doc(i, text=big) for i in range(10)])
    res = wf.run("q", _ctx(ragworkflow_mod, ai, vec))

    doc_sources = [s for s in res.sources if s["source_type"] == "document"]
    assert 1 <= len(doc_sources) < 10
