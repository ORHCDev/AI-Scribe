"""
Standard prescription lines offered by the medication eForm (0.1Rfx).

Each entry is the exact text the form's own drug/dose menu inserts into the prescription
body (`druglist_generic`), including LU codes where the form adds them. The LLM is asked to
pick from this list so auto-filled prescriptions match what a clinician would get by clicking
through the form. Drugs or doses not listed here can still be written as free text.

Keep in sync with the eForm template if the clinic edits its drug menu.
"""

RX_MED_OPTIONS = [
    # Antiplatelets
    "ECASA 81 mg daily",
    "Clopidogrel 75 mg daily",
    "Ticagrelor 90 mg BID, LU code 441",
    "Prasugrel 10 mg daily, LU code 449",
    # Statins / lipids
    "Atorvastatin 5 mg daily", "Atorvastatin 10 mg daily", "Atorvastatin 20 mg daily",
    "Atorvastatin 40 mg daily", "Atorvastatin 80 mg daily",
    "Rosuvastatin 5 mg daily", "Rosuvastatin 10 mg daily", "Rosuvastatin 20 mg daily",
    "Rosuvastatin 40 mg daily",
    "Simvastatin 5 mg daily", "Simvastatin 10 mg daily", "Simvastatin 20 mg daily",
    "Simvastatin 40 mg daily", "Simvastatin 80 mg daily",
    "Pravastatin 5 mg daily", "Pravastatin 10 mg daily", "Pravastatin 20 mg daily",
    "Pravastatin 40 mg daily", "Pravastatin 80 mg daily",
    "Ezetrol 10 mg daily, LU code 380",
    "Vascepa 2 g BID",
    # ACE inhibitors
    "Ramipril 1.25 mg daily", "Ramipril 1.25 mg BID", "Ramipril 2.5 mg daily", "Ramipril 2.5 mg BID",
    "Ramipril 5 mg daily", "Ramipril 5 mg BID", "Ramipril 10 mg daily", "Ramipril 10 mg BID",
    "Trandolapril 1 mg daily", "Trandolapril 2 mg daily", "Trandolapril 4 mg daily",
    "Perindopril 4 mg daily", "Perindopril 8 mg daily", "Perindopril 12 mg daily", "Perindopril 16 mg daily",
    # ARBs / ARNI
    "Valsartan 40 mg BID", "Valsartan 80 mg BID", "Valsartan 160 mg BID",
    "Telmisartan 20 mg daily", "Telmisartan 40 mg daily", "Telmisartan 80 mg daily",
    "Irbesartan 75 mg daily", "Irbesartan 150 mg daily", "Irbesartan 300 mg daily",
    "Candesartan 4 mg daily", "Candesartan 8 mg daily", "Candesartan 12 mg daily",
    "Candesartan 16 mg daily", "Candesartan 32 mg daily",
    "sacubitril/valsartan 24/26 mg BID, LU 497", "sacubitril/valsartan 49/51 mg BID, LU 497",
    "sacubitril/valsartan 97/103 mg BID, LU 497",
    # Beta blockers
    "Metoprolol 12.5 mg BID", "Metoprolol 25 mg BID", "Metoprolol 50 mg BID", "Metoprolol 100 mg BID",
    "Bisoprolol 1.25 mg daily", "Bisoprolol 2.5 mg daily", "Bisoprolol 5 mg daily", "Bisoprolol 10 mg daily",
    "Carvedilol 3.125 mg BID", "Carvedilol 6.25 mg BID", "Carvedilol 12.5 mg BID",
    "Carvedilol 25 mg BID", "Carvedilol 50 mg BID",
    "Nebivolol 2.5 mg daily", "Nebivolol 5 mg daily", "Nebivolol 10 mg daily",
    "Nebivolol 20 mg daily", "Nebivolol 40 mg daily",
    "Labetalol 100 mg BID", "Labetalol 200 mg BID", "Labetalol 400 mg BID",
    "Labetalol 800 mg BID", "Labetalol 1200 mg BID",
    # Anticoagulants
    "Warfarin",
    "Apixaban 2.5 mg BID, LU code 448", "Apixaban 5 mg BID, LU code 448",
    "Rivaroxaban 15 mg daily, LU code 435", "Rivaroxaban 20 mg daily, LU code 435",
    "Rivaroxaban 2.5 mg BID, LU code 539",
    "Dabigatran 110 mg BID, LU code 431", "Dabigatran 150 mg BID, LU code 431",
    "Edoxaban 30 mg daily, LU code 554", "Edoxaban 60 mg daily, LU code 554",
    # Antiarrhythmics
    "Amiodarone 100 mg daily", "Amiodarone 200 mg daily",
    "Amiodarone 400 mg BID for 7 days, 200 mg TID for 3 days, 200 mg BID for 4 days then 200 mg daily",
    "Sotalol 40 mg BID", "Sotalol 80 mg BID", "Sotalol 160 mg BID",
    "Flecainide 50 mg BID", "Flecainide 100 mg BID", "Flecainide 150 mg BID",
    "Propafenone 150 mg TID", "Propafenone 300 mg TID",
    "Dronedarone 400 mg BID",
    "Digoxin 0.0625 mg daily", "Digoxin 0.125 mg daily", "Digoxin 0.25 mg daily",
    # Calcium channel blockers
    "Amlodipine 2.5 mg daily", "Amlodipine 5 mg daily", "Amlodipine 7.5 mg daily", "Amlodipine 10 mg daily",
    "Nifedipine 30 mg XL daily", "Nifedipine 60 mg XL daily", "Nifedipine 90 mg XL daily",
    "Diltiazem CD 120 mg daily", "Diltiazem CD 240 mg daily", "Diltiazem CD 360 mg daily",
    "Verapamil 120 mg daily", "Verapamil 240 mg daily", "Verapamil 360 mg daily",
    # Diuretics / MRAs
    "Furosemide 10 mg daily", "Furosemide 20 mg daily", "Furosemide 40 mg daily", "Furosemide 40 mg BID",
    "Furosemide 80 mg daily", "Furosemide 80 mg BID", "Furosemide 120 mg BID",
    "Chlorthalidone 12.5 mg daily", "Chlorthalidone 25 mg daily", "Chlorthalidone 50 mg daily",
    "HCTZ 12.5 mg daily", "HCTZ 25 mg daily", "HCTZ 50 mg daily",
    "Indapamide 1.25 mg daily", "Indapamide 2.5 mg daily",
    "Indapamide 0.625 mg daily instead of Chlorthalidone",
    "Aldactone 12.5 mg daily", "Aldactone 25 mg daily", "Aldactone 50 mg daily", "Aldactone 100 mg daily",
    "Eplerenone 12.5 mg daily, LU 458", "Eplerenone 25 mg daily, LU 458",
    "Eplerenone 50 mg daily, LU 458", "Eplerenone 100 mg daily, LU 458",
    "Amiloride 5 mg daily",
    # Nitrates / vasodilators / other HF
    "0.2 mg/hr nitro patch", "0.4 mg/hr nitro patch",
    "0.4 mg P.R.N. nitroglycerin spray, SL for chest pain q 5 min to max of 3 sprays in an hour",
    "0.4 mg tab q 4 h PRN Nitroglycerine tabs, SL for chest pain q 5 min to max of 3 tabs in an hour",
    "Hydralazine 37.5 mg TID", "Hydralazine 37.5 mg QID", "Hydralazine 75 mg TID", "Hydralazine 75 mg QID",
    "Isordil 20 mg TID", "Isordil 40 mg TID",
    "Lancora 5 mg BID, LU 538", "Lancora 7.5 mg BID, LU 538",
    "Jardiance 10 mg daily",
    "Ozempic 0.25 mg SC weekly",
    # Supplements / misc
    "Magnesium tablet 150 mg daily",
    "K-Dur 1500 mg daily",
    "Colchicine 0.6 mg BID",
    "Co-enzyme Q10",
    "Pantoloc 40 mg daily, LU 297",
    "Champix 0.5 mg daily x 3 days then 0.5 mg BID for 4 days then 1 mg BID for total of 12 weeks LU code 423",
    "Zyban 150 mg PO daily for 3 days, THEN Increase to 150 mg BID for total of 12 weeks LU code 423",
]
