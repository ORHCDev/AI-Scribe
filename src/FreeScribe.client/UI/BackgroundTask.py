import threading

# class handles the execution of background tasks, with access to state
class BackgroundTask:
    def __init__(self, root, func, args, on_done, poll_ms=200):
        self.root = root
        self.func = func
        self.args = args
        self.on_done = on_done
        self.poll_ms = poll_ms
        self.cancelled = False
        self.thread = None 
        self.result = None
        self.error = None
        self.after_id = None

    @property
    def thread_id(self):
        if self.thread:
            return self.thread.ident
        return None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.after_id = self.root.after(self.poll_ms, self._poll)

    def _run(self):
        try:
            self.result = self.func(*self.args)
        except Exception as e:
            self.error = e

    def _poll(self):
        # runs the poll method recursively
        if self.thread.is_alive():
            self.after_id = self.root.after(self.poll_ms, self._poll)
            return
        self.after_id = None
        if not self.cancelled:
            self.on_done(self.result, self.error)
        
    def cancel(self):
        self.cancelled = True
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

