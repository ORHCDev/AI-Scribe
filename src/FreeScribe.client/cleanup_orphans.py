"""
Kill orphaned geckodriver/Firefox processes left by a crashed/force-killed AI-Scribe.
Safe: skips if a client is running, kills recorded geckodrivers together with their
Firefox children, and sweeps up orphaned Selenium Firefox (identified by the
-marionette flag, so the user's own Firefox is never touched).
Run: python cleanup_orphans.py
"""

import os
import psutil

PID_FILE = r".\chatbot\logs\owned_drivers.pids"


# return True if an AI-Scribe client.py process is currently running
def any_client_running() -> bool:
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if cmdline and "client.py" in " ".join(cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


# read the geckodriver PIDs AI-Scribe recorded, ignoring any junk lines.
def read_recorded_pids(path: str = PID_FILE) -> set[int]:
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return {int(tok) for tok in f.read().split() if tok.strip().isdigit()}


def _is_geckodriver(proc) -> bool:
    """True if the process is still a geckodriver (guards against PID reuse)."""
    try:
        return "geckodriver" in proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _is_selenium_firefox(proc) -> bool:
    """
    True only for a Firefox that Selenium/geckodriver launched. Those always run
    with the -marionette flag; a user's own Firefox does not, so this never kills
    a browser the user opened themselves.
    """
    try:
        if "firefox" not in proc.name().lower():
            return False
        cmdline = proc.cmdline()
        return any("marionette" in arg.lower() for arg in cmdline)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _kill(proc) -> bool:
    """Kill one process, tolerating races. Returns True if a kill was issued."""
    try:
        proc.kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def kill_recorded_drivers(pids: set[int]) -> int:
    """
    Kill each recorded geckodriver that is still a geckodriver, together with its
    Firefox child processes. Children are collected before the parent is killed.
    """
    killed = 0
    for pid in pids:
        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not _is_geckodriver(proc):
            continue

        try:
            victims = proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            victims = []
        victims.append(proc)  # kill children first, parent last

        for victim in victims:
            if _kill(victim):
                killed += 1
    return killed


def kill_orphan_selenium_firefox() -> int:
    """
    Kill Selenium-launched Firefox whose geckodriver parent already died (so it is
    no longer reachable as a child of any recorded PID). Identified by -marionette.
    """
    killed = 0
    for proc in psutil.process_iter():
        if _is_selenium_firefox(proc) and _kill(proc):
            killed += 1
    return killed


def main() -> None:
    if any_client_running():
        print("A client.py is running; skipping cleanup to avoid killing an active session.")
        return

    killed = kill_recorded_drivers(read_recorded_pids())
    killed += kill_orphan_selenium_firefox()

    # Clear the record now that these orphans are handled.
    open(PID_FILE, "w").close()
    print(f"Cleaned up {killed} orphaned geckodriver/Firefox process(es).")


if __name__ == "__main__":
    main()
