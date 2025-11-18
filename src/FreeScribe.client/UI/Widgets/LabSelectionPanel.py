"""
LabSelectionPanel.py

A scrollable panel widget for selecting lab checkboxes organized by category.
Used for the 1.2LabCardiacP eform lab requisition.

Classes:
    LabSelectionPanel: Scrollable panel with categorized lab checkboxes.
"""

import tkinter as tk
from tkinter import ttk
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
    
    def __init__(self, parent, height=8, close_callback=None, **kwargs):
        tk.Frame.__init__(self, parent, **kwargs)
        
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
        """Show the panel."""
        self.grid()
    
    def hide(self):
        """Hide the panel."""
        self.grid_remove()

