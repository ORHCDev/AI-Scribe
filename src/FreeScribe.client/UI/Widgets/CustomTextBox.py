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

        # Create copy button in bottom right corner
        self.copy_button = tk.Button(
            self.scrolled_text,
            text="Copy Text",
            command=self.copy_text,
            relief="raised",
            borderwidth=1
        )
        self.copy_button.place(relx=1.0, rely=1.0, x=-2, y=-2, anchor="se")
        
        # Get Labs button (optional, can be set via set_get_labs_callback)
        self.get_labs_button = None
        self.get_labs_callback = None

        # Download button. Set via set_download_callback
        self.download_button = None
        self.download_callback = None

        # Medical History button. Set via set_med_hist_callback
        self.med_hist_button = None
        self.med_hist_callback = None

        # Consult insert button. Set via set_consult_callback
        self.consult_button = None
        self.consult_callback = None

        # Consult and Medical History insert button. set via set_consult_and_mh_callback
        self.consult_and_mh_button = None
        self.consult_and_mh_callback = None
    
    def set_get_labs_callback(self, callback):
        """Set the callback function for the Get Labs button."""
        self.get_labs_callback = callback
        if self.get_labs_callback:
            if self.get_labs_button is None:
                self.get_labs_button = tk.Button(
                    self.scrolled_text,
                    text="Lab Form",
                    command=self._get_labs,
                    relief="raised",
                    borderwidth=1
                )
                # Place next to copy button
                self.get_labs_button.place(relx=1.0, rely=1.0, x=-82, y=-2, anchor="se")
    
    def _get_labs(self):
        """Internal method to call the Get Labs callback."""
        if self.get_labs_callback:
            self.get_labs_callback()
    

    def set_download_callback(self, callback):
        """Sets the callback function for the download button."""
        self.download_callback = callback
        if self.download_callback:
            if self.download_button is None:
                self.download_button = tk.Button(
                    self.scrolled_text,
                    text="Download",
                    command=self._download,
                    relief="raised",
                    borderwidth=1
                )
                # Place next to copy button
                self.download_button.place(relx=1.0, rely=1.0, x=-162, y=-2, anchor="se")

    def _download(self):
        """Internal method to call the download callback."""
        if self.download_callback:
            self.download_callback()


    def set_med_hist_callback(self, callback):
        """Sets the callback function for the Medical History button."""
        self.med_hist_callback = callback
        if self.med_hist_callback:
            if self.med_hist_button is None:
                self.med_hist_button = tk.Button(
                    self.scrolled_text,
                    text="Insert MH",
                    command=self._med_hist,
                    relief="raised",
                    borderwidth=1
                )
                # Place next to download button
                self.med_hist_button.place(relx=1.0, rely=1.0, x=-242, y=-2, anchor="se")

    def _med_hist(self):
        """Internal method to call the medical history callback."""
        if self.med_hist_callback:
            self.med_hist_callback()


    def set_consult_callback(self, callback):
        """Sets the callback function for the Medical History button."""
        self.consult_callback = callback
        if self.consult_callback:
            if self.consult_button is None:
                self.consult_button = tk.Button(
                    self.scrolled_text,
                    text="Insert Consult",
                    command=self._consult,
                    relief="raised",
                    borderwidth=1
                )
                # Place next to med hist button
                self.consult_button.place(relx=1.0, rely=1.0, x=-322, y=-2, anchor="se")

    def _consult(self):
        """Internal method to call the medical history callback."""
        if self.consult_callback:
            self.consult_callback()


    def set_consult_and_mh_callback(self, callback):
        """Sets the callback function for the Medical History button."""
        self.consult_and_mh_callback = callback
        if self.consult_and_mh_callback:
            if self.consult_and_mh_button is None:
                self.consult_and_mh_button = tk.Button(
                    self.scrolled_text,
                    text="Insert Consult & MH",
                    command=self._consult_and_mh,
                    relief="raised",
                    borderwidth=1
                )
                # Place next to med hist button
                self.consult_and_mh_button.place(relx=1.0, rely=1.0, x=-422, y=-2, anchor="se")

    def _consult_and_mh(self):
        """Internal method to call the medical history callback."""
        if self.consult_and_mh_callback:
            self.consult_and_mh_callback()


    def update_lab_button_text(self, text):
        """Update the lab form button text."""
        if self.get_labs_button:
            self.get_labs_button.config(text=text)

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