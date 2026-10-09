"""
Layer 3: how well the real model drives the medication eForm (manual eval, not a pytest test).

Each case in a gold YAML file gives one of:
  plan:        PLAN text                        -> extraction
  note:        a full consult note              -> extract_plan_section -> extraction
  transcript:  a mock visit transcript          -> note (needs --note-prompt) -> PLAN -> extraction
plus the expected outcome:
  expect_open:   should the medication eForm open?
  expect_lines:  exact prescription-body lines expected (order-insensitive), optional
  expect_labs:   should the labs eForm open? optional

The model is called exactly like the app's send_text_to_api (OpenAI-style /chat/completions), using
the app's settings.txt by default, so results reflect the model the clinic actually runs.

Usage (from src/FreeScribe.client):
  python tests/med_eform/eval_med_extraction.py tests/med_eform/med_extraction_gold.example.yaml
  python tests/med_eform/eval_med_extraction.py gold.yaml --settings path/to/settings.txt --runs 3
  python tests/med_eform/eval_med_extraction.py gold.yaml --note-prompt my_consult_prompt.txt

Do not put real patient text in gold files that are committed; keep those as *.phi.yaml (untracked).
"""

import argparse
import json
import sys
from pathlib import Path

import requests
import yaml

CLIENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CLIENT_ROOT))

from utils import med_eform  # noqa: E402


def make_sender(settings_path, endpoint=None, model=None, api_key=None):
    """Build send(prompt) -> str mirroring client.send_text_to_api for the given settings file."""
    settings = {}
    if settings_path and Path(settings_path).exists():
        settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    editable = settings.get("editable_settings", {})
    endpoint = (endpoint or editable.get("Model Endpoint", "")).rstrip("/")
    model = (model or editable.get("Model", "")).strip()
    key = api_key or settings.get("openai_api_key", "")
    if not endpoint or not model:
        sys.exit("No model endpoint/model: pass --settings pointing at the app's settings.txt, "
                 "or --endpoint and --model.")

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "accept": "application/json"}
    try:
        headers.update(json.loads(editable.get("Model Headers") or "{}"))
    except (json.JSONDecodeError, TypeError):
        pass
    verify = not editable.get("AI Server Self-Signed Certificates", False)

    def num(name, default, cast):
        try:
            return cast(editable.get(name, default))
        except (TypeError, ValueError):
            return default

    def send(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": num("temperature", 0.1, float),
            "top_p": num("top_p", 0.4, float),
        }
        resp = requests.post(endpoint + "/chat/completions", headers=headers, json=payload,
                             verify=verify, timeout=300)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    print(f"Model: {model} @ {endpoint}")
    return send


def load_extract_plan_section():
    """utils/read_files.extract_plan_section without importing its OCR/PDF dependencies."""
    import importlib.util
    import types
    for name in ("cv2", "pytesseract", "numpy", "pdf2image", "PIL", "PIL.Image"):
        if name not in sys.modules:
            try:
                __import__(name)
            except Exception:
                sys.modules[name] = types.ModuleType(name)
    sys.modules["pdf2image"].__dict__.setdefault("convert_from_path", None)
    sys.modules["pdf2image"].__dict__.setdefault("convert_from_bytes", None)
    sys.modules["PIL"].__dict__.setdefault("Image", sys.modules["PIL.Image"])
    spec = importlib.util.spec_from_file_location("read_files", CLIENT_ROOT / "utils" / "read_files.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.extract_plan_section


def scope_for(case, send, note_prompt, extract_plan_section):
    """Return (scope, note) the way the app builds it: PLAN section, else the whole note."""
    if "plan" in case:
        return case["plan"], None
    if "note" in case:
        note = case["note"]
    elif "transcript" in case:
        if not note_prompt:
            raise ValueError("transcript case needs --note-prompt")
        note = send(f"{note_prompt} {case['transcript']}")
    else:
        raise ValueError("case needs plan, note, or transcript")
    return (extract_plan_section(note) or note), note


def lines_of(changes):
    text = med_eform.format_rx_lines(changes)
    return sorted(p.strip() for p in text.split(",\n") if p.strip().rstrip(","))


def norm(lines):
    # Case-insensitive: "Stop amlodipine" vs "Stop Amlodipine" is the same instruction; doses,
    # frequencies and LU codes still have to match character for character.
    return sorted(l.strip().rstrip(",").strip().lower() for l in lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gold", help="gold YAML file")
    ap.add_argument("--settings", default=str(CLIENT_ROOT / "settings.txt"), help="app settings.txt")
    ap.add_argument("--endpoint"), ap.add_argument("--model"), ap.add_argument("--api-key")
    ap.add_argument("--note-prompt", help="text file with the note-generation prompt (for transcript cases)")
    ap.add_argument("--runs", type=int, default=1, help="repeat each case to see run-to-run variation")
    ap.add_argument("--show-notes", action="store_true", help="print generated notes (transcript cases)")
    args = ap.parse_args()

    cases = yaml.safe_load(Path(args.gold).read_text(encoding="utf-8")) or []
    send = make_sender(args.settings, args.endpoint, args.model, args.api_key)
    note_prompt = Path(args.note_prompt).read_text(encoding="utf-8") if args.note_prompt else None
    extract_plan_section = load_extract_plan_section()

    totals = {"open": [0, 0], "lines": [0, 0], "labs": [0, 0], "fallback": 0, "runs": 0}
    for i, case in enumerate(cases, 1):
        label = case.get("id", f"case {i}")
        for run in range(args.runs):
            totals["runs"] += 1
            scope, note = scope_for(case, send, note_prompt, extract_plan_section)
            if note is not None and args.show_notes:
                print(f"\n--- generated note ({label}) ---\n{note}\n")
            try:
                got = med_eform.extract_med_changes(scope.strip(), send)
                fallback = False
            except Exception as e:
                # Same fallback the app uses: keyword decision, nothing pre-filled.
                flags = med_eform.keyword_flags(scope)
                got = {"open": flags["medication"], "changes": [], "labs": flags["labs"]}
                fallback = True
                totals["fallback"] += 1
                print(f"  [{label}] model output unusable -> keyword fallback ({e})")

            problems = []
            ok_open = got["open"] == case["expect_open"]
            totals["open"][0] += ok_open
            totals["open"][1] += 1
            if not ok_open:
                problems.append(f"open={got['open']} expected {case['expect_open']}")
            if "expect_lines" in case:
                got_lines = norm(lines_of(got["changes"]))
                want = norm(case["expect_lines"])
                ok_lines = got_lines == want
                totals["lines"][0] += ok_lines
                totals["lines"][1] += 1
                if not ok_lines:
                    problems.append(f"lines={got_lines} expected {want}")
            if "expect_labs" in case:
                ok_labs = got["labs"] == case["expect_labs"]
                totals["labs"][0] += ok_labs
                totals["labs"][1] += 1
                if not ok_labs:
                    problems.append(f"labs={got['labs']} expected {case['expect_labs']}")

            run_tag = f" run {run + 1}" if args.runs > 1 else ""
            status = "PASS" if not problems else "FAIL"
            print(f"{status} {label}{run_tag}{' (fallback)' if fallback else ''}")
            for p in problems:
                print(f"     {p}")

    def pct(pair):
        return f"{pair[0]}/{pair[1]} ({100 * pair[0] / pair[1]:.0f}%)" if pair[1] else "n/a"

    print("\n=== summary ===")
    print(f"open decision correct : {pct(totals['open'])}")
    print(f"prescription lines    : {pct(totals['lines'])}")
    print(f"labs decision correct : {pct(totals['labs'])}")
    print(f"keyword fallbacks     : {totals['fallback']}/{totals['runs']}")


if __name__ == "__main__":
    main()
