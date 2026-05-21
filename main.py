"""
Karama Registration Automation
================================
Concurrent Playwright-based automation for the Karama ASP.NET WebForms
registration portal with file-based state management and real-time
Telegram notifications.
"""

import asyncio
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

from app_paths import APP_DIR, app_path, pause_on_error, setup_runtime
from config_loader import load_config, AppConfig
from http_client import format_ssl_help, is_ssl_certificate_error, run_with_http_session
from notify_format import build_success_message, is_valid_request_id
from server_messages import (
    POST_SUBMIT_SUCCESS_MARKERS,
    REQUEST_ID_PATTERN,
    detect_post_submit_success,
    parse_server_message,
)
from telegram_utils import normalize_chat_id, send_channel_message

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
STATE_FILE = app_path("processed_state.json")

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


async def get_state_entry(ssn: str) -> dict | None:
    async with _state_lock:
        return _read_state().get("processed_ssns", {}).get(ssn)


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
MAX_RETRIES = 5
RETRY_BASE_DELAY = 2


async def send_telegram(
    cfg: AppConfig,
    bot_token: str,
    channel_id: str,
    case: CaseData,
    req_id: str,
    start_time: str,
    view_url_template: str,
) -> None:
    channel_id = normalize_chat_id(channel_id)
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
        view_url_template=view_url_template,
    )

    async def deliver(session: aiohttp.ClientSession) -> None:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                status, body_text = await send_channel_message(
                    session, bot_token, channel_id, message
                )
                if status == 200:
                    log.info("Telegram notification sent for ssn=%s", case.ssn)
                    print(f"  ✓ أُرسل إشعار تيليجرام لـ {case.full_name or case.ssn}")
                    return
                if status == 429:
                    body = json.loads(body_text)
                    retry_after = body.get("parameters", {}).get(
                        "retry_after", RETRY_BASE_DELAY * attempt
                    )
                    log.warning(
                        "Telegram rate-limited (429), retry_after=%ss (attempt %d/%d)",
                        retry_after, attempt, MAX_RETRIES,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                log.error("Telegram API error %d: %s", status, body_text)
                if status == 400 and "chat not found" in body_text.lower():
                    log.error(
                        "Bot token and CHANNEL may not match — use the bot that is admin on this channel"
                    )
                return
            except Exception as exc:
                if is_ssl_certificate_error(exc):
                    raise
                log.error(
                    "Telegram request failed (attempt %d/%d): %s",
                    attempt, MAX_RETRIES, exc,
                )
                await asyncio.sleep(RETRY_BASE_DELAY * attempt)

        log.error("Telegram notification exhausted retries for ssn=%s", case.ssn)

    try:
        await run_with_http_session(
            deliver,
            verify_ssl=cfg.ssl_verify,
            allow_insecure_fallback=cfg.ssl_verify,
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        print(format_ssl_help())
    except Exception as exc:
        log.error("Telegram notification failed for ssn=%s: %s", case.ssn, exc)


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


def _interpret_server_message(text: str, ssn: str, *, phase: str) -> Optional[str]:
    result = parse_server_message(text)
    if result:
        return result
    log.warning("[%s] Unrecognized server message (%s): %s", ssn, phase, text[:200])
    return None


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
            early = _interpret_server_message(msg_text, case.ssn, phase="after SSN")
            if early == "ALREADY_REGISTERED":
                log.info("[%s] SSN already registered: %s", case.ssn, msg_text)
                return "ALREADY_REGISTERED"
            if early is None and any(kw in msg_text for kw in ["خطأ", "غير صحيح", "فشل"]):
                log.error("[%s] SSN rejected by server: %s", case.ssn, msg_text)
                return None
            if early == "OK":
                log.info("[%s] Active request on server: %s", case.ssn, msg_text)
                return "ALREADY_REGISTERED"

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

    markers_js = ", ".join(repr(m) for m in POST_SUBMIT_SUCCESS_MARKERS)
    try:
        await page.wait_for_function(
            f"""() => {{
                const el = document.querySelector('{ID_MSG}');
                if (el && el.innerText.trim().length > 0) return true;
                const body = document.body?.innerText || '';
                const markers = [{markers_js}];
                return markers.some(m => body.includes(m));
            }}""",
            timeout=30_000,
        )
    except PlaywrightTimeout:
        log.warning("[%s] No response message appeared within 30s", ssn)

    msg_el = await page.query_selector(ID_MSG)
    if msg_el:
        text = (await msg_el.inner_text()).strip()
        if text:
            log.info("[%s] Server response (lblMsg): %s", ssn, text[:200])
            result = _interpret_server_message(text, ssn, phase="after submit")
            if result:
                if result == "OK":
                    log.info("[%s] Submission successful (instruction message)", ssn)
                return result

    body_text = await page.inner_text("body")
    if detect_post_submit_success(body_text):
        log.info("[%s] Submission successful (post-submit banner on page)", ssn)
        return "OK"

    result = _interpret_server_message(body_text, ssn, phase="page body")
    if result:
        if result == "OK":
            log.info("[%s] Submission successful (parsed from page body)", ssn)
        return result

    match = REQUEST_ID_PATTERN.search(body_text)
    if match:
        return match.group(1)

    log.warning("[%s] Could not determine submission result", ssn)
    return None


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------
_file_lock = asyncio.Lock()


def _is_finished_case_file(path: Path) -> bool:
    """Only real case XML/txt files — not status notes or folder readmes."""
    if path.suffix.lower() not in (".xml", ".txt"):
        return False
    if path.name.startswith("_"):
        return False
    if "_حالة" in path.name:
        return False
    return True


async def move_to_finished(source: str, finished_folder: str, reason: str) -> bool:
    """Move completed XML/txt from register_cases to register_finished."""
    async with _file_lock:
        dest_dir = Path(finished_folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = Path(source)
        if not src.is_file():
            log.warning("Cannot move '%s' — file not found", src.name)
            return False

        stem = src.stem.split("_")[0] if src.stem else src.stem
        for existing in dest_dir.iterdir():
            if not existing.is_file() or not _is_finished_case_file(existing):
                continue
            if existing.stem == src.stem or existing.stem.startswith(f"{stem}_"):
                try:
                    src.unlink()
                    log.info(
                        "Removed duplicate '%s' from cases (%s) — already in finished as '%s'",
                        src.name, reason, existing.name,
                    )
                    print(
                        f"  ○ '{src.name}' — {reason}\n"
                        f"    (ملف مكرر — موجود مسبقاً في register_finished كـ '{existing.name}')"
                    )
                    return True
                except Exception as exc:
                    log.warning("Could not remove duplicate '%s': %s", src.name, exc)

        target = dest_dir / src.name
        if target.exists():
            target = dest_dir / f"{src.stem}_{int(time.time())}{src.suffix}"
        for attempt in range(5):
            try:
                shutil.move(str(src), str(target))
                log.info("Moved '%s' -> '%s' (%s)", src.name, target.name, reason)
                print(f"  ✓ نُقل '{src.name}' → register_finished")
                return True
            except Exception as exc:
                if attempt < 4:
                    log.warning(
                        "Failed to move '%s' (attempt %d/5): %s",
                        src.name, attempt + 1, exc,
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    log.error("Failed to move '%s' after 5 attempts: %s", src.name, exc)
                    print(f"  ✗ تعذّر نقل '{src.name}' — سيُعاد المحاولة لاحقاً")
        return False


def write_case_status(finished_folder: str, case: CaseData, status: str, detail: str) -> None:
    """Save a readable status note next to finished cases."""
    folder = Path(finished_folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{case.ssn}_حالة.txt"
    path.write_text(
        f"الرقم القومي: {case.ssn}\n"
        f"الاسم: {case.full_name}\n"
        f"الحالة: {status}\n"
        f"التفاصيل: {detail}\n"
        f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8",
    )


async def save_error_screenshot(
    page: Optional[Page],
    case: CaseData,
    error_folder: str,
    tag: str = "error",
) -> None:
    if page is None:
        return
    folder = Path(error_folder)
    folder.mkdir(parents=True, exist_ok=True)
    screenshot = folder / f"{tag}_{case.ssn}_{int(time.time())}.png"
    try:
        await page.screenshot(path=str(screenshot), full_page=True)
        log.info("Error screenshot saved: %s", screenshot)
    except Exception as exc:
        log.warning("Could not save error screenshot for ssn=%s: %s", case.ssn, exc)


def _is_skipped_case_filename(name: str) -> bool:
    lower = name.lower()
    if name.startswith("_") or name.startswith("#"):
        return True
    if lower in ("sample_case.txt", "sample_case.xml"):
        return True
    if lower.startswith("ضع_") or lower.startswith("readme"):
        return True
    return False


def discover_case_files(cases_folder: str) -> list[str]:
    folder = Path(cases_folder)
    if not folder.is_dir():
        log.warning("Cases folder '%s' does not exist, creating it", cases_folder)
        folder.mkdir(parents=True, exist_ok=True)
        return []
    files = []
    for ext in ("*.xml", "*.txt"):
        for path in folder.glob(ext):
            if not _is_skipped_case_filename(path.name):
                files.append(path)
    files.sort(key=lambda p: p.stat().st_mtime)
    return [str(f) for f in files]


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def process_case(
    case: CaseData,
    cfg: AppConfig,
    semaphore: asyncio.Semaphore,
    browser_context_factory,
) -> None:
    async with semaphore:
        start_ts = datetime.now().strftime("%H:%M:%S %d-%m-%Y")

        prior = await get_state_entry(case.ssn)
        if prior and is_valid_request_id(prior.get("req_id")):
            req_id = str(prior["req_id"])
            log.info(
                "SSN %s already booked (req_id=%s), skipping duplicate file '%s'",
                case.ssn, req_id, Path(case.source_file).name,
            )
            print(
                f"  ✓ {case.ssn} مسجل مسبقاً — رقم الطلب: {req_id}\n"
                f"    (ملف مكرر — لن يُعاد الحجز)"
            )
            await move_to_finished(
                case.source_file, cfg.finished_folder, "duplicate — already booked"
            )
            return

        context: BrowserContext = await browser_context_factory()
        page = await context.new_page()
        try:
            req_id = await fill_form(page, case)

            if req_id is None:
                log.error("Submission failed for ssn=%s (no request ID)", case.ssn)
                write_case_status(
                    cfg.error_images_folder,
                    case,
                    "فشل الحجز",
                    "تحقق من صورة الخطأ في error_images",
                )
                print(
                    f"  ✗ فشل حجز {case.ssn} — راجع error_images "
                    f"والملف يبقى في register_cases"
                )
                await save_error_screenshot(page, case, cfg.error_images_folder)
                return

            if req_id == "ALREADY_REGISTERED":
                log.info(
                    "SSN %s already registered on server, moving '%s' to finished",
                    case.ssn, Path(case.source_file).name,
                )
                detail = "مسجل مسبقاً على موقع كرامة — انتظر موعد الكشف الطبي"
                print(
                    f"  ○ {case.ssn} — {detail}\n"
                    f"    (بدون إشعار تيليجرام — ليس حجزاً جديداً)"
                )
                moved = await move_to_finished(
                    case.source_file, cfg.finished_folder, "already registered on server"
                )
                if moved:
                    write_case_status(cfg.finished_folder, case, "مسجل على الموقع", detail)
                    await mark_processed(
                        case.ssn, "", Path(case.source_file).name
                    )
                return

            if is_valid_request_id(req_id):
                log.info("SUCCESS ssn=%s req_id=%s", case.ssn, req_id)
                detail = f"رقم الطلب: {req_id}"
                print(f"  ✓ {case.ssn} — حجز ناجح req_id={req_id}")
            else:
                log.info("SUCCESS ssn=%s (no request ID in response)", case.ssn)
                detail = "تم التسجيل — اتبع تعليمات الموقع (طباعة الاستمارات والموعد)"
                print(
                    f"  ✓ {case.ssn} — تم الحجز بنجاح "
                    f"(طباعة الاستمارات والالتزام بالموعد)"
                )

            moved = await move_to_finished(
                case.source_file, cfg.finished_folder, "booked successfully"
            )
            write_case_status(cfg.finished_folder, case, "حجز ناجح", detail)

            if not moved:
                log.error(
                    "Booking succeeded for ssn=%s but file was not moved",
                    case.ssn,
                )
                print(f"  ⚠ تم الحجز على الموقع لكن تعذّر نقل الملف — تحقق من register_finished")

            await mark_processed(
                case.ssn,
                req_id if is_valid_request_id(req_id) else "",
                Path(case.source_file).name,
            )

            await send_telegram(
                cfg,
                cfg.telegram_bot,
                cfg.telegram_channel,
                case,
                req_id,
                start_ts,
                cfg.telegram_view_url,
            )

        except PlaywrightTimeout as exc:
            log.error("Playwright timeout for ssn=%s: %s", case.ssn, exc)
            await save_error_screenshot(page, case, cfg.error_images_folder, tag="timeout")
        except Exception as exc:
            log.exception("Unexpected error processing ssn=%s: %s", case.ssn, exc)
            await save_error_screenshot(page, case, cfg.error_images_folder, tag="exception")
        finally:
            await page.close()
            await context.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _load_pending_cases(cases_folder: str) -> list[CaseData]:
    cases: list[CaseData] = []
    seen_ssns: set[str] = set()
    for fp in discover_case_files(cases_folder):
        parsed = parse_case_file(fp)
        if not parsed:
            continue
        if parsed.ssn in seen_ssns:
            log.warning(
                "Duplicate SSN %s in '%s' — only one file per person per run",
                parsed.ssn, Path(fp).name,
            )
            continue
        seen_ssns.add(parsed.ssn)
        cases.append(parsed)
    return cases


async def _process_batch(
    cases: list[CaseData],
    cfg: AppConfig,
    browser,
) -> None:
    semaphore = asyncio.Semaphore(cfg.threads_count)

    async def make_context() -> BrowserContext:
        return await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ar-EG",
        )

    print(f"\n── معالجة {len(cases)} ملف/ملفات ──")
    log.info("Processing %d case(s)…", len(cases))

    tasks = [
        asyncio.create_task(
            process_case(case, cfg, semaphore, make_context)
        )
        for case in cases
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("Batch of %d case(s) finished.", len(cases))
    print("── انتهت الدفعة ──\n")


async def main() -> int:
    cfg = load_config()

    log.info("Program folder: %s", APP_DIR)
    Path(cfg.cases_folder).mkdir(parents=True, exist_ok=True)
    Path(cfg.finished_folder).mkdir(parents=True, exist_ok=True)
    Path(cfg.error_images_folder).mkdir(parents=True, exist_ok=True)

    initial_cases = _load_pending_cases(cfg.cases_folder)
    if not initial_cases:
        log.info("No case files in '%s'. Closing program.", cfg.cases_folder)
        print("لا توجد ملفات في register_cases — ضع ملفات .xml ثم شغّل البرنامج.")
        return 0

    log.info("Found %d case file(s) in '%s'", len(initial_cases), cfg.cases_folder)
    if not cfg.ssl_verify:
        log.info("Telegram SSL_VERIFY=0 — certificate check disabled")
        print("تيليجرام: SSL_VERIFY=0 — بدون فحص شهادة SSL")
    print("للإيقاف في أي وقت: Ctrl+C")
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        log.info("Browser launched (headless).")

        try:
            while True:
                cases = _load_pending_cases(cfg.cases_folder)
                if cases:
                    await _process_batch(cases, cfg, browser)
                    if cfg.watch_idle_seconds <= 0:
                        remaining = _load_pending_cases(cfg.cases_folder)
                        if remaining:
                            print(
                                f"تبقى {len(remaining)} ملف/ملفات في register_cases "
                                "(راجع error_images إن وُجدت)"
                            )
                        print("تم الانتهاء — إغلاق البرنامج...")
                        log.info("Single-pass mode — closing program.")
                        break
                    await asyncio.sleep(cfg.watch_poll_seconds)
                    continue

                if cfg.watch_idle_seconds <= 0:
                    print("لا توجد ملفات — إغلاق البرنامج.")
                    break

                log.info(
                    "Watching '%s' for new files (poll %ds, auto-close after %ds idle)…",
                    cfg.cases_folder,
                    cfg.watch_poll_seconds,
                    cfg.watch_idle_seconds,
                )
                print(
                    f"بانتظار ملفات جديدة في register_cases "
                    f"(Ctrl+C للإيقاف | إغلاق تلقائي بعد {cfg.watch_idle_seconds} ثانية)"
                )
                idle_since = time.monotonic()
                while True:
                    await asyncio.sleep(cfg.watch_poll_seconds)
                    if _load_pending_cases(cfg.cases_folder):
                        break
                    if time.monotonic() - idle_since >= cfg.watch_idle_seconds:
                        print("انتهى — إغلاق البرنامج.")
                        log.info("Idle timeout — closing program.")
                        return 0

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            print("\nتم الإيقاف — أغلقت البرنامج.")
        finally:
            await browser.close()
            log.info("Browser closed.")

    return 0


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = asyncio.run(main())
    except SystemExit as exc:
        code = exc.code
        exit_code = int(code) if isinstance(code, int) else (1 if code else 0)
    except KeyboardInterrupt:
        log.info("Process terminated.")
        exit_code = 0
    except Exception:
        log.exception("Fatal error")
        exit_code = 1
    pause_on_error(exit_code)
    sys.exit(exit_code)
