import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from UI.PromptsWindow import CONSULT_COMPLETE_MASTER_SECTION, CONSULT_COMPLETE_PROMPT, SECTION_GROUPS

class PromptsWindowUI:
    def __init__(self, parent, prompts):
        """
        A prompt management window that allows viewing, editing, 
        creating, deleting, and caching prompts.
        """
        self.parent = parent
        self.prompts = prompts

        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title("Prompt Manager")
        self.window.geometry("750x500")

        # --- Dropdown for prompt selection ---
        top_frame = tk.Frame(self.window)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(top_frame, text="Select Prompt:").pack(side=tk.LEFT, padx=(0, 5))

        self.prompt_var = tk.StringVar()
        self.prompt_selector = ttk.Combobox(top_frame, textvariable=self.prompt_var, state="readonly")
        self.prompt_selector.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.prompt_selector.bind("<<ComboboxSelected>>", self.on_prompt_selected)

        self.section_frame = tk.Frame(self.window)
        tk.Label(self.section_frame, text="Section:").pack(side=tk.LEFT, padx=(0, 5))
        self.section_var = tk.StringVar()
        self.section_selector = ttk.Combobox(
            self.section_frame, textvariable=self.section_var, state="readonly"
        )
        self.section_selector.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.section_selector.bind("<<ComboboxSelected>>", self.on_section_selected)
        self.section_frame.pack(fill=tk.X, padx=10, pady=5)

        # --- Buttons ---
        self.button_frame = tk.Frame(self.window)
        self.button_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        tk.Button(self.button_frame, text="New", width=10, command=self.create_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Save", width=10, command=self.save_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Cache", width=10, command=self.cache_current_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Refresh", width=10, command=self.refresh_prompts).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Delete", width=10, command=self.delete_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Restore", width=10, command=self.restore_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Restore All", width=10, command=self.restore_all_prompts).pack(side=tk.LEFT, padx=5)
        tk.Button(self.button_frame, text="Close", width=10, command=self.close).pack(side=tk.RIGHT, padx=5)

        self.section_frame.pack_forget()
        self._current_prompt = None
        self._current_section = None

        # --- Text box for prompt content ---
        text_frame = tk.Frame(self.window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.text_widget = tk.Text(text_frame, wrap="none")
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbars
        vscroll = tk.Scrollbar(text_frame, command=self.text_widget.yview)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.config(yscrollcommand=vscroll.set)

        hscroll = tk.Scrollbar(self.window, orient="horizontal", command=self.text_widget.xview)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.text_widget.config(xscrollcommand=hscroll.set)

        # Load initial prompt list
        self.load_prompts()

    # --- Internal helpers ---

    def load_prompts(self):
        """Load available prompt names from the prompt directory."""
        values = self._prompt_values()
        self.prompt_selector["values"] = values
        if not values:
            return

        current = self.prompt_var.get()
        if current not in values:
            current = values[0]
        self.prompt_selector.set(current)
        self.load_prompt(current)

    def _prompt_values(self):
        """Returns the prompt names shown in the selector."""
        return self.prompts.list_prompts() + [CONSULT_COMPLETE_PROMPT] + list(SECTION_GROUPS)

    # Consult Complete and the section groups (e.g. Referral Requisition) are edited section by section
    def _is_sectioned(self, name):
        return name == CONSULT_COMPLETE_PROMPT or name in SECTION_GROUPS

    def _sections(self, name):
        if name == CONSULT_COMPLETE_PROMPT:
            return self.prompts.list_consult_complete_sections()
        return self.prompts.list_group_sections(name)

    def _get_section(self, name, section):
        if name == CONSULT_COMPLETE_PROMPT:
            return self.prompts.get_consult_complete_section(section)
        return self.prompts.get_group_section(name, section)

    def _cache_section(self, name, section, text):
        if name == CONSULT_COMPLETE_PROMPT:
            self.prompts.cache_consult_complete_section(section, text)
        else:
            self.prompts.cache_group_section(name, section, text)

    def _save_sections(self, name):
        if name == CONSULT_COMPLETE_PROMPT:
            self.prompts.save_consult_complete()
        else:
            self.prompts.save_group(name)

    def _restore_section(self, name, section):
        if name == CONSULT_COMPLETE_PROMPT:
            self.prompts.restore_consult_complete_section(section)
        else:
            self.prompts.restore_group_section(name, section)

    def _show_section_selector(self):
        """Shows the section selector for the current sectioned prompt."""
        values = self._sections(self._current_prompt)
        self.section_selector["values"] = values
        if self.section_var.get() not in values:
            self.section_var.set(values[0] if values else "")
        self.section_frame.pack(fill=tk.X, padx=10, pady=5, before=self.button_frame)

    def _hide_section_selector(self):
        """Hides the section selector when a regular prompt is selected."""
        self.section_frame.pack_forget()

    def load_prompt(self, name):
        """Load a prompt (from cache or file)."""
        self._current_prompt = name
        if self._is_sectioned(name):
            self._show_section_selector()
            self._load_section(self.section_var.get())
            return

        self._hide_section_selector()
        self._current_section = None
        if name in self.prompts.cache:
            content = self.prompts.cache[name]
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert(tk.END, content)
        else:
            print(f"Prompts {name} does not exist")

    def _load_section(self, section):
        """Loads a section of the current sectioned prompt into the text box."""
        self._current_section = section
        content = self._get_section(self._current_prompt, section)
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert(tk.END, content)

    def _cache_current_section(self):
        """Caches edits made to the current section."""
        if self._is_sectioned(self._current_prompt) and self._current_section:
            self._cache_section(
                self._current_prompt,
                self._current_section,
                self.text_widget.get("1.0", tk.END).strip()
            )

    # --- Event handlers ---

    def on_prompt_selected(self, event=None):
        """When user selects a prompt from dropdown."""
        name = self.prompt_var.get()
        if not name:
            return

        if self._is_sectioned(self._current_prompt) and name != self._current_prompt:
            self._cache_current_section()

        self.load_prompt(name)

    def on_section_selected(self, event=None):
        """When user selects a section from the dropdown."""
        section = self.section_var.get()
        if not section or section == self._current_section:
            return

        self._cache_current_section()
        self._load_section(section)


    # --- User actions ---

    def create_prompt(self):
        """Create a new prompt (new .txt file)."""
        name = simpledialog.askstring("New Prompt", "Enter name for new prompt:")
        if not name:
            return

        if name in {"Auto", "None", CONSULT_COMPLETE_PROMPT, *SECTION_GROUPS}:
            messagebox.showerror("Error", f"Can not use '{name}' for prompt name, as it is a default")
            return

        
        self.prompts.create_prompt(name, "")
        self.load_prompts()
        self.prompt_selector.set(name)
        self.load_prompt(name)

        self.refresh_dropdown(self.prompts.list_prompts())

    def save_prompt(self):
        """Save the current prompt (write cache to file)."""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
            return

        if self._is_sectioned(name):
            section = self.section_var.get()
            if not section:
                messagebox.showwarning("Warning", "No section selected.", parent=self.window)
                return
            self._cache_current_section()
            self._save_sections(name)
            messagebox.showinfo(
                "Saved", f"{name} prompts saved successfully.", parent=self.window
            )
            return

        self.prompts.save_prompt(name, self.text_widget.get("1.0", tk.END).strip())

        messagebox.showinfo("Saved", f"Prompt '{name}' saved successfully.", parent=self.window)

    def cache_current_prompt(self):
        """Cache current text under the currently selected prompt."""
        current = self.prompt_var.get()
        if self._is_sectioned(current):
            self._cache_current_section()
        elif current:
            self.prompts.cache_prompt(current, self.text_widget.get("1.0", tk.END).strip())

    def refresh_prompts(self):
        """Reloads prompts by reading .txt files. Will reset cached changes"""
        if self.prompt_selector["values"]:
            self.prompts.load_prompts()
            self.load_prompts()
            self.refresh_dropdown(self.prompts.list_prompts())

    def refresh_dropdown(self, values):
        """Refreshes main window prompt selector"""
        for widget in self.parent.winfo_children():
            if getattr(widget, "_id", None) == "prompt_selector":
                # The entries after the prompts (Consult Complete, Requisition Generation, ...) are set by the
                # main window, so they are kept instead of being dropped from the menu
                tail = getattr(widget, "_fixed_tail", [CONSULT_COMPLETE_PROMPT, "Consult Complete + MH"])
                widget["values"] = ["Auto", "None", "Scribe"] + list(values or []) + list(tail)


    def delete_prompt(self):
        """Deletes the prompt currently selected"""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
            return

        if self._is_sectioned(name):
            messagebox.showwarning(
                "Warning",
                f"{name} sections cannot be deleted.",
                parent=self.window
            )
            return

        # Ask for confirmation before deleting
        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete '{name}.txt'?",
            parent=self.window
        )

        if not confirm:
          return  # User cancelled
        
        res = self.prompts.delete_prompt(name)
        if res:
            messagebox.showwarning("Info", f"Successfully deleted {name}", parent=self.window)
            # Remove deleted prompt from dropdowns
            values = list(self.prompt_selector["values"])
            if name in values:
                values.remove(name)

            self.prompt_selector["values"] = values
            self.prompt_var.set("")
            self.refresh_dropdown(values)
            self.prompts.load_prompts()
            self.text_widget.delete("1.0", tk.END)
        else:
            messagebox.showwarning("Warning", f"Unable to delete {name}", parent=self.window)


    def restore_prompt(self):
        """Restores given prompt to default"""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
            return

        target = self.section_var.get() if self._is_sectioned(name) else name
        if not target:
            messagebox.showwarning("Warning", "No section selected.", parent=self.window)
            return

        # Ask for confirmation before restoring
        confirm = messagebox.askyesno(
            "Confirm Restore",
            f"Are you sure you want to restore '{target}'? All changes will be overwritten.",
            parent=self.window
        )

        if not confirm:
          return  # User cancelled

        if self._is_sectioned(name):
            self._restore_section(name, target)
            self._load_section(target)
        else:
            self.prompts.restore_prompt(name)
            self.load_prompts()
            self.prompt_var.set(name)

    def restore_all_prompts(self):
        """Restores all prompts to default"""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
            return

        # Ask for confirmation before restoring
        confirm = messagebox.askyesno(
            "Confirm Restore",
            f"Are you sure you want to restore all prompts to their default?",
            parent=self.window
        )

        if not confirm:
          return  # User cancelled

        self.prompts.restore_all_prompts()
        self.prompts.restore_all_consult_complete()
        self.prompts.restore_all_groups()
        self.refresh_prompts()

    def close(self):
        """Close the prompt window."""
        self.cache_current_prompt()
        self.window.destroy()

