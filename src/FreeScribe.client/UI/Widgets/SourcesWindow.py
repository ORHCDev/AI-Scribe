import tkinter as tk

class SourcesWindow:
    def __init__(self, root, widget, sources, open_doc):
        self.root = root
        self.widget = widget
        self.sources = sources
        self.open_doc = open_doc
        self.window = None

        widget.bind('<Enter>', self.show)
        widget.bind('<Leave>', self.hide)

    def show(self, event):
        if self.window:
            return

        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height()
        self.window.geometry(f"+{x}+{y}")
        self.window.bind('<Leave>', self.hide)
        
        for source in self.sources:
            source_type = source.get('source_type', '')
            sid = source.get('id', '')
            data_type = source.get('data_type', '')
            obs_date = source.get('obs_date')
            date_str = obs_date.strftime('%Y-%m-%d') if obs_date else ""

            if source_type == "measurement":
                sid = sid.replace('\n\n', ', ')

            text = f"{source_type.title()} | {data_type} | {sid} | {date_str}"

            if source_type == "document" and self.open_doc:
                lbl = tk.Label(self.window, text=text, fg="blue", cursor="hand2")
                lbl.bind("<Button-1>", lambda e, s=sid: self._click_doc(s))
            else:
                lbl = tk.Label(self.window, text=text)

            lbl.pack(anchor="w", padx=8, pady=4)

    def _destroy_window(self):
        if self.window:
            w = self.window
            self.window = None
            w.destroy()

    def _click_doc(self, sid):
        self.open_doc(sid)
        self._destroy_window()

    def hide(self, event):
        if not self.window:
            return
        w = self.window
        try:
            wx, wy = w.winfo_rootx(), w.winfo_rooty()
            ww, wh = w.winfo_width(), w.winfo_height()
            if wx <= event.x_root <= wx + ww and wy <= event.y_root <= wy + wh:
                return
        except tk.TclError:
            pass

        self._destroy_window()
