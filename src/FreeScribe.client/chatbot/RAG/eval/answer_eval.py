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
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor

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


def _load_done(path):
    # (patient, question_id) pairs already in the report, so --resume can skip them.
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                done.add((str(r["patient"]), r["question_id"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def _summarize(path):
    # Aggregate accuracy per question over the WHOLE report (so batched/resumed runs sum up).
    agg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                agg.setdefault(r["question_id"], []).append(int(r.get("correct", 0)))
    print("=" * 60)
    print(f"{'question':22s} {'n':>3s} {'accuracy':>9s}")
    print("-" * 60)
    allv = []
    for qid in sorted(agg):
        v = agg[qid]
        allv += v
        print(f"{qid:22s} {len(v):>3d} {sum(v)/len(v):>9.3f}")
    print("-" * 60)
    if allv:
        print(f"{'OVERALL':22s} {len(allv):>3d} {sum(allv)/len(allv):>9.3f}")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser(
        description="Answer-correctness eval (batchable / resumable)."
    )
    ap.add_argument("--n", type=int, default=AUTO_PICK_N,
                    help="Auto-pick this many patients by measurement volume (ignored if --patients given).")
    ap.add_argument("--patients", default="",
                    help="Comma-separated demographic_no to evaluate (overrides --n).")
    ap.add_argument("--questions", default="",
                    help="Comma-separated question ids to run (default: all gold-set questions).")
    ap.add_argument("--workers", type=int, default=1,
                    help="Parallel LLM workers. >1 is faster but needs an endpoint that allows concurrency.")
    ap.add_argument("--resume", action="store_true",
                    help="Append to the report and skip (patient, question) pairs already in it.")
    ap.add_argument("--report", default=REPORT, help="Report path (default: %(default)s).")
    args = ap.parse_args()

    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    creds = cfg["VectorDB"]
    ai_cfg = cfg["AIConnection"]
    with open(GOLD, "r", encoding="utf-8") as f:
        questions = [q for q in yaml.safe_load(f) if q.get("target_types")]
    if args.questions:
        want = {s.strip() for s in args.questions.split(",") if s.strip()}
        questions = [q for q in questions if q["id"] in want]
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

    if args.patients:
        patients = [p.strip() for p in args.patients.split(",") if p.strip()]
    else:
        patients = PATIENTS if PATIENTS else _pick_patients(cur, args.n)
    print(f"Patients: {patients}")

    done = _load_done(args.report) if args.resume else set()
    if done:
        print(f"Resume: {len(done)} case(s) already in {args.report}; skipping those.")

    # Build the worklist serially -- SQL is fast and the psycopg2 cursor is NOT thread-safe,
    # so all DB reads happen here; only the (slow) LLM calls are parallelized below.
    worklist = []
    n_skip = n_resume = 0
    for patient in patients:
        for q in questions:
            if (str(patient), q["id"]) in done:
                n_resume += 1
                continue
            rows = _expected_rows(cur, patient, q["target_types"], q.get("auto_rule", "latest"))
            if not rows:
                n_skip += 1
                continue
            worklist.append((patient, q, rows))
    total = len(worklist)
    print(f"Cases to run: {total} (skipped {n_skip} empty, {n_resume} already done)")

    lock = threading.Lock()
    counters = {"eval": 0, "unparsed": 0}
    logf = open(args.report, "a" if args.resume else "w", encoding="utf-8")

    def run_one(item):
        patient, q, rows = item
        context = _context_str(rows)
        followup = prompts["followup"].format(user_input=q["query"], context=context)
        answer = ai.send_message(followup)
        judge = JUDGE_PROMPT.format(
            question=q["query"], records=_records_str(rows), answer=answer,
        )
        verdict, reason = _parse_verdict(ai.send_message(judge))
        rec = {
            "patient": patient,
            "question_id": q["id"],
            "query": q["query"],
            "auto_rule": q.get("auto_rule", "latest"),
            "correct": 0 if verdict is None else verdict,
            "reason": reason,
            "answer": answer,
            "records": [
                {"measurement_ids": r[0], "type": r[1], "date": str(r[2])} for r in rows
            ],
        }
        with lock:
            counters["eval"] += 1
            if verdict is None:
                counters["unparsed"] += 1
            logf.write(json.dumps(rec) + "\n")
            logf.flush()
            print(f"  [{counters['eval']}/{total}] {patient} {q['id']} -> {rec['correct']}")

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(run_one, worklist))
    else:
        for item in worklist:
            run_one(item)

    logf.close()
    ragdb.cleanup()

    _summarize(args.report)
    print(f"ran {counters['eval']} this pass; unparsed judge {counters['unparsed']}; "
          f"report {args.report}")


if __name__ == "__main__":
    main()
