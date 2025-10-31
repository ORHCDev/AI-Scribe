import pandas as pd
import re
from datetime import datetime

EXTRA_LOINC_START_IDX = {
    "CN" : 7,
    "CR" : 8,
    "CXR" : 1,
    "ECHO" : 7,
    "HFC" : 6,
    "TEE" : 7,
    "HOLTER" : 2,
    "EST" : 3,
    "CATH" : 10,
    "DC" : 9,
    "OR" : 2,
    "UNKNOWN" : 7,
}


def extract_observation_date(text, doc_type):
    """
    Parses all dates from given text, applying ambigous patterns depending on document type. Will return the
    most recent date of all parsed dates as a string formatted "YYYY-MM-DD"
    """
    
    def extract_format_markers(text):
        """Extract date format hints from the text."""
        format_patterns = [
            r'\bDD/MM\b', r'\bMM/DD\b',
            r'\bDD-MM\b', r'\bMM-DD\b',
            r'\bD/M\b', r'\bM/D\b',
            r'\bD-M\b', r'\bM-D\b',
            r'\bdd/mm\b', r'\bmm/dd\b',
            r'\bdd-mm\b', r'\bmm-dd\b',
            r'\bd/m\b', r'\bm/d\b',
            r'\bd-m\b', r'\bm-d\b'
        ]
        format_hints = {}
        for pattern in format_patterns:
            match = re.search(pattern, text)
            if match:
                # Convert matched text to lowercase for consistency
                format_hint = match.group(0).lower().replace("-", "/")
                format_hints[format_hint] = True
        return format_hints
    
    dates = []

    # these dates are non-ambiguous (only have one way to read them) - applies to all types of documents
    universal_non_ambiguous_patterns = {
        r'\b\d{4}/\d{2}/\d{2}\b': '%Y/%m/%d',  # YYYY/MM/DD
        r'\b\d{4}-\d{2}-\d{2}\b': '%Y-%m-%d',  # YYYY-MM-DD
        r'\b\d{4}/\d{1}/\d{1}\b': '%Y/%m/%d',  # YYYY/M/D
        r'\b\d{4}/\d{2}/\d{1}\b': '%Y/%m/%d',  # YYYY/MM/D
        r'\b\d{4}/\d{1}/\d{2}\b': '%Y/%m/%d',  # YYYY/M/DD
        r'\b\d{4}-\d{1}-\d{1}\b': '%Y-%m-%d',  # YYYY-M-D
        r'\b\d{4}-\d{2}-\d{1}\b': '%Y-%m-%d',  # YYYY-MM-D
        r'\b\d{4}-\d{1}-\d{2}\b': '%Y-%m-%d',  # YYYY-M-DD
        r'\b\d{2}-[A-Za-z]{3}-\d{4}\b': '%d-%b-%Y',  # DD-MMM-YYYY
        r'\b[A-Za-z]{3}/\d{2}/\d{4}\b': '%b/%d/%Y',  # MMM/DD/YYYY
        r'\b[A-Za-z]{3} \d{2} \d{4}\b': '%b %d %Y',  # MMM DD YYYY
        r'\b[A-Za-z]{3} \d{1} \d{4}\b': '%b %d %Y',  # MMM D YYYY
        r'\b[A-Za-z]{3} \d{2}, \d{4}\b': '%b %d, %Y',  # MMM DD, YYYY
        r'\b[A-Za-z]{3} \d{1}, \d{4}\b': '%b %d, %Y',  # MMM D, YYYY
        r'\b\d{1}-[A-Za-z]{3}-\d{4}\b': '%d-%b-%Y',  # D-MMM-YYYY
        r'\b\d{4}-[A-Za-z]{3}-\d{2}\b': '%Y-%b-%d', # YYYY-MMM-DD
        r'\b[A-Za-z]{3}/\d{1}/\d{4}\b': '%b/%d/%Y',  # MMM/D/YYYY
        r'\b\d{2}/\d{2}/\d{2}\b': '%d/%m/%y',  # DD/MM/YY
        r'\b\d{1,2} [A-Za-z]{3,9} \d{4}\b' : '%d %B %Y',
    }

    # dates in personal documents always follow the format M/D/Y but not other documents
    non_ambiguous_patterns_in_personal_documents = {
        r'\b\d{2}/\d{2}/\d{4}\b': '%m/%d/%Y',  # MM/DD/YYYY
        r'\b\d{1}/\d{1}/\d{4}\b': '%m/%d/%Y',  # M/D/YYYY
        r'\b\d{2}/\d{1}/\d{4}\b': '%m/%d/%Y',  # MM/D/YYYY
        r'\b\d{1}/\d{2}/\d{4}\b': '%m/%d/%Y',  # M/DD/YYYY
        r'\b\d{2}-\d{2}-\d{4}\b': '%m-%d-%Y',  # MM-DD-YYYY
        r'\b\d{1}-\d{1}-\d{4}\b': '%m-%d-%Y',  # M-D-YYYY
        r'\b\d{2}-\d{1}-\d{4}\b': '%m-%d-%Y',  # MM-D-YYYY
        r'\b\d{1}-\d{2}-\d{4}\b': '%m-%d-%Y',  # M-DD-YYYY
    }

    ambiguous_patterns = [
        r'\b\d{2}/\d{2}/\d{4}\b',
        r'\b\d{2}-\d{2}-\d{4}\b',
        r'\b\d{1}/\d{1}/\d{4}\b',
        r'\b\d{2}/\d{1}/\d{4}\b',
        r'\b\d{1}/\d{2}/\d{4}\b',
        r'\b\d{1}-\d{1}-\d{4}\b',
        r'\b\d{2}-\d{1}-\d{4}\b',
        r'\b\d{1}-\d{2}-\d{4}\b'
    ]


    # Define the types of documents that do not require ambiguous date handling
    non_ambiguous_doc_types = ["echo", "holter", "ecg", "stecho", "est"]

    if doc_type in non_ambiguous_doc_types:
        apply_ambiguous_handling = False
    else:
        apply_ambiguous_handling = True

    ambiguous_dates = []

    for pattern, date_format in universal_non_ambiguous_patterns.items():
        for date_str in re.findall(pattern, text):
            try:
                dates.append(datetime.strptime(date_str, date_format))
            except ValueError:
                continue

    if apply_ambiguous_handling:
        for pattern in ambiguous_patterns:
            for date_str in re.findall(pattern, text):
                ambiguous_dates.append(date_str)

        format_markers = extract_format_markers(text)
        for date_str in ambiguous_dates:
            parts = re.split(r'[-/]', date_str)
            if len(parts) == 3:
                try:
                    day, month = int(parts[0]), int(parts[1])
                    if day > 12:
                        dates.append(datetime.strptime(date_str, '%d/%m/%Y' if '/' in date_str else '%d-%m-%Y'))
                    elif month > 12:
                        dates.append(datetime.strptime(date_str, '%m/%d/%Y' if '/' in date_str else '%m-%d-%Y'))
                    elif day == month:
                        dates.append(datetime.strptime(date_str, '%d/%m/%Y' if '/' in date_str else '%d-%m-%Y'))
                    elif format_markers.get('mm/dd') or format_markers.get('m/d'):
                        dates.append(datetime.strptime(date_str, '%m/%d/%Y' if '/' in date_str else '%m-%d-%Y'))
                    elif format_markers.get('dd/mm') or format_markers.get('d/m'):
                        dates.append(datetime.strptime(date_str, '%d/%m/%Y' if '/' in date_str else '%d-%m-%Y'))
                    else:
                        try:
                            # Check both versions d/m/Y and m/d/Y. If one version is within 2 weeks and other isn't,
                            # then likely the closest one
                            def within_n_days(date, days=14):
                                today = datetime.today().date()
                                diff = today - date
                                return (diff > 0) and (diff <= days)
                            
                            dmy = datetime.strptime(date_str, '%d/%m/%Y' if '/' in date_str else '%d-%m-%Y')
                            mdy = dates.append(datetime.strptime(date_str, '%m/%d/%Y' if '/' in date_str else '%m-%d-%Y'))

                            dmy_within = within_n_days(dmy)
                            mdy_within = within_n_days(mdy)

                            if dmy_within and not mdy_within:
                                dates.append(dmy)
                            elif mdy_within and not dmy_within:
                                dates.append(mdy)
                            else:
                                print(f"Unable to identify correct date format for: {date_str}") 
                        except:
                            print(f"Unable to identify correct date format for: {date_str}") #therefore can't convert to datetime object
                except:
                    continue

    else:
        for pattern, date_format in non_ambiguous_patterns_in_personal_documents.items():
            for date_str in re.findall(pattern, text):
                try:
                    dates.append(datetime.strptime(date_str, date_format))
                except ValueError:
                    continue
    
    current_date = datetime.now()
    valid_dates = [date for date in dates if date <= current_date and date.year >= 2000]
    if valid_dates:
        latest_date = max(valid_dates)
        return latest_date.strftime('%Y-%m-%d')

    return



def loinc_code_detector(filename): 
    """
    Identifies LOINC codes in filenames based on predefined parameter mappings

    Args:
    -----
        filename (str): Name/path of file to analyze

    Returns:
    --------
        list: Found LOINC codes in order of appearance
    """
    # Dictionary mapping medical parameters to institutional LOINC codes
    code_pairs = {
        "ECG": "XQ57",   # Electrocardiograph Results
        "CXR": "XQ58",   # Chest X-ray
        "EST": "XQ59",   # Exercise Treadmill Test
        "ECHO": "XQ60",  # Echocardiogram
        "ALLE": "XQ61",  # Allergies
        "RISK": "XQ62",  # Risk Factors
        "BP": "XQ63",  # Blood Pressure
        "PMH": "XQ63",   # Past Medical History
        "HR": "XQ64",  # Heart Rate
        "CATH1": "XQ65",  # Final Notes
        "BRR": "XQ66",   # Breathing Reserve
        "VO2": "XQ67",   # VO2
        "CATH": "XQ69",   # Overflow / Recommendations
        "HOLT": "XQ70",    # Holter Interpretation
        "WT": "XP1",   # Weight
        "HT": "XHT",   # Height
        "EF_B": "3138-5" # Left Ventricular Ejection Fraction
    }
    keycodes = code_pairs.keys()
    pattern = re.compile(r"\b("+"|".join(keycodes) + r")\b", re.IGNORECASE)
    matches = pattern.findall(filename)
    print("LOINC CODE MATCHES")
    loinc_codes = []
    if matches: 
        for match in matches: 
            loinc = code_pairs.get(match.upper())
            if loinc: 
                print(f"LOINC CODE for '{match}': {loinc}")
                loinc_codes.append(loinc) 
                
            else:
                print(f"Code '{match}' does not have a corresponding LOINC code")
    else: 
        print("No matches found")
    return loinc_codes 



def extra_loinc_prompt(loinc_codes, start_index, file_type): 
    """
    Generates additional LOINC code entries for HL7 messages

    Args:
    -----
        loinc_codes (list): Codes detected in file
        start_index (int): Starting OBX segment index
        file_type (str): Document type from detect_type()
    
    Returns:
    --------
        str: Formatted HL7 OBX segments for unexpected LOINC codes
    """
    loinc_translate = {
        "XQ57": "Electrocardiograph Results (ECG)",
        "XQ58": "Chest X-ray (CXR)",
        "XQ59": "Exercise Treadmill Test (EST)",
        "XQ60": "Echocardiogram (ECHO)",
        "XQ61": "Allergies (ALLE)",
        "XQ62": "Risk Factors (RISK)",
        "XQ63": "Blood Pressure (BP) / Past Medical History (PMH)",
        "XQ64": "Heart Rate (HR)",
        "XQ65": "Final Notes (CATH1)",
        "XQ66": "Breathing Reserve (BRR)",
        "XQ67": "VO2",
        "XQ69": "Overflow / Recommendations (CATH)",
        "XQ70": "Holter Interpretation (HOLT)",
        "XP1": "Weight (WT)",
        "XHT": "Height (HT)",
        "3138-5": "Left Ventricular Ejection Fraction (EF_B)"
    }
    file_loincs = {
        "CN": ["XQ64", "XQ63", "XP1", "XHT", "XQ65", "XQ69", "3138-5"],  
        "CR": ["XQ64", "XQ63", "XQ59", "XQ62", "XQ57", "XQ67", "XQ66", "XQ65"],  
        "CXR": ["XQ58"],  
        "ECHO": ["XQ64", "XQ63", "XP1", "XHT", "XQ60", "XQ65", "3138-5"],  
        "HFC": ["XQ64", "XQ63", "XP1", "XQ60", "XQ65", "XQ69"],  
        "TEE": ["XQ64", "XQ63", "XP1", "XHT", "XQ60", "XQ65", "3138-5"],  
        "HOLTER": ["XQ64", "XQ70"],  
        "HRC": ["XQ65"],
        "EST": ["XQ64", "XQ63", "XQ59"],  
        "CATH": ["XQ64", "XQ63", "XP1", "XHT", "XQ65", "XQ69", "3138-5", "XQ63", "XQ62", "XQ61"],  
        "DC": ["XQ64", "XQ63", "XP1", "XHT", "XQ65", "XQ69", "3138-5", "XQ63", "XQ62"],  
        "OR": ["XQ69", "XQ65"],  
        "NONE": ["XQ64", "XQ63", "XP1", "XHT", "XQ65", "XQ69", "3138-5"]  
    }

    extra_loincs = ""
    for loinc in loinc_codes: 
        if loinc not in file_loincs[file_type]: 
            line = f"OBX|{start_index}: {loinc_translate[loinc]}. LOINC CODE: {loinc}\n"
            extra_loincs += line
            start_index += 1
    return extra_loincs



def find_details(file_path, surname, first_name, middle_name=None):
    """
    Reads an Excel sheet to extract patient details such as sex, healthcare number, date of birth, and full name
    based on provided surname, first name, and optionally middle name.

    Args:
    -----
        file_path (str): Path to the Excel file containing patient data.
        surname (str): Patient's surname to search for.
        first_name (str): Patient's first name to search for.
        middle_name (str, optional): Patient's middle name to further refine the search. Defaults to None.

    Returns:
    --------
        tuple: A tuple containing:
            - sex (str): The patient's sex.
            - healthcare_number (int): The patient's healthcare identification number (HIN).
            - dob (str): The patient's date of birth in 'YYYYMMDD' format.
            - name (str): The patient's full name in 'FirstName Surname' format.
    """

    try:
        data = pd.read_excel(file_path)
    except Exception as e:
        print(f"Error reading the file: {e}")
        return

    # Create a Full Name column by combining surname and first name
    data['Full Name'] = data['Surname/eChart'].astype(str).str.strip() + " " + data['First Name/Demographic link'].astype(str).str.strip()

    # Normalize input names for case-insensitive matching
    surname = surname.strip().lower()
    first_name = first_name.strip().lower()
    print(f"Name: {first_name} {surname}")
    # Filter rows where Full Name contains both first name and surname
    person_data = data[
        data['Full Name'].str.lower().str.contains(first_name) &
        data['Full Name'].str.lower().str.contains(surname)
    ]
    # print("Data: ", person_data)
    if person_data.empty:
        print("No match found for the given name.")
        return

    # If multiple rows are found, select the first row
    if person_data.shape[0] > 1:
        print("Multiple Patients found. Using the first matching entry.")
        person_data = person_data.iloc[:1]  # Select only the first row as a DataFrame

    # Further filter by middle name if provided
    if middle_name:
        middle_name = middle_name.strip().lower()
        person_data['Middle Name Match'] = person_data['Full Name'].str.lower().str.contains(middle_name)
        exact_matches = person_data[person_data['Middle Name Match']]

        if not exact_matches.empty:
            person_data = exact_matches.iloc[:1]  # Use the first row from exact matches

    # Extract details from the first row
    first_row = person_data.iloc[0]
    sex = first_row['sex']
    healthcare_number = int(first_row['HIN'])
    YOB = str(first_row['YOB'])
    MOB = str(first_row['MOB']).zfill(2)  # Ensure 2-digit month
    DOB = str(first_row['DOB']).zfill(2)  # Ensure 2-digit day
    demNo = str(first_row['DemNo'])
    name = first_row['First Name/Demographic link'] + " " + first_row['Surname/eChart']

    dob = YOB + MOB + DOB

    print("Patient details:")
    print(f"Sex: {sex}")
    print(f"Healthcare Number: {healthcare_number}")
    print(f"Date of Birth (YYYYMMDD): {dob}")

    return sex, healthcare_number, dob, name, demNo
      


def generate_header(name, hin, dob, sex, date_of_message, date_of_collection):
    """
    Generates HL7 header
    
    Args:
    -----
        name (str): Patients name (FIRST LAST)
        hin (str): Patients Health Insurance Number
        dob (str): Patients Date of Birth
        sex (str): Patients sex
        date_of_message (str): Date the message was sent out
        date_of_collection (str): Date the data was collected

    Returns:
    --------
        Header for an HL7 file
    """

    msh = f"MSH|^~\&|Reports|CML|||{date_of_message}||ORU^R01||1|2.3\n"
    pid = f"PID|1|1000006134|000006134|{hin}^^ON|{name}||{dob}|{sex}|||||\n"
    obr = f"OBR|1|NG80801||117NF^CC||20240909|{date_of_collection}|||||||||24^CC|||||||||{sex}|||\n"

    return msh + pid + obr 

