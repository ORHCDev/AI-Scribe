"""
Kill orphaned geckodriver/Firefox processes left by a crashed/force-killed AI-Scribe. 
Safe: skips if a client is running, only touches recorded PIDs, and only kills processes that are still geckodriver. 
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


def main() -> None:
    if any_client_running():
        print("A client.py is running; skipping cleanup to avoid killing an active session.")
        return

    pids = read_recorded_pids()
    if not pids:
        print("No recorded geckodriver PIDs; nothing to clean up.")
        return

    killed = 0
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            # only kill if this PID is STILL a geckodriver. Guards against PID reuse.
            if "geckodriver" in proc.name().lower():
                proc.kill() 
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Clear the record now that these orphans are handled.
    open(PID_FILE, "w").close()
    print(f"Cleaned up {killed} orphaned geckodriver process(es).")


if __name__ == "__main__":
    main()
    