"""
LabSelectionPanel.py

A scrollable panel widget for selecting lab checkboxes organized by category.
Used for the 1.2LabCardiacP eform lab requisition.

Classes:
    LabSelectionPanel: Scrollable panel with categorized lab checkboxes.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from UI.Widgets.SearchableSelector import SearchableComboBox
from utils.lab_checkbox_mapping import LAB_CHECKBOX_CATEGORIES, get_eform_checkbox_name


class LabSelectionPanel(tk.Frame):
    """
    A scrollable panel widget with checkboxes for lab test selection.
    
    The panel is organized by categories (INSTRUCTIONS, PRE-PROCEDURE, etc.)
    and allows doctors to review and modify LLM-suggested lab tests.
    
    Args:
        parent: The parent widget
        **kwargs: Additional keyword arguments for tk.Frame
    """
    
    def __init__(self, parent, height=8, close_callback=None, oscar=None, **kwargs):
        tk.Frame.__init__(self, parent, **kwargs)
        
        self.oscar = oscar
        
        # Title frame with label and close button
        title_frame = tk.Frame(self)
        title_frame.pack(fill="x", pady=(0, 2))
        
        # Title label - left-aligned
        self.title_label = tk.Label(title_frame, text="Lab Form Checkboxes", font=("Arial", 9, "bold"), anchor="w")
        self.title_label.pack(side="left", fill="x", expand=True)
        
        # Close button (X) on the right - more visible
        self.close_button = tk.Button(
            title_frame,
            text="✕",
            command=close_callback if close_callback else self.hide,
            font=("Arial", 11, "bold"),
            relief="raised",
            width=2,
            height=1,
            cursor="hand2",
            bg="#f0f0f0",
            activebackground="#e0e0e0",
            bd=1
        )
        self.close_button.pack(side="right", padx=(5, 0))
        self.close_callback = close_callback
        
        # Create scrollable frame with specified height - more compact
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height*18, width=200)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Pack canvas and scrollbar
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel only when hovering over the widget
        self.bind("<Enter>", self._bind_mousewheel)
        self.bind("<Leave>", self._unbind_mousewheel)
        
        # Dictionary to store checkboxes: {ui_label: checkbox_var}
        self.checkbox_vars = {}
        
        # Create checkboxes organized by category
        self._create_checkboxes()
        
        # Cache for patient list (formatted strings)
        self._cached_patient_list = None
        
        # Patient selector and open button inside scrollable area (must scroll to see)
        if self.oscar:
            self._create_patient_controls()
        
        # Initially hidden (will be shown via grid when needed)
    
    def _bind_mousewheel(self, event):
        """Bind mousewheel scrolling when mouse enters the widget."""
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
    
    def _unbind_mousewheel(self, event):
        """Unbind mousewheel scrolling when mouse leaves the widget."""
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")
    
    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling on the canvas."""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def _create_checkboxes(self):
        """Create checkboxes organized by category."""
        row = 0
        
        for category, labels in LAB_CHECKBOX_CATEGORIES.items():
            # Category header - more compact
            category_label = tk.Label(
                self.scrollable_frame,
                text=category,
                font=("Arial", 8, "bold"),
                anchor="w"
            )
            category_label.grid(row=row, column=0, columnspan=2, sticky="w", padx=3, pady=(5, 2))
            row += 1
            
            # Create checkboxes for this category - more compact
            for ui_label in labels:
                var = tk.BooleanVar(value=False)
                self.checkbox_vars[ui_label] = var
                
                checkbox = tk.Checkbutton(
                    self.scrollable_frame,
                    text=ui_label,
                    variable=var,
                    anchor="w",
                    wraplength=120,
                    font=("Arial", 8),
                    justify="left"
                )
                checkbox.grid(row=row, column=0, sticky="w", padx=(15, 3), pady=1)
                row += 1
        
        self._last_checkbox_row = row
    
    def set_checkboxes(self, ui_labels: list[str]):
        """
        Set checkboxes based on a list of UI labels.
        
        Args:
            ui_labels: List of UI label strings to check
        """
        # First, uncheck all
        self.clear_all()
        
        # Then check the specified ones
        for ui_label in ui_labels:
            if ui_label in self.checkbox_vars:
                self.checkbox_vars[ui_label].set(True)
    
    def get_checked_eform_names(self) -> list[str]:
        """
        Get list of eform checkbox names for all checked boxes.
        
        Returns:
            List of eform checkbox names (e.g., ["RenalFunction ", "DyslipidemiaOnStatin"])
        """
        checked = []
        for ui_label, var in self.checkbox_vars.items():
            if var.get():
                eform_name = get_eform_checkbox_name(ui_label)
                if eform_name:
                    checked.append(eform_name)
        return checked
    
    def get_checked_ui_labels(self) -> list[str]:
        """
        Get list of UI labels for all checked boxes.
        
        Returns:
            List of UI label strings
        """
        return [ui_label for ui_label, var in self.checkbox_vars.items() if var.get()]
    
    def clear_all(self):
        """Uncheck all checkboxes."""
        for var in self.checkbox_vars.values():
            var.set(False)
    
    def show(self):
        """Show the panel and refresh patient list if needed."""
        self.grid()
        if self.oscar and hasattr(self, 'patient_selector'):
            self._refresh_patient_list(force_refresh=False)
    
    def hide(self):
        """Hide the panel."""
        self.grid_remove()
    
    def _create_patient_controls(self):
        """Create patient selector and open lab form button inside scrollable area."""
        row = getattr(self, '_last_checkbox_row', len(self.checkbox_vars) + len(LAB_CHECKBOX_CATEGORIES))
        
        separator = ttk.Separator(self.scrollable_frame, orient="horizontal")
        separator.grid(row=row, column=0, columnspan=2, sticky="ew", padx=3, pady=(10, 5))
        row += 1
        
        patient_frame = tk.Frame(self.scrollable_frame)
        patient_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=3, pady=(0, 5))
        row += 1
        
        patient_label = tk.Label(patient_frame, text="Patient (Chart #):", font=("Arial", 8, "bold"), anchor="w")
        patient_label.pack(fill="x", pady=(0, 2))
        
        self.patient_var = tk.StringVar()
        self.patient_selector = SearchableComboBox(patient_frame, textvariable=self.patient_var, values=[])
        self.patient_selector.pack(fill="x", pady=(0, 5))
        self.patient_selector.bind("<Button-1>", lambda e: self._refresh_patient_list())
        self.patient_selector.bind("<<ComboboxSelected>>", self._on_patient_selected)
        
        self.open_button = tk.Button(
            patient_frame,
            text="Open Lab Form",
            command=self._open_lab_form,
            font=("Arial", 9),
            cursor="hand2",
            relief="raised",
            bd=2
        )
        self.open_button.pack(fill="x")
    
    def _refresh_patient_list(self, force_refresh=False):
        """
        Refresh the patient list from appointments when selector is clicked.
        Uses cached list if available, unless force_refresh is True.
        
        Args:
            force_refresh: If True, force a refresh even if cache exists
        """
        if hasattr(self, 'patient_selector'):
            try:
                patient_values = self._get_patient_list(force_refresh=force_refresh)
                self.patient_selector.set_values(patient_values)
            except Exception as e:
                print(f"Could not load patient list: {e}")
                self.patient_selector.set_values([])
    
    def _get_patient_list(self, force_refresh=False):
        """
        Get list of all patients from appointments, formatted for display.
        Uses cached formatted list if available, and uses oscar.appts directly
        if it exists (avoiding unnecessary scans).
        
        Args:
            force_refresh: If True, refresh cache even if it exists
        
        Returns:
            List of formatted patient strings: ["Lastname, Firstname (Chart#)"]
        """
        if not self.oscar:
            return []
        
        if self._cached_patient_list is not None and not force_refresh:
            return self._cached_patient_list
        
        if self.oscar.appts:
            all_patients = []
            for doctor, appts in self.oscar.appts.items():
                all_patients.extend(appts)
        else:
            all_patients = self.oscar.get_all_patients()
        
        patients = []
        for appt in all_patients:
            name = appt.get("Name", "")
            chart_no = appt.get("Demo#", "")
            if name and chart_no:
                formatted = f"{name} ({chart_no})"
                patients.append(formatted)
        
        self._cached_patient_list = sorted(set(patients))
        return self._cached_patient_list
    
    def _on_patient_selected(self, event=None):
        """When a patient is selected from dropdown, extract and store just the chart number."""
        selected = self.patient_var.get().strip()
        if selected:
            chart_no = self._extract_chart_number(selected)
            if chart_no:
                self.patient_var.set(chart_no)
    
    def _extract_chart_number(self, selection):
        """
        Extract chart number from selection string.
        
        Args:
            selection: Either "Lastname, Firstname (Chart#)" format or just chart number
        
        Returns:
            Chart number string, or None if not found
        """
        if not selection:
            return None
        
        if selection.isdigit():
            return selection
        
        try:
            if "(" in selection and ")" in selection:
                chart_part = selection[selection.rindex("(")+1:selection.rindex(")")].strip()
                return chart_part
        except Exception:
            pass
        
        return None
    
    def _get_patient_name_from_chart(self, chart_no):
        """
        Look up patient name from chart number in appointments.
        
        Args:
            chart_no: Demographic number
        
        Returns:
            Tuple of (first_name, last_name) or (None, None) if not found
        """
        if not self.oscar or not self.oscar.appts:
            return (None, None)
        
        for doctor, appts in self.oscar.appts.items():
            for appt in appts:
                if appt.get("Demo#") == chart_no:
                    name = appt.get("Name", "")
                    if name and "," in name:
                        parts = name.split(",", 1)
                        return (parts[1].strip(), parts[0].strip())
        
        return (None, None)
    
    def _open_lab_form(self):
        """Open the lab form with selected patient and checked checkboxes."""
        if not self.oscar:
            messagebox.showerror("Error", "Oscar connection not available.", parent=self)
            return
        
        selected = self.patient_var.get().strip()
        if not selected:
            messagebox.showwarning("Missing Patient", "Please enter or select a patient chart number.", parent=self)
            return
        
        chart_no = self._extract_chart_number(selected)
        if not chart_no:
            messagebox.showerror("Error", "Invalid chart number format.", parent=self)
            return
        
        checkbox_names = self.get_checked_eform_names()
        
        first_name, last_name = self._get_patient_name_from_chart(chart_no)
        
        self.oscar.open_lab_eform_with_checkboxes(first_name, last_name, checkbox_names, None, chart_no)

