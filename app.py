"""
server.py — Flask web server for the Tee Time Booker
=====================================================
Serves the dashboard page and exposes two API endpoints:
  GET  /status  → returns last run info + recent log lines
  POST /run     → triggers an immediate booking attempt

Run with:  python server.py
"""

from flask import Flask, jsonify, send_from_directory, request
import threading
import subprocess
import json
import os
import re
from datetime import datetime

app = Flask(__name__, static_folder=".")

STATUS_FILE = "last_run.json"   # persists last booking result
LOG_FILE    = "booker.log"
SCRIPT      = "booker.py"       # your tee time booker script
VENV_PYTHON = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python3")

# Fall back to system python if venv not found
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python3"

_running = threading.Lock()     # prevent double-runs


def save_status(result: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump(result, f, indent=2)


def load_status() -> dict:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {}


def tail_log(n=40) -> list:
    """Return the last n lines of the log file."""
    if not os.path.exists(LOG_FILE):
        return ["No log file yet."]
    with open(LOG_FILE) as f:
        lines = f.readlines()
    return [l.rstrip() for l in lines[-n:]]


def run_booker_subprocess() -> dict:
    """Run booker.py as a subprocess and parse its output."""
    try:
        result = subprocess.run(
            [PYTHON, SCRIPT],
            capture_output=True,
            text=True,
            timeout=120,          # 2-minute timeout
            cwd=os.path.dirname(__file__)
        )
        output = result.stdout + result.stderr

        # Parse outcome from log output
        booked_match = re.search(r"BOOKED.*?(\d{1,2}:\d{2})", output, re.IGNORECASE)
        date_match   = re.search(r"Target date:\s*(\S+)", output)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = date_match.group(1) if date_match else "Saturday"

        if booked_match:
            status = {
                "ran_at":       now,
                "target_date":  target,
                "result":       "✅ Booked!",
                "time_booked":  booked_match.group(1),
                "success":      True,
            }
        elif "no eligible" in output.lower() or "no tee times" in output.lower():
            status = {
                "ran_at":       now,
                "target_date":  target,
                "result":       "❌ No times available",
                "time_booked":  None,
                "success":      False,
                "message":      "No tee times between 8–10 AM for 4 players.",
            }
        elif "login" in output.lower() and "fail" in output.lower():
            status = {
                "ran_at":       now,
                "target_date":  target,
                "result":       "❌ Login failed",
                "time_booked":  None,
                "success":      False,
                "message":      "Could not log in to foreUP. Check credentials in .env",
            }
        else:
            status = {
                "ran_at":       now,
                "target_date":  target,
                "result":       "⚠️ Unknown outcome",
                "time_booked":  None,
                "success":      False,
                "message":      "Check the activity log for details.",
            }

        save_status(status)
        return status

    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Booking timed out after 2 minutes."}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


@app.route("/status")
def status():
    return jsonify({
        "last_run":  load_status(),
        "log_lines": tail_log(50),
    })


@app.route("/run", methods=["POST"])
def run():
    if not _running.acquire(blocking=False):
        return jsonify({
            "success": False,
            "message": "A booking is already in progress — please wait."
        }), 409

    def do_run():
        try:
            run_booker_subprocess()
        finally:
            _running.release()

    thread = threading.Thread(target=do_run, daemon=True)
    thread.start()
    thread.join(timeout=90)   # wait up to 90s for result

    result = load_status()
    return jsonify(result)


if __name__ == "__main__":
    # 0.0.0.0 makes it accessible from outside the VM
    # Port 5000 — we'll put Nginx in front of it
    app.run(host="0.0.0.0", port=5000, debug=False)