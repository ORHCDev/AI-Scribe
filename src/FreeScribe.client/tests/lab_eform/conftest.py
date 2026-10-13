"""Puts src/FreeScribe.client on sys.path so `Oscar` and `utils.*` import the way the app does."""

import sys
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))
