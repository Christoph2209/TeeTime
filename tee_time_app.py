"""
Tee Time Booker GUI Application
This application provides a graphical interface for configuring and running the James Baird Tee Time Booker script.
Features:
- Set booking preferences (time of day, players, holes, headless mode, etc.)
- Save settings locally in a JSON file
- Run the booker script immediately and view the last run status and log output
- Install or delete a Windows scheduled task to run the booker every Friday at a specified time
- View the last few lines of the booker log directly in the GUI
Requirements:
- Python 3.8 or higher
- The booker.py script and its dependencies must be in the same directory as this GUI script
- On Windows, the schtasks command is used for scheduling, so this GUI is primarily designed
    for Windows users, but the immediate run and settings features should work on any platform.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from dotenv import load_dotenv


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()

load_dotenv(BASE_DIR / ".env")

DEFAULT_ENV_FOREUP_EMAIL = os.getenv("FOREUP_EMAIL", "")
DEFAULT_ENV_FOREUP_PASSWORD = os.getenv("FOREUP_PASSWORD", "")
DEFAULT_ENV_GMAIL_USER = os.getenv("GMAIL_USER", "")
DEFAULT_ENV_GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
DEFAULT_ENV_NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
SETTINGS_PATH = BASE_DIR / "settings.json"
STATUS_PATH = BASE_DIR / "last_run.json"
LOG_PATH = BASE_DIR / "booker.log"

# In packaged mode, the GUI should run booker.exe.
# In source mode, it should run booker.py with python.
BOOKER_EXE_PATH = BASE_DIR / "booker.exe"
BOOKER_PY_PATH = BASE_DIR / "booker.py"
LAUNCHER_BAT_PATH = BASE_DIR / "run_booker_hidden.bat"

DEFAULT_SETTINGS = {
    "time_pref": "morning",
    "players": 4,
    "holes": "18",
    "headless": True,
    "click_final_book_button": True,
    "schedule_time": "18:59",
    "foreup_email": DEFAULT_ENV_FOREUP_EMAIL,
    "foreup_password": DEFAULT_ENV_FOREUP_PASSWORD,
    "gmail_user": DEFAULT_ENV_GMAIL_USER,
    "gmail_app_password": DEFAULT_ENV_GMAIL_APP_PASSWORD,
    "notify_email": DEFAULT_ENV_NOTIFY_EMAIL,
}

TIME_WINDOWS = {
    "morning": (8, 10),
    "midday": (10, 13),
    "evening": (13, 16),
}


def load_settings():
    env_defaults = {
        "time_pref": "morning",
        "players": 4,
        "holes": "18",
        "headless": True,
        "click_final_book_button": True,
        "schedule_time": "18:59",
        "foreup_email": DEFAULT_ENV_FOREUP_EMAIL,
        "foreup_password": DEFAULT_ENV_FOREUP_PASSWORD,
        "gmail_user": DEFAULT_ENV_GMAIL_USER,
        "gmail_app_password": DEFAULT_ENV_GMAIL_APP_PASSWORD,
        "notify_email": DEFAULT_ENV_NOTIFY_EMAIL,
    }

    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            merged = env_defaults.copy()

            for key, value in data.items():
                if value not in ("", None):
                    merged[key] = value

            return merged
        except Exception:
            pass

    return env_defaults.copy()

def save_settings(data):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_status():
    if STATUS_PATH.exists():
        try:
            with open(STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def tail_log(lines=50):
    if not LOG_PATH.exists():
        return "No log file yet."
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()
        return "".join(content[-lines:])
    except Exception as e:
        return f"Could not read log: {e}"


def build_booker_command(settings):
    earliest, latest = TIME_WINDOWS[settings["time_pref"]]

    if BOOKER_EXE_PATH.exists():
        cmd = [str(BOOKER_EXE_PATH)]
    else:
        cmd = [sys.executable, str(BOOKER_PY_PATH)]

    cmd.extend([
        "--players", str(settings["players"]),
        "--holes", str(settings["holes"]),
        "--earliest-hour", str(earliest),
        "--latest-hour", str(latest),
    ])

    if settings.get("headless", True):
        cmd.append("--headless")
    else:
        cmd.append("--no-headless")

    if settings.get("click_final_book_button", False):
        cmd.append("--click-final-book-button")

    if settings.get("foreup_email"):
        cmd.extend(["--foreup-email", settings["foreup_email"]])
    if settings.get("foreup_password"):
        cmd.extend(["--foreup-password", settings["foreup_password"]])
    if settings.get("gmail_user"):
        cmd.extend(["--gmail-user", settings["gmail_user"]])
    if settings.get("gmail_app_password"):
        cmd.extend(["--gmail-app-password", settings["gmail_app_password"]])
    if settings.get("notify_email"):
        cmd.extend(["--notify-email", settings["notify_email"]])

    return cmd


def quote_arg(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


class TeeTimeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Tee Time Booker")
        self.root.geometry("860x760")
        self.root.minsize(860, 760)

        self.settings = load_settings()
        self.running = False

        self.time_pref = tk.StringVar(value=self.settings["time_pref"])
        self.players = tk.IntVar(value=self.settings["players"])
        self.holes = tk.StringVar(value=self.settings["holes"])
        self.headless = tk.BooleanVar(value=self.settings["headless"])
        self.click_final = tk.BooleanVar(value=self.settings["click_final_book_button"])
        self.schedule_time = tk.StringVar(value=self.settings["schedule_time"])

        self.foreup_email = tk.StringVar(value=self.settings.get("foreup_email") or DEFAULT_ENV_FOREUP_EMAIL)
        self.foreup_password = tk.StringVar(value=self.settings.get("foreup_password") or DEFAULT_ENV_FOREUP_PASSWORD)
        self.gmail_user = tk.StringVar(value=self.settings.get("gmail_user") or DEFAULT_ENV_GMAIL_USER)
        self.gmail_app_password = tk.StringVar(value=self.settings.get("gmail_app_password") or DEFAULT_ENV_GMAIL_APP_PASSWORD)
        self.notify_email = tk.StringVar(value=self.settings.get("notify_email") or DEFAULT_ENV_NOTIFY_EMAIL)

        self.build_ui()
        self.refresh_status()

    def build_ui(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        title = ttk.Label(frame, text="James Baird Tee Time Booker", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w", pady=(0, 12))

        pref_box = ttk.LabelFrame(frame, text="Booking Preferences", padding=12)
        pref_box.pack(fill="x", pady=(0, 10))

        ttk.Label(pref_box, text="Time preference").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Radiobutton(pref_box, text="Morning", variable=self.time_pref, value="morning").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(pref_box, text="Midday", variable=self.time_pref, value="midday").grid(row=0, column=2, sticky="w")
        ttk.Radiobutton(pref_box, text="Evening", variable=self.time_pref, value="evening").grid(row=0, column=3, sticky="w")

        ttk.Label(pref_box, text="Players").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Combobox(pref_box, textvariable=self.players, values=[1, 2, 3, 4], width=12, state="readonly").grid(row=1, column=1, sticky="w")

        ttk.Label(pref_box, text="Holes").grid(row=1, column=2, sticky="w", padx=(10, 10), pady=6)
        ttk.Combobox(pref_box, textvariable=self.holes, values=["9", "18"], width=12, state="readonly").grid(row=1, column=3, sticky="w")

        ttk.Checkbutton(pref_box, text="Run headless", variable=self.headless).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Checkbutton(pref_box, text="Actually click final Book Time button", variable=self.click_final).grid(row=2, column=1, columnspan=3, sticky="w", pady=6)

        ttk.Label(pref_box, text="ForeUp email").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(pref_box, textvariable=self.foreup_email, width=36).grid(row=3, column=1, columnspan=3, sticky="we")

        ttk.Label(pref_box, text="ForeUp password").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(pref_box, textvariable=self.foreup_password, width=36, show="*").grid(row=4, column=1, columnspan=3, sticky="we")

        ttk.Label(pref_box, text="Gmail user").grid(row=5, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(pref_box, textvariable=self.gmail_user, width=36).grid(row=5, column=1, columnspan=3, sticky="we")

        ttk.Label(pref_box, text="Gmail app password").grid(row=6, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(pref_box, textvariable=self.gmail_app_password, width=36, show="*").grid(row=6, column=1, columnspan=3, sticky="we")

        ttk.Label(pref_box, text="Notification email(s)").grid(row=7, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(pref_box, textvariable=self.notify_email, width=36).grid(row=7, column=1, columnspan=3, sticky="we")

        sched_box = ttk.LabelFrame(frame, text="Local Schedule", padding=12)
        sched_box.pack(fill="x", pady=(0, 10))

        ttk.Label(sched_box, text="Friday time (24-hour HH:MM)").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(sched_box, textvariable=self.schedule_time, width=10).grid(row=0, column=1, sticky="w")

        ttk.Label(
            sched_box,
            text="This creates or updates a Windows scheduled task on this computer."
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill="x", pady=(0, 10))

        ttk.Button(btn_box, text="Save Settings", command=self.save_clicked).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Run Now", command=self.run_now).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Install / Update Friday Schedule", command=self.install_schedule).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Delete Friday Schedule", command=self.delete_schedule).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Refresh Status", command=self.refresh_status).pack(side="left")

        status_box = ttk.LabelFrame(frame, text="Last Result", padding=12)
        status_box.pack(fill="x", pady=(0, 10))

        self.status_label = ttk.Label(status_box, text="No runs yet.", font=("Segoe UI", 10))
        self.status_label.pack(anchor="w")

        self.log_box = tk.Text(frame, height=22, wrap="word")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def current_settings(self):
        return {
            "time_pref": self.time_pref.get(),
            "players": int(self.players.get()),
            "holes": self.holes.get(),
            "headless": bool(self.headless.get()),
            "click_final_book_button": bool(self.click_final.get()),
            "schedule_time": self.schedule_time.get().strip() or "18:59",
            "foreup_email": self.foreup_email.get().strip(),
            "foreup_password": self.foreup_password.get(),
            "gmail_user": self.gmail_user.get().strip(),
            "gmail_app_password": self.gmail_app_password.get(),
            "notify_email": self.notify_email.get().strip(),
        }

    def save_clicked(self):
        data = self.current_settings()
        save_settings(data)
        self.settings = data
        messagebox.showinfo("Saved", "Settings saved locally.")

    def run_now(self):
        if self.running:
            messagebox.showwarning("Already running", "A booking run is already in progress.")
            return

        self.save_clicked()
        self.running = True
        self.status_label.config(text="Running now...")
        thread = threading.Thread(target=self._run_booker_thread, daemon=True)
        thread.start()

    def _run_booker_thread(self):
        try:
            cmd = build_booker_command(self.current_settings())
            result = subprocess.run(
                cmd,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=420
            )

            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            with open(BASE_DIR / "last_subprocess_output.txt", "w", encoding="utf-8") as f:
                f.write(combined)

        except subprocess.TimeoutExpired:
            messagebox.showerror("Timeout", "Booking run timed out.")
        except Exception as e:
            messagebox.showerror("Error", f"Run failed: {e}")
        finally:
            self.running = False
            self.root.after(0, self.refresh_status)

    def install_schedule(self):
        self.save_clicked()
        time_text = self.schedule_time.get().strip()

        try:
            datetime.strptime(time_text, "%H:%M")
        except ValueError:
            messagebox.showerror("Invalid time", "Use HH:MM in 24-hour format, like 18:59")
            return

        cmd = build_booker_command(self.current_settings())

        bat_lines = [
            "@echo off",
            f'cd /d {quote_arg(str(BASE_DIR))}',
            " ".join(quote_arg(part) for part in cmd),
        ]

        with open(LAUNCHER_BAT_PATH, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(bat_lines) + "\n")

        task_name = "TeeTimeBookerFriday"
        schtasks_cmd = [
            "schtasks",
            "/Create",
            "/F",
            "/SC", "WEEKLY",
            "/D", "FRI",
            "/TN", task_name,
            "/TR", str(LAUNCHER_BAT_PATH),
            "/ST", time_text,
        ]

        try:
            completed = subprocess.run(schtasks_cmd, capture_output=True, text=True, timeout=30)
            if completed.returncode == 0:
                messagebox.showinfo("Scheduled", f"Installed/updated Friday task at {time_text}.")
            else:
                messagebox.showerror("Schedule failed", completed.stderr or completed.stdout or "Unknown error")
        except Exception as e:
            messagebox.showerror("Schedule failed", str(e))

    def delete_schedule(self):
        task_name = "TeeTimeBookerFriday"
        cmd = ["schtasks", "/Delete", "/TN", task_name, "/F"]

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if completed.returncode == 0:
                messagebox.showinfo("Deleted", "Friday scheduled task deleted.")
            else:
                messagebox.showerror("Delete failed", completed.stderr or completed.stdout or "Task may not exist.")
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))

    def refresh_status(self):
        status = read_status()
        if status:
            text = (
                f"Last run: {status.get('ran_at', '—')} | "
                f"Target date: {status.get('target_date', '—')} | "
                f"Result: {status.get('result', '—')} | "
                f"Time: {status.get('time_booked', '—')}"
            )
        else:
            text = "No runs yet."

        self.status_label.config(text=text)

        log_text = tail_log(60)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", tk.END)
        self.log_box.insert("1.0", log_text)
        self.log_box.configure(state="disabled")


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = TeeTimeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()