import json
import os
import subprocess
import sys
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")
STATUS_PATH = os.path.join(BASE_DIR, "last_run.json")
LOG_PATH = os.path.join(BASE_DIR, "booker.log")
BOOKER_PATH = os.path.join(BASE_DIR, "booker.py")

DEFAULT_SETTINGS = {
    "time_pref": "morning",          # morning | midday | evening
    "players": 4,
    "holes": "18",
    "headless": True,
    "click_final_book_button": False,
    "notify_email": "",
    "schedule_day": "FRI",
    "schedule_time": "18:59"
}

TIME_WINDOWS = {
    "morning": (8, 10),
    "midday": (10, 13),
    "evening": (13, 16),
}

def load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_SETTINGS.copy()
        merged.update(data)
        return merged
    return DEFAULT_SETTINGS.copy()

def save_settings(data):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def read_status():
    if os.path.exists(STATUS_PATH):
        try:
            with open(STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def tail_log(lines=40):
    if not os.path.exists(LOG_PATH):
        return "No log file yet."
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()
        return "".join(content[-lines:])
    except Exception as e:
        return f"Could not read log: {e}"

def python_executable():
    return sys.executable if getattr(sys, "frozen", False) else sys.executable

def build_booker_command(settings):
    earliest, latest = TIME_WINDOWS[settings["time_pref"]]
    cmd = [
        python_executable(),
        BOOKER_PATH,
        "--players", str(settings["players"]),
        "--holes", str(settings["holes"]),
        "--earliest-hour", str(earliest),
        "--latest-hour", str(latest),
    ]
    if settings.get("headless", True):
        cmd.append("--headless")
    if settings.get("click_final_book_button", False):
        cmd.append("--click-final-book-button")
    return cmd

class TeeTimeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Tee Time Booker")
        self.root.geometry("760x620")
        self.root.minsize(760, 620)

        self.settings = load_settings()
        self.running = False

        self.time_pref = tk.StringVar(value=self.settings["time_pref"])
        self.players = tk.IntVar(value=self.settings["players"])
        self.holes = tk.StringVar(value=self.settings["holes"])
        self.headless = tk.BooleanVar(value=self.settings["headless"])
        self.click_final = tk.BooleanVar(value=self.settings["click_final_book_button"])
        self.schedule_time = tk.StringVar(value=self.settings["schedule_time"])

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
        ttk.Combobox(pref_box, textvariable=self.players, values=[1, 2, 3, 4], width=10, state="readonly").grid(row=1, column=1, sticky="w")

        ttk.Label(pref_box, text="Holes").grid(row=1, column=2, sticky="w", padx=(10, 10), pady=6)
        ttk.Combobox(pref_box, textvariable=self.holes, values=["9", "18"], width=10, state="readonly").grid(row=1, column=3, sticky="w")

        ttk.Checkbutton(pref_box, text="Run headless", variable=self.headless).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Checkbutton(pref_box, text="Actually click final Book Time button", variable=self.click_final).grid(row=2, column=1, columnspan=3, sticky="w", pady=6)

        sched_box = ttk.LabelFrame(frame, text="Local Schedule", padding=12)
        sched_box.pack(fill="x", pady=(0, 10))

        ttk.Label(sched_box, text="Friday time (24-hour HH:MM)").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(sched_box, textvariable=self.schedule_time, width=10).grid(row=0, column=1, sticky="w")

        ttk.Label(
            sched_box,
            text="Use the button below to install a Windows scheduled task on this computer."
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill="x", pady=(0, 10))

        ttk.Button(btn_box, text="Save Settings", command=self.save_clicked).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Run Now", command=self.run_now).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Install Friday Schedule", command=self.install_schedule).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Refresh Status", command=self.refresh_status).pack(side="left")

        status_box = ttk.LabelFrame(frame, text="Last Result", padding=12)
        status_box.pack(fill="x", pady=(0, 10))

        self.status_label = ttk.Label(status_box, text="No runs yet.", font=("Segoe UI", 10))
        self.status_label.pack(anchor="w")

        self.log_box = tk.Text(frame, height=20, wrap="word")
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
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=420
            )

            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            with open(os.path.join(BASE_DIR, "last_subprocess_output.txt"), "w", encoding="utf-8") as f:
                f.write(combined)

        except subprocess.TimeoutExpired:
            pass
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

        launcher = os.path.join(BASE_DIR, "run_booker_hidden.bat")
        if not os.path.exists(launcher):
            with open(launcher, "w", encoding="utf-8") as f:
                f.write(f'''@echo off
cd /d "{BASE_DIR}"
"{python_executable()}" "{BOOKER_PATH}" --players {self.players.get()} --holes {self.holes.get()} --earliest-hour {TIME_WINDOWS[self.time_pref.get()][0]} --latest-hour {TIME_WINDOWS[self.time_pref.get()][1]} {"--headless" if self.headless.get() else ""} {"--click-final-book-button" if self.click_final.get() else ""}
''')

        task_name = "TeeTimeBookerFriday"
        cmd = [
            "schtasks",
            "/Create",
            "/F",
            "/SC", "WEEKLY",
            "/D", "FRI",
            "/TN", task_name,
            "/TR", launcher,
            "/ST", time_text,
        ]

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if completed.returncode == 0:
                messagebox.showinfo("Scheduled", f"Installed Friday task at {time_text}.")
            else:
                messagebox.showerror("Schedule failed", completed.stderr or completed.stdout or "Unknown error")
        except Exception as e:
            messagebox.showerror("Schedule failed", str(e))

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

        log_text = tail_log(50)
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