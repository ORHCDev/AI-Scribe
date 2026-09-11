"""Tests for cleanup_orphans PID-file parsing and process identification."""

import psutil

import cleanup_orphans


class FakeProc:
    """Duck-typed stand-in for psutil.Process for identification tests."""

    def __init__(self, name="", cmdline=None, raises=None):
        self._name = name
        self._cmdline = cmdline or []
        self._raises = raises

    def name(self):
        if self._raises:
            raise self._raises
        return self._name

    def cmdline(self):
        if self._raises:
            raise self._raises
        return self._cmdline


def test_reads_clean_pids(tmp_path):
    f = tmp_path / "pids.txt"
    f.write_text("21756\n2712\n9164\n")
    assert cleanup_orphans.read_recorded_pids(str(f)) == {21756, 2712, 9164}


def test_skips_junk_tokens(tmp_path):
    f = tmp_path / "pids.txt"
    f.write_text("21756\n\nNone\nabc\n2712\n")
    assert cleanup_orphans.read_recorded_pids(str(f)) == {21756, 2712}


def test_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    assert cleanup_orphans.read_recorded_pids(str(missing)) == set()


def test_is_geckodriver_matches_name():
    assert cleanup_orphans._is_geckodriver(FakeProc(name="geckodriver.exe"))
    assert cleanup_orphans._is_geckodriver(FakeProc(name="GeckoDriver"))
    assert not cleanup_orphans._is_geckodriver(FakeProc(name="firefox.exe"))


def test_is_geckodriver_handles_vanished_process():
    gone = FakeProc(raises=psutil.NoSuchProcess(pid=123))
    assert not cleanup_orphans._is_geckodriver(gone)


def test_selenium_firefox_needs_marionette():
    selenium_ff = FakeProc(
        name="firefox.exe",
        cmdline=["firefox.exe", "-marionette", "-foreground", "-profile", r"C:\Temp\rust_moz"],
    )
    assert cleanup_orphans._is_selenium_firefox(selenium_ff)


def test_user_firefox_is_spared():
    # A browser the user opened has no -marionette flag and must never be killed.
    user_ff = FakeProc(name="firefox.exe", cmdline=["firefox.exe", "https://example.com"])
    assert not cleanup_orphans._is_selenium_firefox(user_ff)


def test_non_firefox_is_ignored():
    other = FakeProc(name="chrome.exe", cmdline=["chrome.exe", "-marionette"])
    assert not cleanup_orphans._is_selenium_firefox(other)


def test_is_selenium_firefox_handles_access_denied():
    denied = FakeProc(raises=psutil.AccessDenied(pid=123))
    assert not cleanup_orphans._is_selenium_firefox(denied)
