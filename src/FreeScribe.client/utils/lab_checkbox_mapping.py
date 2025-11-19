"""
Mapping between UI checkbox labels and OSCAR eform checkbox names for 1.2LabCardiacP.

This mapping is used to translate between:
- Human-readable labels shown in the UI
- Exact checkbox names used in the OSCAR eform HTML
"""

# Mapping: UI Label -> Eform Checkbox Name
LAB_CHECKBOX_MAPPING = {
    # INSTRUCTIONS
    "Fasting Instructions": "FastingInfo",
    
    # PRE-PROCEDURE
    "pre-cath": "cath",
    "pre-EP procedure": "EP",
    
    # THERAPEUTIC MONITORING
    "Amiodarone follow up": "Amiodarone",
    "Digoxin level": "Digoxin",
    
    # COMPREHENSIVE CARDIAC
    "comprehensive": "comprehensive",
    "minicomprehensive": "minicomprehensive",
    "RR": "COMRR",
    "Cardiomyopathy": "NewCardiomyopathy",
    
    # CHF
    "CHF Baseline": "CHFBaseline",
    "CHF Follow-up": "CHFFollowUp",
    "CHF Standing Order Q3M": "CHFFollowUpStandingQ3months",
    "CHF Follow-up post thiazide": "thiazideFollowUp",
    "CHF Follow-up post SGLT2": "SGLT2FollowUp",
    "CHF Follow-up post high K+": "KFollowUp",
    
    # CKD STAGE 3
    "CKD Annual": "CKDAnnual",
    "eGFR/ACR Q6M": "CKDQ6months",
    
    # DM
    "DM Annual": "DMAnnual",
    "A1C Q3M": "DMStandingQ3months",
    
    # DYSLIPIDEMIA
    "Screening": "CholesterolFBS",
    "On Statin": "DyslipidemiaOnStatin",
    
    # HYPERTENSION
    "Hypertension Annual": "HypertensionAnnual",
    "New Hypertension": "NewHypertension",
    "New Hypotension": "NewHypotension",
    
    # OTHERS
    "Autoimmune ANA, RF": "Autoimmune",
    "CBC": "CompleteBloodCount",
    "Pericarditis follow up": "Pericarditis",
    "CTD Workup": "CTDSerology",
    "Dementia": "Dementia",
    "Eating disorder workup": "Eatingdisorderworkup",
    "Fatigue": "Fatigue",
    "INR - Standing Order": "INRStanding",
    "LFTs": "LFT",
    "LFT Elevation Acute": "AcuteElevatedLFT",
    "LFT Elevation Chronic": "ChronicElevatedLFT",
    "Renal Function (RAAS start)": "RenalFunction",
    "Thrombosis screen": "Thrombosisscreen",
    "TSH Standing Order": "TSHStandingorder",
    "Urine C&S": "UrineC&S",
}

# Reverse mapping: Eform Checkbox Name -> UI Label (for display)
EFORM_TO_UI_LABEL = {v: k for k, v in LAB_CHECKBOX_MAPPING.items()}

# Categories for organizing checkboxes in UI
LAB_CHECKBOX_CATEGORIES = {
    "INSTRUCTIONS": [
        "Fasting Instructions",
    ],
    "PRE-PROCEDURE": [
        "pre-cath",
        "pre-EP procedure",
    ],
    "THERAPEUTIC MONITORING": [
        "Amiodarone follow up",
        "Digoxin level",
    ],
    "COMPREHENSIVE CARDIAC": [
        "comprehensive",
        "minicomprehensive",
        "RR",
        "Cardiomyopathy",
    ],
    "CHF": [
        "CHF Baseline",
        "CHF Follow-up",
        "CHF Standing Order Q3M",
        "CHF Follow-up post thiazide",
        "CHF Follow-up post SGLT2",
        "CHF Follow-up post high K+",
    ],
    "CKD STAGE 3": [
        "CKD Annual",
        "eGFR/ACR Q6M",
    ],
    "DM": [
        "DM Annual",
        "A1C Q3M",
    ],
    "DYSLIPIDEMIA": [
        "Screening",
        "On Statin",
    ],
    "HYPERTENSION": [
        "Hypertension Annual",
        "New Hypertension",
        "New Hypotension",
    ],
    "OTHERS": [
        "Autoimmune ANA, RF",
        "CBC",
        "Pericarditis follow up",
        "CTD Workup",
        "Dementia",
        "Eating disorder workup",
        "Fatigue",
        "INR - Standing Order",
        "LFTs",
        "LFT Elevation Acute",
        "LFT Elevation Chronic",
        "Renal Function (RAAS start)",
        "Thrombosis screen",
        "TSH Standing Order",
        "Urine C&S",
    ],
}

def get_eform_checkbox_name(ui_label: str) -> str:
    """
    Get the eform checkbox name for a given UI label.
    
    Args:
        ui_label (str): The human-readable UI label
        
    Returns:
        str: The eform checkbox name, or None if not found
    """
    return LAB_CHECKBOX_MAPPING.get(ui_label)


def get_ui_label(eform_name: str) -> str:
    """
    Get the UI label for a given eform checkbox name.
    
    Args:
        eform_name (str): The eform checkbox name
        
    Returns:
        str: The UI label, or None if not found
    """
    return EFORM_TO_UI_LABEL.get(eform_name)


def get_all_ui_labels() -> list[str]:
    """
    Get all UI labels, organized by category.
    
    Returns:
        list[str]: All UI labels in category order
    """
    labels = []
    for category, category_labels in LAB_CHECKBOX_CATEGORIES.items():
        labels.extend(category_labels)
    return labels

# The following is for KEYWORD extraction, we are currently not using this as we are using the LLM analysis --------------------------------------------

# Keyword patterns for automatic checkbox detection from PLAN text
# Format: {ui_label: [list of keyword patterns]}
PLAN_KEYWORD_PATTERNS = {
    "Fasting Instructions": ["fasting", "fast", "nothing to eat", "npo"],
    
    "pre-cath": ["pre-cath", "pre cath", "precatheterization", "before cath", "prior to cath"],
    "pre-EP procedure": ["pre-ep", "pre ep", "pre-electrophysiology", "before ep", "prior to ep"],
    
    "Amiodarone follow up": ["amiodarone", "amiodarone monitoring", "amiodarone follow"],
    "Digoxin level": ["digoxin", "digoxin level", "digoxin monitoring"],
    
    "comprehensive": ["comprehensive cardiac", "comprehensive blood work", "full cardiac panel"],
    "minicomprehensive": ["mini comprehensive", "minicomprehensive"],
    "RR": ["rr", "comrr", "renal risk"],
    "Cardiomyopathy": ["cardiomyopathy", "new cardiomyopathy", "ihd"],
    
    "CHF Baseline": ["chf baseline", "heart failure baseline", "congestive heart failure baseline"],
    "CHF Follow-up": ["chf follow", "heart failure follow", "chf follow-up", "chf follow up"],
    "CHF Standing Order Q3M": ["chf standing", "chf q3", "standing order q3"],
    "CHF Follow-up post thiazide": ["post thiazide", "after thiazide", "thiazide follow"],
    "CHF Follow-up post SGLT2": ["post sglt2", "after sglt2", "sglt2 follow"],
    "CHF Follow-up post high K+": ["post high k", "after high potassium", "high k+ follow", "hyperkalemia follow"],
    
    "CKD Annual": ["ckd annual", "chronic kidney disease annual", "ckd stage 3"],
    "eGFR/ACR Q6M": ["egfr/acr q6", "egfr acr q6", "egfr q6", "acr q6"],
    
    "DM Annual": ["dm annual", "diabetes annual", "diabetic annual"],
    "A1C Q3M": ["a1c q3", "hba1c q3", "a1c q3month", "diabetes q3"],
    
    "Screening": ["cholesterol screening", "lipid screening", "dyslipidemia screening"],
    "On Statin": ["on statin", "statin", "lipid profile", "lipids", "cholesterol"],
    
    "Hypertension Annual": ["hypertension annual", "htn annual", "high blood pressure annual"],
    "New Hypertension": ["hypertension", "htn", "high blood pressure", "new hypertension"],
    "New Hypotension": ["hypotension", "low blood pressure"],
    
    "Autoimmune ANA, RF": ["autoimmune", "ana", "rf", "rheumatoid factor", "antinuclear antibody"],
    "CBC": ["cbc", "complete blood count", "blood count"],
    "Pericarditis follow up": ["pericarditis", "pericarditis follow"],
    "CTD Workup": ["ctd", "connective tissue disease", "ctd workup"],
    "Dementia": ["dementia", "memory issues", "cognitive"],
    "Eating disorder workup": ["eating disorder", "anorexia", "bulimia"],
    "Fatigue": ["fatigue", "tiredness", "lethargy"],
    "INR - Standing Order": ["inr standing", "warfarin", "inr prn", "inr monitoring"],
    "LFTs": ["lft", "lfts", "liver function", "liver function test"],
    "LFT Elevation Acute": ["acute elevated lft", "acute liver", "acute lft elevation"],
    "LFT Elevation Chronic": ["chronic elevated lft", "chronic liver", "chronic lft elevation"],
    "Renal Function (RAAS start)": ["renal function", "kidney function", "raas start", "raas inhibitor"],
    "Thrombosis screen": ["thrombosis", "thrombophilia", "clotting disorder"],
    "TSH Standing Order": ["tsh standing", "tsh annually", "hypothyroidism", "thyroid"],
    "Urine C&S": ["urine c&s", "urine culture", "uti", "urinary tract infection"],
}


def extract_lab_checkboxes_from_plan(plan_text: str) -> list[str]:
    """
    Extract lab checkbox UI labels from PLAN text using keyword matching.
    
    This function analyzes the PLAN text and matches keywords to determine
    which lab checkboxes should be checked. Similar to the eform's JavaScript
    checkLetterPlan() function but more comprehensive.
    
    Args:
        plan_text: The PLAN section text from a medical note
        
    Returns:
        List of UI label strings for checkboxes that should be checked
    """
    if not plan_text or not plan_text.strip():
        return []
    
    plan_lower = plan_text.lower()
    matched_labels = []
    
    # Check each checkbox pattern
    for ui_label, keywords in PLAN_KEYWORD_PATTERNS.items():
        for keyword in keywords:
            if keyword.lower() in plan_lower:
                # Found a match - add to list if not already added
                if ui_label not in matched_labels:
                    matched_labels.append(ui_label)
                break  # Only need one keyword match per checkbox
    
    return matched_labels

