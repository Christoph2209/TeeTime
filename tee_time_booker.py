import time
import logging
import smtplib
import imaplib
import email
import email.header
import re
import os

from datetime import datetime, timedelta
from email.mime.text import MIMEText
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


load_dotenv()

FOREUP_EMAIL = os.getenv("FOREUP_EMAIL")
FOREUP_PASSWORD = os.getenv("FOREUP_PASSWORD")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASSWORD")

COURSE_ID = "19757"
SCHEDULE_ID = "2440"
BASE_URL = "https://foreupsoftware.com"
BOOKING_URL = f"{BASE_URL}/index.php/booking/{COURSE_ID}/{SCHEDULE_ID}"

TARGET_PLAYERS = 4
TARGET_HOLES = "18"
EARLIEST_HOUR = 13   # 1 PM
LATEST_HOUR = 18     # 4 PM
HEADLESS = False

# Safety switch: leave False so it DOES NOT actually book
CLICK_FINAL_BOOK_BUTTON = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("booker.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def next_saturday() -> str:
    today = datetime.now()
    days_ahead = (5 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    sat = today + timedelta(days=days_ahead)
    return sat.strftime("%m-%d-%Y")


def send_notification(subject: str, body: str):
    if not all([GMAIL_USER, GMAIL_APP_PASS, NOTIFY_EMAIL]):
        log.warning("Notification config incomplete — skipping.")
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = NOTIFY_EMAIL

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())

        log.info(f"Notification sent to {NOTIFY_EMAIL}")
    except Exception as e:
        log.error(f"Failed to send notification: {e}")


def save_screenshot(driver, name="debug"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    photos_dir = os.path.join(script_dir, "photos")
    os.makedirs(photos_dir, exist_ok=True)
    path = os.path.join(photos_dir, f"{name}_{datetime.now().strftime('%H%M%S')}.png")
    driver.save_screenshot(path)
    log.info(f"Screenshot saved: {path}")


def make_driver() -> webdriver.Chrome:
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

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
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


def next_saturday_human() -> str:
    today = datetime.now()
    days_ahead = (5 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    sat = today + timedelta(days=days_ahead)
    return sat.strftime("%b %d, %Y")


def load_tee_times(driver, wait, saturday: str):
    log.info(f"Loading booking page for {saturday}...")
    driver.get(BOOKING_URL)
    time.sleep(3)
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
        time.sleep(2)
    except TimeoutException:
        log.warning("Date input not found by CSS — trying fallback")
        try:
            date_input = driver.find_element(By.XPATH, "//input[@type='text' and contains(@value, '-')]")
            driver.execute_script(f"arguments[0].value = '{saturday}';", date_input)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                date_input
            )
            time.sleep(2)
        except Exception as e:
            log.error(f"Could not set date: {e}")
            raise

    save_screenshot(driver, "02_date_set")

    try:
        player_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[normalize-space(text())='4'] | //a[normalize-space(text())='4']"
        )))
        driver.execute_script("arguments[0].click();", player_btn)
        log.info("Clicked '4' players button")
        time.sleep(1.5)
    except TimeoutException:
        log.warning("Could not find player '4' button — maybe already selected")

    try:
        morning_btn = driver.find_element(
            By.XPATH, "//button[contains(text(),'Evening')] | //a[contains(text(),'Evening')]"
        )
        driver.execute_script("arguments[0].click();", morning_btn)
        log.info("Clicked 'Morning' filter")
        time.sleep(1.5)
    except NoSuchElementException:
        log.warning("No 'Morning' button found — showing all times")

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
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", card)
            log.info(f"Clicked card for {raw}")
            time.sleep(3)
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
        log.info("No login form visible yet — trying nav 'Log In'")
        try:
            login_link = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((
                By.XPATH,
                "//a[contains(normalize-space(.), 'Log In')] | "
                "//a[contains(normalize-space(.), 'Login')] | "
                "//button[contains(normalize-space(.), 'Log In')]"
            )))
            driver.execute_script("arguments[0].click();", login_link)
            time.sleep(2)
            save_screenshot(driver, "07_login_link_clicked")
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
            log.info(f"Email field found: {sel}")
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

    time.sleep(4)
    save_screenshot(driver, "09_after_login")

    page = driver.page_source.lower()
    if any(x in page for x in ["logout", "log out", "sign out", "my account", "booking code", "reservation process"]):
        log.info("Login step appears successful.")
        return True

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
            modal = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            return modal
        except TimeoutException:
            continue

    raise TimeoutException("Could not find booking modal.")


def select_holes(driver, wait, holes: str = TARGET_HOLES) -> bool:
    log.info(f"Selecting {holes} holes in booking modal...")

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
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
                log.info(f"Selected {holes} holes in modal")
                save_screenshot(driver, f"10_holes_{holes}_selected")
                return True
        except Exception as e:
            log.warning(f"Hole selection attempt failed for xpath {xp}: {e}")

    log.error("Could not select modal hole button.")
    save_screenshot(driver, "10_holes_not_selected")
    return False


import time
import imaplib
import email
import email.header
import re
from datetime import datetime


def decode_header_value(value: str) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for part, enc in parts:
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


def print_email_match(from_header: str, subject: str, date_header: str, text_body: str, html_body: str, code: str | None):
    preview = text_body.strip() if text_body.strip() else strip_html(html_body)
    preview = preview[:1000].replace("\n", " ")

    print("\n" + "=" * 80)
    print("MATCHED EMAIL")
    print("=" * 80)
    print(f"FROM   : {from_header}")
    print(f"SUBJECT: {subject}")
    print(f"DATE   : {date_header}")
    print(f"CODE   : {code}")
    print("BODY PREVIEW:")
    print(preview)
    print("=" * 80 + "\n")

    log.info("=" * 80)
    log.info("MATCHED EMAIL")
    log.info(f"FROM   : {from_header}")
    log.info(f"SUBJECT: {subject}")
    log.info(f"DATE   : {date_header}")
    log.info(f"CODE   : {code}")
    log.info(f"BODY PREVIEW: {preview}")
    log.info("=" * 80)


def click_resend_code(driver, wait) -> bool:
    try:
        btn = wait.until(EC.element_to_be_clickable((
            By.CSS_SELECTOR, "button.js-reservation-confirmation-resend-button"
        )))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        log.info("Clicked Resend Code")
        save_screenshot(driver, "11_resend_code_clicked")
        return True
    except Exception as e:
        log.warning(f"Could not click Resend Code: {e}")
        return False


def get_booking_code_from_email(timeout_seconds: int = 180, poll_every: int = 5) -> str | None:
    if not GMAIL_USER or not GMAIL_APP_PASS:
        log.error("Missing GMAIL_USER or GMAIL_APP_PASSWORD.")
        return None

    end_time = time.time() + timeout_seconds

    while time.time() < end_time:
        try:
            log.info("Checking Gmail for ForeUp reservation confirmation email...")
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_USER, GMAIL_APP_PASS)

            mailbox_candidates = ["[Gmail]/All Mail", "All Mail", "INBOX"]
            selected_box = None

            for box in mailbox_candidates:
                try:
                    status, _ = mail.select(f'"{box}"')
                    if status == "OK":
                        selected_box = box
                        break
                except Exception:
                    continue

            if not selected_box:
                status, _ = mail.select("INBOX")
                if status != "OK":
                    log.error("Could not select any mailbox.")
                    mail.logout()
                    time.sleep(poll_every)
                    continue
                selected_box = "INBOX"

            log.info(f"Searching mailbox: {selected_box}")

            status, data = mail.search(None, "ALL")
            if status != "OK":
                log.error("IMAP search failed.")
                mail.logout()
                time.sleep(poll_every)
                continue

            ids = data[0].split()
            ids = list(reversed(ids[-50:]))

            for num in ids:
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                subject = decode_header_value(msg.get("Subject", ""))
                from_header = decode_header_value(msg.get("From", ""))
                date_header = decode_header_value(msg.get("Date", ""))

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

                print_email_match(
                    from_header=from_header,
                    subject=subject,
                    date_header=date_header,
                    text_body=text_body,
                    html_body=html_body,
                    code=code,
                )

                if code:
                    log.info(f"Booking code found: {code}")
                    mail.logout()
                    return code

            mail.logout()

        except Exception as e:
            log.warning(f"Gmail polling error: {e}")

        log.info(f"No valid booking code email yet. Retrying in {poll_every}s...")
        time.sleep(poll_every)

    log.error("Timed out waiting for booking code email.")
    return None


def enter_booking_code(driver, wait) -> bool:
    log.info("Waiting for booking code email and entering it...")

    code = get_booking_code_from_email(timeout_seconds=180, poll_every=5)
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
        time.sleep(0.3)

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
        log.info(f"Booking code field now contains: {entered}")

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


def enter_booking_code(driver, wait) -> bool:
    log.info("Waiting for booking code email and entering it...")

    code = get_booking_code_from_email(timeout_seconds=120, poll_every=5)
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
        time.sleep(0.3)

        wait.until(lambda d: code_input.is_displayed() and code_input.is_enabled())

        driver.execute_script("""
            arguments[0].removeAttribute('readonly');
            arguments[0].removeAttribute('disabled');
            arguments[0].focus();
            arguments[0].value = '';
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            arguments[0].dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '6' }));
        """, code_input, code)

        entered = code_input.get_attribute("value") or ""
        log.info(f"Booking code field now contains: {entered}")

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
        time.sleep(0.5)
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
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        log.info("Clicked Book Time button")
        time.sleep(4)
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

    # Optional: click resend to force a fresh email
    click_resend_code(driver, wait)

    if not enter_booking_code(driver, wait):
        return False

    if CLICK_FINAL_BOOK_BUTTON:
        if not click_confirm_button(driver, wait):
            return False
        page = driver.page_source.lower()
        if any(kw in page for kw in ["confirmation", "confirmed", "receipt", "booked", "success", "thank you"]):
            log.info(f"BOOKING CONFIRMED: {time_str}")
            return True
        log.warning("Booking confirmation not detected after clicking Book Time.")
        return False

    return preview_without_booking(driver, wait)


def run_booking_job():
    log.info("=" * 60)
    log.info("Booking job started.")
    saturday = next_saturday()
    log.info(f"Target date: {saturday}")

    driver = make_driver()
    wait = WebDriverWait(driver, 20)

    try:
        load_tee_times(driver, wait, saturday)

        chosen_time = select_tee_time(driver, wait)
        if not chosen_time:
            send_notification(
                "Tee time bot: no slots",
                f"No tee times between target hours on {saturday} for {TARGET_PLAYERS} players."
            )
            return

        if not login_when_prompted(driver, wait):
            send_notification(
                "Tee time bot: login failed",
                f"Could not log in for {saturday}. Check screenshots."
            )
            return

        success = complete_until_final_step(driver, wait, chosen_time)

        if success:
            if CLICK_FINAL_BOOK_BUTTON:
                send_notification(
                    "⛳ Tee time booked!",
                    f"James Baird\nDate: {saturday}\nTime: {chosen_time}\nPlayers: {TARGET_PLAYERS}\nHoles: {TARGET_HOLES}"
                )
                log.info("Job complete — booked!")
            else:
                send_notification(
                    "Tee time bot: reached final step",
                    f"Reached final Book Time button without clicking it.\n"
                    f"Date: {saturday}\n"
                    f"Time: {chosen_time}\n"
                    f"Players: {TARGET_PLAYERS}\n"
                    f"Holes: {TARGET_HOLES}"
                )
                log.info("Job complete — reached final step without booking.")
        else:
            send_notification(
                "Tee time bot: not completed",
                f"Could not reach the final step for {saturday}. Try manually."
            )

    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        save_screenshot(driver, "error")
        send_notification("Tee time bot: error", str(e))
    finally:
        if not HEADLESS:
            log.info("Pausing 20s so you can inspect the browser...")
            time.sleep(20)
        driver.quit()
        log.info("Browser closed.")


if __name__ == "__main__":
    run_booking_job()