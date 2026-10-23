from datetime import datetime
from pathlib import Path
import subprocess

def generate_build_info():
    commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()

    output_path = Path(__file__).resolve().parent / "build_info.py"

    output_path.write_text(
        f'GIT_COMMIT = "{commit_hash}"\n',
        encoding="utf-8"
    )

    print(f"Generated build info: {commit_hash}")