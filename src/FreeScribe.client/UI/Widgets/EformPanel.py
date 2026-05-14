import tkinter as tk
from tkinter import ttk, messagebox
from UI.Widgets.SearchableSelector import SearchableComboBox
from utils.read_files import pdf_image_to_text

class EformPanel(tk.Frame):
    """
    A scrollable panel widget with checkboxes for lab test selection.
    
    The panel is organized by categories (INSTRUCTIONS, PRE-PROCEDURE, etc.)
    and allows doctors to review and modify LLM-suggested lab tests.
    
    Args:
        parent: The parent widget
        **kwargs: Additional keyword arguments for tk.Frame
    """
    
    def __init__(self, parent, height=8, close_callback=None, oscar=None, db_conn=None, **kwargs):
        tk.Frame.__init__(self, parent, **kwargs)
        
        self.oscar = oscar
        self.db_conn = db_conn
        self.parent = parent

        # Title frame with label and close button
        title_frame = tk.Frame(self)
        title_frame.pack(fill="x", pady=(0, 2))
        
        # Title label - left-aligned
        self.title_label = tk.Label(title_frame, text="eForm Panel", font=("Arial", 9, "bold"), anchor="w")
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
        
        # eForm buttons
        button_frame = tk.Frame(self)
        button_frame.pack(fill="x", pady=(0, 2))

        for i in range(3):
            button_frame.grid_columnconfigure(i, weight=1)
            button_frame.grid_rowconfigure(i, weight=1)

        # Buttons
        self.open_button = tk.Button(
            button_frame,
            text="Open",
            command=self.open_new_eform,
            font=("Arial", 11),
            relief="raised",
            width=12,
            height=1,
            cursor="hand2",
            bg="#f0f0f0",
            activebackground="#e0e0e0",
            bd=1
        )
        # self.scan_button = tk.Button(
        #     button_frame,
        #     text="Scan",
        #     command=self.scan_eforms,
        #     font=("Arial", 11),
        #     relief="raised",
        #     width=12,
        #     height=1,
        #     cursor="hand2",
        #     bg="#f0f0f0",
        #     activebackground="#e0e0e0",
        #     bd=1
        # )        
        self.doc_select_button = tk.Button(
            button_frame,
            text="Doc Selector",
            command=self.select_documents,
            font=("Arial", 11),
            relief="raised",
            width=12,
            height=1,
            cursor="hand2",
            bg="#f0f0f0",
            activebackground="#e0e0e0",
            bd=1
        )
        self.med_hist = tk.Button(
            button_frame,
            text="Med Hist",
            command=self.load_medical_history,
            font=("Arial", 11),
            relief="raised",
            width=12,
            height=1,
            cursor="hand2",
            bg="#f0f0f0",
            activebackground="#e0e0e0",
            bd=1
        )
        
        self.open_button.grid(row=0, column=0, padx=2, pady=2, sticky="nsew")
        #self.scan_button.grid(row=0, column=1, padx=2, pady=2, sticky="nsew")
        self.doc_select_button.grid(row=1, column=0, padx=2, pady=2, sticky="nsew")
        self.med_hist.grid(row=1, column=1, padx=2, pady=2, sticky="nsew")

        

        self.eforms = self._load_eforms()
        self.doc_types = self._load_document_types()
        self.document_defaults = [
            "DC summary",
            "CATH",
        ]
        self.doc_cbs = {}

        # Dropdown
        self.eform_var = tk.StringVar(value=list(self.eforms.keys())[0])

        values = list(self.eforms.keys())
        self.eform_selector = SearchableComboBox(button_frame, textvariable=self.eform_var, values=values)
        self.eform_selector.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")


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


        # Checkboxes
        self.checkbox_vars = {}
        self.eform_var.trace_add("write", self._load_checkboxes)
        self._load_checkboxes()
        

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

    def show(self):
        """Show the panel"""
        self.grid()

    def hide(self):
        """Hide the panel."""
        self.grid_remove()


    def _load_eforms(self):
        """
        Queries Oscar EMR database for all active eForm templates.

        Returns a dictionary of eForms, where the key is the eForm name and the value is it's form id (fid).
        """
        # Query database
        query = """
        SELECT
            fid,
            form_name
        FROM eform
        WHERE status = 1
        ORDER BY form_name;
        """
        res = self.db_conn.query_database(query)

        # Load eforms from rows
        eforms = {}
        for form in res:
            eforms[form['form_name']] = form['fid']


        return eforms


    def _load_checkboxes(self, *args):
        """
        Loads checkboxes for the selected eForm in the dropdown.
        """
        form_name = self.eform_var.get()
        fid = self.eforms[form_name]
        print(f"Loading checkboxes for {form_name}")

        checkboxes = self.oscar.get_eform_checkboxes(fid)

        self.checkbox_vars.clear()

        for row, checkbox in enumerate(checkboxes):
            # create checkbox
            var = tk.BooleanVar(value=False)            
            name = checkbox["name"]
            full_name = checkbox["full_name"]
            self.checkbox_vars[name] = var

            cb = tk.Checkbutton(
                self.scrollable_frame,
                text=full_name,
                variable=var,
                anchor="w",
                wraplength=120,
                font=("Arial", 8),
                justify="left"
            )
            cb.grid(row=row, column=0, sticky="w", padx=(15, 3), pady=1)

        self._clear_checkboxes()


    def _clear_checkboxes(self):
        """Uncheck all checkboxes."""
        for var in self.checkbox_vars.values():
            var.set(False)


    def open_new_eform(self):
        """
        Opens new eForm for opened patient. The opened eForm is chosen via the eForm dropdown
        and opens with the selected checkboxes.
        """
        # Get form id
        form_name = self.eform_var.get()
        fid = self.eforms[form_name]
        # Get selected checkboxes
        checkboxes = [k for k, v in self.checkbox_vars.items() if v.get()]        
        # Open eForm
        res = self.oscar.open_new_eform(fid, checkboxes)

        # If failed to open, then no patient encounter page is opened.
        # Notify user to open encounter page.
        if not res:
            messagebox.showwarning("Missing Patient", "Unable to open eForm. Please open the encouter page of the patient you want to open the eForm for.", parent=self)


    def _load_document_types(self) -> list[str]:
        """
        Queries Oscar EMR database for all the distinct document types that have been recorded.
        
        Returns a list of the unique document types.
        """
        # Query database
        query = """
        SELECT DISTINCT doctype
        FROM document;
        """
        res = self.db_conn.query_database(query)
        
        # Extract document type from returned rows
        doc_types = []
        for row in res:
            doc_type = row.get("doctype")
            if not doc_type.strip(): continue
            doc_types.append(doc_type)

        # Return types
        return doc_types


    def select_documents(self):
        """
        Opens window for selecting documents to be scanned when loading medical history.
        """
        
        # Document Window 
        doc_window = tk.Toplevel(self)
        doc_window.title("Document Selector")
        doc_window.geometry("400x300")

        # Document Frame
        doc_frame = tk.Frame(doc_window)
        doc_frame.pack(fill="x", pady=(0, 2))

        # Scrollable canvas + frame
        doc_canvas = tk.Canvas(doc_frame, highlightthickness=0)
        doc_scrollbar = ttk.Scrollbar(doc_frame, orient="vertical", command=doc_canvas.yview)

        # The scollable frame inside the canvas
        doc_scrollable_frame = tk.Frame(doc_canvas)

        # Update scroll region whenever the inner frame grows
        doc_scrollable_frame.bind(
            "<Configure>",
            lambda e: doc_canvas.configure(scrollregion=doc_canvas.bbox("all"))
        )

        # Put the scrollable frame inside the canvas
        doc_canvas.create_window((0, 0), window=doc_scrollable_frame, anchor="nw")
        doc_canvas.configure(yscrollcommand=doc_scrollbar.set)

        doc_canvas.pack(side="left", fill="both", expand=True)
        doc_scrollbar.pack(side="right", fill="y")

        # --- Mousewheel handling ---
        def _on_mousewheel(event):
            doc_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(event):
            doc_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            doc_canvas.unbind_all("<MouseWheel>")

        doc_frame.bind("<Enter>", _bind_mousewheel)
        doc_frame.bind("<Leave>", _unbind_mousewheel)
        
        # Adding checkboxes
        if self.doc_cbs: 
            self.document_defaults = [opt for opt, var in self.doc_cbs.items() if var.get()]
        row = 0
        col = 0
        for opt in self.doc_types:
            var = tk.BooleanVar(value=opt in self.document_defaults)
            self.doc_cbs[opt] = var

            cb = tk.Checkbutton(
                doc_scrollable_frame, 
                text=opt, 
                variable=var,
                anchor="w",
                wraplength=120,
                font=("Arial", 8),
                justify="left"
            )
            

            cb.grid(row=row, column=col, padx=5, pady=2)
            cb.configure(width=20)

            if col == 0:
                col = 1
            else:
                col = 0
                row += 1

        return vars


    def get_most_recent_0letter(self, demo_no=None):
        """
        Returns the fdid of the most recent 0letter for the opened patient.
        """
        if demo_no is None:
            demo_no = self.oscar.get_demographic_no()
        if demo_no is None:
            messagebox.showwarning("Missing Patient", "Unable to open eForm. Please open the encouter page of the patient you want to open the eForm for.", parent=self)
            return
        
        # Read most recent 0letter and append that text
        query = f"""
        SELECT
            fdid,
            fid,
            form_name,
            form_date,
            demographic_no
        FROM eform_data
        WHERE demographic_no = {demo_no}
          AND form_name LIKE '%letter%'
        ORDER BY form_date DESC
        LIMIT 1;
        """
        res = self.db_conn.query_database(query)

        fdid = res[0]["fdid"]
        return fdid



    def load_medical_history(self, doc_names=None, display=True):
        """
        Queries Oscar EMR database to find most recent 0letter eForm and the most recent documents
        for the documents the User selected. Then extracts and concats the text from 0letter and documents before
        pasting it into the User input textbox.
        """
        demo_no = self.oscar.get_demographic_no()
        if demo_no is None:
            messagebox.showwarning("Missing Patient", "Unable to open eForm. Please open the encouter page of the patient you want to open the eForm for.", parent=self)
            return

        query = f"""
        SELECT 
            cd.document_no,
            d.doctype,
            d.docdesc,
            d.observationdate
        FROM ctl_document AS cd
        LEFT JOIN document AS d
        ON cd.document_no = d.document_no
        WHERE cd.module = "demographic"
            AND cd.module_id = {demo_no}
        ORDER BY d.observationdate DESC;
        """
        res = self.db_conn.query_database(query)
        
        # Get selected documents
        if doc_names is None:
            selected_docs = [opt for opt, var in self.doc_cbs.items() if var.get()]
        else:
            selected_docs = doc_names
        print(selected_docs)

        # Filter documents to get most recent
        doc_nos = []
        doc_data = {}
        for doc in selected_docs:
            for row in res:
                print(row)
                row_type = row.get("doctype")
                row_desc = row.get("docdesc")
                doc_no   = row.get("document_no")
                obs_date = row.get("observationdate")
                
                # Check if type match 
                if doc.lower() == row_type.lower():
                    if doc_no not in doc_nos:
                        doc_nos.append(doc_no)
                        doc_data[doc_no] = (row_type, obs_date)
                        # Only keep first match, only want most recent document for each type selected
                        break
                # Could also add something to compare doc with row description to get more matches if
                # document type wasn't entered, but may match with wrong documents

        # Read document and append text
        text = ""
        for doc_no in doc_nos:
            try:
                pdf_bytes = self.oscar.get_document_bytes(doc_no)
                doc_text = pdf_image_to_text(pdf_bytes=pdf_bytes, last_page=3)
                data = doc_data[doc_no]

                text += f"DOCUMENT TYPE: {data[0]}\nOBSERVATION DATE: {data[1]}\n{doc_text}"
            except Exception as e:
                print(f"Error when reading text from {doc_no}: {e}")

        
        # Read most recent 0letter and append that text
        query = f"""
        SELECT
            fdid,
            fid,
            form_name,
            form_date,
            demographic_no
        FROM eform_data
        WHERE demographic_no = {demo_no}
          AND form_name LIKE '%letter%'
        ORDER BY form_date DESC
        LIMIT 1;
        """
        res = self.db_conn.query_database(query)

        fdid = res[0]["fdid"]
        date = res[0]["form_date"]

        letter_text = self.oscar.get_0letter_text(fdid)
        text += f"LETTER\nLETTER DATE: {date}\n{letter_text}"


        if display:
            for widget in self.parent.winfo_children():
                # Display extracted text in input textbox
                if getattr(widget, "_id", None) == "input_tbox":
                    widget.scrolled_text.delete("1.0", tk.END)
                    widget.scrolled_text.insert(tk.END, text)
        
        return text


    def get_patient_info(self, mute_popup=False):
        """
        Queries Oscar EMR database to retrieve information for opened patient
        """
        demo_no = self.oscar.get_demographic_no()
        if demo_no is None:
            if not mute_popup:
                messagebox.showwarning("Missing Patient", "Unable to open eForm. Please open the encouter page of the patient you want to open the eForm for.", parent=self)
            return False
        
        query = f"""
        SELECT *
        FROM demographic
        WHERE demographic_no = {demo_no}
        LIMIT 1;
        """
        res = self.db_conn.query_database(query)
        return res[0]