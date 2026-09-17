"""
Routing eval: does the tool-selection LLM pick the right tool for a question,
given only the question text? This exercises the real RAGWorkflow tool stage
(vector tool search -> cross-encoder rank -> tool prompt -> LLM), which the
retrieval evals skip. Each case carries expected_tool (any-of acceptable tools,
or [] for no tool), so both under-selection and over-selection are measured, per
tool and for get_measurements specifically. Negatives (no target_types) probe
whether get_measurements is wrongly chosen. Also dumps distinct measurement_type
values to keep the tool description aligned. No LLM answer step.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import yaml

import chatbot.Tools  # noqa: F401
from chatbot.Tools.Tool import ToolEmbeddings, TOOL_REGISTRY
from chatbot.RAG.VectorSearch import VectorDB, VectorSearch
from chatbot.AIConnect import AIConnect

CONFIG = "configs/config.yaml"
GOLD = "chatbot/RAG/eval/gold_set.example.yaml"
PROMPTS = "prompts/chatbot_prompts.yaml"
TOOL_EMBDS = "chatbot/Tools/tool_embeddings.jsonl"
TARGET_TOOL = "get_measurements"
DEMO = "18931"
RETRIEVE_K = 10
REPORT = "routing_eval_report.jsonl"


def _distinct_types(cur):
    cur.execute("SELECT DISTINCT measurement_type FROM measurement_chunks ORDER BY 1;")
    return [r[0] for r in cur.fetchall()]


def _chunks_from(embeddings):
    chunks = []
    for t in embeddings["tools"] or []:
        chunks.append({
            "tool_name": t["tool_name"], "text": t["description"],
            "args": t["metadata"]["params"], "is_tool": True,
        })
    for d in embeddings["documents"]:
        chunks.append({
            "id": d["document_id"], "type": d["document_type"],
            "obs_date": d["observation_date"], "text": d["chunk_text"],
            "is_tool": False, "source_type": "document",
        })
    for m in embeddings["measurements"]:
        chunks.append({
            "id": m["measurement_ids"], "type": m["measurement_type"],
            "obs_date": m["observation_date"], "text": m["chunk_text"],
            "is_tool": False, "source_type": "measurement",
        })
    return chunks


def _parse_tools(resp):
    resp = resp.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
    if not resp.startswith("["):
        return []
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        return []


def _norm(v):
    if isinstance(v, str):
        return {v.strip().upper()}
    if isinstance(v, (list, tuple)):
        out = set()
        for x in v:
            out |= _norm(x)
        return out
    return set()


def _rate(items, key):
    vals = [x[key] for x in items if x[key] is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _pr(tp, fp, fn):
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    creds = cfg["VectorDB"]
    ai_cfg = cfg["AIConnection"]
    with open(GOLD, "r", encoding="utf-8") as f:
        questions = [q for q in yaml.safe_load(f) if "expected_tool" in q]
    with open(PROMPTS, "r", encoding="utf-8") as f:
        prompts = yaml.safe_load(f)

    ragdb = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    print("Loading models (embedder + MedCPT cross-encoder) ...")
    tool_embds = ToolEmbeddings(path=TOOL_EMBDS)
    vs = VectorSearch(ragdb, tool_embds)
    ai = AIConnect(
        ai_cfg["endpoint"], api_key=ai_cfg["api_key"],
        headers=ai_cfg.get("headers", {}), top_p=0.25, top_k=20,
    )

    db_types = _distinct_types(ragdb.cursor)
    print(f"\nmeasurement_type values in DB ({len(db_types)}):")
    print("  " + ", ".join(str(t) for t in db_types) + "\n")

    embedded = {t["tool_name"] for t in tool_embds.tools}
    if TARGET_TOOL not in embedded:
        print(f"WARNING: {TARGET_TOOL} has no embedding; run store_tool_embeddings first\n")

    rows = []
    gm = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    per_tool = {}

    with open(REPORT, "w", encoding="utf-8") as log:
        for q in questions:
            exp_tools = set(q.get("expected_tool") or [])
            is_msr = bool(q.get("target_types"))
            exp_mode = ("all" if q.get("auto_rule") == "all" else "latest") if is_msr else None
            exp_types = _norm(q["target_types"]) if is_msr else set()

            for phrasing in [q["query"]] + (q.get("phrasings") or []):
                embeddings = vs.search(
                    query=phrasing, patient_id=DEMO, top_k=RETRIEVE_K, to_dict=True,
                )
                chunks = _chunks_from(embeddings)
                reranked = vs.rank(phrasing, chunks, key="text", batch_size=8)
                top = reranked[:RETRIEVE_K]

                tool_str = ""
                for elem in top:
                    if elem[1]["is_tool"]:
                        tool_str += f"{elem[1]}\n"
                offered = TARGET_TOOL in tool_str

                names, sel_types, sel_mode = [], set(), None
                if tool_str:
                    prompt = prompts["rag_tool_prompt"].format(
                        tool_protocol=prompts["rag_tool_protocol"],
                        demo_no=DEMO, user_input=phrasing, tools=tool_str,
                    )
                    resp = ai.send_message(prompt)
                    selected = _parse_tools(resp)
                    names = [t.get("tool_name") for t in selected]
                    if TARGET_TOOL in names:
                        args = next(t.get("args", {}) for t in selected if t.get("tool_name") == TARGET_TOOL)
                        sel_types = _norm(args.get("types"))
                        sel_mode = str(args.get("mode", "")).lower() or None

                name_set = set(names)
                picked_gm = TARGET_TOOL in name_set
                routing_ok = bool(name_set & exp_tools) if exp_tools else (len(name_set) == 0)
                type_ok = (picked_gm and bool(sel_types & exp_types)) if is_msr else None
                type_full = (picked_gm and exp_types <= sel_types) if is_msr else None
                mode_ok = (picked_gm and sel_mode == exp_mode) if is_msr else None

                gm_exp = TARGET_TOOL in exp_tools
                if gm_exp and picked_gm:
                    gm["tp"] += 1
                elif gm_exp and not picked_gm:
                    gm["fn"] += 1
                elif not gm_exp and picked_gm:
                    gm["fp"] += 1
                else:
                    gm["tn"] += 1

                for t in exp_tools | name_set:
                    d = per_tool.setdefault(t, {"tp": 0, "fp": 0, "fn": 0})
                    if t in exp_tools and t in name_set:
                        d["tp"] += 1
                    elif t in exp_tools:
                        d["fn"] += 1
                    else:
                        d["fp"] += 1

                rows.append({
                    "id": q["id"], "picked_gm": picked_gm, "routing_ok": routing_ok,
                    "type_ok": type_ok, "type_full": type_full, "mode_ok": mode_ok,
                })
                log.write(json.dumps({
                    "question_id": q["id"], "phrasing": phrasing,
                    "expected_tool": sorted(exp_tools),
                    "expected_types": sorted(exp_types), "expected_mode": exp_mode,
                    "offered": offered, "selected_tools": names,
                    "selected_types": sorted(sel_types), "selected_mode": sel_mode,
                    "routing_ok": routing_ok, "picked_gm": picked_gm,
                    "type_ok": type_ok, "type_full": type_full, "mode_ok": mode_ok,
                }) + "\n")

    ragdb.cleanup()

    def cell(v):
        return f"{v:.2f}" if v is not None else "   -"

    print("=" * 84)
    print(f"{'question':18s} {'n':>3s} {'route_ok':>8s} {'pick_gm':>7s} "
          f"{'type_ok':>8s} {'type_full':>9s} {'mode_ok':>8s}")
    print("-" * 84)
    for q in questions:
        grp = [r for r in rows if r["id"] == q["id"]]
        if not grp:
            continue
        print(f"{q['id']:18s} {len(grp):>3d} {_rate(grp,'routing_ok'):>8.2f} "
              f"{_rate(grp,'picked_gm'):>7.2f} {cell(_rate(grp,'type_ok')):>8s} "
              f"{cell(_rate(grp,'type_full')):>9s} {cell(_rate(grp,'mode_ok')):>8s}")
    print("-" * 84)
    print(f"{'OVERALL route_ok':18s} {len(rows):>3d} {_rate(rows,'routing_ok'):>8.2f}")
    print("=" * 84)

    prec, rec, f1 = _pr(gm["tp"], gm["fp"], gm["fn"])
    print(f"\nget_measurements  precision {prec:.2f}  recall {rec:.2f}  f1 {f1:.2f}  "
          f"(tp {gm['tp']} fp {gm['fp']} fn {gm['fn']} tn {gm['tn']})\n")

    print(f"{'tool':28s} {'prec':>5s} {'rec':>5s} {'f1':>5s}  tp/fp/fn")
    print("-" * 60)
    for t in sorted(per_tool):
        d = per_tool[t]
        p, r, f = _pr(d["tp"], d["fp"], d["fn"])
        print(f"{t:28s} {p:>5.2f} {r:>5.2f} {f:>5.2f}  {d['tp']}/{d['fp']}/{d['fn']}")
    print(f"\ndiagnostics in {REPORT}")


if __name__ == "__main__":
    main()
