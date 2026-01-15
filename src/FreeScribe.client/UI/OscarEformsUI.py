import tkinter as tk
from tkinter import ttk, messagebox
from UI.Widgets.SearchableSelector import SearchableComboBox
from datetime import datetime
class OscarEformsUI:
    def __init__(self, parent, oscar):
        """
        Initializes a simple Tkinter window that provides a user interface to interact with the Oscar EMR system for easy eForm creation.
        It includes fields for patient information and buttons for opening eForm windows.

        Args
        ----
            parent: The parent Tkinter window/widget
            oscar: An OscarEforms object that handles Selenium interactions with Oscar EMR
        """

        self.parent = parent
        self.oscar = oscar
        # Document selection options
        self.document_opts = [
            "REFERRAL LETTER",
            "CLINIC NOTES",
            "CONSULTANT NOTES",
            "DC Summary", 
            "CATH",
            "OR NOTES",
            "Rx",
            "FMD COMMUNICATION",
            "LAB",
            "OUTGOING REFERRALS",
            "ECG",
            "ECHO",
            "STRESS",
            "STRESSECHO",
            "NUCLEAR STRESS",
            "HOLTER",
            "RADIOLOGY",
            "CTCA",
            "CARDIAC MRI",
            "PATHOLOGY",
            "REPORTS",
            "OTHERS",
            "OLDCHART",
            "PACEMAKER RECORDS",
            "OUT-PATIENT CLINICS",
            "clinic notes",
            "HFCNote",
            "SMH ER/ClinicRecord",
            "SLake ER/ClinicRecord",
            "ER CONSULTATION",
            "ecg",
            "CT SCAN",
            "EP REPORT",
            "ER REPORTS",
            "RX2",
            "ABP Monitor",
            "Patient Form",
            "LAB REQN",
            "Echo_consent",
            "consentEcho",
            "mrirequisition",
        ]
        # Defaults to select
        self.document_defaults = [
            "DC Summary",
            "CATH",
        ]
        self.doc_cbs = {}

        # Create popup window
        self.window = tk.Toplevel(parent)
        self.window.transient(parent)

        self.window.title("Oscar eForms")
        self.window.geometry("500x600")

        def _sync_move_parent(event=None):
            try:
                x = self.parent.winfo_x()
                y = self.parent.winfo_y()
                self.window.geometry(f"+{x + 930}+{y}")
            except tk.TclError:
                pass

        self.parent.bind("<Configure>", _sync_move_parent)

        # Frame for inputs and button
        self.frame = ttk.Frame(self.window)
        self.frame.pack(padx=20, pady=20)

        # Grid columns and rows configuration
        for i in range(3):
            self.frame.grid_columnconfigure(i, weight=1)

        for i in range(6):
            self.frame.grid_rowconfigure(i, weight=1)


        # --- INPUTS --- #
        # First Name
        self.first_name_lbl = ttk.Label(self.frame, text="First Name:", font=('Ariel', 8, 'bold'), width=18)
        self.first_name_lbl.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.first_name_entry = ttk.Entry(self.frame, width=20)
        self.first_name_entry.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        # Last Name
        self.last_name_lbl = ttk.Label(self.frame, text="Last Name:", font=('Ariel', 8, 'bold'), width=18)
        self.last_name_lbl.grid(row=0, column=1, padx=5, pady=5, sticky="nsew") 

        self.last_name_entry = ttk.Entry(self.frame, width=18)
        self.last_name_entry.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")

        # Chart Number
        self.chartno_lbl = ttk.Label(self.frame, text="Chart No.", font=('Ariel', 8, 'bold'), width=18)
        self.chartno_lbl.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")

        self.chartno_entry = ttk.Entry(self.frame, width=18)
        self.chartno_entry.grid(row=1, column=2, padx=5, pady=5, sticky="nsew")
        
        

        # --- DROPDOWNS --- #
        self.eform_var = tk.StringVar(value="Auto")
        values = list(self.oscar.eforms.keys())
        self.eform_selector = SearchableComboBox(self.frame, textvariable=self.eform_var, values=values)
        self.eform_selector.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")


        # Doctor Name
        vals = list(self.oscar.appts.keys())
        self.doctor_name = tk.StringVar(value="Maheswaran Srivamadevan")
        self.doctor_selector = ttk.Combobox(self.frame, textvariable=self.doctor_name, values=vals, state="readonly")
        self.doctor_selector.grid(row=5, column=0,  columnspan=3, padx=5, pady=5, sticky="nsew")
        self.doctor_selector.bind("<<ComboboxSelected>>", self.load_appointments)

        # --- BUTTONS --- #
        # Open eForms by navigating Oscar
        self.search_eform = ttk.Button(self.frame, text="Search eForm", command=self.open_eforms, width=18)
        self.search_eform.grid(row=3, column=0, padx=5, pady=5, sticky="nsew")

        # Open eForms by link
        self.link_eform = ttk.Button(self.frame, text="Link eForm", command=lambda: self.open_eforms(True), width=18)
        self.link_eform.grid(row=3, column=1, padx=5, pady=5, sticky="nsew")

        # Scan eForm library for all eForms and load them into dropdown selector
        self.eform_scan = ttk.Button(self.frame, text="eForm Scan", command=self.scan_eforms, width=18)
        self.eform_scan.grid(row=3, column=2, padx=5, pady=5, sticky="nsew")

        # Open encounter page
        self.encounter_btn = ttk.Button(self.frame, text="Open Encounter", command=lambda: self.search_patient(open_eform_lib=False), width=18)
        self.encounter_btn.grid(row=4, column=0, padx=5, pady=5, sticky="nsew")

        # Read Medical History 
        self.letter_btn = ttk.Button(self.frame, text="Medical History", command=self.read_medical_history, width=18)
        self.letter_btn.grid(row=4, column=2, padx=5, pady=5, sticky="nsew")

        # Opens Document Selector 
        self.doc_window_btn = ttk.Button(self.frame, text="Doc Selector", command=self.open_doc_selector, width=18)
        self.doc_window_btn.grid(row=4, column=1, padx=5, pady=5, sticky="nsew")


        # ---- SCROLLABLE FRAME ----
        # Scrollable frame for Patient Appointments
        scroll_container = ttk.Frame(self.window)
        scroll_container.pack(fill="both", expand=True)

        # Canvas for scrolling
        self.canvas = tk.Canvas(scroll_container)
        self.canvas.pack(side="left", fill="both", expand=True)

        # Scrollbar
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # The Frame INSIDE the canvas (for patient appointments)
        self.appt_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.appt_frame, anchor="nw")

        # Auto-resize scroll region
        self.appt_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        # Expand inner frame horizontally
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Mouse wheel scroll.
        # Only allows scrolling when mouse is hovering over appointments frame
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        # Grid setup for scrollable frame
        for i in range(3):
            self.appt_frame.grid_columnconfigure(i, weight=1)

        # Load appointments into frame
        self.load_appointments()

        # Focus first entry
        self.first_name_entry.focus_set()


    def _on_mousewheel(self, event):
        """Controls mousewheel scrolling for patient appointment frame"""
        # Get current scrollregion
        _, y1, _, y2 = self.canvas.bbox("all")

        # Height of scrollable content
        content_height = y2 - y1
        # Height of visible area
        visible_height = self.canvas.winfo_height()

        # If content fits, ignore scroll
        if content_height <= visible_height:
            return

        # Otherwise scroll normally
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_mousewheel(self, event):
        """Binds mousewheel for appointment frame scrollability"""
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        """Unbinds mousewheel from appointment frame"""
        self.canvas.unbind_all("<MouseWheel>")


    def _on_canvas_resize(self, event):
        """Keeps the appointment frame stretched to canvas width."""
        self.canvas.itemconfig(self.canvas_window, width=event.width)


    def search_patient(self, open_encounter=True, open_eform_lib=True):
        """
        Gets input from first name, last name, and chart number entries and calls OscarEforms search_patient() method
        which opens the Oscar search window and searches for patient.

        If patient is found, will enable eform buttons.
        """
        first = self.first_name_entry.get().strip()
        last = self.last_name_entry.get().strip()
        chartNo = self.chartno_entry.get().strip()
        if not ((first and last) or chartNo):
            messagebox.showwarning("Missing Info", "Please enter both first and last names or patients chart number.", parent=self.window)
            return

        # Call OscarEforms search method
        res = self.oscar.search_patient(
            first, 
            last, 
            chartNo, 
            open_encounter=open_encounter,
            open_eform_lib=open_eform_lib
        )

        if not res:
            messagebox.showerror("Search Result", f"Patient {first} {last} not found.", parent=self.window)

        return res


    def open_single_eform(self, type, bylink=False, checkbox_names=None, plan_text=None):
        """
        Opens eForm window for creating a new eForm.

        Args
        ----
          type (str): 
            Name of eForm that gets opened

          bylink (bool, optional):
            If True, will open eForm via link creation rather than selenium navigation
            
          checkbox_names (list, optional):
            List of eform checkbox names to check (for lab eforms)
            
          plan_text (str, optional):
            PLAN text to populate in eform (for lab eforms)
        """
        # Special handling for 1.2LabCardiacP eform with checkboxes
        if type == "1.2LabCardiacP" and checkbox_names is not None:
            first = self.first_name_entry.get().strip()
            last = self.last_name_entry.get().strip()
            chartNo = self.chartno_entry.get().strip()
            if not ((first and last) or chartNo):
                messagebox.showwarning("Missing Info", "Please enter both first and last names or patients chart number.", parent=self.window)
                return
            self.oscar.open_lab_eform_with_checkboxes(first, last, checkbox_names, plan_text, chartNo)
            return
        
        if not bylink:
            res = self.search_patient()
            if not res: return
            self.oscar.open_eform_from_search(type)

        else:
            first = self.first_name_entry.get().strip()
            last = self.last_name_entry.get().strip()
            chartNo = self.chartno_entry.get().strip()
            if not ((first and last) or chartNo):
                messagebox.showwarning("Missing Info", "Please enter both first and last names or patients chart number.", parent=self.window)
                return
            self.oscar.open_eform_from_link(first, last, type, chartNo)

        
    def open_all_eforms(self, bylink=False):
        """
        Reads the inputted text and identifies eforms that need to be created for the patient.
        Will open these eForm windows.
        """
        
        eform_map = {
            "PLAN:" : "0.1Rfx",
            "LAB WORK" : "1.2LabCardiacP"
        }

        for widget in self.parent.winfo_children():
            if getattr(widget, "_id", None) == "input_tbox":
                text = widget.scrolled_text.get("1.0", tk.END).strip()

        for key, val in eform_map.items():
            if key in text:
                # For lab eform, get checked boxes and plan text
                checkbox_names = None
                plan_text = None
                
                if val == "1.2LabCardiacP":
                    # Find lab panel and get checked boxes
                    def find_lab_panel(widget):
                        if hasattr(widget, 'get_checked_eform_names'):
                            return widget
                        for child in widget.winfo_children():
                            result = find_lab_panel(child)
                            if result:
                                return result
                        return None
                    
                    lab_panel = find_lab_panel(self.parent)
                    if lab_panel:
                        checkbox_names = lab_panel.get_checked_eform_names()
                    
                    # Get plan text from response display
                    def find_response_display(widget):
                        if hasattr(widget, 'scrolled_text'):
                            try:
                                content = widget.scrolled_text.get("1.0", "10.0")
                                if "Medical Note" in content or len(content.strip()) > 50:
                                    return widget
                            except:
                                pass
                        for child in widget.winfo_children():
                            result = find_response_display(child)
                            if result:
                                return result
                        return None
                    
                    response_widget = find_response_display(self.parent)
                    if response_widget:
                        response_text = response_widget.scrolled_text.get("1.0", tk.END).strip()
                        from utils.read_files import extract_plan_section
                        plan_text = extract_plan_section(response_text)
                
                self.open_single_eform(val, bylink=bylink, checkbox_names=checkbox_names, plan_text=plan_text)


    def open_eforms(self, bylink=False):
        """Opens eform window(s)"""
        eform = self.eform_var.get()

        if eform == "Auto":
            self.open_all_eforms(bylink)
        else:
            # Check if this is the lab eform and get checked boxes from panel
            checkbox_names = None
            plan_text = None
            
            if eform == "1.2LabCardiacP":
                # Try to find lab_selection_panel in parent window
                # Search recursively through all widgets
                def find_lab_panel(widget):
                    if hasattr(widget, 'get_checked_eform_names'):
                        return widget
                    for child in widget.winfo_children():
                        result = find_lab_panel(child)
                        if result:
                            return result
                    return None
                
                lab_panel = find_lab_panel(self.parent)
                if lab_panel:
                    checkbox_names = lab_panel.get_checked_eform_names()
                
                # Also try to get plan text from response_display
                def find_response_display(widget):
                    if hasattr(widget, 'scrolled_text'):
                        # Check if it's the response display (has title "Medical Note" or similar)
                        try:
                            content = widget.scrolled_text.get("1.0", "10.0")
                            if "Medical Note" in content or len(content.strip()) > 50:
                                return widget
                        except:
                            pass
                    for child in widget.winfo_children():
                        result = find_response_display(child)
                        if result:
                            return result
                    return None
                
                response_widget = find_response_display(self.parent)
                if response_widget:
                    response_text = response_widget.scrolled_text.get("1.0", tk.END).strip()
                    from utils.read_files import extract_plan_section
                    plan_text = extract_plan_section(response_text)
            
            self.open_single_eform(eform, bylink, checkbox_names, plan_text)
     

    def scan_eforms(self):
        """
        Opens eForm library page, scans eForm names and form IDs and updates
        dropdown to all scanned eForms.
        """
        # Ask for confirmation before scanning
        confirm = messagebox.askyesno(
            "Confirm Scan",
            f"Are you sure you want to scan all eforms?",
            parent=self.window
        )

        if not confirm:
          return  # User cancelled
        
        self.oscar.scan_and_update_eforms()
        self.eform_selector.set_values(self.oscar.eforms.keys())
        

    def read_medical_history(self):
        """Reads patient's most recent 0letter, angiogram, and dc, and pastes the text in the input box"""
        # Search for patient
        res = self.search_patient(open_eform_lib=False)
        if not res: return
        # Get selected documents to be scanned
        checked = [opt for opt, var in self.doc_cbs.items() if var.get()]
        if not checked: checked = self.document_defaults
        print(f"Scanning for documents: {checked}")
        # Read 0letter and documents
        text = self.oscar.read_medical_history(doc_names=checked)
        if not text: return
        # Paste text in input box
        for widget in self.parent.winfo_children():
            # Display extracted text in input textbox
            if getattr(widget, "_id", None) == "input_tbox":
                widget.scrolled_text.delete("1.0", tk.END)
                widget.scrolled_text.insert(tk.END, text)

            # Change prompt to "Medical History"
            elif getattr(widget, "_id", None) == "prompt_selector":
                widget.set("Medical History")


    def insert_patient_details(self, first_name, last_name, chartNo):
        """Inserts patients first and last name and chartNo into entries"""
        self.first_name_entry.delete(0, tk.END)
        self.last_name_entry.delete(0, tk.END)
        self.chartno_entry.delete(0, tk.END)
        self.first_name_entry.insert(0, first_name)
        self.last_name_entry.insert(0, last_name)
        self.chartno_entry.insert(0, chartNo)

        # Also open patients encounter page
        self.search_patient(open_eform_lib=False)


    def load_appointments(self, event=None):
        """
        Reads the inputted doctor name and loads all of the doctor's appointments
        into the scrollable frame at the bottom of the window. 
        Each appointment will be structured like:
            <Patient Name>        <Chart Number>        <Button to load info into entry boxes>
        """
        # Scan all appointments
        if not self.oscar.appts:
            print("Scanning appointments")
            self.oscar.scan_appointments()
            self.doctor_selector["values"] = list(self.oscar.appts.keys())

        # Clear any previous elements in appointment frame
        for widget in self.appt_frame.winfo_children():
            widget.destroy()
        
        # Get appointments only for given doctor
        appts = self.oscar.appts.get(self.doctor_name.get())
        

        # For each appointment, create row in scrollable frame
        for i, elem in enumerate(appts, start=0):
            appt_time = elem.get("Time") # Currently not used
            chartNo = elem.get("Demo#")
            name = elem.get("Name").split(',', 1)

            # Create row
            # NAME
            ttk.Label(
                self.appt_frame, 
                text=elem.get("Name"), 
                font=('Ariel', 8, 'bold'), 
                width=25
            ).grid(row=i, column=0, padx=5, pady=5, sticky="nsew")
            # CHART NUMBER
            ttk.Label(
                self.appt_frame, 
                text=chartNo, 
                font=('Ariel', 8, 'bold'), 
                width=12
            ).grid(row=i, column=1, padx=15, pady=5, sticky="nsew")
            # LOAD BUTTON
            ttk.Button(
                self.appt_frame,
                text="Load",
                command=lambda n=name, c=chartNo: self.insert_patient_details(n[1], n[0], c),
                width=18
            ).grid(row=i, column=2, padx=5, pady=5, sticky="nsew")
                        
                
        
    def open_doc_selector(self):
        """
        Opens the document selector window which consists of checkboxes that correspond
        to the different document types in Oscar EMR. Selections are used when loading
        a patients medical history as the documents selected will be the ones that get 
        their text extracted and pasted into the input textbox.

        Assigns checkboxes to self.doc_cbs
        """
        # Document Window 
        doc_window = tk.Toplevel(self.window)
        doc_window.title("Document Selector")
        doc_window.geometry("400x300")

        # Document Frame
        doc_frame = tk.Frame(doc_window)
        doc_frame.pack(fill="x", pady=(0, 2))

        # Scrollable canvas + frame
        doc_canvas = tk.Canvas(doc_frame, highlightthickness=0)
        doc_scrollbar = ttk.Scrollbar(doc_frame, orient="vertical", command=doc_canvas.yview)

        # The scollable frame inside the canvas
        doc_scrollable_frame = tk.Frame(doc_canvas)

        # Update scroll region whenever the inner frame grows
        doc_scrollable_frame.bind(
            "<Configure>",
            lambda e: doc_canvas.configure(scrollregion=doc_canvas.bbox("all"))
        )

        # Put the scrollable frame inside the canvas
        doc_canvas.create_window((0, 0), window=doc_scrollable_frame, anchor="nw")
        doc_canvas.configure(yscrollcommand=doc_scrollbar.set)

        doc_canvas.pack(side="left", fill="both", expand=True)
        doc_scrollbar.pack(side="right", fill="y")

        # --- Mousewheel handling ---
        def _on_mousewheel(event):
            doc_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(event):
            doc_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            doc_canvas.unbind_all("<MouseWheel>")

        doc_frame.bind("<Enter>", _bind_mousewheel)
        doc_frame.bind("<Leave>", _unbind_mousewheel)
        
        # Adding checkboxes
        #if not self.doc_cbs:
        
        if self.doc_cbs: 
            self.document_defaults = [opt for opt, var in self.doc_cbs.items() if var.get()]
        row = 0
        col = 0
        for opt in self.document_opts:
            var = tk.BooleanVar()
            self.doc_cbs[opt] = var

            cb = tk.Checkbutton(
                doc_scrollable_frame, 
                text=opt, 
                variable=var,
                anchor="w",
                wraplength=120,
                font=("Arial", 8),
                justify="left"
            )
            

            cb.grid(row=row, column=col, padx=5, pady=2)
            cb.configure(width=20)

            if col == 0:
                col = 1
            else:
                col = 0
                row += 1

        # Setting truth values
        for var in self.doc_cbs.values():
            var.set(False)

        for opt in self.document_defaults:
            self.doc_cbs[opt].set(True)

        return vars

