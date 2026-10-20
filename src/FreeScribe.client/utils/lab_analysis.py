"""
lab_analysis.py

Lab analysis functionality for extracting lab checkboxes from PLAN sections.
Separated from client.py to keep code organized.
"""

import json


LAB_CHECKBOX_ANALYSIS_PROMPT = """Analyze the medical PLAN section and identify which lab test checkboxes should be checked on a requisition form. Return a JSON array of eform checkbox code names.

Available checkboxes by section (use the CODE NAME, not the description):

INSTRUCTIONS:
- FastingInfo (do NOT select - auto-added by fasting-required checkboxes)

PRE-PROCEDURE:
- cath (pre-cath procedure)
- EP (pre-EP procedure)

THERAPEUTIC MONITORING:
- Amiodarone (Amiodarone follow up - should be checked when Amiodarone is started or the dose is changed)
- Digoxin (Digoxin level - should be checked when Digoxin is started or the dose is changed)

COMPREHENSIVE CARDIAC:
- comprehensive (most complete cardiac panel - should be checked when comprehensive or full blood work is requested)
- minicomprehensive (alternative when full panel not needed - should be checked when testing LP(a)/lipoprotein A)
- COMRR (renal risk for statin patients - should be checked when CK is requested)
- NewCardiomyopathy (new cardiomyopathy/IHD workup - should be checked when the plan requests a work-up for cardiomyopathy)

CHF:
- CHFBaseline (initial CHF workup)
- CHFFollowUp (CHF Follow-up - the default checkbox when follow-up lab work is requested for a CHF patient; mentioning CHF alone does not count)
- CHFFollowUpStandingQ3months (CHF Standing Order Q3M)
- thiazideFollowUp (CHF Follow-up post thiazide - should be checked when a thiazide drug is started, stopped, increased or decreased - HCTZ/hydrochlorothiazide, Indapamide, chlorthalidone)
- SGLT2FollowUp (CHF Follow-up post SGLT2 - should be checked when a SGLT2 drug is started, stopped, increased or decreased - dapagliflozin/Forxiga, Canagliflozin, empagliflozin/Jardiance)
- KFollowUp (CHF Follow-up post high K+)

CKD STAGE 3:
- CKDAnnual (CKD Annual)
- CKDQ6months (eGFR/ACR Q6M - standing order)

DM:
- DMAnnual (DM Annual)
- DMStandingQ3months (A1C Q3M - standing order)

DYSLIPIDEMIA:
- CholesterolFBS (Screening)
- DyslipidemiaOnStatin (On Statin - should be checked when a statin drug is started, stopped, increased or decreased - lipitor/atorvastatin, Crestor/rosuvastatin, Zocor/simvastatin, Pravachol/pravastatin, lovastatin; also when "lipids" or a "lipid profile" is requested)

HYPERTENSION:
- HypertensionAnnual (if the plan explicitly requests Hypertension Annual lab work)
- NewHypertension (if the plan explicitly requests New Hypertension lab work)
- NewHypotension (if the plan explicitly requests New Hypotension lab work)

OTHERS:
- Autoimmune (Autoimmune ANA, RF)
- CompleteBloodCount (CBC - check if a CBC is requested)
- Pericarditis (Pericarditis follow up)
- CTDSerology (CTD Workup - connective tissue disease)
- Dementia (Dementia)
- Eatingdisorderworkup (Eating disorder workup)
- Fatigue (Fatigue)
- INRStanding (INR - Standing Order - warfarin)
- LFT (LFTs - check if LFTs are requested)
- AcuteElevatedLFT (LFT Elevation Acute)
- ChronicElevatedLFT (LFT Elevation Chronic)
- RenalFunction (check if renal function, kidney function and electrolytes, or kidney function tests are requested, or if any ACe inhibitor or ARB is started/stopped/increased/decreased: Ramipril/Altace, Coversyl/perindopril, Mavik/Trandolapril, Enalapril, Quinapril, Atacand/Candesartan, Diovan/valsartan, Olmetec/Olmesartan, Micardis/Telmisartan, Losartan)
- Thrombosisscreen (Thrombosis screen)
- TSHStandingorder (TSH Standing Order)
- UrineC&S (Urine C&S - UTI)

CRITICAL RULES:
0. Only include checkboxes for lab work the PLAN actually orders or requests at this visit (to be done now
   or by a future date), or that the medication-change rules above require. Do NOT include a checkbox
   because a test or diagnosis is only mentioned, reviewed, discussed, or because previous results are
   reported (e.g. "recent CBC was normal", "we discussed his cholesterol", "known CHF, stable"). If
   nothing is requested, return [].
1. Return ONLY a JSON array. Do NOT include any explanatory text, comments, or additional content before or after the JSON array.
2. Your response must start with [ and end with ]. No other text.
3. ONLY use code names from the list above. Do NOT invent new code names or use descriptions.
4. If a term in the PLAN doesn't match any checkbox code name in the list above, do NOT include it in your response.
5. Include EVERY checkbox that applies to the PLAN. Only one box is ticked on the form in the end (the one
   with the most tests), and that choice is made after your answer, so do not drop matches yourself.

Example PLAN snippet: "Check lipid profile and CBC."
Correct response: ["DyslipidemiaOnStatin", "CompleteBloodCount"]

Example PLAN snippet: "repeat chf follow-up labs in 2 weeks to recheck renal function and electrolytes while patient remains on Lasix."
Correct response: ["RenalFunction ", "CHFFollowUp"]
"""


def analyze_plan_for_labs(plan_text: str, send_text_to_chatgpt_func, map_response: bool = True) -> list[str]:
    """
    Analyze PLAN section text using LLM to identify which lab checkboxes should be checked.
    
    Args:
        plan_text: The PLAN section text from a medical note
        send_text_to_chatgpt_func: Function to call LLM (e.g., send_text_to_chatgpt)
        
    Returns:
        List of UI label strings for checkboxes that should be checked
    """
    if not plan_text or not plan_text.strip():
        return []
    
    try:
        # Call LLM with the prompt and plan text
        full_prompt = f"{LAB_CHECKBOX_ANALYSIS_PROMPT}\n\nPLAN text:\n{plan_text}"
        response = send_text_to_chatgpt_func(full_prompt)
        
        # Parse JSON response
        # Try to extract JSON from response (handle cases where LLM adds extra text)
        response = response.strip()
        
        # Remove markdown code blocks if present
        if response.startswith("```"):
            # Find the first newline after ```
            start_idx = response.find("\n") + 1
            # Find the last ```
            end_idx = response.rfind("```")
            if end_idx > start_idx:
                response = response[start_idx:end_idx].strip()
        elif response.startswith("```json"):
            start_idx = response.find("\n") + 1
            end_idx = response.rfind("```")
            if end_idx > start_idx:
                response = response[start_idx:end_idx].strip()
        
        # Try to find JSON array in the response
        # Look for the last complete JSON array (in case LLM provides multiple)
        json_start = response.rfind("[")
        json_end = response.rfind("]") + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = response[json_start:json_end]
            try:
                checkbox_code_names = json.loads(json_str)
            except json.JSONDecodeError:
                # If that fails, try finding all JSON arrays and use the longest one
                import re
                json_arrays = re.findall(r'\[[^\]]*\]', response)
                if json_arrays:
                    # Use the longest array (most likely to be complete)
                    json_str = max(json_arrays, key=len)
                    checkbox_code_names = json.loads(json_str)
                else:
                    raise
            
            # Validate that it's a list of strings
            if isinstance(checkbox_code_names, list):
                # Convert eform code names back to UI labels
                from utils.lab_checkbox_mapping import get_ui_label
                if map_response:
                    ui_labels = []
                    for code_name in checkbox_code_names:
                        code_name_str = str(code_name).strip()
                        ui_label = get_ui_label(code_name_str)
                        if ui_label:
                            ui_labels.append(ui_label)
                        else:
                            # If code name not found, warn and skip
                            print(f"Warning: Could not map code name '{code_name}' to UI label")
                    return ui_labels
                else:
                    return checkbox_code_names
        
        print(f"Failed to parse LLM response as JSON: {response}")
        return []
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error in analyze_plan_for_labs: {e}")
        if 'response' in locals():
            print(f"Response was: {response}")
        return []
    except Exception as e:
        print(f"Error in analyze_plan_for_labs: {e}")
        import traceback
        traceback.print_exc()
        return []


# --- one checkbox per form ----------------------------------------------------------------------

import re as _re

_X_BOX = _re.compile(r"document\.lab\.(\w+)\.value\s*=\s*'X'")
_OTHER_TESTS = _re.compile(r"add\(\s*'OtherTests'\s*,\s*'([^']*)'\s*\)")


def count_lab_tests(onclick: str | None) -> int:
    """Number of tests a lab eForm checkbox orders: distinct X-boxes it marks plus the items it adds to
    "Other Tests" (split on commas, newlines and '&')."""
    onclick = onclick or ""
    x_boxes = set(_X_BOX.findall(onclick))
    other = []
    for chunk in _OTHER_TESTS.findall(onclick):
        other += [p.strip() for p in _re.split(r",|\\n|&|\n", chunk) if p.strip()]
    return len(x_boxes) + len(other)


def pick_most_extensive(checkboxes: list[dict]) -> list[dict]:
    """Keep only the checkbox (from Oscar.get_eform_checkboxes) that orders the most tests. Ties go to
    the one that comes first on the form. Returns [] or a one-element list."""
    if not checkboxes:
        return []
    best = max(enumerate(checkboxes), key=lambda pair: (count_lab_tests(pair[1].get("onclick")), -pair[0]))[1]
    if len(checkboxes) > 1:
        ranked = ", ".join(f"{cb['name'].strip()}={count_lab_tests(cb.get('onclick'))}" for cb in checkboxes)
        print(f"Lab eForm: only one checkbox per form; keeping {best['name'].strip()!r} (tests: {ranked})")
    return [best]
