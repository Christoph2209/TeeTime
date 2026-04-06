"""
James Baird Golf Course — Automatic Tee Time Booker
====================================================
Selenium version — visible browser for debugging, headless when working.

Setup:
  pip install selenium webdriver-manager schedule python-dotenv
"""

import time
import logging
import schedule
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from dotenv import load_dotenv
import os

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

FOREUP_EMAIL    = os.getenv("FOREUP_EMAIL")
FOREUP_PASSWORD = os.getenv("FOREUP_PASSWORD")
NOTIFY_EMAIL    = os.getenv("NOTIFY_EMAIL")
GMAIL_USER      = os.getenv("GMAIL_USER")
GMAIL_APP_PASS  = os.getenv("GMAIL_APP_PASSWORD")

COURSE_ID       = "19757"
SCHEDULE_ID     = "2440"
BASE_URL        = "https://foreupsoftware.com"

TARGET_PLAYERS  = 4
EARLIEST_HOUR   = 8    # 8 AM
LATEST_HOUR     = 10   # 10 AM (inclusive)

# ── Set HEADLESS = False to watch the browser, True to run silently ───────────
HEADLESS        = False   # ← flip to True once everything is working

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("booker.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def next_saturday() -> str:
    today = datetime.now()
    days_ahead = (5 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    sat = today + timedelta(days=days_ahead)
    return sat.strftime("%m-%d-%Y")   # foreUP URL format: MM-DD-YYYY


def send_notification(subject: str, body: str):
    if not all([GMAIL_USER, GMAIL_APP_PASS, NOTIFY_EMAIL]):
        log.warning("Notification config incomplete — skipping.")
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = NOTIFY_EMAIL
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        log.info(f"Notification sent to {NOTIFY_EMAIL}")
    except Exception as e:
        log.error(f"Failed to send notification: {e}")


def save_screenshot(driver, name="debug"):
    path = f"{name}_{datetime.now().strftime('%H%M%S')}.png"
    driver.save_screenshot(path)
    log.info(f"Screenshot saved: {path}")


def make_driver() -> webdriver.Chrome:
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def wait_and_click(driver, wait, selector, by=By.CSS_SELECTOR, timeout=15):
    el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))
    driver.execute_script("arguments[0].scrollIntoView(true);", el)
    time.sleep(0.3)
    el.click()
    return el


def slow_type(element, text):
    """Type like a human to avoid bot detection."""
    element.clear()
    for ch in text:
        element.send_keys(ch)
        time.sleep(0.05)


# ── foreUP Login ──────────────────────────────────────────────────────────────

def login(driver, wait) -> bool:
    """
    foreUP login flow:
      1. Load the booking page
      2. Click the "Login" link in the nav
      3. A modal appears — fill email + password + submit
    """
    booking_page = f"{BASE_URL}/index.php/booking/{COURSE_ID}/{SCHEDULE_ID}"
    log.info(f"Loading: {booking_page}")
    driver.get(booking_page)
    time.sleep(3)
    save_screenshot(driver, "01_booking_page")

    # ── Click the Login / Sign In link ────────────────────────────────────────
    # foreUP puts a "Login" link in the top-right nav bar
    LOGIN_LINK_SELECTORS = [
        "//a[contains(translate(text(),'LOGIN','login'),'login')]",
        "//a[contains(translate(text(),'SIGN IN','sign in'),'sign in')]",
        "//button[contains(translate(text(),'LOGIN','login'),'login')]",
        "//li[contains(@class,'login')]//a",
        "//a[@href='#login-modal']",
    ]
    clicked = False
    for xpath in LOGIN_LINK_SELECTORS:
        try:
            el = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            el.click()
            clicked = True
            log.info(f"Clicked login trigger: {xpath}")
            break
        except TimeoutException:
            continue

    if not clicked:
        log.warning("Could not find login link — checking if already logged in or form is inline.")
        save_screenshot(driver, "02_no_login_link")

    time.sleep(2)
    save_screenshot(driver, "03_after_login_click")

    # ── Fill in the login form ────────────────────────────────────────────────
    # foreUP modal uses these IDs: #login-email and #login-password (or name attrs)
    EMAIL_SELECTORS = [
        "#login-email",
        "input[name='username']",
        "input[type='email']",
        ".modal input[type='email']",
        ".modal input[name='username']",
    ]
    email_field = None
    for sel in EMAIL_SELECTORS:
        try:
            email_field = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
            )
            log.info(f"Found email field: {sel}")
            break
        except TimeoutException:
            continue

    if email_field is None:
        log.error("Could not find email input. Check screenshots.")
        save_screenshot(driver, "04_no_email_field")
        # Dump all input fields to help debug
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for i, inp in enumerate(inputs):
            log.info(f"  Input[{i}]: type={inp.get_attribute('type')} "
                     f"name={inp.get_attribute('name')} "
                     f"id={inp.get_attribute('id')} "
                     f"placeholder={inp.get_attribute('placeholder')}")
        return False

    slow_type(email_field, FOREUP_EMAIL)

    PASS_SELECTORS = [
        "#login-password",
        "input[name='password']",
        "input[type='password']",
        ".modal input[type='password']",
    ]
    pass_field = None
    for sel in PASS_SELECTORS:
        try:
            pass_field = driver.find_element(By.CSS_SELECTOR, sel)
            log.info(f"Found password field: {sel}")
            break
        except NoSuchElementException:
            continue

    if pass_field is None:
        log.error("Could not find password field.")
        save_screenshot(driver, "05_no_pass_field")
        return False

    slow_type(pass_field, FOREUP_PASSWORD)

    # Submit
    SUBMIT_SELECTORS = [
        "button[type='submit']",
        "input[type='submit']",
        ".modal button[type='submit']",
        "//button[contains(translate(text(),'LOGIN','login'),'login')]",
        "//button[contains(translate(text(),'SIGN IN','sign in'),'sign in')]",
    ]
    submitted = False
    for sel in SUBMIT_SELECTORS:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            submitted = True
            log.info(f"Clicked submit: {sel}")
            break
        except TimeoutException:
            continue

    if not submitted:
        log.error("Could not find submit button.")
        save_screenshot(driver, "06_no_submit")
        return False

    time.sleep(3)
    save_screenshot(driver, "07_after_submit")

    # Check for login success — foreUP shows user's name or a logout link
    page = driver.page_source.lower()
    if "logout" in page or "log out" in page or "sign out" in page or FOREUP_EMAIL.lower().split("@")[0] in page:
        log.info("Login successful!")
        return True
    else:
        log.error("Login may have failed — no logout link found.")
        save_screenshot(driver, "08_login_failed")
        return False


# ── Tee Time Search & Booking ─────────────────────────────────────────────────

def book_tee_time(driver, wait, saturday: str) -> bool:
    """Navigate to tee times for Saturday and book the first eligible slot."""

    # foreUP tee time URL with filters
    url = (
        f"{BASE_URL}/index.php/booking/{COURSE_ID}/{SCHEDULE_ID}#/teetimes"
        f"?date={saturday}&players={TARGET_PLAYERS}&holes=18&time=any"
    )
    log.info(f"Loading tee times: {url}")
    driver.get(url)
    time.sleep(5)   # JS needs time to render slots
    save_screenshot(driver, "09_teetimes_page")

    # foreUP renders each tee time as a <li> or <div> with class "booking-slot"
    # The time is in a <span class="booking-start-time"> or similar
    SLOT_SELECTOR = ".booking-slot, .teetime-row, li.time-slot, [class*='booking'][class*='slot']"

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SLOT_SELECTOR))
        )
    except TimeoutException:
        log.warning("No tee time slots found on page.")
        save_screenshot(driver, "10_no_slots")
        # Dump page structure hint
        log.info(f"Page title: {driver.title}")
        log.info(f"Current URL: {driver.current_url}")
        return False

    slots = driver.find_elements(By.CSS_SELECTOR, SLOT_SELECTOR)
    log.info(f"Found {len(slots)} slots.")

    for slot in slots:
        try:
            # Grab the time text from the slot
            time_el = slot.find_element(By.CSS_SELECTOR,
                ".booking-start-time, .time, [class*='time'], span, strong"
            )
            time_text = time_el.text.strip()
            if not time_text:
                continue

            # Parse to hour
            hour = -1
            for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M", "%I %p"):
                try:
                    parsed = datetime.strptime(time_text.upper().strip(), fmt)
                    hour = parsed.hour
                    break
                except ValueError:
                    continue

            if hour < EARLIEST_HOUR or hour > LATEST_HOUR:
                log.debug(f"Skipping {time_text} (outside window)")
                continue

            log.info(f"Eligible slot: {time_text} — booking...")

            # Click Book button within this slot
            book_btn = slot.find_element(By.CSS_SELECTOR,
                "button, a.book, .book-btn, [class*='book']"
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", book_btn)
            time.sleep(0.5)
            book_btn.click()
            time.sleep(2)
            save_screenshot(driver, "11_booking_clicked")

            # Handle confirmation modal if it appears
            try:
                confirm = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    ".btn-confirm, button.confirm, [class*='confirm'], "
                    "button[data-action='confirm'], .modal .btn-primary"
                )))
                confirm.click()
                time.sleep(2)
                save_screenshot(driver, "12_confirmation")
            except TimeoutException:
                log.info("No confirmation dialog — booking may have gone through directly.")

            # Check for success
            page_src = driver.page_source.lower()
            if any(kw in page_src for kw in ["confirmation", "confirmed", "booked", "success", "receipt"]):
                log.info(f"✅ BOOKED: {time_text} on {saturday}")
                return True
            else:
                log.warning(f"Slot {time_text} didn't confirm. Trying next...")
                driver.back()
                time.sleep(3)

        except NoSuchElementException as e:
            log.debug(f"Element missing in slot: {e}")
            continue

    return False


# ── Main job ──────────────────────────────────────────────────────────────────

def run_booking_job():
    log.info("=" * 60)
    log.info("Booking job started.")
    saturday = next_saturday()
    log.info(f"Target date: {saturday}")

    driver = make_driver()
    wait = WebDriverWait(driver, 20)

    try:
        if not login(driver, wait):
            send_notification(
                "Tee time bot: login failed",
                f"Login failed for {saturday}. Check screenshots in script folder."
            )
            return

        success = book_tee_time(driver, wait, saturday)

        if success:
            send_notification(
                "⛳ Tee time booked!",
                f"James Baird\nDate: {saturday}\nPlayers: {TARGET_PLAYERS}\n"
                f"Manage: {BASE_URL}/index.php/booking/{COURSE_ID}/{SCHEDULE_ID}"
            )
            log.info("Job complete — booked!")
        else:
            send_notification(
                "Tee time bot: no slots booked",
                f"Could not book a slot for {saturday}. Try manually."
            )
            log.warning("Job complete — nothing booked.")

    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        save_screenshot(driver, "error")
        send_notification("Tee time bot: error", str(e))
    finally:
        if not HEADLESS:
            log.info("Keeping browser open 10s for inspection...")
            time.sleep(10)
        driver.quit()
        log.info("Browser closed.")


# ── Scheduler ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run immediately for testing:
    run_booking_job()

    # Uncomment for scheduled mode:
    # schedule.every().friday.at("18:59:58").do(run_booking_job)
    # log.info("Waiting for Friday 6:59:58 PM...")
    # while True:
    #     schedule.run_pending()
    #     time.sleep(1)