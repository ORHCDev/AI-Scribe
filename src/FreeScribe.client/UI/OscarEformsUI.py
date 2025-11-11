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

        # Read 0letters
        self.letter_btn = ttk.Button(frame, text="Read 0letter", command=self.read_0letter, width=18)
        self.letter_btn.grid(row=4, column=2, padx=5, pady=5, sticky="nsew")


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


    def open_single_eform(self, type, bylink=False):
        """
        Opens eForm window for creating a new eForm.

        Args
        ----
          type (str): 
            Name of eForm that gets opened

          bylink (bool, optional):
            If True, will open eForm via link creation rather than selenium navigation
        """
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
            "LAB WORK" : "1.2LabCardiac"
        }

        for widget in self.parent.winfo_children():
            if getattr(widget, "_id", None) == "input_tbox":
                text = widget.scrolled_text.get("1.0", tk.END).strip()

        for key, val in eform_map.items():
            if key in text:
                self.open_single_eform(val, bylink=bylink)


    def open_eforms(self, bylink=False):
        """Opens eform window(s)"""
        eform = self.eform_var.get()

        if eform == "Auto":
            self.open_all_eforms(bylink)
        else:
            self.open_single_eform(eform, bylink)
     

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
        

    def read_0letter(self):
        """Reads patient's 0letters and pastes the text in the input box"""
        # Search for patient
        res = self.search_patient(open_eform_lib=False)
        if not res: return
        # Read 0letter text
        text = self.oscar.read_0letters()
        if not text: return
        # Paste text in input box
        for widget in self.parent.winfo_children():
            if getattr(widget, "_id", None) == "input_tbox":
                # Display 0letter text
                widget.scrolled_text.delete("1.0", tk.END)
                widget.scrolled_text.insert(tk.END, text)



