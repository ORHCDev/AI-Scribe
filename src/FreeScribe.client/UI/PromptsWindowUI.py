import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

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

        # --- Buttons ---
        button_frame = tk.Frame(self.window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        tk.Button(button_frame, text="New", width=10, command=self.create_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Save", width=10, command=self.save_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Cache", width=10, command=self.cache_current_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Refresh", width=10, command=self.refresh_prompts).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Delete", width=10, command=self.delete_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Restore", width=10, command=self.restore_prompt).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Restore All", width=10, command=self.restore_all_prompts).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Close", width=10, command=self.close).pack(side=tk.RIGHT, padx=5)

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
        # Get file names without .txt ending
        prompts = self.prompts.list_prompts()
        self.prompt_selector["values"] = prompts
        if prompts:
            self.prompt_selector.current(0)
            self.load_prompt(prompts[0])

    def load_prompt(self, name):
        """Load a prompt (from cache or file)."""
        if name in self.prompts.cache:
            content = self.prompts.cache[name]
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert(tk.END, content)
        else:
            print(f"Prompts {name} does not exist")
        


    # --- Event handlers ---

    def on_prompt_selected(self, event=None):
        """When user selects a prompt from dropdown."""
        name = self.prompt_var.get()
        if name:
            self.load_prompt(name)


    # --- User actions ---

    def create_prompt(self):
        """Create a new prompt (new .txt file)."""
        name = simpledialog.askstring("New Prompt", "Enter name for new prompt:")
        if not name:
            return

        if name == "Auto" or name == "None":
            messagebox.showerror("Error", f"Can not use 'Auto' or 'None' for prompt name, as they are defaults")
            return

        
        self.prompts.create_prompt(name, "")
        self.load_prompts()
        self.prompt_selector.set(name)
        self.text_widget.delete("1.0", tk.END)

        self.refresh_dropdown(self.prompts.list_prompts())

    def save_prompt(self):
        """Save the current prompt (write cache to file)."""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
            return

        self.prompts.save_prompt(name, self.text_widget.get("1.0", tk.END).strip())

        messagebox.showinfo("Saved", f"Prompt '{name}' saved successfully.", parent=self.window)

    def cache_current_prompt(self):
        """Cache current text under the currently selected prompt."""
        current = self.prompt_var.get()
        if current:
            self.prompts.cache_prompt(current, self.text_widget.get("1.0", tk.END).strip())

    def refresh_prompts(self):
        """Reloads prompts by reading .txt files. Will reset cached changes"""
        if self.prompt_selector["values"]:
            current = self.prompt_var.get()
            self.prompts.load_prompts()
            self.load_prompts()
            self.prompt_var.set(current)
            self.refresh_dropdown(self.prompts.list_prompts())

    def refresh_dropdown(self, values):
        """Refreshes main window prompt selector"""
        defaults = ["Auto", "None"]
        for widget in self.parent.winfo_children():
            if getattr(widget, "_id", None) == "prompt_selector":
                if values:
                    widget["values"] = defaults + values
                else:
                    widget["values"] = defaults


    def delete_prompt(self):
        """Deletes the prompt currently selected"""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
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

        # Ask for confirmation before deleting
        confirm = messagebox.askyesno(
            "Confirm Restore",
            f"Are you sure you want to restore '{name}'? All changes will be overwritten.",
            parent=self.window
        )

        if not confirm:
          return  # User cancelled
        
        self.prompts.restore_prompt(name)
        self.load_prompts()
        self.prompt_var.set(name)

    def restore_all_prompts(self):
        """Restores all prompts to default"""
        name = self.prompt_var.get()
        if not name:
            messagebox.showwarning("Warning", "No prompt selected.", parent=self.window)
            return

        # Ask for confirmation before deleting
        confirm = messagebox.askyesno(
            "Confirm Restore",
            f"Are you sure you want to restore all prompts to their default?",
            parent=self.window
        )

        if not confirm:
          return  # User cancelled
        
        self.prompts.restore_all_prompts()
        self.refresh_prompts()

    def close(self):
        """Close the prompt window."""
        self.cache_current_prompt()
        self.window.destroy()

