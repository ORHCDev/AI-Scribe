from datetime import datetime
import uuid


class ChatSession:
    def __init__(self, demo_no, conversation, history):
        self.id = uuid.uuid4().hex
        self.created_at = datetime.now()
        self.label = self.created_at.strftime("%H:%M:%S")
        self.demo_no = demo_no
        self.conversation = dict(conversation)
        self.history = list(history)

    def update(self, demo_no, conversation, history):
        self.demo_no = demo_no
        self.conversation = dict(conversation)
        self.history = list(history)
