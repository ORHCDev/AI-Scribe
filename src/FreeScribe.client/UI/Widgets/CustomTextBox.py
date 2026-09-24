"""
CustomTextBox.py

This software is released under the AGPL-3.0 license
Copyright (c) 2023-2024 Braedon Hendy

Further updates and packaging added in 2024 through the ClinicianFOCUS initiative, 
a collaboration with Dr. Braedon Hendy and Conestoga College Institute of Applied 
Learning and Technology as part of the CNERG+ applied research project, 
Unburdening Primary Healthcare: An Open-Source AI Clinician Partner Platform". 
Prof. Michael Yingbull (PI), Dr. Braedon Hendy (Partner), 
and Research Students - Software Developer Alex Simko, Pemba Sherpa (F24), and Naitik Patel.

Classes:
    CustomTextBox: Custom text box with copy text button overlay.
"""

import tkinter as tk
from tkinter import messagebox

class CustomTextBox(tk.Frame):
    """
    A custom text box widget with a built-in copy button.

    This widget extends the `tk.Frame` class and contains a `tk.scrolledtext.ScrolledText` widget
    with an additional copy button placed in the bottom-right corner. The copy button allows
    users to copy the entire content of the text widget to the clipboard.

    :param parent: The parent widget.
    :type parent: tk.Widget
    :param height: The height of the text widget in lines of text. Defaults to 10.
    :type height: int, optional
    :param state: The state of the text widget, which can be 'normal' or 'disabled'. Defaults to 'normal'.
    :type state: str, optional
    :param kwargs: Additional keyword arguments to pass to the `tk.Frame` constructor.
    """
    def __init__(self, parent, height=10, state='normal', **kwargs):
        tk.Frame.__init__(self, parent, **kwargs)
        
        # Create scrolled text widget
        self.scrolled_text = tk.scrolledtext.ScrolledText(self, wrap="word", height=height, state=state)
        self.scrolled_text.pack(side="left", fill="both", expand=True)

        # Frame for button alignment
        self.button_frame = tk.Frame(self.scrolled_text)
        self.button_frame.place(
            relx=1.0,
            rely=1.0,
            x=-2,
            y=-2,
            anchor="se"
        )

        # Initialize callback functions
        self.med_hist_callback = None
        self.consult_callback = None
        self.consult_and_mh_callback = None
        self.consult_complete_callback = None
        self.get_eform_callback = None
        self.download_callback = None
        self.cancel_callback = None

        # Buttons, in order of appearance

        self.consult_button = tk.Button(
            self.button_frame,
            text="Insert Consult",
            command=self._consult,
            relief="raised",
            borderwidth=1
        )

        self.consult_and_mh_button = tk.Button(
            self.button_frame,
            text="Insert Consult & MH",
            command=self._consult_and_mh,
            relief="raised",
            borderwidth=1
        )

        self.consult_complete_button = tk.Button(
            self.button_frame,
            text="Insert Complete Consult",
            command=self._consult_complete,
            relief="raised",
            borderwidth=1
        )

        self.med_hist_button = tk.Button(
            self.button_frame,
            text="Insert MH",
            command=self._med_hist,
            relief="raised",
            borderwidth=1
        )

        self.get_eforms_button = tk.Button(
            self.button_frame,
            text="eForms",
            command=self._get_eforms,
            relief="raised",
            borderwidth=1
        )

        self.download_button = tk.Button(
            self.button_frame,
            text="Download",
            command=self._download,
            relief="raised",
            borderwidth=1
        )

        self.cancel_button = tk.Button(
            self.button_frame,
            text="Cancel",
            command=self._cancel,
            relief="raised",
            borderwidth=1,
            state="disabled"
        )

        self.copy_button = tk.Button(
            self.button_frame,
            text="Copy Text",
            command=self.copy_text,
            relief="raised",
            borderwidth=1
        )

        # Button order
        self._button_order = [
            self.med_hist_button,
            self.consult_button,
            self.consult_and_mh_button,
            self.consult_complete_button,
            self.get_eforms_button,
            self.download_button,
            self.cancel_button,
            self.copy_button
        ]

        for button in self._button_order:
            button.pack_forget()

        self.copy_button.pack(
            side="left",
            padx=4
        )

    # Button visibility
    def _show_button(self, button):
        """Show a button while preserving the predefined button order."""

        button.pack_forget()

        button_index = self._button_order.index(button)

        for next_button in self._button_order[button_index + 1:]:
            if next_button.winfo_manager() == "pack":
                button.pack(
                    side="left",
                    padx=4,
                    before=next_button
                )
                return

        button.pack(
            side="left",
            padx=4
        )

    # Medical history button
    def set_med_hist_callback(self, callback):
        self.med_hist_callback = callback

        if self.med_hist_callback:
            self._show_button(self.med_hist_button)

    def _med_hist(self):
        if self.med_hist_callback:
            self.med_hist_callback()

    # Consult button
    def set_consult_callback(self, callback):
        self.consult_callback = callback

        if self.consult_callback:
            self._show_button(self.consult_button)

    def _consult(self):
        if self.consult_callback:
            self.consult_callback()

    # Consult & Medical History button
    def set_consult_and_mh_callback(self, callback):
        self.consult_and_mh_callback = callback

        if self.consult_and_mh_callback:
            self._show_button(self.consult_and_mh_button)

    def _consult_and_mh(self):
        if self.consult_and_mh_callback:
            self.consult_and_mh_callback()

    # Complete consult button
    def set_consult_complete_callback(self, callback):
        self.consult_complete_callback = callback

        if self.consult_complete_callback:
            self._show_button(self.consult_complete_button)

    def _consult_complete(self):
        if self.consult_complete_callback:
            self.consult_complete_callback()

    # E-Forms button
    def set_get_eforms_callback(self, callback):
        self.get_eform_callback = callback

        if self.get_eform_callback:
            self._show_button(self.get_eforms_button)

    def _get_eforms(self):
        if self.get_eform_callback:
            self.get_eform_callback()

    def update_eform_button_text(self, text):
        if self.get_eforms_button:
            self.get_eforms_button.config(text=text)

    # Download button
    def set_download_callback(self, callback):
        self.download_callback = callback

        if self.download_callback:
            self._show_button(self.download_button)

    def _download(self):
        if self.download_callback:
            self.download_callback()

    # Cancel button
    def set_cancel_callback(self, callback):
        """Sets the callback function for the cancel button."""

        self.cancel_callback = callback

        if self.cancel_callback:
            self._show_button(self.cancel_button)

    def _cancel(self):
        if self.cancel_callback:
            self.cancel_callback()

    def set_cancel_button_active(self, active):
        if self.cancel_button is not None:
            self.cancel_button.config(
                state="normal" if active else "disabled"
            )

    

    def copy_text(self):
        """
        Copy all text from the text widget to the clipboard.

        If an error occurs during the copy operation, a message box will display the error message.
        """
        try:
            # Clear clipboard and append new text
            self.clipboard_clear()
            text_content = self.scrolled_text.get("1.0", "end-1c")
            self.clipboard_append(text_content)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy text: {str(e)}")
            
    def configure(self, **kwargs):
        """
        Configure the text widget with the given keyword arguments.

        :param kwargs: Keyword arguments to pass to the `configure` method of the `ScrolledText` widget.
        """
        self.scrolled_text.configure(**kwargs)
        
    def insert(self, index, text):
        """
        Insert text into the widget at the specified index.

        If the widget is in a 'disabled' state, it will be temporarily set to 'normal' to allow insertion.

        :param index: The index at which to insert the text.
        :type index: str
        :param text: The text to insert.
        :type text: str
        """
        current_state = self.scrolled_text['state']
        self.scrolled_text.configure(state='normal')
        self.scrolled_text.insert(index, text)
        self.scrolled_text.configure(state=current_state)
        
    def delete(self, start, end=None):
        """
        Delete text from the widget between the specified start and end indices.

        If the widget is in a 'disabled' state, it will be temporarily set to 'normal' to allow deletion.

        :param start: The start index of the text to delete.
        :type start: str
        :param end: The end index of the text to delete. If None, deletes from `start` to the end of the text.
        :type end: str, optional
        """
        current_state = self.scrolled_text['state']
        self.scrolled_text.configure(state='normal')
        self.scrolled_text.delete(start, end)
        self.scrolled_text.configure(state=current_state)
        
    def get(self, start, end=None):
        """
        Get text from the widget between the specified start and end indices.

        :param start: The start index of the text to retrieve.
        :type start: str
        :param end: The end index of the text to retrieve. If None, retrieves from `start` to the end of the text.
        :type end: str, optional
        :return: The text between the specified indices.
        :rtype: str
        """
        return self.scrolled_text.get(start, end)
    
    def see(self, index):
        """
        Scroll the text widget so the specified index is visible.
        """
        self.scrolled_text.see(index)