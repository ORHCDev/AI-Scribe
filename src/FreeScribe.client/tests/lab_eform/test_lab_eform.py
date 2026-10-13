"""
Lab requisition eForm (fid 659, "LABNew"): opening it with checkboxes ticked, against the real template.

Loads tests/lab_eform/fixtures/lab_659.html in a headless browser and drives it through
Oscar.open_new_eform - the same call the app makes after a consult upload - with the checkbox list
built the way client._open_labs_eform builds it. Skipped without selenium / a browser driver.
"""

import os
import re
from pathlib import Path

import pytest

webdriver = pytest.importorskip("selenium.webdriver")
pytest.importorskip("bs4")
from selenium.common.exceptions import TimeoutException, WebDriverException  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

from Oscar import Oscar  # noqa: E402
from utils.lab_analysis import LAB_CHECKBOX_ANALYSIS_PROMPT  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lab_659.html"


@pytest.fixture(scope="module")
def driver():
    # The app drives Firefox (geckodriver); EFORM_TEST_BROWSER=firefox runs these tests in it.
    browser = os.environ.get("EFORM_TEST_BROWSER", "chrome").lower()
    try:
        if browser == "firefox":
            options = webdriver.FirefoxOptions()
            options.add_argument("-headless")
            options.set_preference("dom.disable_open_during_load", False)
            drv = webdriver.Firefox(options=options)
        else:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-popup-blocking")
            drv = webdriver.Chrome(options=options)
    except WebDriverException as e:
        pytest.skip(f"{browser} WebDriver unavailable: {e.msg}")
    yield drv
    drv.quit()


def make_oscar(driver, form_url, timeout=10):
    """An Oscar object wired to the test browser, without logging in to a real server."""
    oscar = Oscar.__new__(Oscar)
    oscar.driver = driver
    oscar.wait = WebDriverWait(driver, timeout)
    oscar.new_eform_template = form_url + "?fid={fid}&demographic_no={demo_no}"
    oscar.get_demographic_no = lambda: "1"
    # Fresh "home" window for each test, with any eForm windows from earlier tests closed.
    for handle in driver.window_handles[1:]:
        driver.switch_to.window(handle)
        driver.close()
    driver.switch_to.window(driver.window_handles[0])
    # A file:// home page: Chrome will not open file:// windows from a data: page.
    home = Path(form_url.split("://", 1)[-1]).parent / "home.html"
    home.write_text("<title>home</title>home", encoding="utf-8")
    driver.get(home.as_uri())
    oscar.home_window = driver.current_window_handle
    return oscar


def write_form(tmp_path):
    page = tmp_path / "lab_form.html"
    page.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return page.as_uri()


def form_checkboxes(monkeypatch):
    """Oscar.get_eform_checkboxes() on the fixture, as client._open_labs_eform calls it."""
    oscar = Oscar.__new__(Oscar)
    monkeypatch.setattr(oscar, "_get_blank_eform_html", lambda fid: FIXTURE.read_bytes(), raising=False)
    return oscar.get_eform_checkboxes(659)


def select_like_open_labs_eform(checkbox_data, codes):
    """Same matching as client._open_labs_eform: compare stripped names, pass the form's own dicts."""
    wanted = {c.strip() for c in codes}
    return [cb for cb in checkbox_data if cb["name"].strip() in wanted]


def boxes(*names):
    return [{"type": "checkbox", "name": n, "value": None} for n in names]


def eform_window_state(driver, oscar):
    """Switch to the opened eForm window and read back checkboxes and X-boxes."""
    form_window = next(h for h in driver.window_handles if h != oscar.home_window)
    driver.switch_to.window(form_window)
    return driver.execute_script("""
        var checked = Array.from(document.querySelectorAll('input[type=checkbox]'))
            .filter(function (c) { return c.checked; }).map(function (c) { return c.name; });
        var x = Array.from(document.querySelectorAll('input[type=text]'))
            .filter(function (i) { return i.value === 'X'; }).map(function (i) { return i.name; });
        return {checked: checked, x: x, subject: document.getElementById('subject').value,
                otherTests: document.getElementById('OtherTests').value};
    """)


# --- the prompt and the form agree on checkbox names -------------------------------------------

def test_prompt_codes_match_the_form_except_kfollowup(monkeypatch):
    form_names = {cb["name"].strip() for cb in form_checkboxes(monkeypatch)}
    prompt_codes = set(re.findall(r"^- (\S+) \(", LAB_CHECKBOX_ANALYSIS_PROMPT, re.M))
    assert prompt_codes, "could not read codes from the prompt"
    # Known gap: the prompt offers KFollowUp ("CHF Follow-up post high K+"), but fid 659 has no
    # such checkbox, so that pick is dropped (and logged). Update this when either side changes.
    assert prompt_codes - form_names == {"KFollowUp"}


def test_get_eform_checkboxes_without_html_returns_empty(monkeypatch):
    oscar = Oscar.__new__(Oscar)
    monkeypatch.setattr(oscar, "_get_blank_eform_html", lambda fid: None, raising=False)
    assert oscar.get_eform_checkboxes(659) == []


# --- opening the form with boxes ticked --------------------------------------------------------

def test_ticks_requested_boxes_and_runs_their_onclick(driver, tmp_path):
    oscar = make_oscar(driver, write_form(tmp_path))
    assert oscar.open_new_eform(659, boxes("CHFFollowUp", "CompleteBloodCount", "UrineC&S")) is True
    assert driver.current_window_handle == oscar.home_window
    state = eform_window_state(driver, oscar)
    assert set(state["checked"]) == {"CHFFollowUp", "CompleteBloodCount", "UrineC&S"}
    # their onclick handlers ran once: X-boxes marked, text added
    assert {"Sodium", "Potassium", "Chloride", "Creatinine", "Albumin", "CBC", "UrineCulture"} <= set(state["x"])
    assert "NT-proBNP" in state["otherTests"]
    assert "UTI" in state["subject"]


def test_renal_function_checkbox_with_trailing_space_in_name(driver, tmp_path, monkeypatch):
    # The real template has name="RenalFunction " (trailing space); the LLM returns "RenalFunction".
    fields = select_like_open_labs_eform(form_checkboxes(monkeypatch), ["RenalFunction", "CHFFollowUp"])
    assert {f["name"] for f in fields} == {"RenalFunction ", "CHFFollowUp"}
    oscar = make_oscar(driver, write_form(tmp_path))
    oscar.open_new_eform(659, fields)
    state = eform_window_state(driver, oscar)
    assert {"RenalFunction ", "CHFFollowUp"} <= set(state["checked"])
    assert "INSTRUCTIONS - do in 1 week" in state["subject"]


def test_box_ticked_once_onclick_runs_once(driver, tmp_path):
    oscar = make_oscar(driver, write_form(tmp_path))
    oscar.open_new_eform(659, boxes("Digoxin", "Digoxin"))   # duplicate pick from the LLM
    state = eform_window_state(driver, oscar)
    assert state["checked"].count("Digoxin") == 1
    assert state["otherTests"].count("Digoxin") == 1


def test_unknown_names_are_skipped_without_error(driver, tmp_path, capsys):
    oscar = make_oscar(driver, write_form(tmp_path))
    oscar.open_new_eform(659, boxes("NotARealBox", "CHFFollowUp"))
    assert "not found: ['NotARealBox']" in capsys.readouterr().out
    assert "CHFFollowUp" in eform_window_state(driver, oscar)["checked"]


def test_no_boxes_just_opens_the_form(driver, tmp_path):
    oscar = make_oscar(driver, write_form(tmp_path))
    assert oscar.open_new_eform(659, []) is True
    assert driver.current_window_handle == oscar.home_window
    assert len(driver.window_handles) == 2


# --- the driver always comes back to the main window -------------------------------------------

class _WaitThatTimesOutOnLoad:
    """Real wait for the new window to appear; then 'times out' waiting for the form to load -
    i.e. fails after the driver has already switched to the eForm window."""

    def __init__(self, real):
        self.real, self.calls = real, 0

    def until(self, method, message=""):
        self.calls += 1
        if self.calls == 1:
            return self.real.until(method, message)
        raise TimeoutException("form did not finish loading")


def test_returns_to_main_window_when_form_never_loads(driver, tmp_path):
    oscar = make_oscar(driver, write_form(tmp_path))
    oscar.wait = _WaitThatTimesOutOnLoad(oscar.wait)
    with pytest.raises(TimeoutException):
        oscar.open_new_eform(659, boxes("CHFFollowUp"))
    assert oscar.wait.calls == 2
    assert driver.current_window_handle == oscar.home_window
