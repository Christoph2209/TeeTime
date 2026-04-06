# James Baird Tee Time Booker

Automatically books a Saturday tee time at James Baird Golf Course
every Friday at 6:59:58 PM via the foreUP booking system.

## Project structure

```
golf_booker/
├── app.py               ← Flask web UI (settings panel)
├── tee_time_booker.py   ← Booking bot (runs on a schedule)
├── config.json          ← Preferences (written by UI, read by bot)
├── booker.log           ← Activity log
├── .env                 ← Credentials (never commit this)
├── .env.template        ← Copy this to .env and fill in
└── templates/
    └── index.html       ← Settings UI
```

## Setup

**1. Install dependencies**
```bash
pip install flask requests schedule python-dotenv
```

**2. Create your .env file**
```bash
cp .env.template .env
# then edit .env with real credentials
```

**3. Run both processes**

In one terminal — the web UI:
```bash
python app.py
```

In a second terminal — the booking bot:
```bash
python tee_time_booker.py
```

Open http://localhost:5000 to adjust settings.

## How it works

1. Every Friday at 6:59:58 PM the bot wakes up
2. Reads preferences from config.json
3. Logs into foreUP with stored credentials
4. Fetches Saturday tee times
5. Books the first slot in the preferred window
6. Falls back to any available time if preferred window is gone
7. Texts a confirmation via email-to-SMS

## Deploying (free)

**Oracle Cloud Free Tier** (recommended — never expires):
- Create a free VM at cloud.oracle.com
- Upload project files via scp or git
- Run both processes with `nohup` or set up systemd services

**Railway.app** (easier setup):
- Push to a private GitHub repo
- Connect repo to Railway
- Add .env variables in Railway dashboard
- Deploy — it runs 24/7
