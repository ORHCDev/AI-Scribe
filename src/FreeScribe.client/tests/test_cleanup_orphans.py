"""Tests for cleanup_orphans PID-file parsing."""

import cleanup_orphans

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
