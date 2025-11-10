from tkinter import ttk

class SearchableComboBox(ttk.Combobox):
    """
    Wrapper class for ttk.Combobox to allow for searching within the selector
    """
    def __init__(self, master=None, values=None, **kwargs):
        super().__init__(master, values=values, **kwargs)
        self._full_values = list(values)  
        self.bind("<KeyRelease>", self._on_keyrelease)

    def _on_keyrelease(self, event):
        # Ignore navigation keys
        if event.keysym in ("BackSpace", "Left", "Right", "Up", "Down", "Escape"):
            return

        # Open Dropdown on Return/Enter
        if event.keysym in ("Return", "Enter"):
            self.event_generate("<Down>")

        # Filter values
        value = self.get().lower()
        if value == "":
            filtered = self._full_values
        else:
            filtered = [v for v in self._full_values if value in v.lower()]

        # update dropdown
        self["values"] = filtered

    def set_values(self, values):
        self._full_values = list(values)
        self["values"] = self._full_values