"""Start the local studio from this checkout and open it after it is ready."""
import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = "http://127.0.0.1:8786"


def ready():
    try:
        with urllib.request.urlopen(ADDRESS + "/app.js", timeout=2) as response:
            return response.read() == (ROOT / "backspace_mvp/web_static/app.js").read_bytes()
    except (OSError, urllib.error.URLError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not ready():
        logs = ROOT / "output"
        logs.mkdir(exist_ok=True)
        with (logs / "studio.stdout.log").open("ab") as stdout, (logs / "studio.stderr.log").open("ab") as stderr:
            process = subprocess.Popen(
                [sys.executable, "-m", "backspace_mvp.web", "--port", "8786"],
                cwd=ROOT, stdout=stdout, stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        deadline = time.monotonic() + 30
        while not ready():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise SystemExit("Backspace could not start. Check output/studio.stderr.log.")
            time.sleep(0.2)
    print("Backspace: " + ADDRESS)
    if not args.no_browser:
        webbrowser.open(ADDRESS)


if __name__ == "__main__":
    main()
