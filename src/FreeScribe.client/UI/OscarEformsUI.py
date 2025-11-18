import tkinter as tk
from tkinter import ttk, messagebox
from UI.Widgets.SearchableSelector import SearchableComboBox

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

        # Create popup window
        self.window = tk.Toplevel(parent)
        self.window.title("Oscar eForms")
        self.window.geometry("500x300")

         # Frame for inputs and button
        frame = ttk.Frame(self.window)
        frame.pack(padx=20, pady=20)

        # Grid columns and rows configuration
        for i in range(3):
            frame.grid_columnconfigure(i, weight=1)

        for i in range(6):
            frame.grid_rowconfigure(i, weight=1)


        # --- INPUTS --- #
        # First Name
        self.first_name_lbl = ttk.Label(frame, text="First Name:", font=('Ariel', 8, 'bold'), width=18)
        self.first_name_lbl.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.first_name_entry = ttk.Entry(frame, width=20)
        self.first_name_entry.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        # Last Name
        self.last_name_lbl = ttk.Label(frame, text="Last Name:", font=('Ariel', 8, 'bold'), width=18)
        self.last_name_lbl.grid(row=0, column=1, padx=5, pady=5, sticky="nsew") 

        self.last_name_entry = ttk.Entry(frame, width=18)
        self.last_name_entry.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")

        # Chart Number
        self.chartno_lbl = ttk.Label(frame, text="Chart No.", font=('Ariel', 8, 'bold'), width=18)
        self.chartno_lbl.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")

        self.chartno_entry = ttk.Entry(frame, width=18)
        self.chartno_entry.grid(row=1, column=2, padx=5, pady=5, sticky="nsew")
        


        # --- EFORM DROPDOWN --- #
        self.eform_var = tk.StringVar(value="Auto")
        values = list(self.oscar.eforms.keys())
        self.eform_selector = SearchableComboBox(frame, textvariable=self.eform_var, values=values)
        self.eform_selector.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")



        # --- BUTTONS --- #
        # Open eForms by navigating Oscar
        self.search_eform = ttk.Button(frame, text="Search eForm", command=self.open_eforms, width=18)
        self.search_eform.grid(row=3, column=0, padx=5, pady=5, sticky="nsew")

        # Open eForms by link
        self.link_eform = ttk.Button(frame, text="Link eForm", command=lambda: self.open_eforms(True), width=18)
        self.link_eform.grid(row=3, column=1, padx=5, pady=5, sticky="nsew")

        # Scan eForm library for all eForms and load them into dropdown selector
        self.eform_scan = ttk.Button(frame, text="eForm Scan", command=self.scan_eforms, width=18)
        self.eform_scan.grid(row=3, column=2, padx=5, pady=5, sticky="nsew")

        # Read Medical History 
        self.letter_btn = ttk.Button(frame, text="Medical History", command=self.read_medical_history, width=18)
        self.letter_btn.grid(row=4, column=2, padx=5, pady=5, sticky="nsew")

        # Read Documents
        #self.doc_btn = ttk.Button(frame, text="Read Docs", command=self.read_docs, width=18)
        #self.doc_btn.grid(row=5, column=2, padx=5, pady=5, sticky="nsew")


        # Focus first entry
        self.first_name_entry.focus_set()



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
        # Read 0letter text
        text = self.oscar.read_medical_history()
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

            


    def read_docs(self):
        self.search_patient(open_eform_lib=False)
        self.oscar.read_dcs_and_angiograms()


