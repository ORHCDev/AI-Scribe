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
        "Start Metoprolol 25 mg BID,\n"
        "Increase Furosemide to 80 mg daily,\n"
        "Stop Amlodipine,"
    )


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
    assert body == "Start Apixaban 5 mg BID, LU code 448,"
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
    assert value_of(driver, "druglist_generic") == "Start Nitro 0.4 mg SL \"PRN\" q 5 min, it's max 3,"


def test_form_is_not_submitted(driver, tmp_path):
    url = open_form(driver, tmp_path)
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), CHANGES)
    time.sleep(0.5)
    assert driver.current_url == url
    assert value_of(driver, "druglist_generic").startswith("Start Metoprolol")


def test_missing_reset_button_times_out_without_filling(driver, tmp_path):
    def remove_button(html):
        return html.replace('value="Click for new or dose change"', 'value="Something else"')

    open_form(driver, tmp_path, html_edit=remove_button)
    with pytest.raises(TimeoutException):
        med_eform.prepare_med_form(driver, WebDriverWait(driver, 2), CHANGES)
    # The app catches this and leaves the form as Oscar opened it.
    assert "Metoprolol" not in value_of(driver, "druglist_generic")


# --- what the form's own "Update Med List" (med_update) makes of our lines ---------------------
# The clinician may click it after reviewing the prescription. med_update() matches lines to the
# current meds by their first word and only strips "Increase "/"Decrease "/"to " first.

def update_med_list(driver, tmp_path, changes):
    open_form(driver, tmp_path)
    med_eform.prepare_med_form(driver, WebDriverWait(driver, 10), changes)
    driver.execute_script("med_update();")
    return [m.strip() for m in value_of(driver, "m$MEDS#value").split(",") if m.strip()]


def test_update_med_list_applies_dose_increase(driver, tmp_path):
    meds = update_med_list(driver, tmp_path, [
        {"action": "increase", "name": "Ramipril", "text": "Ramipril 10 mg daily"}])
    assert "Ramipril 10 mg daily" in meds
    assert "Ramipril 5 mg daily" not in meds


@pytest.mark.xfail(strict=True, reason="'Start ' prefix is copied into CURRENT MEDS by med_update(); "
                                       "open question whether to drop the prefix")
def test_update_med_list_adds_new_med_cleanly(driver, tmp_path):
    meds = update_med_list(driver, tmp_path, [
        {"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"}])
    assert "Metoprolol 25 mg BID" in meds


@pytest.mark.xfail(strict=True, reason="med_update() cannot remove a med: 'Stop X' is added and X stays; "
                                       "open question where stopped meds should be written")
def test_update_med_list_removes_stopped_med(driver, tmp_path):
    meds = update_med_list(driver, tmp_path, [{"action": "stop", "name": "Ramipril", "text": ""}])
    assert not any(m.startswith("Ramipril") for m in meds)
    assert not any(m.startswith("Stop") for m in meds)
