import cv2
import csv
import pandas as pd
from pdf2image import convert_from_path, convert_from_bytes
from PIL import Image
import pytesseract
import numpy as np
import os
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.formatting.rule import CellIsRule
from datetime import datetime
from dateutil.relativedelta import relativedelta
import textwrap


def pdf_image_to_text(pdf_path=None, pdf_bytes=None, first_page=None, last_page=None, write_out_text=False, filename="output.txt"):
    """
    Convert a PDF (or pdf bytes) file containing images to text using pytesseract OCR.
    
    Args:
    -----
        pdf_path (str, optional if pdf_bytes provided): Path to PDF file
        pdf_bytes (bytes, optional if pdf_path provided): PDF content as bytes.
        first_page (int, optional): First page to process.
        last_page (int, optional): Last page to process.
        write_out_text (bool, optional): If True, saves the extracted text to a file.
        filename (str, optional): Filename for writing out text.
    ** Either pdf_path or pdf_bytes must be provided, if both provided will use bytes **
        
        
    Returns:
    --------
        str: Extracted text from the PDF images.
    """

    if not pdf_path and not pdf_bytes:
        raise Exception("Must specify pdf_path or pdf_bytes")

    # Convert PDF to a list of images
    if pdf_bytes:
        pages = convert_from_bytes(
            pdf_bytes,
            dpi=375,
            first_page=first_page,
            last_page=last_page
        )
    else:
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


def period_parser(period : str, return_str : bool = True, str_format : str = "%Y-%m-%d") -> datetime:
    """
    Given a period that has the form of an integer followed by 'd', 'm', or 'y' for days, months and years respectfully,
    will return the date that is that many days/months/years from today.

    
    Params
    ------
    period : str
        Integer followed by either 'd', 'm', or 'y' for days, months, and years respectfully. \\
        I.e. '6m' represents 6 months.

    return_str : bool
        If True, will return a date string following given format, else will return a datetime object.

    str_format : str
        String format to convert datetime object to if return_str is True.

        
    Example
    -------
    Given period = '6m' and today's date is 2025-06-01, will return 2025-01-01.
    """

    try:
        # Parse period
        freq = period[-1]
        amount = int(period[:-1])

        # Get days/months/years
        if freq == 'd':
            sub_date = relativedelta(days=amount)
        elif freq == 'y':
            sub_date = relativedelta(years=amount)
        else:
            sub_date = relativedelta(months=amount)

    except:
        print("Unable to parse period")
        return
    
    # Subtract to get period starts
    today = datetime.now().date()
    start_date = today - sub_date

    if return_str:
        return start_date.strftime(str_format)
    else:
        return start_date


def export_data(data : list[dict], file_name : str, format : str = "xlsx", prettify : bool = True):
    """
    Exports the provided data as an Excel file or a CSV.

    Params
    ------
    data : list[dict]
        List of dictionaries (rows) that are to be exported as a CSV.

    file_name : str
        Name of the file to export to.

    format : str
        Either 'xls' (default) for Excel file or 'csv' for CSV file. \\
        
    prettify : bool
        If exporting as Excel file, and prettify is True, will add highlights, borders, and spacing \\
        to make the excel file easier to read (i.e. prettifying it).
    """
    if not data:
        raise ValueError("No data to export")
    
    # CSV Export
    if format == "csv":
        with open(file_name, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

    # Excel Export
    else:
        # Create Dataframe
        df = pd.DataFrame(data)
        df.to_excel(file_name, index=False, sheet_name="Data")

        if prettify:
            # Load workbook
            wb = load_workbook(file_name)
            ws = wb["Data"]

            # Header Styles
            header_font = Font(bold=True)
            header_fill = PatternFill("solid", fgColor="D9E1F2")
            hborder = Border(
                left=Side(style="thick"),
                right=Side(style="thick"),
                top=Side(style="thick"),
                bottom=Side(style="thick"),
            )
            # Row Styles
            EVEN_FILL = PatternFill("solid", fgColor="FFFFFF")
            ODD_FILL = PatternFill("solid", fgColor="F5F7FB")
            cborder = Border(
                left=Side(style="thin"),
                right=Side(style="thin"),
                top=Side(style="thin"),
                bottom=Side(style="thin"),
            )

            # Format header 
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.border = hborder

            # Add borders to all cells 
            for i, row in enumerate(ws.iter_rows(min_row=2)):
                fill = EVEN_FILL if i % 2 == 0 else ODD_FILL        
                for cell in row:
                    cell.border = cborder
                    cell.alignment = Alignment(wrap_text=True)
                    cell.fill = fill

            
            # Auto-size columns 
            MAX_LEN = 70
            for col in ws.columns:
                max_length = 0
                col_letter = col[0].column_letter
                for cell in col:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                ws.column_dimensions[col_letter].width = min(max_length + 5, MAX_LEN)

            #  Freeze header 
            ws.freeze_panes = "A2"

            # Save changes
            wb.save(file_name)


def wrap_text(text, width=40):
    return "\n".join(textwrap.wrap(text, width=width))