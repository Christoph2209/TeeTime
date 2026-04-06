"""
Golf Booker — Flask Backend
Serves the settings UI and exposes API endpoints the frontend calls to
read and write config.json. The booking bot reads the same config.json.

Run:
    python app.py
Then open http://localhost:5000 in a browser.
"""

from flask import Flask, jsonify, request, render_template
import json, os, logging

app = Flask(__name__)
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "day":        "saturday",
    "time_from":  "08:00",
    "time_to":    "10:00",
    "players":    4,
    "holes":      18,
    "fallback":   "next",
    "phone":      "",
    "carrier":    "vtext.com",
    "notify_booked":   True,
    "notify_fallback": True,
    "notify_failed":   True,
    "notify_reminder": False,
}


def read_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        write_config(DEFAULT_CONFIG)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def write_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info("Config saved.")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(read_config())


@app.route("/api/config", methods=["POST"])
def save_config():
    incoming = request.get_json(force=True)
    if not incoming:
        return jsonify({"error": "No data received"}), 400

    current = read_config()
    current.update(incoming)          # merge — only overwrite what was sent
    write_config(current)
    return jsonify({"status": "ok", "config": current})


@app.route("/api/logs", methods=["GET"])
def get_logs():
    log_file = os.path.join(os.path.dirname(__file__), "booker.log")
    if not os.path.exists(log_file):
        return jsonify({"lines": []})
    with open(log_file, "r") as f:
        lines = f.readlines()
    last_20 = [l.strip() for l in lines[-20:] if l.strip()]
    return jsonify({"lines": last_20})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)