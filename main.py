"""
Karama Registration Automation
================================
Concurrent Playwright-based automation for the Karama ASP.NET WebForms
registration portal with file-based state management and real-time
Telegram notifications.
"""

import asyncio
import configparser
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from app_paths import APP_DIR, app_path, is_frozen, resolve_data_path, setup_runtime
from notify_format import DEFAULT_VIEW_URL, build_success_message, is_valid_request_id

setup_runtime()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
def _configure_logging() -> None:
    handlers: list[logging.Handler] = [
        logging.FileHandler(app_path("automation.log"), encoding="utf-8"),
    ]
    stream = logging.StreamHandler(sys.stdout)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    handlers.append(stream)
    logging.basicConfig(level=logging.INFO, format=LOG_FMT, handlers=handlers)


_configure_logging()
log = logging.getLogger("karama")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_URL = "http://karama.smcegy.com/karama/Register.aspx"
VIEW_URL_TEMPLATE = DEFAULT_VIEW_URL
STATE_FILE = app_path("processed_state.json")
CONFIG_FILE = app_path("register.ini")

# ---------------------------------------------------------------------------
# Real ASP.NET element IDs (from live page probe)
# ---------------------------------------------------------------------------
ID_SSN = "#ContentPlaceHolder1_txtCitizenSSN"
ID_FNAME = "#ContentPlaceHolder1_txtFName"
ID_SNAME = "#ContentPlaceHolder1_txtSName"
ID_TNAME = "#ContentPlaceHolder1_txtTName"
ID_LNAME = "#ContentPlaceHolder1_txtLName"
ID_BIRTHDATE = "#ContentPlaceHolder1_txtBirthDate"
ID_GENDER = "#ContentPlaceHolder1_ddlGender"
ID_MARITAL = "#ContentPlaceHolder1_ddlMaritalStatus"
ID_GOV = "#ContentPlaceHolder1_ddlGovernorate"
ID_CITY = "#ContentPlaceHolder1_ddlCity"
ID_ADDRESS = "#ContentPlaceHolder1_txtAddress"
ID_JOB = "#ContentPlaceHolder1_ddlJob"
ID_PHONE = "#ContentPlaceHolder1_txtPhone"
ID_SUBMIT = "#ContentPlaceHolder1_btnSave"
ID_MSG = "#ContentPlaceHolder1_lblMsg"

# Disability checkboxes — value→ID mapping
DISABILITY_CHECKBOX_MAP = {
    "1": "#ContentPlaceHolder1_chbDistype_0",  # إعاقة حركية
    "2": "#ContentPlaceHolder1_chbDistype_1",  # إعاقة ذهنية
    "7": "#ContentPlaceHolder1_chbDistype_2",  # طيف توحد
    "3": "#ContentPlaceHolder1_chbDistype_3",  # أمراض مزمنة
    "4": "#ContentPlaceHolder1_chbDistype_4",  # إعاقة سمعية
    "5": "#ContentPlaceHolder1_chbDistype_5",  # إعاقة بصرية
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class DropdownValue:
    value: str = ""
    text: str = ""


@dataclass
class CaseData:
    ssn: str = ""
    first_name: str = ""
    second_name: str = ""
    third_name: str = ""
    fourth_name: str = ""
    city: str = ""
    address: str = ""
    phone_number: str = ""
    governorate: DropdownValue = field(default_factory=DropdownValue)
    marital_status: DropdownValue = field(default_factory=DropdownValue)
    job: DropdownValue = field(default_factory=DropdownValue)
    ddl: DropdownValue = field(default_factory=DropdownValue)
    note: str = ""
    source_file: str = ""

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.second_name, self.third_name, self.fourth_name]
        return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    telegram_bot: str = ""
    telegram_channel: str = ""
    sleep_delay: int = 3
    cases_folder: str = "cases"
    finished_folder: str = "finished"
    threads_count: int = 4


def load_config(ini_path: Path | None = None) -> AppConfig:
    ini_path = ini_path or CONFIG_FILE
    parser = configparser.ConfigParser()
    if not ini_path.exists():
        log.error("Config file '%s' not found", ini_path)
        sys.exit(1)

    parser.read(ini_path, encoding="utf-8")

    section = None
    for s in parser.sections():
        if s.upper() == "SETTINGS":
            section = s
            break
    if section is None:
        log.error("No [SETTINGS] or [Settings] section in '%s'", ini_path)
        sys.exit(1)

    cfg = AppConfig(
        telegram_bot=parser.get(section, "TELEGRAM_BOT", fallback="").strip(),
        telegram_channel=parser.get(section, "TELEGRAM_CHANNEL", fallback="").strip(),
        sleep_delay=parser.getint(section, "SLEEP", fallback=3),
        cases_folder=str(resolve_data_path(
            parser.get(section, "CASES_FOLDER", fallback="register_cases").strip()
        )),
        finished_folder=str(resolve_data_path(
            parser.get(section, "FINISHED_FOLDER", fallback="register_finished").strip()
        )),
        threads_count=parser.getint(section, "THREADS_COUNT", fallback=4),
    )
    log.info(
        "Config loaded: threads=%d, sleep=%ds, cases='%s', finished='%s'",
        cfg.threads_count, cfg.sleep_delay, cfg.cases_folder, cfg.finished_folder,
    )
    return cfg


# ---------------------------------------------------------------------------
# State management (processed_state.json)
# ---------------------------------------------------------------------------
_state_lock = asyncio.Lock()


def _read_state() -> dict:
    if not Path(STATE_FILE).exists():
        return {"processed_ssns": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.warning("Corrupt state file, resetting")
            return {"processed_ssns": {}}


def _write_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


async def is_already_processed(ssn: str) -> bool:
    async with _state_lock:
        return ssn in _read_state().get("processed_ssns", {})


async def mark_processed(ssn: str, req_id: str, file_name: str) -> None:
    async with _state_lock:
        state = _read_state()
        state.setdefault("processed_ssns", {})[ssn] = {
            "req_id": req_id,
            "file": file_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _write_state(state)
        log.info("State updated: ssn=%s req_id=%s", ssn, req_id)


# ---------------------------------------------------------------------------
# Case file parser (supports both .xml and .txt)
# ---------------------------------------------------------------------------
_SIMPLE_TAGS = [
    ("ssn", "ssn"),
    ("firstName", "first_name"),
    ("secondName", "second_name"),
    ("thirdName", "third_name"),
    ("fourthName", "fourth_name"),
    ("city", "city"),
    ("address", "address"),
    ("phoneNumber", "phone_number"),
    ("note", "note"),
]

_DROPDOWN_TAGS = [
    ("governorate", "governorate"),
    ("MaritalStatus", "marital_status"),
    ("Job", "job"),
    ("ddl", "ddl"),
]


def _extract_simple(soup: BeautifulSoup, tag_name: str) -> str:
    tag = soup.find(tag_name.lower())
    if tag is None:
        tag = soup.find(tag_name)
    if tag is None:
        return ""
    option = tag.find("option")
    if option:
        return ""
    return tag.get_text(strip=True)


def _extract_dropdown(soup: BeautifulSoup, tag_name: str) -> DropdownValue:
    parent = soup.find(tag_name.lower()) or soup.find(tag_name)
    if parent is None:
        return DropdownValue()
    option = parent.find("option", attrs={"checked": "1"})
    if option is None:
        option = parent.find("option")
    if option is None:
        text = parent.get_text(strip=True)
        return DropdownValue(text=text) if text else DropdownValue()
    return DropdownValue(
        value=option.get("value", ""),
        text=option.get_text(strip=True),
    )


def parse_case_file(file_path: str) -> Optional[CaseData]:
    path = Path(file_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        log.error("Cannot read file '%s': %s", file_path, exc)
        return None

    wrapped = f"<root>{raw}</root>"
    soup = BeautifulSoup(wrapped, "html.parser")

    case = CaseData(source_file=str(path))

    for xml_tag, attr in _SIMPLE_TAGS:
        setattr(case, attr, _extract_simple(soup, xml_tag))

    for xml_tag, attr in _DROPDOWN_TAGS:
        setattr(case, attr, _extract_dropdown(soup, xml_tag))

    if not case.ssn:
        log.warning("No <ssn> found in '%s', skipping", file_path)
        return None

    log.info(
        "Parsed case: ssn=%s name='%s' gov=%s city=%s job=%s ddl=%s from '%s'",
        case.ssn, case.full_name,
        case.governorate.text, case.city,
        case.job.text, case.ddl.text,
        path.name,
    )
    return case


# ---------------------------------------------------------------------------
# Telegram notifications
# ---------------------------------------------------------------------------
TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_RETRIES = 5
RETRY_BASE_DELAY = 2


async def send_telegram(
    session: aiohttp.ClientSession,
    bot_token: str,
    channel_id: str,
    case: CaseData,
    req_id: str,
    start_time: str,
) -> None:
    if not bot_token or not channel_id:
        log.warning("Telegram credentials missing, skipping notification")
        return

    message = build_success_message(
        start_time=start_time,
        full_name=case.full_name,
        ssn=case.ssn,
        phone=case.phone_number,
        case_type=case.ddl.text,
        note=case.note,
        req_id=req_id,
        view_url_template=VIEW_URL_TEMPLATE,
    )

    payload = {
        "chat_id": channel_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    url = TELEGRAM_SEND_URL.format(token=bot_token)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    log.info("Telegram notification sent for ssn=%s", case.ssn)
                    return
                if resp.status == 429:
                    body = await resp.json()
                    retry_after = body.get("parameters", {}).get(
                        "retry_after", RETRY_BASE_DELAY * attempt
                    )
                    log.warning(
                        "Telegram rate-limited (429), retry_after=%ss (attempt %d/%d)",
                        retry_after, attempt, MAX_RETRIES,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                body_text = await resp.text()
                log.error("Telegram API error %d: %s", resp.status, body_text)
                return
        except Exception as exc:
            log.error(
                "Telegram request failed (attempt %d/%d): %s",
                attempt, MAX_RETRIES, exc,
            )
            await asyncio.sleep(RETRY_BASE_DELAY * attempt)

    log.error("Telegram notification exhausted retries for ssn=%s", case.ssn)


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------
async def _wait_for_enabled(page: Page, selector: str, timeout: int = 15_000) -> bool:
    """Wait until an element exists and is no longer disabled."""
    try:
        await page.wait_for_selector(selector, state="attached", timeout=timeout)
        await page.wait_for_function(
            f"""() => {{
                const el = document.querySelector('{selector}');
                return el && !el.disabled;
            }}""",
            timeout=timeout,
        )
        return True
    except PlaywrightTimeout:
        return False


async def _safe_fill(page: Page, selector: str, value: str) -> bool:
    """Enable a field via JS if needed, then fill it."""
    if not value:
        return True
    try:
        await page.evaluate(
            f"document.querySelector('{selector}').disabled = false"
        )
        await page.fill(selector, value)
        return True
    except Exception as exc:
        log.warning("Could not fill %s: %s", selector, exc)
        return False


async def _safe_select(page: Page, selector: str, value: str) -> bool:
    """Enable a dropdown via JS if needed, then select by value."""
    if not value:
        return True
    try:
        await page.evaluate(
            f"document.querySelector('{selector}').disabled = false"
        )
        await page.select_option(selector, value=value)
        return True
    except Exception as exc:
        log.warning("Could not select %s with value '%s': %s", selector, value, exc)
        return False


async def _safe_select_by_label(page: Page, selector: str, label: str) -> bool:
    """Enable a dropdown via JS if needed, then select by visible text."""
    if not label:
        return True
    try:
        await page.evaluate(
            f"document.querySelector('{selector}').disabled = false"
        )
        await page.select_option(selector, label=label)
        return True
    except Exception as exc:
        log.warning("Could not select %s by label '%s': %s", selector, label, exc)
        return False


# ---------------------------------------------------------------------------
# Web automation core
# ---------------------------------------------------------------------------
REQUEST_ID_PATTERN = re.compile(r"(\d{4,})")


async def fill_form(page: Page, case: CaseData) -> Optional[str]:
    """
    Full automation flow:
      1. Navigate + enter SSN → triggers ASP.NET async postback
      2. Wait for form fields to enable
      3. Fill names, select dropdowns (gov → city cascade), check disability
      4. Submit and extract result
    """
    log.info("Navigating to %s for ssn=%s", TARGET_URL, case.ssn)
    await page.goto(TARGET_URL, wait_until="networkidle", timeout=60_000)
    await page.wait_for_load_state("domcontentloaded")

    # ── Step 1: Enter SSN (triggers postback via onkeyup → validateSSN) ──
    log.info("[%s] Entering SSN…", case.ssn)
    await page.wait_for_selector(ID_SSN, timeout=10_000)
    await page.fill(ID_SSN, "")
    await page.type(ID_SSN, case.ssn, delay=30)

    # Wait for the async postback to complete and enable the form
    log.info("[%s] Waiting for SSN postback…", case.ssn)
    enabled = await _wait_for_enabled(page, ID_MARITAL, timeout=20_000)
    if not enabled:
        log.warning("[%s] Fields did not enable after SSN postback, forcing via JS", case.ssn)

    await page.wait_for_timeout(1000)

    # Check for error messages after SSN entry
    msg_el = await page.query_selector(ID_MSG)
    if msg_el:
        msg_text = (await msg_el.inner_text()).strip()
        if msg_text:
            log.warning("[%s] Server message after SSN: %s", case.ssn, msg_text)
            if any(kw in msg_text for kw in ["خطأ", "غير صحيح", "مسجل", "موجود"]):
                log.error("[%s] SSN rejected by server: %s", case.ssn, msg_text)
                return None

    # ── Step 2: Fill name fields (fill only if empty / auto-filled) ──
    for selector, value in [
        (ID_FNAME, case.first_name),
        (ID_SNAME, case.second_name),
        (ID_TNAME, case.third_name),
        (ID_LNAME, case.fourth_name),
    ]:
        current = await page.evaluate(
            f"document.querySelector('{selector}')?.value || ''"
        )
        if not current.strip():
            await _safe_fill(page, selector, value)

    # ── Step 3: Marital status ──
    await _safe_select(page, ID_MARITAL, case.marital_status.value)

    # ── Step 4: Governorate → triggers postback → populates city dropdown ──
    if case.governorate.value:
        log.info("[%s] Selecting governorate=%s…", case.ssn, case.governorate.text)
        await _safe_select(page, ID_GOV, case.governorate.value)

        # The governorate onchange triggers __doPostBack which reloads the city
        # dropdown inside UpdatePanel1. Wait for city options to appear.
        await page.wait_for_timeout(500)
        await page.evaluate(
            f"__doPostBack('ctl00$ContentPlaceHolder1$ddlGovernorate', '')"
        )
        log.info("[%s] Waiting for city dropdown to populate…", case.ssn)
        try:
            await page.wait_for_function(
                f"""() => {{
                    const sel = document.querySelector('{ID_CITY}');
                    return sel && sel.options.length > 1;
                }}""",
                timeout=15_000,
            )
        except PlaywrightTimeout:
            log.warning("[%s] City dropdown did not populate in time", case.ssn)

        await page.wait_for_timeout(500)

    # ── Step 5: City (select by text since XML has city name, not numeric ID) ──
    if case.city:
        log.info("[%s] Selecting city='%s'…", case.ssn, case.city)
        await _safe_select_by_label(page, ID_CITY, case.city)

    # ── Step 6: Address ──
    await _safe_fill(page, ID_ADDRESS, case.address)

    # ── Step 7: Job (dropdown) ──
    if case.job.value:
        log.info("[%s] Selecting job=%s (%s)…", case.ssn, case.job.value, case.job.text)
        await _safe_select(page, ID_JOB, case.job.value)

    # ── Step 8: Phone ──
    await _safe_fill(page, ID_PHONE, case.phone_number)

    # ── Step 9: Disability type checkbox(es) ──
    if case.ddl.value:
        cb_selector = DISABILITY_CHECKBOX_MAP.get(case.ddl.value)
        if cb_selector:
            log.info(
                "[%s] Checking disability checkbox value=%s (%s)",
                case.ssn, case.ddl.value, case.ddl.text,
            )
            try:
                await page.evaluate(
                    f"document.querySelector('{cb_selector}').checked = true"
                )
            except Exception as exc:
                log.warning("[%s] Could not check disability box: %s", case.ssn, exc)
        else:
            log.warning(
                "[%s] Unknown disability value '%s', skipping checkbox",
                case.ssn, case.ddl.value,
            )

    # ── Step 10: Submit ──
    log.info("[%s] Submitting form…", case.ssn)
    try:
        await page.wait_for_selector(ID_SUBMIT, timeout=5_000)
        await page.evaluate(
            f"document.querySelector('{ID_SUBMIT}').disabled = false"
        )
        await page.click(ID_SUBMIT)
    except PlaywrightTimeout:
        log.error("[%s] Submit button not found", case.ssn)
        return None

    # ── Step 11: Wait for server response ──
    return await _extract_result(page, case.ssn)


async def _extract_result(page: Page, ssn: str) -> Optional[str]:
    """Wait for the server response message and extract the request ID."""
    log.info("[%s] Waiting for server response…", ssn)
    await page.wait_for_timeout(3000)

    try:
        await page.wait_for_function(
            f"""() => {{
                const el = document.querySelector('{ID_MSG}');
                return el && el.innerText.trim().length > 0;
            }}""",
            timeout=30_000,
        )
    except PlaywrightTimeout:
        log.warning("[%s] No response message appeared within 30s", ssn)

    msg_el = await page.query_selector(ID_MSG)
    if msg_el:
        text = (await msg_el.inner_text()).strip()
        log.info("[%s] Server response: %s", ssn, text[:200])

        if any(kw in text for kw in ["خطأ", "غير صحيح", "فشل"]):
            log.error("[%s] Submission FAILED: %s", ssn, text)
            return None

        match = REQUEST_ID_PATTERN.search(text)
        if match:
            return match.group(1)

        if any(kw in text for kw in ["تم", "نجاح", "بنجاح", "حفظ"]):
            log.info("[%s] Submission appears successful (no numeric ID found)", ssn)
            return "OK"

    body_text = await page.inner_text("body")
    match = REQUEST_ID_PATTERN.search(body_text[-600:])
    if match:
        return match.group(1)

    log.warning("[%s] Could not determine submission result", ssn)
    return None


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------
_file_lock = asyncio.Lock()


async def move_to_finished(source: str, finished_folder: str) -> None:
    async with _file_lock:
        dest = Path(finished_folder)
        dest.mkdir(parents=True, exist_ok=True)
        src = Path(source)
        target = dest / src.name
        if target.exists():
            stem = src.stem
            target = dest / f"{stem}_{int(time.time())}{src.suffix}"
        try:
            shutil.move(str(src), str(target))
            log.info("Moved '%s' -> '%s'", src.name, target)
        except Exception as exc:
            log.error("Failed to move '%s': %s", src.name, exc)


def discover_case_files(cases_folder: str) -> list[str]:
    folder = Path(cases_folder)
    if not folder.is_dir():
        log.warning("Cases folder '%s' does not exist, creating it", cases_folder)
        folder.mkdir(parents=True, exist_ok=True)
        return []
    files = []
    for ext in ("*.xml", "*.txt"):
        files.extend(folder.glob(ext))
    files.sort(key=lambda p: p.stat().st_mtime)
    return [str(f) for f in files]


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def process_case(
    case: CaseData,
    cfg: AppConfig,
    http_session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    browser_context_factory,
) -> None:
    async with semaphore:
        start_ts = datetime.now().strftime("%H:%M:%S %d-%m-%Y")

        if await is_already_processed(case.ssn):
            log.info("SSN %s already processed, skipping '%s'", case.ssn, case.source_file)
            await move_to_finished(case.source_file, cfg.finished_folder)
            return

        context: BrowserContext = await browser_context_factory()
        page = await context.new_page()
        try:
            req_id = await fill_form(page, case)

            if req_id is None:
                log.error("Submission failed for ssn=%s (no request ID)", case.ssn)
                screenshot = app_path(f"error_{case.ssn}_{int(time.time())}.png")
                try:
                    await page.screenshot(path=str(screenshot), full_page=True)
                    log.info("Error screenshot saved: %s", screenshot)
                except Exception:
                    pass
                return

            if is_valid_request_id(req_id):
                log.info("SUCCESS ssn=%s req_id=%s", case.ssn, req_id)
            else:
                log.info("SUCCESS ssn=%s (no request ID in response)", case.ssn)

            await mark_processed(
                case.ssn,
                req_id if is_valid_request_id(req_id) else "",
                Path(case.source_file).name,
            )
            await move_to_finished(case.source_file, cfg.finished_folder)

            asyncio.create_task(
                send_telegram(
                    http_session, cfg.telegram_bot, cfg.telegram_channel,
                    case, req_id, start_ts,
                )
            )

        except PlaywrightTimeout as exc:
            log.error("Playwright timeout for ssn=%s: %s", case.ssn, exc)
        except Exception as exc:
            log.exception("Unexpected error processing ssn=%s: %s", case.ssn, exc)
        finally:
            await page.close()
            await context.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    cfg = load_config()

    log.info("Program folder: %s", APP_DIR)
    Path(cfg.cases_folder).mkdir(parents=True, exist_ok=True)
    Path(cfg.finished_folder).mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(cfg.threads_count)

    async with aiohttp.ClientSession() as http_session:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)

            async def make_context() -> BrowserContext:
                return await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="ar-EG",
                )

            log.info(
                "Browser launched (headless). Monitoring '%s' for .xml/.txt case files…",
                cfg.cases_folder,
            )

            try:
                while True:
                    files = discover_case_files(cfg.cases_folder)
                    if not files:
                        await asyncio.sleep(cfg.sleep_delay)
                        continue

                    log.info("Found %d case file(s) to process", len(files))

                    cases: list[CaseData] = []
                    for fp in files:
                        parsed = parse_case_file(fp)
                        if parsed:
                            cases.append(parsed)

                    if not cases:
                        await asyncio.sleep(cfg.sleep_delay)
                        continue

                    tasks = [
                        asyncio.create_task(
                            process_case(case, cfg, http_session, semaphore, make_context)
                        )
                        for case in cases
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)

                    log.info(
                        "Batch complete. Sleeping %ds before next scan…",
                        cfg.sleep_delay,
                    )
                    await asyncio.sleep(cfg.sleep_delay)

            except KeyboardInterrupt:
                log.info("Shutdown requested via keyboard interrupt")
            finally:
                await browser.close()
                log.info("Browser closed. Exiting.")


def _pause_before_exit() -> None:
    if is_frozen():
        print()
        input("Press Enter to close... ")


if __name__ == "__main__":
    exit_code = 0
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Process terminated.")
    except Exception:
        log.exception("Fatal error")
        exit_code = 1
    finally:
        _pause_before_exit()
    sys.exit(exit_code)
