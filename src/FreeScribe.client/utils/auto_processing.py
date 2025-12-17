"""
Auto Processing Utility

Handles automated processing of documents in batch mode.
Supports two processing modes:
1. HL7 Processing: Converts medical documents to HL7 format
2. Feedback Processing: Generates AI responses for doctor queries from feedback forms
"""

import os
import time
import re
from datetime import datetime
import shutil
from utils.read_files import file_reader, extract_patient_name, detect_type, extract_patient_notes
from utils.hl7 import find_details, extract_observation_date, generate_header, loinc_code_detector, extra_loinc_prompt, lab_detector, EXTRA_LOINC_START_IDX
from utils.lab_processor import generate_lab_hl7
import scrubadub


class AutoProcessor:
    """
    Handles automated processing of medical documents.
    
    Supports two modes:
    - HL7: Converts documents to HL7 format with headers
    - Feedback: Generates AI feedback for doctor queries
    """
    
    def __init__(self, settings, ai_callback, prompts, log_callback=None):
        """
        Initialize the auto processor.
        
        Args:
            settings: Settings object containing folder paths and configuration
            ai_callback: Function to call for AI text generation (e.g., send_text_to_chatgpt)
            prompts: PromptsWindow class for managing AI prompts
            log_callback: Optional function to call for logging messages
        """
        self.settings = settings
        self.ai_callback = ai_callback
        self.prompts = prompts
        self.log_callback = log_callback or print
        self.stop_processing = False
        self.prompt_type = None
        
    def log(self, message, new_line=True):
        """Log a message using the callback."""
        self.log_callback(message, new_line)
        
    def stop(self):
        """Signal the processor to stop after the current file."""
        self.stop_processing = True
        
    def scrub_message(self, text):
        """Remove PHI from text using scrubadub and regex patterns."""
        # Skip scrubbing for OSCAR_FEEDBACK since extract_patient_notes already removes sensitive info
        if self.prompt_type == "OSCAR_FEEDBACK":
            return text
            
        scrubbed_message = scrubadub.clean(text)
        
        cleaned_message = scrubbed_message
        re_ohip_plain = re.compile(r'\b\d{10}\b')
        re_ohip_dashed = re.compile(r'\b(\d{4})-(\d{3})-(\d{3})(?:[- ]?[A-Za-z]{2})?\b')
        re_postal = re.compile(r'\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b', re.IGNORECASE)
        re_address = re.compile(r'\b\d+ [A-Z][a-z]+ (Street|St|Avenue|Ave|Road|Rd|Drive|Dr)\b', re.IGNORECASE)
        
        scrub_patterns = [
            (re_ohip_plain, '{{OHIP}}'),
            (re_ohip_dashed, '{{OHIP}}'),
            (re_postal, '{{POSTAL_CODE}}'),
            (re_address, '{{ADDRESS}}'),
        ]
        
        for regex, replacement in scrub_patterns:
            cleaned_message = regex.sub(replacement, cleaned_message)
            
        return cleaned_message
    
    def move_file(self, curr_dir, move_dir, file):
        """
        Move a file from curr_dir to move_dir, handling name conflicts.
        
        Args:
            curr_dir: Source directory
            move_dir: Destination directory
            file: Filename to move
            
        Returns:
            str: New file path
        """
        file_path = os.path.join(curr_dir, file)
        
        try:
            new_path = os.path.join(move_dir, file)
            shutil.move(file_path, new_path)
            return new_path
        except OSError:
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_file = re.sub(r'[<>:"/\\|?*]', '_', file)
            new_filename = f"{date_str}_{safe_file}"
            new_path = os.path.join(move_dir, new_filename)
            shutil.move(file_path, new_path)
            return new_path
    
    
    def save_feedback(self, analysis, first_name, last_name, demographic_num, base_folder):
        """
        Saves the feedback response directly to the output folder.
        
        Args:
            analysis: The GPT-generated analysis
            first_name: Patient's first name
            last_name: Patient's last name
            demographic_num: Patient's demographic number
            base_folder: Base folder for saving feedback files
        """
        # Clean and validate names
        first_name = re.sub(r'[<>:"/\\|?*]', '', str(first_name or "Unknown").strip())
        last_name = re.sub(r'[<>:"/\\|?*]', '', str(last_name or "Unknown").strip())
        demographic_num = re.sub(r'[<>:"/\\|?*]', '', str(demographic_num or "UNKNOWN").strip())
        
        # Create filename with demographic number: lastname_firstname_demographic.txt
        filename = f"{last_name}_{first_name}_{demographic_num}.txt"
        
        # Ensure filename is valid
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = filename.replace('\n', '').replace('\r', '')
        
        file_path = os.path.join(base_folder, filename)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(analysis)
            self.log(f"Saved OSCAR feedback to: {file_path}")
        except Exception as e:
            self.log(f"Error saving file {file_path}: {e}")
            # Try with a safe fallback filename
            safe_filename = f"feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            safe_file_path = os.path.join(base_folder, safe_filename)
            try:
                with open(safe_file_path, 'w', encoding='utf-8') as f:
                    f.write(analysis)
                self.log(f"Saved OSCAR feedback with safe filename: {safe_file_path}")
            except Exception as e2:
                self.log(f"Failed to save with safe filename: {e2}")
    
    
    def run(self):
        """
        Start the auto processing loop that watches both HL7 and Feedback folders.
        """
        # Base folder paths
        hl7_base_folder = self.settings.editable_settings["HL7 Base Folder"]
        feedback_base_folder = self.settings.editable_settings["Feedback Base Folder"]
        
        # Create subfolder structure
        hl7_in_folder = os.path.join(hl7_base_folder, "input")
        hl7_out_folder = os.path.join(hl7_base_folder, "output")
        hl7_fin_folder = os.path.join(hl7_base_folder, "done")
        hl7_fail_folder = os.path.join(hl7_base_folder, "failed")
        
        feedback_in_folder = os.path.join(feedback_base_folder, "input")
        feedback_out_folder = os.path.join(feedback_base_folder, "output")
        feedback_fin_folder = os.path.join(feedback_base_folder, "done")
        feedback_fail_folder = os.path.join(feedback_base_folder, "failed")
        
        # Create all folders
        for folder in [hl7_base_folder, feedback_base_folder, 
                      hl7_in_folder, hl7_out_folder, hl7_fin_folder, hl7_fail_folder,
                      feedback_in_folder, feedback_out_folder, feedback_fin_folder, feedback_fail_folder]:
            os.makedirs(folder, exist_ok=True)
        
        self.log("Starting dual-mode auto processing...")
        self.log(f"Watching HL7 folder: {hl7_in_folder}")
        self.log(f"Watching Feedback folder: {feedback_in_folder}")
        
        time.sleep(3)
        
        # Main processing loop
        while not self.stop_processing:
            # Check HL7 folder
            hl7_files = os.listdir(hl7_in_folder)
            if hl7_files:
                self.log(f"\nFound {len(hl7_files)} file(s) in HL7 folder")
                self.process_hl7_files(hl7_in_folder, hl7_out_folder, hl7_fin_folder, hl7_fail_folder, hl7_files)
            
            # Check Feedback folder
            feedback_files = os.listdir(feedback_in_folder)
            if feedback_files:
                self.log(f"\nFound {len(feedback_files)} file(s) in Feedback folder")
                self.process_feedback_files(feedback_in_folder, feedback_out_folder, feedback_fin_folder, feedback_fail_folder, feedback_files)
            
            # If no files in either folder, wait
            if not hl7_files and not feedback_files:
                self.log("\nNo files in either folder, waiting...")
                time.sleep(15)
            else:
                time.sleep(2)  # Brief pause between checks
    
    def process_hl7_files(self, in_folder, out_folder, fin_folder, fail_folder, files):
        """Process a batch of HL7 files."""
        self.prompt_type = "HL7"  # Set prompt type for scrubbing logic
        for file in files:
            if self.stop_processing:
                break
            try:
                self.log(f"{50*'='}\nProcessing HL7: {file}\n{50*'='}")
                
                text = file_reader(os.path.join(in_folder, file))
                doc_type = detect_type(file).upper()
                if doc_type == "UNKNOWN":
                    # See if file is lab
                    is_lab = lab_detector(text)
                    if is_lab: doc_type = "LAB"

                first_name, last_name, _ = extract_patient_name(file)
                
                self.log(f"Document Type: {doc_type}")
                
                res = None
                if first_name and last_name:
                    self.log(f"Extracted Patient: {last_name}, {first_name}")
                    res = find_details(
                        self.settings.editable_settings['ReportMasterPath'], 
                        last_name, 
                        first_name
                    )

                if res:
                    sex, hin, dob, name, _ = res
                    obs_date = extract_observation_date(text, doc_type)
                    hl7_header = generate_header(name, hin, dob, sex, obs_date, obs_date)
                else:
                    self.log("Could not extract patient name, using HL7 header template")
                    hl7_header = generate_header(
                        "<PATIENT NAME>", "<HIN>", "<DOB>", 
                        "<SEX>", "<MESSAGE DATE>", "<OBSERVATION DATE>"
                    )
                
                prompt = self.prompts.get(doc_type)
                if not prompt:
                    prompt = self.prompts.get("UNKNOWN")
                
                if "{prompt_addon}" in prompt:
                    loinc_codes = loinc_code_detector(file)
                    prompt = prompt.format(
                        prompt_addon=extra_loinc_prompt(
                            loinc_codes, 
                            EXTRA_LOINC_START_IDX.get(doc_type, 0), 
                            doc_type
                        )
                    )
                
                
                if doc_type == "LAB":
                    ai_response = generate_lab_hl7(text)
                else:
                    clean_text = self.scrub_message(text)
                    ai_response = self.ai_callback(f"{prompt}\n{clean_text}")
                    self.log("Received AI response")
                
                output_name = file.replace(".pdf", ".hl7") if file.endswith(".pdf") else file.replace(".txt", ".hl7")
                with open(os.path.join(out_folder, output_name), "w") as f:
                    f.write(hl7_header + ai_response)
                self.log(f"Outputted HL7 file to {out_folder}")
                
                self.move_file(in_folder, fin_folder, file)
                self.log(f"Moved file to {fin_folder}")
                
            except Exception as e:
                self.log(f"Error processing HL7 file {file}: {e}")
                self.log(f"Moving {file} to {fail_folder}")
                self.move_file(in_folder, fail_folder, file)
            
            self.log(f"{50*'-'}\n\n")
            time.sleep(2)
    
    def extract_feedback_patient_info(self, text):
        """
        Extract patient information from feedback form PDF text.
        Uses the exact same method as formfeedback.py
        Returns: (first_name, last_name, demographic_num, patient_notes)
        """
        try:
            demo_num = text[text.index("Demographic Number:") + len("Demographic Number:"): text.rindex("First Name:")].strip()
            if demo_num == '': 
                demo_num = None
            first_name = text[text.index("First Name:") + len("First Name:"): text.rindex("Last Name:")].strip()
            last_name = text[text.index("Last Name:") + len("Last Name:"): text.rindex("Patient Notes")].strip()
            patient_notes = text[text.index("Patient Notes") + len("Patient Notes:"): text.rindex("Extras")].strip()
            
            # Clean up the names - take only the first word and remove any extra text
            if first_name:
                first_name = first_name.split()[0] if first_name.split() else None
            if last_name:
                last_name = last_name.split()[0] if last_name.split() else None
            
            return first_name, last_name, demo_num, patient_notes
            
        except Exception as e:
            self.log(f"Error extracting patient info from PDF: {e}")
            return None, None, None, text

    def process_feedback_files(self, in_folder, out_folder, fin_folder, fail_folder, files):
        """Process a batch of feedback files."""
        self.prompt_type = "OSCAR_FEEDBACK"  # Set prompt type for scrubbing logic
        for file in files:
            if self.stop_processing:
                break
            try:
                self.log(f"{50*'='}\nProcessing Feedback: {file}\n{50*'='}")
                
                text = file_reader(os.path.join(in_folder, file))
                
                first_name, last_name, demographic_num, patient_notes = self.extract_feedback_patient_info(text)
                
                if first_name and last_name:
                    self.log(f"Extracted Patient: {last_name}, {first_name}")
                    if demographic_num:
                        self.log(f"Demographic Number: {demographic_num}")
                else:
                    self.log("Warning: Could not extract patient name from PDF content")
                    # Try filename as fallback
                    first_name, last_name, _ = extract_patient_name(file)
                    if first_name and last_name:
                        self.log(f"Using filename patient info: {last_name}, {first_name}")
                
                self.log(f"Extracted patient notes ({len(patient_notes)} chars)")
                
                prompt = self.prompts.get("OSCAR_FEEDBACK")
                clean_text = self.scrub_message(patient_notes)
                ai_response = self.ai_callback(f"{prompt}\n{clean_text}")
                self.log("Received AI response")
                
                self.save_feedback(
                    ai_response, 
                    first_name or "Unknown", 
                    last_name or "Unknown",
                    demographic_num or "UNKNOWN",
                    out_folder
                )
                
                self.move_file(in_folder, fin_folder, file)
                self.log(f"Moved file to {fin_folder}")
                
            except Exception as e:
                self.log(f"Error processing OSCAR file {file}: {e}")
                self.log(f"Moving {file} to {fail_folder}")
                self.move_file(in_folder, fail_folder, file)
            
            self.log(f"{50*'-'}\n\n")
            time.sleep(2)

