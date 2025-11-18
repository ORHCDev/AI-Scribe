"""
lab_analysis.py

Lab analysis functionality for extracting lab checkboxes from PLAN sections.
Separated from client.py to keep code organized.
"""

import json


LAB_CHECKBOX_ANALYSIS_PROMPT = """Analyze the medical PLAN section and identify which lab test checkboxes should be checked. Return a JSON array of checkbox names.

Available checkboxes by section:

INSTRUCTIONS:
- Fasting Instructions (do NOT select - auto-added by fasting-required checkboxes)

PRE-PROCEDURE:
- pre-cath
- pre-EP procedure

THERAPEUTIC MONITORING:
- Amiodarone follow up
- Digoxin level

COMPREHENSIVE CARDIAC:
- comprehensive (most complete cardiac panel)
- minicomprehensive (alternative when full panel not needed)
- RR (renal risk for statin patients)
- Cardiomyopathy (new cardiomyopathy/IHD workup)

CHF:
- Baseline (initial CHF workup)
- Follow-up
- Standing Order Q3M
- Follow-up post thiazide
- Follow-up post SGLT2
- Follow-up post high K+

CKD STAGE 3:
- Annual
- eGFR/ACR Q6M (standing order)

DM:
- DM Annual
- A1C Q3M (standing order)

DYSLIPIDEMIA:
- Screening
- On Statin

HYPERTENSION:
- Hypertension Annual
- Hypertension (new hypertension)
- Hypotension

OTHERS:
- Autoimmune ANA, RF
- CBC
- Pericarditis follow up
- CTD Workup (connective tissue disease)
- Dementia
- Eating disorder workup
- Fatigue
- INR - Standing Order (warfarin)
- LFTs (routine liver function)
- LFT Elevation Acute (recently elevated - mutually exclusive with Chronic)
- LFT Elevation Chronic (long-standing - mutually exclusive with Acute)
- Renal Function (RAAS start) (before ACE/ARB)
- Thrombosis screen
- TSH Standing Order
- Urine C&S (UTI)

Return ONLY a JSON array matching the PLAN. Do NOT include "Fasting Instructions".

Example: ["Renal Function (RAAS start)", "On Statin"]"""


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
        json_start = response.find("[")
        json_end = response.rfind("]") + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = response[json_start:json_end]
            checkbox_labels = json.loads(json_str)
            
            # Validate that it's a list of strings
            if isinstance(checkbox_labels, list):
                return [str(label) for label in checkbox_labels if isinstance(label, str)]
        
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

