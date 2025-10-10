import cv2
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
import numpy as np
import os


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
