from flask import Flask, jsonify, request, Response
import threading
import subprocess
import json
import os
import re
from datetime import datetime

app = Flask(__name__)

STATUS_FILE = "last_run.json"
SETTINGS_FILE = "user_settings.json"
LOG_FILE = "booker.log"
SCRIPT = "booker.py"
BOOKING_CONFIG_FILE = "booking_config.json"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WIN_VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
LINUX_VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "bin", "python3")
PYTHON = (
    WIN_VENV_PYTHON if os.path.exists(WIN_VENV_PYTHON)
    else LINUX_VENV_PYTHON if os.path.exists(LINUX_VENV_PYTHON)
    else "python"
)

DEFAULT_CONFIG = {
    "players": 4,
    "holes": "18",
    "earliest_hour": 8,
    "latest_hour": 10,
    "click_final_book_button": False,
}

DEFAULT_USER_SETTINGS = {
    "foreup_email": "",
    "foreup_password": "",
    "notify_email": "",
    "notify_phone": "",
    "notify_sms_enabled": False,
    "sms_gateway_domain": "",
}

_running = threading.Lock()
_current_process = None
_current_config = None

def load_booking_config() -> dict:
    stored = load_json(BOOKING_CONFIG_FILE)
    return {**DEFAULT_CONFIG, **stored}

def save_booking_config(payload: dict):
    merged = {**DEFAULT_CONFIG, **payload}
    save_json(BOOKING_CONFIG_FILE, merged)
    
HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tee Time Booker — James Baird</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --green:#1a4a2e; --green-mid:#2d6e47; --cream:#f5f0e8; --cream-dark:#ede7d9;
    --gold:#c8a84b; --white:#fdfaf5; --text:#1a1a1a; --text-soft:#4a5568; --red:#c0392b;
    --shadow:0 4px 24px rgba(26,74,46,0.13);
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body {
    font-family:'DM Sans', sans-serif; background:var(--green); min-height:100vh;
    display:flex; flex-direction:column; align-items:center; padding:0 0 60px;
  }
  header {
    width:100%; background:rgba(0,0,0,0.25); border-bottom:1px solid rgba(255,255,255,0.08);
    padding:20px 32px; display:flex; align-items:center; gap:14px;
  }
  .logo-text h1 { font-family:'Playfair Display', serif; color:var(--cream); font-size:1.4rem; }
  .logo-text p { color:var(--gold); font-size:0.78rem; letter-spacing:0.12em; text-transform:uppercase; }
  .container { width:100%; max-width:760px; padding:28px 20px 0; display:flex; flex-direction:column; gap:18px; }
  .card { background:var(--white); border-radius:20px; padding:28px; box-shadow:var(--shadow); }
  .status-badge {
    display:inline-flex; align-items:center; gap:8px; background:#f0f4f8; border:1.5px solid #cbd5e0;
    color:#4a5568; font-size:0.8rem; font-weight:600; padding:6px 16px; border-radius:100px; margin-bottom:18px;
  }
  .status-badge.running { background:#fef9e7; border-color:#f9d849; color:#7d6608; }
  .status-badge.error { background:#fdf0ef; border-color:#f5b7b1; color:var(--red); }
  .status-badge.success { background:#e8f5ee; border-color:#a8d5b8; color:var(--green); }
  .pulse { width:8px; height:8px; background:currentColor; border-radius:50%; }
  .status-card h2 { font-family:'Playfair Display', serif; font-size:1.7rem; color:var(--text); margin-bottom:6px; }
  .subtitle { color:var(--text-soft); margin-bottom:24px; }
  .button-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:20px; }
  .book-btn {
    display:flex; align-items:center; justify-content:center; gap:10px; width:100%;
    background:linear-gradient(135deg, var(--green) 0%, var(--green-mid) 100%);
    color:var(--cream); border:none; border-radius:14px; padding:18px; font-size:1rem;
    font-weight:600; cursor:pointer;
  }
  .book-btn:disabled { opacity:0.6; cursor:not-allowed; }
  .cancel-btn { background:linear-gradient(135deg,#8b2d2d 0%, #b33939 100%); }
  .spinner {
    width:18px; height:18px; border:2.5px solid rgba(255,255,255,0.3);
    border-top-color:white; border-radius:50%; animation:spin 0.8s linear infinite; display:none;
  }
  .book-btn.loading .spinner { display:block; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .section-title { font-family:'Playfair Display', serif; font-size:1.1rem; color:var(--text); margin-bottom:16px; }
  .setting-row, .result-item {
    display:flex; justify-content:space-between; align-items:center; gap:12px;
    padding:11px 0; border-bottom:1px solid var(--cream-dark);
  }
  .setting-row:last-child, .result-item:last-child { border-bottom:none; }
  .setting-label, .label { color:var(--text-soft); }
  .setting-control {
    min-width:220px; padding:8px 10px; border-radius:8px; border:1px solid #d8d1c0; background:var(--cream);
  }
  .value { font-weight:600; text-align:right; }
  .value.success { color:var(--green-mid); }
  .value.fail { color:var(--red); }
  .value.pending { color:#b7791f; }
  .log-box {
    background:#0f1e14; border-radius:10px; padding:16px; font-family:'Courier New', monospace;
    font-size:0.76rem; line-height:1.7; color:#7ec89a; max-height:240px; overflow-y:auto; white-space:pre-wrap;
  }
  .toast {
    position:fixed; bottom:24px; left:50%; transform:translateX(-50%) translateY(80px);
    background:var(--green); color:var(--cream); padding:14px 24px; border-radius:12px;
    transition:transform 0.3s; z-index:1000;
  }
  .toast.show { transform:translateX(-50%) translateY(0); }
  .toast.error { background:var(--red); }
  @media (max-width:640px) {
    .button-row { grid-template-columns:1fr; }
    .setting-row, .result-item { flex-direction:column; align-items:flex-start; }
    .setting-control { width:100%; min-width:0; }
  }
</style>
</head>
<body>
<header>
  <div style="font-size:2rem;">⛳</div>
  <div class="logo-text">
    <h1>Tee Time Booker</h1>
    <p>James Baird Golf Course</p>
  </div>
</header>

<div class="container">
  <div class="card status-card">
    <div class="status-badge idle" id="statusBadge">
      <div class="pulse"></div>
      <span id="statusText">Ready</span>
    </div>
    <h2 id="statusHeading">All Set</h2>
    <p class="subtitle" id="statusSubtitle">Fill in your info once, then change booking settings whenever you want.</p>

    <div class="button-row">
      <button class="book-btn" id="bookBtn" onclick="triggerBooking()">
        <div class="spinner"></div>
        <span class="btn-text">⛳ Run Booking</span>
      </button>
      <button class="book-btn cancel-btn" id="cancelBtn" onclick="cancelBooking()" disabled>
        <span class="btn-text">🛑 Cancel Current Run</span>
      </button>
    </div>
  </div>

  <div class="card">
    <div class="section-title">🔐 Account & Notifications</div>

    <div class="setting-row">
      <span class="setting-label">ForeUp email</span>
      <input id="foreupEmailInput" class="setting-control" type="email" placeholder="name@example.com">
    </div>
    <div class="setting-row">
      <span class="setting-label">ForeUp password</span>
      <input id="foreupPasswordInput" class="setting-control" type="password" placeholder="Enter password">
    </div>
    <div class="setting-row">
      <span class="setting-label">Notification Gmail</span>
      <input id="notifyEmailInput" class="setting-control" type="email" placeholder="yourgmail@gmail.com">
    </div>
    <div class="setting-row">
      <span class="setting-label">Phone number</span>
      <input id="notifyPhoneInput" class="setting-control" type="text" placeholder="5551234567">
    </div>
    <div class="setting-row">
      <span class="setting-label">SMS gateway domain</span>
      <input id="smsGatewayInput" class="setting-control" type="text" placeholder="vtext.com">
    </div>
    <div class="setting-row">
      <span class="setting-label">Send SMS too</span>
      <select id="notifySmsEnabledInput" class="setting-control">
        <option value="false" selected>No</option>
        <option value="true">Yes</option>
      </select>
    </div>

    <div class="button-row">
      <button class="book-btn" onclick="saveUserSettings()">💾 Save Settings</button>
      <button class="book-btn" onclick="loadUserSettings()">↻ Reload Settings</button>
    </div>
  </div>

  <div class="card">
    <div class="section-title">⚙️ Booking Controls</div>

    <div class="setting-row">
      <span class="setting-label">Players</span>
      <select id="playersInput" class="setting-control">
        <option value="1">1</option>
        <option value="2">2</option>
        <option value="3">3</option>
        <option value="4" selected>4</option>
      </select>
    </div>
    <div class="setting-row">
      <span class="setting-label">Holes</span>
      <select id="holesInput" class="setting-control">
        <option value="9">9</option>
        <option value="18" selected>18</option>
      </select>
    </div>
    <div class="setting-row">
      <span class="setting-label">Earliest hour</span>
      <input id="earliestHourInput" class="setting-control" type="number" min="0" max="23" value="8">
    </div>
    <div class="setting-row">
      <span class="setting-label">Latest hour</span>
      <input id="latestHourInput" class="setting-control" type="number" min="0" max="23" value="10">
    </div>
    <div class="setting-row">
      <span class="setting-label">Live booking</span>
      <select id="liveBookingInput" class="setting-control">
        <option value="false" selected>Preview only</option>
        <option value="true">Actually book</option>
      </select>
    </div>
  </div>

  <div class="card">
    <div class="section-title">📋 Last Booking Attempt</div>
    <div class="result-item"><span class="label">Date run</span><span class="value" id="lastRunDate">Never</span></div>
    <div class="result-item"><span class="label">Target Saturday</span><span class="value" id="lastTargetDate">—</span></div>
    <div class="result-item"><span class="label">Result</span><span class="value pending" id="lastResult">No runs yet</span></div>
    <div class="result-item"><span class="label">Time booked</span><span class="value" id="lastTimeBooked">—</span></div>
  </div>

  <div class="card">
    <div class="section-title">🖥 Activity Log</div>
    <div class="log-box" id="logBox">Waiting for first run...</div>
  </div>
</div>

<div class="toast" id="toast"><span id="toastMsg">Saved</span></div>

<script>
  let initializedDefaults = false;

  function showToast(msg, isError = false) {
    const t = document.getElementById('toast');
    t.className = 'toast' + (isError ? ' error' : '');
    document.getElementById('toastMsg').textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3500);
  }

  function setStatus(type, heading, subtitle) {
    const badge = document.getElementById('statusBadge');
    const text = document.getElementById('statusText');
    badge.className = 'status-badge ' + type;
    text.textContent = { idle: 'Ready', running: 'Running…', error: 'Error', success: 'Booked!' }[type] || type;
    document.getElementById('statusHeading').textContent = heading;
    document.getElementById('statusSubtitle').textContent = subtitle;
  }

  function updateResult(date, targetSat, result, timeBooked) {
    document.getElementById('lastRunDate').textContent = date;
    document.getElementById('lastTargetDate').textContent = targetSat;
    const el = document.getElementById('lastResult');
    el.textContent = result;
    el.className = 'value ' + (
      result.toLowerCase().includes('booked') ? 'success' :
      result.toLowerCase().includes('fail') || result.toLowerCase().includes('error') || result.toLowerCase().includes('cancel') ? 'fail' :
      'pending'
    );
    document.getElementById('lastTimeBooked').textContent = timeBooked || '—';
  }

  function getCurrentBookingConfig() {
    return {
      players: parseInt(document.getElementById('playersInput').value, 10),
      holes: document.getElementById('holesInput').value,
      earliest_hour: parseInt(document.getElementById('earliestHourInput').value, 10),
      latest_hour: parseInt(document.getElementById('latestHourInput').value, 10),
      click_final_book_button: document.getElementById('liveBookingInput').value === 'true'
    };
  }

  function getCurrentUserSettings() {
    return {
      foreup_email: document.getElementById('foreupEmailInput').value.trim(),
      foreup_password: document.getElementById('foreupPasswordInput').value,
      notify_email: document.getElementById('notifyEmailInput').value.trim(),
      notify_phone: document.getElementById('notifyPhoneInput').value.trim(),
      sms_gateway_domain: document.getElementById('smsGatewayInput').value.trim(),
      notify_sms_enabled: document.getElementById('notifySmsEnabledInput').value === 'true'
    };
  }

  function applyConfigToInputs(config) {
    if (!config) return;
    document.getElementById('playersInput').value = String(config.players);
    document.getElementById('holesInput').value = String(config.holes);
    document.getElementById('earliestHourInput').value = String(config.earliest_hour);
    document.getElementById('latestHourInput').value = String(config.latest_hour);
    document.getElementById('liveBookingInput').value = String(!!config.click_final_book_button);
  }

  function applyUserSettings(settings) {
    if (!settings) return;
    document.getElementById('foreupEmailInput').value = settings.foreup_email || '';
    document.getElementById('foreupPasswordInput').value = settings.foreup_password || '';
    document.getElementById('notifyEmailInput').value = settings.notify_email || '';
    document.getElementById('notifyPhoneInput').value = settings.notify_phone || '';
    document.getElementById('smsGatewayInput').value = settings.sms_gateway_domain || '';
    document.getElementById('notifySmsEnabledInput').value = String(!!settings.notify_sms_enabled);
  }

  async function saveUserSettings() {
    try {
      const payload = getCurrentUserSettings();
      const resp = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.message || 'Could not save settings.');
      showToast('Settings saved.');
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function loadUserSettings() {
    try {
      const resp = await fetch('/api/settings');
      const data = await resp.json();
      applyUserSettings(data.settings || {});
      showToast('Settings loaded.');
    } catch (err) {
      showToast('Could not load settings.', true);
    }
  }

  async function triggerBooking() {
    const bookBtn = document.getElementById('bookBtn');
    const cancelBtn = document.getElementById('cancelBtn');
    const config = getCurrentBookingConfig();

    if (config.earliest_hour > config.latest_hour) {
      showToast('Earliest hour must be less than or equal to latest hour.', true);
      return;
    }

    bookBtn.disabled = true;
    cancelBtn.disabled = false;
    bookBtn.classList.add('loading');
    bookBtn.querySelector('.btn-text').textContent = 'Booking in progress…';
    setStatus('running', 'Booking Now…', 'Starting booking run...');

    try {
      const resp = await fetch('/api/tee-time/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.message || 'Failed to start booking.');
      showToast('Booking started.');
    } catch (err) {
      setStatus('error', 'Could not start', err.message);
      showToast(err.message, true);
      bookBtn.disabled = false;
      cancelBtn.disabled = true;
      bookBtn.classList.remove('loading');
      bookBtn.querySelector('.btn-text').textContent = '⛳ Run Booking';
    }
  }

  async function cancelBooking() {
    try {
      const resp = await fetch('/api/tee-time/cancel', { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.message || 'Could not cancel.');
      showToast('Booking cancelled.');
      setStatus('idle', 'Cancelled', 'The current booking run was cancelled.');
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function loadStatus() {
    try {
      const resp = await fetch('/api/tee-time/status');
      const data = await resp.json();

      const bookBtn = document.getElementById('bookBtn');
      const cancelBtn = document.getElementById('cancelBtn');

      if (!initializedDefaults && data.defaults) {
        applyConfigToInputs(data.defaults);
        initializedDefaults = true;
      }

      if (data.running) {
        setStatus('running', 'Booking Now…', 'A booking attempt is currently in progress.');
        bookBtn.disabled = true;
        cancelBtn.disabled = !data.can_cancel;
        bookBtn.classList.add('loading');
        bookBtn.querySelector('.btn-text').textContent = 'Booking in progress…';
      } else {
        bookBtn.disabled = false;
        cancelBtn.disabled = true;
        bookBtn.classList.remove('loading');
        bookBtn.querySelector('.btn-text').textContent = '⛳ Run Booking';
      }

      if (data.last_run && Object.keys(data.last_run).length) {
        updateResult(
          data.last_run.ran_at || '—',
          data.last_run.target_date || data.last_run.date || '—',
          data.last_run.result || '—',
          data.last_run.time_booked || data.last_run.time || '—'
        );
      }

      if (data.log_lines) {
        document.getElementById('logBox').textContent = data.log_lines.join('\\n');
      }
    } catch (err) {
      console.error(err);
    }
  }

  loadUserSettings();
  loadStatus();
  setInterval(loadStatus, 3000);
</script>
</body>
</html>
"""


def save_json(path: str, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_status(result: dict):
    save_json(STATUS_FILE, result)


def load_status() -> dict:
    return load_json(STATUS_FILE)


def load_user_settings() -> dict:
    stored = load_json(SETTINGS_FILE)
    merged = {**DEFAULT_USER_SETTINGS, **stored}
    return merged


def save_user_settings(payload: dict):
    merged = {**DEFAULT_USER_SETTINGS, **payload}
    save_json(SETTINGS_FILE, merged)


def tail_log(n=50) -> list[str]:
    if not os.path.exists(LOG_FILE):
        return ["No log file yet."]
    with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return [line.rstrip() for line in lines[-n:]]


def normalize_config(data: dict | None) -> dict:
    data = data or {}
    return {
        "players": int(data.get("players", DEFAULT_CONFIG["players"])),
        "holes": str(data.get("holes", DEFAULT_CONFIG["holes"])),
        "earliest_hour": int(data.get("earliest_hour", DEFAULT_CONFIG["earliest_hour"])),
        "latest_hour": int(data.get("latest_hour", DEFAULT_CONFIG["latest_hour"])),
        "click_final_book_button": bool(data.get("click_final_book_button", DEFAULT_CONFIG["click_final_book_button"])),
    }


def normalize_user_settings(data: dict | None) -> dict:
    data = data or {}
    return {
        "foreup_email": str(data.get("foreup_email", "")).strip(),
        "foreup_password": str(data.get("foreup_password", "")),
        "notify_email": str(data.get("notify_email", "")).strip(),
        "notify_phone": re.sub(r"\D", "", str(data.get("notify_phone", ""))),
        "sms_gateway_domain": str(data.get("sms_gateway_domain", "")).strip(),
        "notify_sms_enabled": bool(data.get("notify_sms_enabled", False)),
    }


def build_notification_target(settings: dict) -> str:
    targets = []
    if settings.get("notify_email"):
        targets.append(settings["notify_email"])
    if settings.get("notify_sms_enabled") and settings.get("notify_phone") and settings.get("sms_gateway_domain"):
        targets.append(f"{settings['notify_phone']}@{settings['sms_gateway_domain']}")
    return ",".join(targets)


def build_booker_command(config: dict) -> list[str]:
    cmd = [
        PYTHON,
        SCRIPT,
        "--players", str(config["players"]),
        "--holes", str(config["holes"]),
        "--earliest-hour", str(config["earliest_hour"]),
        "--latest-hour", str(config["latest_hour"]),
        "--headless",
    ]
    if config.get("click_final_book_button", False):
        cmd.append("--click-final-book-button")
    return cmd


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

    final_step_signals = [
        "reached final step successfully",
        "book time button found, but not clicked",
        "job complete — reached final step without booking",
        "job complete - reached final step without booking",
        "ready to book",
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
        "message": "The run finished, but the server could not classify the result.",
    }


def run_booker_background(config: dict):
    global _current_process, _current_config

    settings = load_user_settings()
    env = os.environ.copy()
    env["FOREUP_EMAIL"] = settings.get("foreup_email", "")
    env["FOREUP_PASSWORD"] = settings.get("foreup_password", "")
    env["NOTIFY_EMAIL"] = build_notification_target(settings)

    try:
        cmd = build_booker_command(config)
        _current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=BASE_DIR,
            env=env,
        )
        _current_config = config

        output, _ = _current_process.communicate(timeout=300)

        with open("last_run_output.txt", "w", encoding="utf-8", errors="ignore") as f:
            f.write(output or "")

        status = parse_booker_output(output or "", config)
        save_status(status)

    except subprocess.TimeoutExpired:
        if _current_process:
            _current_process.kill()
        save_status({
            "success": False,
            "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_date": "Saturday",
            "result": "❌ Timed out",
            "time_booked": None,
            "date": "Saturday",
            "time": None,
            "message": "Booking attempt timed out after 5 minutes.",
            "config": config,
        })

    except Exception as e:
        save_status({
            "success": False,
            "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_date": "Saturday",
            "result": "❌ Server error",
            "time_booked": None,
            "date": "Saturday",
            "time": None,
            "message": str(e),
            "config": config,
        })

    finally:
        _current_process = None
        _current_config = None
        _running.release()


@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify({
        "success": True,
        "settings": load_user_settings(),
    })


@app.route("/api/settings", methods=["POST"])
def post_settings():
    payload = normalize_user_settings(request.get_json(silent=True))
    save_user_settings(payload)
    return jsonify({
        "success": True,
        "message": "Settings saved.",
    })


@app.route("/api/tee-time/status")
def status():
    return jsonify({
        "last_run": load_status(),
        "log_lines": tail_log(50),
        "running": _running.locked(),
        "current_config": _current_config,
        "can_cancel": _current_process is not None,
        "defaults": DEFAULT_CONFIG,
    })


@app.route("/api/tee-time/run", methods=["POST"])
def run():
    settings = load_user_settings()
    if not settings.get("foreup_email") or not settings.get("foreup_password"):
        return jsonify({
            "success": False,
            "message": "Please save ForeUp email and password first.",
        }), 400

    if not _running.acquire(blocking=False):
        return jsonify({
            "success": False,
            "message": "A booking is already in progress — please wait."
        }), 409

    incoming = request.get_json(silent=True)
    config = normalize_config(incoming) if incoming else load_booking_config()

    thread = threading.Thread(target=run_booker_background, args=(config,), daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "message": "Booking started.",
        "config": config,
    })


@app.route("/api/tee-time/cancel", methods=["POST"])
def cancel():
    global _current_process

    if _current_process is None:
        return jsonify({
            "success": False,
            "message": "No booking is currently running."
        }), 400

    try:
        _current_process.terminate()
        save_status({
            "success": False,
            "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_date": "Saturday",
            "result": "🛑 Cancelled",
            "time_booked": None,
            "date": "Saturday",
            "time": None,
            "message": "Booking run was cancelled by the user.",
            "config": _current_config or {},
        })
        return jsonify({
            "success": True,
            "message": "Booking cancelled."
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
        }), 500

@app.route("/api/booking-config", methods=["GET"])
def get_booking_config():
    return jsonify({
        "success": True,
        "config": load_booking_config(),
    })

@app.route("/api/booking-config", methods=["POST"])
def post_booking_config():
    payload = normalize_config(request.get_json(silent=True))
    save_booking_config(payload)
    return jsonify({
        "success": True,
        "message": "Booking config saved.",
        "config": payload,
    })
    
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)