"""
Layer 2: fill the real medication eForm page in a headless browser (no Oscar needed).

Loads tests/med_eform/fixtures/rx_0.1Rfx.html with "current meds" injected the way Oscar does,
then runs utils.med_eform.prepare_med_form - the same function the app calls - and checks what
ends up in the form. Skipped when selenium or a Chrome browser is not available.
"""

import time
from pathlib import Path

import pytest

from utils import med_eform

webdriver = pytest.importorskip("selenium.webdriver")
from selenium.common.exceptions import TimeoutException, WebDriverException  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rx_0.1Rfx.html"

# What Oscar would pre-fill from the patient's MEDS measurement. Brand names and LU-code-less
# lines on purpose: the form's own onload scripts rewrite them (replacer / reloadSignature).
CURRENT_MEDS = "Lipitor 40 mg daily, Apixaban 5 mg BID, Ramipril 5 mg daily, "


@pytest.fixture(scope="module")
def driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    try:
        drv = webdriver.Chrome(options=options)
    except WebDriverException as e:
        pytest.skip(f"Chrome WebDriver unavailable: {e.msg}")
    drv.set_page_load_timeout(30)
    yield drv
    drv.quit()


def open_form(driver, tmp_path, current_meds=CURRENT_MEDS, html_edit=None):
    """Write the fixture with the patient's meds injected and load it like Oscar would serve it."""
    html = FIXTURE.read_text(encoding="utf-8")
    html = html.replace("<!--FIXTURE:DRUGLIST-->", current_meds)
    html = html.replace("<!--FIXTURE:CURRENTMEDS-->", current_meds)
    # The template pulls jQuery from a CDN it never uses; drop it so the test needs no network.
    html = html.replace('<script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>', "")
    if html_edit:
        html = html_edit(html)
    page = tmp_path / "rx_form.html"
    page.write_text(html, encoding="utf-8")
    driver.get(page.as_uri())
    return page.as_uri()


def value_of(driver, element_id):
    return driver.execute_script("return document.getElementById(arguments[0]).value;", element_id)


CHANGES = [
    {"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"},
    {"action": "increase", "name": "Furosemide", "text": "Furosemide 80 mg daily"},
    {"action": "stop", "name": "Amlodipine", "text": ""},
]


def test_reset_then_fill_prescription_body(driver, tmp_path):
    open_form(driver, tmp_path)
    result = med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), CHANGES)
    assert result["reset"].endswith("Click for new or dose change")
    assert result["fill"] == "filled"
    assert value_of(driver, "druglist_generic") == (
        "Metoprolol 25 mg BID, Increase Furosemide to 80 mg daily, Stop Amlodipine, ")


def test_current_meds_are_not_touched(driver, tmp_path):
    open_form(driver, tmp_path)
    before = value_of(driver, "m$MEDS#value")
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), CHANGES)
    assert value_of(driver, "m$MEDS#value") == before


def test_fill_happens_after_onload_scripts(driver, tmp_path):
    open_form(driver, tmp_path)
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), CHANGES)
    # replacer() ran on load (brand -> generic in CURRENT MEDS) before we filled anything ...
    assert "Atorvastatin 40 mg daily" in value_of(driver, "m$MEDS#value")
    # ... and nothing from the old pre-filled prescription body survived the reset.
    assert "Atorvastatin" not in value_of(driver, "druglist_generic")


def test_lu_code_not_duplicated(driver, tmp_path):
    # reloadSignature() appends LU codes on load; filling afterwards must not double them.
    open_form(driver, tmp_path)
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), [
        {"action": "start", "name": "Apixaban", "text": "Apixaban 5 mg BID, LU code 448"}])
    body = value_of(driver, "druglist_generic")
    assert body == "Apixaban 5 mg BID, LU code 448, "
    assert body.count("LU code 448") == 1


def test_no_changes_resets_and_leaves_body_empty(driver, tmp_path):
    open_form(driver, tmp_path)
    result = med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), [])
    assert result["fill"] is None
    assert value_of(driver, "druglist_generic") == ""


def test_text_with_quotes_and_newlines_is_written_verbatim(driver, tmp_path):
    open_form(driver, tmp_path)
    tricky = [{"action": "start", "name": "Nitro", "text": "Nitro 0.4 mg SL \"PRN\" q 5 min, it's max 3"}]
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), tricky)
    assert value_of(driver, "druglist_generic") == "Nitro 0.4 mg SL \"PRN\" q 5 min, it's max 3, "


def test_form_is_not_submitted(driver, tmp_path):
    url = open_form(driver, tmp_path)
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), CHANGES)
    time.sleep(0.5)
    assert driver.current_url == url
    assert value_of(driver, "druglist_generic").startswith("Metoprolol 25 mg BID")


def test_missing_reset_button_times_out_without_filling(driver, tmp_path):
    def remove_button(html):
        return html.replace('value="Click for new or dose change"', 'value="Something else"')

    open_form(driver, tmp_path, html_edit=remove_button)
    with pytest.raises(TimeoutException):
        med_eform.prepare_med_form(driver, WebDriverWait(driver, 2), CHANGES)
    # The app catches this and leaves the form as Oscar opened it.
    assert "Metoprolol" not in value_of(driver, "druglist_generic")


# --- "Update Med List" in the form AI Scribe opens ---------------------------------------------
# prepare_med_form swaps in the fixed med_update (utils/rx_med_update.py) for that window only; the
# clinician may click the button after reviewing, and CURRENT MEDS is saved to the chart on submit.

MEDS = "Lipitor 40 mg daily, Ramipril 5 mg daily, Furosemide 40 mg daily, Amlodipine 5 mg daily, "


def update_med_list(driver, tmp_path, changes=None, body=None, current_meds=MEDS):
    """Open the form the way the app does, fill it (from `changes`, or `body` typed by the clinician),
    click the real "Update Med List" button and return CURRENT MEDS as a list of entries."""
    open_form(driver, tmp_path, current_meds=current_meds)
    result = med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), changes or [])
    assert result["update_med_list"] == "fixed version installed"
    if body is not None:
        driver.execute_script("document.getElementById('druglist_generic').value = arguments[0];", body)
    driver.find_element("id", "update_med").click()
    text = value_of(driver, "m$MEDS#value")
    assert text == "" or text.endswith(", ")     # same "Drug dose frequency, " format as before
    return text, ([m.strip() for m in text[:-2].split(", ")] if text else [])


INCREASE = {"action": "increase", "name": "Furosemide", "text": "Furosemide 80 mg daily"}
DECREASE = {"action": "decrease", "name": "Ramipril", "text": "Ramipril 2.5 mg daily"}
START = {"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"}
STOP = {"action": "stop", "name": "Amlodipine", "text": ""}
APIXABAN = {"action": "start", "name": "Apixaban", "text": "Apixaban 5 mg BID, LU code 448"}
ENTRESTO = {"action": "start", "name": "sacubitril/valsartan", "text": "sacubitril/valsartan 49/51 mg BID, LU 497"}


def test_prescription_keeps_increase_wording_but_current_meds_get_only_the_new_regimen(driver, tmp_path):
    open_form(driver, tmp_path, current_meds=MEDS)
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), [INCREASE, DECREASE])
    assert value_of(driver, "druglist_generic") == (
        "Increase Furosemide to 80 mg daily, Decrease Ramipril to 2.5 mg daily, ")
    driver.find_element("id", "update_med").click()
    assert value_of(driver, "m$MEDS#value") == (
        "Atorvastatin 40 mg daily, Ramipril 2.5 mg daily, Furosemide 80 mg daily, Amlodipine 5 mg daily, ")
    # the prescription itself still says what changed
    assert value_of(driver, "druglist_generic").startswith("Increase Furosemide to 80 mg daily")


def test_update_multi_word_drug_dose_change(driver, tmp_path):
    _, meds = update_med_list(driver, tmp_path,
                              [{"action": "increase", "name": "Diltiazem", "text": "Diltiazem CD 240 mg daily"}],
                              current_meds="Diltiazem CD 120 mg daily, Ramipril 5 mg daily, ")
    assert meds == ["Diltiazem CD 240 mg daily", "Ramipril 5 mg daily"]


def test_update_applies_new_changed_and_stopped_meds(driver, tmp_path):
    _, meds = update_med_list(driver, tmp_path, [START, INCREASE, DECREASE, STOP])
    assert meds == ["Metoprolol 25 mg BID", "Atorvastatin 40 mg daily", "Ramipril 2.5 mg daily",
                    "Furosemide 80 mg daily"]


def test_update_drops_lu_codes_from_current_meds(driver, tmp_path):
    _, meds = update_med_list(driver, tmp_path, [APIXABAN, ENTRESTO])
    assert "Apixaban 5 mg BID" in meds
    assert "sacubitril/valsartan 49/51 mg BID" in meds
    assert not any("LU" in m for m in meds)


def test_update_handles_the_forms_own_buttons(driver, tmp_path):
    # Lines a clinician builds by hand with the form's "Start" / "increase dose" / "decrease dose"
    # checkboxes, two changes at once - the case the original med_update got wrong.
    body = ("Start Metoprolol 25 mg BID, Increase Furosemide to  80 mg daily, "
            "Decrease Ramipril to 2.5 mg daily, ")
    _, meds = update_med_list(driver, tmp_path, body=body)
    assert meds == ["Metoprolol 25 mg BID", "Atorvastatin 40 mg daily", "Ramipril 2.5 mg daily",
                    "Furosemide 80 mg daily", "Amlodipine 5 mg daily"]


def test_update_keeps_multi_part_standard_lines_together(driver, tmp_path):
    body = ("Amiodarone 400 mg BID for 7 days, 200 mg TID for 3 days, 200 mg BID for 4 days then 200 mg daily, "
            "0.4 mg P.R.N. nitroglycerin spray, SL for chest pain q 5 min to max of 3 sprays in an hour, ")
    text, _ = update_med_list(driver, tmp_path, body=body, current_meds="Ramipril 5 mg daily, ")
    assert ("Amiodarone 400 mg BID for 7 days, 200 mg TID for 3 days, "
            "200 mg BID for 4 days then 200 mg daily, ") in text
    assert "0.4 mg P.R.N. nitroglycerin spray, SL for chest pain" in text
    assert text.count("Amiodarone") == 1
    assert text.endswith("Ramipril 5 mg daily, ")


def test_update_stop_of_unlisted_med_changes_nothing(driver, tmp_path):
    _, meds = update_med_list(driver, tmp_path, [{"action": "stop", "name": "Digoxin", "text": ""}])
    assert meds == ["Atorvastatin 40 mg daily", "Ramipril 5 mg daily", "Furosemide 40 mg daily",
                    "Amlodipine 5 mg daily"]


def test_update_with_nothing_filled_keeps_current_meds(driver, tmp_path):
    _, meds = update_med_list(driver, tmp_path, [])
    assert meds == ["Atorvastatin 40 mg daily", "Ramipril 5 mg daily", "Furosemide 40 mg daily",
                    "Amlodipine 5 mg daily"]


def test_forms_opened_by_hand_keep_the_original_update(driver, tmp_path):
    # Only the window AI Scribe prepares is changed; the template (and forms opened in Oscar by
    # hand) still have the form's own med_update.
    open_form(driver, tmp_path)
    assert driver.execute_script("return !!(window.med_update && window.med_update.aiScribeFixed);") is False
