"""
Answer-correctness eval (stage 4 in isolation). Given the deterministically
correct context (the exact type+date records get_measurements would return), run
the real followup prompt to produce an answer, then score whether the answer is
faithful to and supported by those records via an LLM judge. This does not test
retrieval or routing -- it isolates whether the model answers correctly WHEN it
is handed the right records. A per-case diagnostic (context, answer, verdict,
reason) is written to REPORT.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import yaml

from chatbot.RAG.VectorSearch import VectorDB, VectorSearch
from chatbot.AIConnect import AIConnect

CONFIG = "configs/config.yaml"
GOLD = "chatbot/RAG/eval/gold_set.example.yaml"
PROMPTS = "prompts/chatbot_prompts.yaml"
PATIENTS = None
AUTO_PICK_N = 10
REPORT = "answer_eval_report.jsonl"

JUDGE_PROMPT = """You are grading a clinical assistant's answer.

You are given a user's question, the SOURCE RECORDS that are the only ground
truth, and the assistant's ANSWER. Decide if the answer is correct: it must be
factually supported by the source records, must not invent values or findings,
must report the value the question asks for (for "most recent/latest" questions
it must use the newest record), and a "no findings / none documented" answer is
correct when the records do not contain the asked-for finding.

Question:
"{question}"

Source records:
{records}

Answer:
"{answer}"

Respond with ONLY JSON:
{{"correct": 0 or 1, "reason": "<one short sentence>"}}
"""


def _expected_rows(cur, patient, target_types, rule):
    placeholders = ",".join(["%s"] * len(target_types))
    if rule == "all":
        cur.execute(
            f"SELECT measurement_ids, measurement_type, observation_date, chunk_text "
            f"FROM measurement_chunks "
            f"WHERE demographic_no = %s AND measurement_type IN ({placeholders});",
            (patient, *target_types),
        )
        return cur.fetchall()
    cur.execute(
        f"SELECT measurement_ids, measurement_type, observation_date, chunk_text "
        f"FROM measurement_chunks "
        f"WHERE demographic_no = %s AND measurement_type IN ({placeholders}) "
        f"AND observation_date = ("
        f"  SELECT MAX(observation_date) FROM measurement_chunks "
        f"  WHERE demographic_no = %s AND measurement_type IN ({placeholders})"
        f");",
        (patient, *target_types, patient, *target_types),
    )
    return cur.fetchall()


def _pick_patients(cur, n):
    cur.execute(
        "SELECT demographic_no FROM measurement_chunks "
        "GROUP BY demographic_no ORDER BY COUNT(*) DESC LIMIT %s;",
        (n,),
    )
    return [r[0] for r in cur.fetchall()]


def _context_str(rows):
    out = ""
    for r in rows:
        date = r[2].strftime("%Y-%m-%d") if r[2] else ""
        out += f"Date Observed: {date}\nDocument ID: {r[0]}\nContent:{r[3]}\n\n"
    return f"Document Context:\n{out}"


def _records_str(rows):
    out = ""
    for r in rows:
        date = r[2].strftime("%Y-%m-%d") if r[2] else ""
        out += f"- [{r[1]} {date}] {r[3]}\n"
    return out


def _parse_verdict(resp):
    resp = resp.replace("```json", "").replace("```", "").strip()
    start = resp.find("{")
    end = resp.rfind("}")
    if start == -1 or end == -1:
        return None, resp
    try:
        v = json.loads(resp[start:end + 1])
        return int(v.get("correct", 0)), str(v.get("reason", ""))
    except (json.JSONDecodeError, ValueError):
        return None, resp


def main():
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    creds = cfg["VectorDB"]
    ai_cfg = cfg["AIConnection"]
    with open(GOLD, "r", encoding="utf-8") as f:
        questions = [q for q in yaml.safe_load(f) if q.get("target_types")]
    with open(PROMPTS, "r", encoding="utf-8") as f:
        prompts = yaml.safe_load(f)

    ragdb = VectorDB(
        host=creds["host"], port=creds["port"], dbname=creds["dbname"],
        user=creds["user"], password=creds["password"],
    )
    ai = AIConnect(
        ai_cfg["endpoint"], api_key=ai_cfg["api_key"],
        headers=ai_cfg.get("headers", {}), top_p=0.25, top_k=20,
    )
    cur = ragdb.cursor

    patients = PATIENTS if PATIENTS else _pick_patients(cur, AUTO_PICK_N)
    print(f"Patients: {patients}\n")

    results = {q["id"]: [] for q in questions}
    n_eval = n_skip = n_unparsed = 0

    with open(REPORT, "w", encoding="utf-8") as log:
        for patient in patients:
            for q in questions:
                rule = q.get("auto_rule", "latest")
                rows = _expected_rows(cur, patient, q["target_types"], rule)
                if not rows:
                    n_skip += 1
                    continue

                context = _context_str(rows)
                followup = prompts["followup"].format(user_input=q["query"], context=context)
                answer = ai.send_message(followup)

                judge = JUDGE_PROMPT.format(
                    question=q["query"], records=_records_str(rows), answer=answer,
                )
                verdict, reason = _parse_verdict(ai.send_message(judge))
                if verdict is None:
                    n_unparsed += 1
                    verdict = 0
                results[q["id"]].append(verdict)
                n_eval += 1

                log.write(json.dumps({
                    "patient": patient,
                    "question_id": q["id"],
                    "query": q["query"],
                    "auto_rule": rule,
                    "correct": verdict,
                    "reason": reason,
                    "answer": answer,
                    "records": [
                        {"measurement_ids": r[0], "type": r[1], "date": str(r[2])}
                        for r in rows
                    ],
                }) + "\n")

    ragdb.cleanup()

    print("=" * 60)
    print(f"{'question':22s} {'n':>3s} {'accuracy':>9s}")
    print("-" * 60)
    allv = []
    for q in questions:
        v = results[q["id"]]
        if not v:
            print(f"{q['id']:22s}   0")
            continue
        allv += v
        print(f"{q['id']:22s} {len(v):>3d} {sum(v)/len(v):>9.3f}")
    print("-" * 60)
    if allv:
        print(f"{'OVERALL':22s} {len(allv):>3d} {sum(allv)/len(allv):>9.3f}")
    print("=" * 60)
    print(f"evaluated {n_eval}; skipped {n_skip}; unparsed judge {n_unparsed}; "
          f"diagnostics in {REPORT}")


if __name__ == "__main__":
    main()
