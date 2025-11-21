import re
import pandas as pd

def generate_lab_hl7(text, testing=False):
    """
    Extracts laboratory test results from a given text and formats them into HL7 OBX segments.
    This function scans the input text for known laboratory analytes, extracts their corresponding values,
    and generates HL7 OBX segment strings for each found analyte. It avoids duplicate entries by only
    processing the first occurrence of each analyte. The mapping of analyte names to HL7 codes and units
    is predefined within the function.

    Args:
    -----
        text (str): The input text containing laboratory test results, typically from an OCR process.
        testing (bool, optional): Boolean flag that returns an annotated hl7, making easier to identify result names
    
    Returns:
    --------
        str: A string containing HL7 OBX segments for each extracted laboratory test result, one per line.
    
    Notes:
    ------
        - Only the first occurrence of each analyte is processed.
        - Analytes with 'N/A' as their HL7 code are skipped.
    """

    df = pd.read_csv(r".\utils\lab_results.csv", index_col="Test Name")
    df.fillna("", inplace=True)

    results = df.to_dict(orient="index")
    results = {idx: list(row.values()) for idx, row in results.items()}

    hl7_keys = results.keys()
    i=0
    description=""

    # Assume the first appearance of the lab analytes in the text are the ones of interest,
    # so 'found' keeps track of what has already been processed to avoid duplicates
    found = []
    

    lines = text.splitlines()
    pattern = pattern = re.compile(r"^([A-Z\-\/()\[\] ]+)\s+([+-]?\d+(?:\.\d+)?)")
    matches = []
    # Iterating through each line of text
    for line in lines:
        match = pattern.match(line)
        if match:
            matches.append(match.group(0))
        # Checking if any of the lab analytes are in the current line
        for key in hl7_keys: 
            if key.lower() in line[:35].lower() and key not in found:
                if results[key][0]:
                    # Check if abbreviated form is used (e.g. ALT, CK)
                    if key == 'CK ' and line[:2] != 'CK':
                        continue # Skip to avoid matching other words with 'ck' in them
                    
                    
                    qty = 'N/A'
                    for e in line.split():
                        # Take first float
                        try:
                            if 'H' in e or 'L' in e:
                                rem_h = e[:-2]
                                float(rem_h)
                                qty = e
                            else:  
                                float(e)
                                qty = e
                            break
                        except:
                            pass


                    # Appending results in hl7 format
                    if testing:
                        description += f"{key:<18} OBX|{i}|ST|{results[key][0]}|COCV|{qty}|{results[key][1]}||{results[key][2]}\n"
                    else:
                        description += f"OBX|{i}|ST|{results[key][0]}|COCV|{qty}|{results[key][1]}||{results[key][2]}\n"

                    # Marking key as found and iterateing index
                    i += 1
                    found.append(key)
                else:
                    break
    
    return description
