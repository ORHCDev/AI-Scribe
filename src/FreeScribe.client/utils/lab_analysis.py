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
- Amiodarone (Amiodarone follow up)
- Digoxin (Digoxin level)

COMPREHENSIVE CARDIAC:
- comprehensive (most complete cardiac panel)
- minicomprehensive (alternative when full panel not needed)
- COMRR (renal risk for statin patients)
- NewCardiomyopathy (new cardiomyopathy/IHD workup)

CHF:
- CHFBaseline (initial CHF workup)
- CHFFollowUp (CHF Follow-up)
- CHFFollowUpStandingQ3months (CHF Standing Order Q3M)
- thiazideFollowUp (CHF Follow-up post thiazide)
- SGLT2FollowUp (CHF Follow-up post SGLT2)
- KFollowUp (CHF Follow-up post high K+)

CKD STAGE 3:
- CKDAnnual (CKD Annual)
- CKDQ6months (eGFR/ACR Q6M - standing order)

DM:
- DMAnnual (DM Annual)
- DMStandingQ3months (A1C Q3M - standing order)

DYSLIPIDEMIA:
- CholesterolFBS (Screening)
- DyslipidemiaOnStatin (check if "lipids" or "lipid profile" is mentioned)

HYPERTENSION:
- HypertensionAnnual (Hypertension Annual)
- NewHypertension (New Hypertension)
- NewHypotension (New Hypotension)

OTHERS:
- Autoimmune (Autoimmune ANA, RF)
- CompleteBloodCount (CBC - check if "cbc" is mentioned)
- Pericarditis (Pericarditis follow up)
- CTDSerology (CTD Workup - connective tissue disease)
- Dementia (Dementia)
- Eatingdisorderworkup (Eating disorder workup)
- Fatigue (Fatigue)
- INRStanding (INR - Standing Order - warfarin)
- LFT (LFTs - check if "lft" or "lfts" is mentioned)
- AcuteElevatedLFT (LFT Elevation Acute)
- ChronicElevatedLFT (LFT Elevation Chronic)
- RenalFunction (check if "renal function", "kidney function and electrolytes", or "kidney function" is mentioned)
- Thrombosisscreen (Thrombosis screen)
- TSHStandingorder (TSH Standing Order)
- UrineC&S (Urine C&S - UTI)

CRITICAL RULES:
1. Return ONLY a JSON array. Do NOT include any explanatory text, comments, or additional content before or after the JSON array.
2. Your response must start with [ and end with ]. No other text.
3. ONLY use code names from the list above. Do NOT invent new code names or use descriptions.
4. If a term in the PLAN doesn't match any checkbox code name in the list above, do NOT include it in your response.

Example PLAN snippet: "Check lipid profile and CBC."
Correct response: ["DyslipidemiaOnStatin", "CompleteBloodCount"]

Example PLAN snippet: "repeat chf follow-up labs in 2 weeks to recheck renal function and electrolytes while patient remains on Lasix."
Correct response: ["RenalFunction ", "CHFFollowUp"]
"""


def analyze_plan_for_labs(plan_text: str, send_text_to_chatgpt_func) -> list[str]:
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
                return ui_labels
        
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

