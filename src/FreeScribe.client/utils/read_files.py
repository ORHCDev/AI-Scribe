import cv2
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
import numpy as np
import os
import re
import unicodedata


def pdf_image_to_text(pdf_path, first_page=None, last_page=None, write_out_text=False, filename=None):
    """
    Convert a PDF (or pdf bytes) file containing images to text using pytesseract OCR.
    
    Args:
    -----
        pdf_path (str): Path to PDF file
        first_page (int, optional): First page to process.
        last_page (int, optional): Last page to process.
        write_out_text (bool, optional): If True, saves the extracted text to a file.
        filename (str, optional): Filename for writing out text.
        
        
    Returns:
    --------
        str: Extracted text from the PDF images.
    """

    pages = convert_from_path(
        pdf_path, 
        dpi=375,
        first_page=first_page,
        last_page=last_page
    )

    # Extract text from each image using pytesseract
    text = ""
    for page in pages:
        # --- IMAGE PREPROCESSING BEFORE OCR ---
        # Convert PIL.Image to numpy array
        image = np.array(page)

        # Convert RGB (PIL default) to BGR (OpenCV expects BGR)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        # Get grayscale image
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Threshold 
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Denoise
        denoised = cv2.medianBlur(thresh, 3)

        # Convert back to image
        pil_image = Image.fromarray(denoised)

        # --- OCR ---
        text += pytesseract.image_to_string(pil_image, config="--psm 6")


    # Create text file
    if write_out_text:
        if not filename:
            dir = os.path.dirname(pdf_path)
            pdf = os.path.basename(pdf_path)
            try:
                filename = os.path.join(dir, pdf.replace(".pdf", ".txt")) 
            except:
                filename = os.path.join(dir, pdf.lower().replace(".pdf", ".txt"))
        
        with open(filename, "w") as writer:
            writer.write(text)


    return text



def file_reader(file_path):
    """
    Assumes passed file is either .txt or .pdf and will extract the text from the file.
    
    Will also try and extract additional information from the file name and text like 
    the file type and patient name.
    """
    print(f"Reading file {file_path}")
    
    try:
        if file_path.lower().endswith(".txt"):
            with open(file_path, "r") as f:
                text = f.read()
                return text

        elif file_path.lower().endswith(".pdf"):
            text = pdf_image_to_text(file_path)
            return text

        else:
            print("File type is not supported")
            return ''
    except Exception as e:
        print(f"An unexpected error occurred when trying to extract file text: {e}")



def extract_patient_name(file_name):
    """
    Extracts the patients name from the given file name.

    Args:
    -----
        file_name (str): Name of a pdf or txt file
    
    Returns:
    --------
        Tuple containing patients name: (first_name, last_name, middle_name)
    """
    
    # Normalize file_name to decode special characters
    file_name = unicodedata.normalize('NFKD', file_name).encode('ascii', 'ignore').decode('utf-8')

    pattern = r"^\d*([A-Za-z\s\-]+)(?:,|-\s?)([A-Za-z\s\-]+)"
    match = re.match(pattern, file_name)

    if match:
        # Found name match
        last_name = match.group(1).strip()
        first_name= match.group(2).strip()
        
        # Remove anything after "-" or "," in the first name/nickname
        first_name = re.split(r"[-,]", first_name)[0].strip()

        seperator = re.split(r"\s+", first_name)
        first_name = seperator[0]
        middle = None
        if len(seperator) > 1:
            middle = " ".join(seperator[1:])
        
        return first_name, last_name, middle
    
    else:
        print("Unable to extract patient name from file name")
        return None, None, None
    



def extract_patient_notes(text: str) -> str:
    """
    Extracts the Patient Notes section from a text blob (e.g., OSCAR eForm text).

    Strategy:
    - Look for a heading like "Patient Notes" (case-insensitive)
    - Return content from that heading to the next known label (e.g., "Extras") or end of text
    - If heading not found, return original text
    """
    try:
        lower_text = text.lower()
        # Identify start index
        candidates = ["patient notes:", "patient notes"]
        start = -1
        for c in candidates:
            start = lower_text.find(c)
            if start != -1:
                start += len(c)
                break

        if start == -1:
            return text

        # Identify end index (next known label)
        end_labels = [
            "extras:", "extras", "first name:", "last name:", "demographic number:",
            "query:", "questions:", "notes end:", "end of notes"
        ]
        end = len(text)
        for label in end_labels:
            idx = lower_text.find(label, start)
            if idx != -1:
                end = min(end, idx)

        return text[start:end].strip()
    except Exception:
        return text




def detect_type(filename):
    """
    Identifies document type from filename keywords

    Args:
    -----
        filename (str): Name/path of file to analyze

    Returns:
    --------
        str: Document type code based on keyword matches
    """

    # Group keywords
    cn_keywords = [
        "CN", "clinical notes", "consult notes", "consult", "nephro", "renal",
        "hematology", "rheumatology", "oncology", "respirology", "pulmonology"
    ]
    cr_keywords = ["CR", "cardiac rehab"]
    hfc_keywords = ["HFC", "heart function clinic"]
    cxr_keywords = ["CXR", "chest x-ray", "XRAY", "US", "CT", "MRI", "ultrasound", "x-ray chest", "x-ray", "x ray"]
    tee_keywords = ["TEE"]
    cath_keywords = ["CATH", "interventional cardiology", "angiogram", "catheterization", "interventional"]
    echo_keywords = ["ECHO"]
    holter_keywords = ["HOLTER", "heart rhythm"]
    est_keywords = ["EST", "stress"]
    dc_keywords = ["discharge", "DC summary", "discharge summary", "DC"]
    or_keywords = ["OR note", "OR"]
    diag_keywords = ["diag", "Diagnostic"]
    lab_keywords = ["lab", "lab"]

    # All keywords
    all_keywords = (
        cn_keywords + cr_keywords + hfc_keywords + cxr_keywords + tee_keywords +
        cath_keywords + echo_keywords + holter_keywords + est_keywords +
        dc_keywords + or_keywords + diag_keywords + lab_keywords
    )


    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in all_keywords) + r")\b", re.IGNORECASE)
    match = pattern.search(filename)

    if match:
        # Found document type
        keyword = match.group(0).lower()

        if keyword in [k.lower() for k in cxr_keywords]:
            return "CXR"
        elif keyword in cn_keywords:
            return "CN"
        elif keyword in cr_keywords:
            return "CR"
        elif keyword in hfc_keywords:
            return "HFC"
        elif keyword in est_keywords:
            return "EST"
        elif keyword in holter_keywords:
            return "HOLTER"
        elif keyword in dc_keywords:
            return "DC"
        elif keyword in cath_keywords:
            return "CATH"
        elif keyword in or_keywords:
            return "OR"
        elif keyword in tee_keywords:
            return "TEE"
        elif keyword in echo_keywords:
            return "ECHO"
        elif keyword in diag_keywords: 
            return "DIAG"
        elif keyword in lab_keywords: 
            return "LAB"
        
        return match.group(0)
    else:
        # Unknown document type
        return "UNKNOWN"
        

