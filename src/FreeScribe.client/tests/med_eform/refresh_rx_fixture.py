"""
Replace fixtures/rx_0.1Rfx.html with the live 0.1Rfx eForm template from Oscar.

The template is the blank form (no patient data). The two placeholders the Layer 2 tests use to
inject "current meds" are added back into the prescription body and CURRENT MEDS textareas.

Run from src/FreeScribe.client on a machine with Oscar access (same setup as tests/test_sql.py):
    python tests/med_eform/refresh_rx_fixture.py
Then re-run the tests and review the diff before committing.
"""

import re
import sys
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CLIENT_ROOT))

from chatbot.OscarChatbot import OscarCB  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rx_0.1Rfx.html"
FORM_PREFIX = "0.1Rfx"


def add_placeholder(html: str, element_id: str, marker: str) -> str:
    """Put `marker` inside the (empty) <textarea id="element_id"> ... </textarea>."""
    pattern = re.compile(r'(<textarea[^>]*\bid="' + re.escape(element_id) + r'"[^>]*>)\s*(</textarea>)', re.I)
    new_html, count = pattern.subn(lambda m: m.group(1) + marker + m.group(2), html, count=1)
    if count != 1:
        sys.exit(f"Could not find an empty <textarea id=\"{element_id}\"> in the template.")
    return new_html


def main():
    chatbot = OscarCB(config_path=str(CLIENT_ROOT / "configs" / "config.yaml"))
    try:
        rows = chatbot.db_conn.query_database(
            f"SELECT fid, form_name, form_html FROM eform "
            f"WHERE status = 1 AND form_name LIKE '{FORM_PREFIX}%' ORDER BY fid DESC LIMIT 1;"
        )
    finally:
        chatbot.cleanup()
    if not rows:
        sys.exit(f"No active eForm named {FORM_PREFIX}* found.")
    row = rows[0]
    html = row["form_html"]
    html = add_placeholder(html, "druglist_generic", "<!--FIXTURE:DRUGLIST-->")
    html = add_placeholder(html, "m$MEDS#value", "<!--FIXTURE:CURRENTMEDS-->")
    header = (f"<!--\n  Test fixture: {row['form_name']} eForm template from Oscar (fid {row['fid']}),\n"
              f"  refreshed by tests/med_eform/refresh_rx_fixture.py. Template only - no patient data.\n-->\n")
    FIXTURE.write_text(header + html, encoding="utf-8")
    print(f"Wrote {FIXTURE} from fid {row['fid']} ({row['form_name']}).")


if __name__ == "__main__":
    main()
