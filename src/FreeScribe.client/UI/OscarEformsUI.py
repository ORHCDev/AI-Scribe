import tkinter as tk
from tkinter import ttk, messagebox

class OscarEformsUI:
    def __init__(self, parent, oscar):
        """
        Popup window for searching patients in Oscar.
        """
        self.parent = parent
        self.oscar = oscar

        # Create popup window
        self.window = tk.Toplevel(parent)
        self.window.title("Patient Search")
        self.window.geometry("500x300")
        self.window.resizable(False, False)

         # Frame for inputs and button
        frame = ttk.Frame(self.window)
        frame.pack(padx=20, pady=20)

        # First Name
        ttk.Label(frame, text="First:").grid(row=0, column=0, padx=(0,5))
        self.first_name_entry = ttk.Entry(frame, width=15)
        self.first_name_entry.grid(row=0, column=1, padx=(0,15))

        # Last Name
        ttk.Label(frame, text="Last:").grid(row=0, column=2, padx=(0,5))
        self.last_name_entry = ttk.Entry(frame, width=15)
        self.last_name_entry.grid(row=0, column=3, padx=(0,15))

        # Search button
        ttk.Button(frame, text="Search", command=self.search_patient).grid(row=0, column=4)

        # Eform buttons (initially disabled until a patient has been found)
        self.rfx_btn = ttk.Button(frame, text="Rfx", command=lambda: self.open_eform("0.1Rfx"), state='disabled')
        self.rfx_btn.grid(row=1, column=0)

        self.lab_btn = ttk.Button(frame, text="Lab", command=lambda: self.open_eform("1.2LabCardiac"), state='disabled')
        self.lab_btn.grid(row=1, column=1)

        self.eform_btn = ttk.Button(frame, text="eForms", command=self.open_all_eforms, state='disabled')
        self.eform_btn.grid(row=1, column=2)

        # Focus first entry
        self.first_name_entry.focus_set()



    def search_patient(self):
        first = self.first_name_entry.get().strip()
        last = self.last_name_entry.get().strip()

        if not first or not last:
            messagebox.showwarning("Missing Info", "Please enter both first and last names.", parent=self.window)
            return

        # Call OscarEforms search method
        success = self.oscar.search_patient(first, last)

        if success:
            messagebox.showinfo("Search Result", f"Patient {first} {last} found!", parent=self.window)
            self.eform_btn.config(state='normal')
            self.lab_btn.config(state='normal')
            self.rfx_btn.config(state='normal')
        else:
            messagebox.showerror("Search Result", f"Patient {first} {last} not found.", parent=self.window)

    def open_eform(self, type):
        self.oscar.open_eform_from_search(type)

    def open_all_eforms(self):
        """
        Reads the inputted text and identifies eforms that need to be created for the patient
        """
        
        eform_map = {
            "PLAN:" : "0.1Rfx",
            "LAB WORK" : "1.2LabCardiac"
        }

        for widget in self.parent.winfo_children():
            if getattr(widget, "_id", None) == "input_tbox":
                text = widget.scrolled_text.get("1.0", tk.END).strip()
                print(f"Extracted text: \n{text}")

        for key, val in eform_map.items():
            if key in text:
                self.oscar.open_eform_from_search(val)
        