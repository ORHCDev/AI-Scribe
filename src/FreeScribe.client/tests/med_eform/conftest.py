"""
Shared fixtures for the medication eForm tests.

Puts src/FreeScribe.client on sys.path so `utils.med_eform` imports the same way the app does,
and loads utils/read_files.py with its heavy OCR/PDF deps stubbed when they are not installed.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
CLIENT_ROOT = _HERE.parent.parent
FIXTURES = _HERE / "fixtures"

if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except Exception:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod


@pytest.fixture(scope="session")
def read_files():
    """utils/read_files.py, with cv2 / pdf2image / PIL / pytesseract / numpy stubbed if absent."""
    _stub_if_missing("cv2")
    _stub_if_missing("pdf2image", convert_from_path=None, convert_from_bytes=None)
    _stub_if_missing("PIL")
    if not hasattr(sys.modules["PIL"], "Image"):
        sys.modules["PIL"].Image = types.ModuleType("PIL.Image")
        sys.modules["PIL.Image"] = sys.modules["PIL"].Image
    _stub_if_missing("pytesseract")
    _stub_if_missing("numpy")
    spec = importlib.util.spec_from_file_location("read_files_under_test", CLIENT_ROOT / "utils" / "read_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLLM:
    """Stand-in for send_text_to_chatgpt: returns a fixed reply (or raises it) and records prompts."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def fake_llm():
    return FakeLLM
