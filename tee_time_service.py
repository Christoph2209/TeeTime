import subprocess
import json
import os
import re
from datetime import datetime

STATUS_FILE = "last_run.json"
LOG_FILE = "booker.log"
SCRIPT = "booker.py"


def save_status(result: dict):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)


def load_status() -> dict:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def tail_log(n=50) -> list[str]:
    if not os.path.exists(LOG_FILE):
        return ["No log file yet."]
    with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return [line.rstrip() for line in lines[-n:]]


def parse_booker_output(output: str, config: dict | None = None) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lower = output.lower()

    date_match = re.search(r"Target date:\s*(\S+)", output)
    target_date = date_match.group(1) if date_match else "Saturday"

    time_match = re.search(r"Eligible time found:\s*([0-9:apm]+)", output, re.IGNORECASE)
    booked_match = re.search(r"BOOKING CONFIRMED:\s*([0-9:apm]+)", output, re.IGNORECASE)

    base = {
        "ran_at": now,
        "target_date": target_date,
        "config": config or {},
        "raw_output_tail": "\n".join(output.strip().splitlines()[-20:]) if output.strip() else "",
    }

    if booked_match:
        booked_time = booked_match.group(1)
        return {
            **base,
            "success": True,
            "result": "✅ Booked!",
            "time_booked": booked_time,
            "date": target_date,
            "time": booked_time,
            "message": f"Booked successfully for {booked_time}.",
        }

    # Preview-only / reached final step variants
    final_step_signals = [
        "reached final step successfully",
        "book time button found, but not clicked",
        "job complete — reached final step without booking",
        "ready to book",
        "preview_without_booking",
    ]
    if any(signal in lower for signal in final_step_signals):
        found_time = time_match.group(1) if time_match else None
        return {
            **base,
            "success": True,
            "result": "🟡 Reached final step",
            "time_booked": found_time,
            "date": target_date,
            "time": found_time,
            "message": "Reached the final Book Time step without clicking it.",
        }

    if "no eligible" in lower or "no tee times" in lower or "no slots" in lower:
        return {
            **base,
            "success": False,
            "result": "❌ No times available",
            "time_booked": None,
            "date": target_date,
            "time": None,
            "message": "No qualifying tee times were found.",
        }

    if "login" in lower and ("fail" in lower or "failed" in lower):
        return {
            **base,
            "success": False,
            "result": "❌ Login failed",
            "time_booked": None,
            "date": target_date,
            "time": None,
            "message": "Could not log in to ForeUp. Check credentials.",
        }

    if "timed out waiting for foreup booking code email" in lower or "no booking code" in lower:
        return {
            **base,
            "success": False,
            "result": "❌ Email code not found",
            "time_booked": None,
            "date": target_date,
            "time": None,
            "message": "Could not find the booking code email in time.",
        }

    if "cancelled" in lower or "canceled" in lower:
        return {
            **base,
            "success": False,
            "result": "🛑 Cancelled",
            "time_booked": None,
            "date": target_date,
            "time": None,
            "message": "Booking run was cancelled.",
        }

    return {
        **base,
        "success": False,
        "result": "⚠️ Unknown outcome",
        "time_booked": time_match.group(1) if time_match else None,
        "date": target_date,
        "time": time_match.group(1) if time_match else None,
        "message": "The run finished, but the server could not classify the result. Check raw output below.",
    }


def run_booker(python_exec: str = "python3", cwd: str | None = None) -> dict:
    try:
        result = subprocess.run(
            [python_exec, SCRIPT],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=cwd or os.getcwd(),
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        status = parse_booker_output(output)
        save_status(status)
        return status
    except subprocess.TimeoutExpired:
        status = {
            "success": False,
            "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_date": "Saturday",
            "result": "❌ Timed out",
            "time_booked": None,
            "date": "Saturday",
            "time": None,
            "message": "Booking attempt timed out after 5 minutes.",
        }
        save_status(status)
        return status