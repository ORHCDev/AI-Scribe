import tkinter as tk
from tkinter import ttk, messagebox

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
        

        # --- BUTTONS --- #
        # Search Via Oscar
        self.search_oscar = ttk.Button(frame, text="Oscar Search", command=self.search_patient, width=18)
        self.search_oscar.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")

        # Eform buttons (initially disabled until a patient has been found)
        self.rfx_btn = ttk.Button(frame, text="Oscar Rfx", command=lambda: self.open_eform("0.1Rfx"), state='disabled', width=18)
        self.rfx_btn.grid(row=3, column=0, padx=5, pady=5, sticky="nsew")

        self.lab_btn = ttk.Button(frame, text="Oscar Lab", command=lambda: self.open_eform("1.2LabCardiac"), state='disabled', width=18)
        self.lab_btn.grid(row=4, column=0, padx=5, pady=5, sticky="nsew")

        self.eform_btn = ttk.Button(frame, text="Oscar eForms", command=self.open_all_eforms, state='disabled', width=18)
        self.eform_btn.grid(row=5, column=0, padx=5, pady=5, sticky="nsew")


        # Search Via Link
        self.eform_link_btn = ttk.Button(frame, text="Link eForms", command=lambda: self.open_all_eforms(bylink=True), width=18)
        self.eform_link_btn.grid(row=2, column=2, padx=5, pady=5, sticky="nsew")

        self.rfx_link_btn = ttk.Button(frame, text="Link Rfx", command=lambda: self.open_eform("0.1Rfx", bylink=True), width=18)
        self.rfx_link_btn.grid(row=3, column=2, padx=5, pady=5, sticky="nsew")

        self.lab_link_btn = ttk.Button(frame, text="Link Lab", command=lambda: self.open_eform("1.2LabCardiac", bylink=True), width=18)
        self.lab_link_btn.grid(row=4, column=2, padx=5, pady=5, sticky="nsew")


        # Focus first entry
        self.first_name_entry.focus_set()



    def search_patient(self):
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
        success = self.oscar.search_patient(first, last, chartNo)

        if success:
            messagebox.showinfo("Search Result", f"Patient {first} {last} found!", parent=self.window)
            self.eform_btn.config(state='normal')
            self.lab_btn.config(state='normal')
            self.rfx_btn.config(state='normal')
        else:
            messagebox.showerror("Search Result", f"Patient {first} {last} not found.", parent=self.window)

    def open_eform(self, type, bylink=False):
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
                self.open_eform(val, bylink=bylink)

        