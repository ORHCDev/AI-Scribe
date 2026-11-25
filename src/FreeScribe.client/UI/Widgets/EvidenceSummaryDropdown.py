"""
EvidenceSummaryDropdown.py

A collapsed dropdown shown under an evidence-workflow answer. Expanding it
reveals the generated 255-character APLAN2 summary. The dropdown starts
collapsed so it does not change the normal chat layout.
"""

import tkinter as tk

from utils import evidence_aplan


class EvidenceSummaryDropdown(tk.Frame):
    """A collapsible chart-summary row."""

    def __init__(self, parent, summary: str, max_chars: int = evidence_aplan.APLAN2_MAX_CHARS):
        background = parent.cget("background")
        super().__init__(parent, background=background)
        self.summary = summary
        self.max_chars = max_chars
        self._expanded = False

        self.toggle = tk.Label(
            self,
            text="Evidence summary \u25b8",
            fg="blue",
            cursor="hand2",
            background=background,
            anchor="w",
            justify="left",
        )
        self.toggle.pack(fill="x")
        self.toggle.bind("<Button-1>", self._toggle)

        self.body = tk.Frame(self, background=background)

        self.summary_label = tk.Label(
            self.body,
            text=summary,
            wraplength=600,
            justify="left",
            anchor="w",
            background=background,
        )
        self.summary_label.pack(fill="x", padx=(16, 0), pady=(2, 4))

    def _toggle(self, event=None):
        if self._expanded:
            self.body.pack_forget()
            self.toggle.config(text="Evidence summary \u25b8")
        else:
            self.body.pack(fill="x")
            self.toggle.config(text="Evidence summary \u25be")
        self._expanded = not self._expanded
