"""
ComparePlanWindow.py

The "Compare Action Plan" choice: plan A (EBM rules) and plan B (evidence summary) side by side,
each editable with its APLAN length, and one button per plan. Nothing is saved here: the chosen
plan's text is handed to `on_choose(choice, text)`.
"""

import tkinter as tk

from utils import compare_plan


class ComparePlanWindow(tk.Toplevel):
    def __init__(self, parent, plan_a: str, plan_b: str, on_choose, note_a: str = "", note_b: str = ""):
        super().__init__(parent)
        self.title(compare_plan.COMPARE_PROMPT)
        self.transient(parent)
        self.on_choose = on_choose

        tk.Label(self, text="Pick the action plan to save to APLAN. You can edit it first.",
                 font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 4), sticky="w")

        self._a = self._column(0, "A: EBM rules", plan_a, note_a)
        self._b = self._column(1, "B: Evidence summary", plan_b, note_b)

        buttons = tk.Frame(self)
        buttons.grid(row=4, column=0, columnspan=2, pady=(4, 10))
        tk.Button(buttons, text="Save A", width=12, state="normal" if plan_a else "disabled",
                  command=lambda: self._choose("A", self._a)).pack(side="left", padx=6)
        tk.Button(buttons, text="Save B", width=12, state="normal" if plan_b else "disabled",
                  command=lambda: self._choose("B", self._b)).pack(side="left", padx=6)
        tk.Button(buttons, text="Cancel", width=12, command=self.destroy).pack(side="left", padx=6)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.grab_set()

    def _column(self, col, title, plan, note):
        tk.Label(self, text=title, font=("Arial", 9, "bold")).grid(row=1, column=col, padx=10, sticky="w")
        text = tk.Text(self, width=48, height=10, wrap="word")
        text.grid(row=2, column=col, padx=10, sticky="nsew")
        text.insert("1.0", plan or note)
        if not plan:
            text.config(state="disabled", fg="grey")
        length = tk.Label(self, fg="grey")
        length.grid(row=3, column=col, padx=10, pady=(2, 6), sticky="w")

        def update_length(_event=None):
            length.config(text=compare_plan.length_label(text.get("1.0", "end").strip()) if plan else "")
            text.edit_modified(False)

        text.bind("<<Modified>>", update_length)
        update_length()
        return text

    def _choose(self, choice, text):
        plan = text.get("1.0", "end").strip()
        if not plan:
            return
        self.destroy()
        self.on_choose(choice, plan)
