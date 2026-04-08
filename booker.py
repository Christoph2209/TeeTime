"""
Booking script for ForeUp-based golf course reservation systems, tailored for James Baird State Park.
Features:
- Selenium-based web automation to navigate the booking process
- IMAP polling to retrieve booking confirmation codes from email
- Configurable target date, time window, player count, and holes
- Robust error handling with detailed logging and screenshots
- Email notifications for success, failure, and key events
Usage:
- Set environment variables in a .env file or via CLI arguments for credentials and preferences
- Run the script on a schedule (e.g., via cron) to attempt booking when slots open
Environment Variables:
- FOREUP_EMAIL: Your ForeUp account email
- FOREUP_PASSWORD: Your ForeUp account password
- GMAIL_USER: Gmail address for receiving booking code emails and sending notifications
- GMAIL_APP_PASSWORD: App password for the Gmail account
- NOTIFY_EMAIL: Comma-separated list of email addresses to notify about booking results
CLI Arguments:
--players: Number of players (default: 4)
--holes: "9" or "18" (default: "18")
--earliest-hour: Earliest tee time hour in 24h format (default: 8)
--latest-hour: Latest tee time hour in 24h format (default: 10)
--headless / --no-headless: Run browser in headless mode (default: headless)
--click-final-book-button: Whether to click the final "Book Time" button (default: True)
"""


import argparse
import email
import email.header
import imaplib
import json
import logging
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# =========================
# Paths / PyInstaller-safe
# =========================

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
ENV_PATH = BASE_DIR / ".env"
LOG_PATH = BASE_DIR / "booker.log"
STATUS_PATH = BASE_DIR / "last_run.json"
PHOTOS_DIR = BASE_DIR / "photos"

load_dotenv(ENV_PATH)

# =========================
# Env / defaults
# =========================

FOREUP_EMAIL = os.getenv("FOREUP_EMAIL", "")
FOREUP_PASSWORD = os.getenv("FOREUP_PASSWORD", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASSWORD", "")

COURSE_ID = "19757"
SCHEDULE_ID = "2440"
BASE_URL = "https://foreupsoftware.com"
BOOKING_URL = f"{BASE_URL}/index.php/booking/{COURSE_ID}/{SCHEDULE_ID}"

DEFAULT_PLAYERS = 4
DEFAULT_HOLES = "18"
DEFAULT_EARLIEST_HOUR = 8
DEFAULT_LATEST_HOUR = 10
DEFAULT_HEADLESS = True
DEFAULT_CLICK_FINAL_BOOK_BUTTON = True
DEBUG_SCREENSHOTS = False

HEADLESS = DEFAULT_HEADLESS
CLICK_FINAL_BOOK_BUTTON = DEFAULT_CLICK_FINAL_BOOK_BUTTON
TARGET_PLAYERS = DEFAULT_PLAYERS
TARGET_HOLES = DEFAULT_HOLES
EARLIEST_HOUR = DEFAULT_EARLIEST_HOUR
LATEST_HOUR = DEFAULT_LATEST_HOUR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# =========================
# Helpers
# =========================

def write_status(result: str, target_date: str = "", time_booked: str = "", message: str = ""):
    payload = {
        "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_date": target_date,
        "result": result,
        "time_booked": time_booked,
        "message": message,
    }
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        log.warning(f"Could not write status file: {e}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=DEFAULT_PLAYERS)
    parser.add_argument("--holes", type=str, default=DEFAULT_HOLES, choices=["9", "18"])
    parser.add_argument("--earliest-hour", type=int, default=DEFAULT_EARLIEST_HOUR)
    parser.add_argument("--latest-hour", type=int, default=DEFAULT_LATEST_HOUR)
    parser.add_argument("--headless", dest="headless", action="store_true")
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.set_defaults(headless=DEFAULT_HEADLESS)
    parser.add_argument("--click-final-book-button", action="store_true")

    # Optional CLI overrides
    parser.add_argument("--foreup-email", type=str, default=None)
    parser.add_argument("--foreup-password", type=str, default=None)
    parser.add_argument("--gmail-user", type=str, default=None)
    parser.add_argument("--gmail-app-password", type=str, default=None)
    parser.add_argument("--notify-email", type=str, default=None)

    return parser.parse_args()


def next_saturday() -> str:
    today = datetime.now()

    # Always target NEXT week's Saturday
    days_until_this_saturday = (5 - today.weekday()) % 7
    if today.weekday() <= 5:   # Mon-Sat
        days_ahead = days_until_this_saturday + 7
    else:                      # Sunday
        days_ahead = (5 - today.weekday()) % 7

    sat = today + timedelta(days=days_ahead)
    return sat.strftime("%m-%d-%Y")


def send_notification(subject: str, body: str):
    if not all([GMAIL_USER, GMAIL_APP_PASS, NOTIFY_EMAIL]):
        log.warning("Notification config incomplete — skipping.")
        return

    recipients = [addr.strip() for addr in NOTIFY_EMAIL.split(",") if addr.strip()]
    if not recipients:
        log.warning("No valid notification recipients.")
        return

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = ", ".join(recipients)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, recipients, msg.as_string())

        log.info(f"Notification sent to: {', '.join(recipients)}")
    except Exception as e:
        log.error(f"Failed to send notification: {e}")


def save_screenshot(driver, name="debug"):
    if not DEBUG_SCREENSHOTS:
        return
    try:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        path = PHOTOS_DIR / f"{name}_{datetime.now().strftime('%H%M%S')}.png"
        driver.save_screenshot(str(path))
        log.info(f"Screenshot saved: {path}")
    except Exception as e:
        log.warning(f"Could not save screenshot: {e}")


def make_driver() -> ChromeWebDriver:
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    )

    log.info("Starting Chrome WebDriver...")

    chromedriver_path = BASE_DIR / "chromedriver.exe"
    if chromedriver_path.exists():
        log.info(f"Using local ChromeDriver: {chromedriver_path}")
        service = Service(str(chromedriver_path))
        driver = ChromeWebDriver(service=service, options=opts)
    else:
        log.info("No local chromedriver.exe found, using Selenium Manager/default resolution.")
        driver = ChromeWebDriver(options=opts)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    log.info("Chrome WebDriver started successfully.")
    return driver

def decode_header_value(value: str) -> str:
    if not value:
        return ""
    decoded_parts = email.header.decode_header(value)
    out = []
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(part)
    return "".join(out)


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;|&#160;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def get_text_bodies(msg) -> tuple[str, str]:
    text_plain = []
    text_html = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = (part.get_content_type() or "").lower()
            disposition = str(part.get("Content-Disposition") or "").lower()

            if "attachment" in disposition:
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="ignore")

            if content_type == "text/plain":
                text_plain.append(decoded)
            elif content_type == "text/html":
                text_html.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="ignore")
            if (msg.get_content_type() or "").lower() == "text/html":
                text_html.append(decoded)
            else:
                text_plain.append(decoded)

    return "\n".join(text_plain), "\n".join(text_html)


def extract_booking_code(subject: str, text_body: str, html_body: str) -> str | None:
    plain = text_body or ""
    html_text = strip_html(html_body or "")
    combined = "\n".join([subject, plain, html_text])

    patterns = [
        r"booking code[^0-9]{0,80}(\d{6})",
        r"confirmation code[^0-9]{0,80}(\d{6})",
        r"enter (?:that|this) code[^0-9]{0,80}(\d{6})",
        r"code[^0-9]{0,30}(\d{6})",
    ]

    for text in [plain, html_text, combined]:
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                return m.group(1)

    codes = re.findall(r"\b\d{6}\b", combined)
    codes = [c for c in codes if c not in {"123456", "666666", "000000", "111111"}]
    return codes[-1] if codes else None


def get_booking_code_from_email(timeout_seconds: int = 30, poll_every: float = 1.0) -> str | None:
    if not GMAIL_USER or not GMAIL_APP_PASS:
        log.error("Missing GMAIL_USER or GMAIL_APP_PASSWORD.")
        return None

    end_time = time.time() + timeout_seconds

    while time.time() < end_time:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_USER, GMAIL_APP_PASS)

            selected_box = None
            for box in ['"[Gmail]/All Mail"', '"All Mail"', "INBOX"]:
                try:
                    status, _ = mail.select(box)
                    if status == "OK":
                        selected_box = box
                        break
                except Exception:
                    continue

            if not selected_box:
                mail.logout()
                time.sleep(poll_every)
                continue

            status, data = mail.search(None, "ALL")
            if status != "OK":
                mail.logout()
                time.sleep(poll_every)
                continue

            ids = data[0].split()
            ids = list(reversed(ids[-10:]))

            for num in ids:
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                subject = decode_header_value(msg.get("Subject", ""))
                from_header = decode_header_value(msg.get("From", ""))

                from_lower = from_header.lower()
                subject_lower = subject.lower()

                looks_like_target = (
                    "no-reply@foreupsoftware.com" in from_lower
                    or "reservation confirmation" in subject_lower
                    or "james baird state park" in subject_lower
                )

                if not looks_like_target:
                    continue

                text_body, html_body = get_text_bodies(msg)
                code = extract_booking_code(subject, text_body, html_body)
                if code:
                    log.info("Booking code found in email.")
                    mail.logout()
                    return code

            mail.logout()

        except Exception as e:
            log.warning(f"Gmail polling error: {e}")

        time.sleep(poll_every)

    log.error("Timed out waiting for booking code email.")
    return None


def load_tee_times(driver, wait, saturday: str):
    log.info(f"Loading booking page for {saturday}...")
    driver.get(BOOKING_URL)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    save_screenshot(driver, "01_loaded")

    try:
        date_input = wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR,
            "input[id*='date'], input[name*='date'], input.date-input, #date-field"
        )))
        driver.execute_script("arguments[0].value = '';", date_input)
        date_input.clear()
        date_input.send_keys(saturday)
        date_input.send_keys(Keys.ENTER)
        log.info(f"Set date to {saturday}")
    except TimeoutException:
        try:
            date_input = driver.find_element(By.XPATH, "//input[@type='text' and contains(@value, '-')]")
            driver.execute_script(f"arguments[0].value = '{saturday}';", date_input)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                date_input
            )
        except Exception as e:
            log.error(f"Could not set date: {e}")
            raise

    try:
        player_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            f"//button[normalize-space(text())='{TARGET_PLAYERS}'] | "
            f"//a[normalize-space(text())='{TARGET_PLAYERS}']"
        )))
        driver.execute_script("arguments[0].click();", player_btn)
        log.info(f"Clicked '{TARGET_PLAYERS}' players button")
        time.sleep(1)
    except TimeoutException:
        log.warning(f"Could not find player '{TARGET_PLAYERS}' button — maybe already selected")

    save_screenshot(driver, "03_filtered")


def select_tee_time(driver, wait) -> str | None:
    log.info("Looking for eligible tee time cards...")

    try:
        wait.until(EC.presence_of_element_located((
            By.XPATH, "//*[contains(@class,'booking') or contains(@class,'teetime') or contains(@class,'time-slot')]"
        )))
    except TimeoutException:
        log.error("No tee time cards appeared on page.")
        save_screenshot(driver, "04_no_cards")
        return None

    time_elements = driver.find_elements(
        By.XPATH,
        "//*[contains(@class,'booking') or contains(@class,'teetime') or contains(@class,'time-slot')]"
        "//*[contains(text(),'am') or contains(text(),'pm')]"
    )

    if not time_elements:
        time_elements = driver.find_elements(
            By.XPATH,
            "//*[string-length(normalize-space(text())) < 10 and "
            "(contains(normalize-space(text()),'am') or contains(normalize-space(text()),'pm'))]"
        )

    log.info(f"Found {len(time_elements)} time-like elements")

    for el in time_elements:
        raw = el.text.strip().lower()
        if not raw or len(raw) > 12:
            continue

        hour = -1
        for fmt in ("%I:%M%p", "%I:%M %p", "%I%p"):
            try:
                parsed = datetime.strptime(raw.upper(), fmt)
                hour = parsed.hour
                break
            except ValueError:
                continue

        if hour < EARLIEST_HOUR or hour > LATEST_HOUR:
            continue

        log.info(f"Eligible time found: {raw}")

        try:
            card = el
            for _ in range(6):
                try:
                    parent = card.find_element(By.XPATH, "..")
                    tag = parent.tag_name.lower()
                    cls = (parent.get_attribute("class") or "").lower()
                    if tag in ("div", "li", "article", "a", "button") and any(
                        kw in cls for kw in ["booking", "teetime", "slot", "time", "card"]
                    ):
                        card = parent
                        break
                    card = parent
                except Exception:
                    break

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
            driver.execute_script("arguments[0].click();", card)

            wait.until(lambda d: (
                "password" in d.page_source.lower()
                or "booking code" in d.page_source.lower()
                or "reservation process" in d.page_source.lower()
                or "log in" in d.page_source.lower()
            ))

            save_screenshot(driver, f"05_clicked_{raw.replace(':', '').replace(' ', '')}")
            return raw
        except Exception as e:
            log.warning(f"Could not click card for {raw}: {e}")

    log.warning("No eligible tee times found in target window.")
    save_screenshot(driver, "04_no_eligible")
    return None


def login_when_prompted(driver, wait) -> bool:
    save_screenshot(driver, "06_after_card_click")
    page = driver.page_source.lower()

    if "password" not in page and "log in" not in page and "login" not in page:
        try:
            login_link = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((
                By.XPATH,
                "//a[contains(normalize-space(.), 'Log In')] | "
                "//a[contains(normalize-space(.), 'Login')] | "
                "//button[contains(normalize-space(.), 'Log In')]"
            )))
            driver.execute_script("arguments[0].click();", login_link)
        except TimeoutException:
            log.warning("No nav login link found")

    page = driver.page_source.lower()
    if "password" not in page:
        log.error("Still no login form visible.")
        save_screenshot(driver, "07_still_no_login")
        return False

    email_field = None
    for sel in [
        "input[type='email']",
        "input[name='username']",
        "input[name='email']",
        "input[placeholder*='email' i]",
        "input[placeholder*='user' i]",
        "#username",
        "#email",
    ]:
        try:
            email_field = driver.find_element(By.CSS_SELECTOR, sel)
            break
        except NoSuchElementException:
            continue

    if not email_field:
        log.error("Could not find email input.")
        save_screenshot(driver, "08_no_email_field")
        return False

    try:
        email_field.clear()
        email_field.send_keys(FOREUP_EMAIL)

        pass_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pass_field.clear()
        pass_field.send_keys(FOREUP_PASSWORD)
    except NoSuchElementException:
        log.error("Could not find password field.")
        return False

    try:
        login_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[normalize-space(text())='Log In']"
        )))
        driver.execute_script("arguments[0].click();", login_btn)
        log.info("Clicked 'Log In' button.")
    except TimeoutException:
        pass_field.send_keys(Keys.ENTER)
        log.info("Submitted via Enter key.")

    try:
        wait.until(lambda d: any(
            x in d.page_source.lower()
            for x in ["logout", "log out", "sign out", "my account", "booking code", "reservation process"]
        ))
        save_screenshot(driver, "09_after_login")
        log.info("Login step appears successful.")
        return True
    except TimeoutException:
        log.warning("Login may have failed.")
        return False


def find_booking_modal(driver, wait):
    modal_xpaths = [
        "//div[contains(@class,'modal') and .//*[contains(normalize-space(.), 'Book Time')]]",
        "//div[contains(@class,'modal') and .//*[contains(normalize-space(.), 'Booking Code')]]",
        "//div[contains(@class,'modal') and .//*[@id='reservation_confirmation_uid']]",
    ]

    for xp in modal_xpaths:
        try:
            return wait.until(EC.presence_of_element_located((By.XPATH, xp)))
        except TimeoutException:
            continue

    raise TimeoutException("Could not find booking modal.")


def select_holes(driver, wait, holes: str = None) -> bool:
    if holes is None:
        holes = TARGET_HOLES

    try:
        modal = find_booking_modal(driver, wait)
    except TimeoutException:
        log.error("Could not find booking modal.")
        save_screenshot(driver, "10_modal_not_found")
        return False

    xpaths = [
        f".//label[contains(normalize-space(.), 'Holes')]/following::button[normalize-space(text())='{holes}'][1]",
        f".//label[contains(normalize-space(.), 'Holes')]/following::*[self::button or self::a][normalize-space(text())='{holes}'][1]",
        f".//button[normalize-space(text())='{holes}']",
        f".//a[normalize-space(text())='{holes}']",
    ]

    for xp in xpaths:
        try:
            candidates = modal.find_elements(By.XPATH, xp)
            for btn in candidates:
                if not btn.is_displayed() or not btn.is_enabled():
                    continue
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                log.info(f"Selected {holes} holes in modal")
                save_screenshot(driver, f"10_holes_{holes}_selected")
                return True
        except Exception as e:
            log.warning(f"Hole selection attempt failed for xpath {xp}: {e}")

    log.error("Could not select modal hole button.")
    save_screenshot(driver, "10_holes_not_selected")
    return False


def enter_booking_code(driver, wait) -> bool:
    log.info("Waiting for booking code email and entering it...")

    code = get_booking_code_from_email(timeout_seconds=30, poll_every=1.0)
    if not code:
        save_screenshot(driver, "12_no_booking_code_found")
        return False

    try:
        code_input = wait.until(EC.presence_of_element_located((By.ID, "reservation_confirmation_uid")))
    except TimeoutException:
        log.error("Could not find reservation_confirmation_uid input.")
        save_screenshot(driver, "12_code_input_missing")
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", code_input)
        driver.execute_script("""
            arguments[0].removeAttribute('readonly');
            arguments[0].removeAttribute('disabled');
            arguments[0].focus();
            arguments[0].value = '';
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        """, code_input, code)

        entered = code_input.get_attribute("value") or ""
        if entered != code:
            log.error(f"Booking code did not stick. Expected {code}, got {entered}")
            save_screenshot(driver, "12_code_value_mismatch")
            return False

        log.info("Entered booking code")
        save_screenshot(driver, "12_code_entered")
        return True

    except Exception as e:
        log.error(f"Could not enter booking code: {e}")
        save_screenshot(driver, "12_code_entry_failed")
        return False


def find_book_time_button(driver, wait):
    modal = find_booking_modal(driver, wait)

    xpaths = [
        ".//button[normalize-space()='Book Time']",
        ".//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'book time')]",
        ".//button[contains(@class,'btn-success') and normalize-space()='Book Time']",
    ]

    for xp in xpaths:
        try:
            buttons = modal.find_elements(By.XPATH, xp)
            for btn in buttons:
                if btn.is_displayed() and btn.is_enabled():
                    return btn
        except Exception:
            continue

    raise TimeoutException("Could not find Book Time button.")


def preview_without_booking(driver, wait) -> bool:
    try:
        btn = find_book_time_button(driver, wait)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        save_screenshot(driver, "13_ready_to_book_not_clicked")
        log.info("Reached final step successfully. Book Time button found, but not clicked.")
        return True
    except Exception as e:
        log.error(f"Could not locate Book Time button for preview: {e}")
        save_screenshot(driver, "13_book_time_missing")
        return False


def click_confirm_button(driver, wait) -> bool:
    try:
        btn = find_book_time_button(driver, wait)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        driver.execute_script("arguments[0].click();", btn)
        log.info("Clicked Book Time button")
        save_screenshot(driver, "13_after_final_confirm")
        return True
    except Exception as e:
        log.error(f"Could not click Book Time button: {e}")
        save_screenshot(driver, "13_book_time_click_failed")
        return False


def complete_until_final_step(driver, wait, time_str: str) -> bool:
    save_screenshot(driver, "10_confirm_page")

    if not select_holes(driver, wait, TARGET_HOLES):
        return False

    if not enter_booking_code(driver, wait):
        return False

    return click_confirm_button(driver, wait) if CLICK_FINAL_BOOK_BUTTON else preview_without_booking(driver, wait)


def run_booking_job():
    log.info("=" * 60)
    log.info("Booking job started.")
    saturday = next_saturday()
    log.info(f"Target date: {saturday}")

    if not FOREUP_EMAIL or not FOREUP_PASSWORD:
        msg = "Missing ForeUp credentials."
        log.error(msg)
        write_status("missing_credentials", saturday, "", msg)
        return

    driver = make_driver()
    wait = WebDriverWait(driver, 10)

    try:
        load_tee_times(driver, wait, saturday)

        chosen_time = select_tee_time(driver, wait)
        if not chosen_time:
            msg = f"No tee times between target hours on {saturday} for {TARGET_PLAYERS} players."
            send_notification("Tee time bot: no slots", msg)
            write_status("no_slots", saturday, "", msg)
            return

        if not login_when_prompted(driver, wait):
            msg = f"Could not log in for {saturday}. Check screenshots/log."
            send_notification("Tee time bot: login failed", msg)
            write_status("login_failed", saturday, chosen_time, msg)
            return

        success = complete_until_final_step(driver, wait, chosen_time)

        if success:
            if CLICK_FINAL_BOOK_BUTTON:
                msg = (
                    f"James Baird\n"
                    f"Date: {saturday}\n"
                    f"Time: {chosen_time}\n"
                    f"Players: {TARGET_PLAYERS}\n"
                    f"Holes: {TARGET_HOLES}"
                )
                send_notification("⛳ Tee time booked!", msg)
                log.info("BOOKING CONFIRMED: %s", chosen_time)
                write_status("booked", saturday, chosen_time, msg)
            else:
                msg = (
                    f"Reached final Book Time button without clicking it.\n"
                    f"Date: {saturday}\n"
                    f"Time: {chosen_time}\n"
                    f"Players: {TARGET_PLAYERS}\n"
                    f"Holes: {TARGET_HOLES}"
                )
                send_notification("Tee time bot: reached final step", msg)
                write_status("reached_final_step", saturday, chosen_time, msg)
        else:
            msg = f"Could not reach the final step for {saturday}. Try manually."
            send_notification("Tee time bot: not completed", msg)
            write_status("not_completed", saturday, chosen_time, msg)

    except Exception as e:
        msg = str(e)
        log.error(f"Unexpected error: {e}", exc_info=True)
        save_screenshot(driver, "error")
        send_notification("Tee time bot: error", msg)
        write_status("error", saturday, "", msg)
    finally:
        try:
            if not HEADLESS:
                time.sleep(5)
            driver.quit()
        except Exception:
            pass
        log.info("Browser closed.")


if __name__ == "__main__":
    args = parse_args()

    TARGET_PLAYERS = args.players
    TARGET_HOLES = args.holes
    EARLIEST_HOUR = args.earliest_hour
    LATEST_HOUR = args.latest_hour
    HEADLESS = args.headless
    CLICK_FINAL_BOOK_BUTTON = args.click_final_book_button

    if args.foreup_email:
        FOREUP_EMAIL = args.foreup_email
    if args.foreup_password:
        FOREUP_PASSWORD = args.foreup_password
    if args.gmail_user:
        GMAIL_USER = args.gmail_user
    if args.gmail_app_password:
        GMAIL_APP_PASS = args.gmail_app_password
    if args.notify_email:
        NOTIFY_EMAIL = args.notify_email

    run_booking_job()