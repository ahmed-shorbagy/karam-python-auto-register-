"""
Load settings from register.ini next to the program (KaramaStart.exe folder).

Edit register.ini anytime — changes apply on the next run.
"""
from __future__ import annotations

import configparser
import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from app_paths import app_path, resolve_data_path
from telegram_utils import normalize_chat_id

log = logging.getLogger("karama")

CONFIG_FILE = app_path("register.ini")
TEMPLATE_FILE = app_path("register.ini.template")

# Legacy keys still supported for older installs
_BOT_KEYS = ("BOT_TOKEN", "TELEGRAM_BOT", "TELEGRAM_BOT_TOKEN", "BOT")
_CHANNEL_KEYS = (
    "CHANNEL",
    "TELEGRAM_CHANNEL",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_USERNAME",
    "CHAT_ID",
)
_VIEW_URL_KEYS = ("VIEW_URL", "TELEGRAM_VIEW_URL", "LINK_TEMPLATE", "VIEW_LINK")


@dataclass
class AppConfig:
    telegram_bot: str = ""
    telegram_channel: str = ""
    telegram_view_url: str = "http://www.smcegy.com/Karama/ViewAll.aspx?reqId={req_id}"
    sleep_delay: int = 3
    cases_folder: str = "register_cases"
    finished_folder: str = "register_finished"
    error_images_folder: str = "error_images"
    threads_count: int = 4
    watch_poll_seconds: int = 3
    watch_idle_seconds: int = 0
    ssl_verify: bool = True


def ensure_config_file() -> Path:
    """Create register.ini from template if missing."""
    if CONFIG_FILE.exists():
        return CONFIG_FILE
    if TEMPLATE_FILE.exists():
        shutil.copy2(TEMPLATE_FILE, CONFIG_FILE)
        log.warning(
            "Created '%s' from template — please set Telegram BOT_TOKEN and CHANNEL.",
            CONFIG_FILE.name,
        )
        return CONFIG_FILE
    log.error("Missing '%s' and '%s'", CONFIG_FILE.name, TEMPLATE_FILE.name)
    sys.exit(1)


def _find_section(parser: configparser.ConfigParser, names: tuple[str, ...]) -> str | None:
    upper = {s.upper(): s for s in parser.sections()}
    for name in names:
        if name.upper() in upper:
            return upper[name.upper()]
    return None


def _get_option(
    parser: configparser.ConfigParser,
    sections: list[str | None],
    keys: tuple[str, ...],
    fallback: str = "",
) -> str:
    for section in sections:
        if not section:
            continue
        for key in keys:
            if parser.has_option(section, key):
                return parser.get(section, key).strip()
    return fallback


def _get_int(
    parser: configparser.ConfigParser,
    sections: list[str | None],
    keys: tuple[str, ...],
    fallback: int,
) -> int:
    for section in sections:
        if not section:
            continue
        for key in keys:
            if parser.has_option(section, key):
                try:
                    return parser.getint(section, key)
                except ValueError:
                    log.warning("Invalid integer for %s.%s", section, key)
    return fallback


def _get_bool(
    parser: configparser.ConfigParser,
    sections: list[str | None],
    keys: tuple[str, ...],
    fallback: bool,
) -> bool:
    for section in sections:
        if not section:
            continue
        for key in keys:
            if parser.has_option(section, key):
                raw = parser.get(section, key).strip().lower()
                if raw in ("1", "true", "yes", "on"):
                    return True
                if raw in ("0", "false", "no", "off"):
                    return False
                log.warning("Invalid boolean for %s.%s: %r", section, key, raw)
    return fallback


def _mask_token(token: str) -> str:
    if not token or len(token) < 12:
        return "(not set)"
    return f"{token[:6]}…{token[-4:]}"


def validate_telegram(cfg: AppConfig) -> None:
    errors: list[str] = []
    if not cfg.telegram_bot or "ضع_" in cfg.telegram_bot or "YOUR_BOT" in cfg.telegram_bot.upper():
        errors.append("BOT_TOKEN / TELEGRAM_BOT is empty or still placeholder")
    if (
        not cfg.telegram_channel
        or "ضع_" in cfg.telegram_channel
        or "YOUR_CHANNEL" in cfg.telegram_channel.upper()
        or "@اسم_" in cfg.telegram_channel
    ):
        errors.append("CHANNEL / TELEGRAM_CHANNEL is empty or still placeholder")
    if "{req_id}" not in cfg.telegram_view_url:
        log.warning("VIEW_URL has no {req_id} placeholder — link may be wrong")

    if errors:
        log.error("Invalid Telegram settings in '%s':", CONFIG_FILE)
        for err in errors:
            log.error("  - %s", err)
        log.error(
            "Open '%s' in Notepad, set TELEGRAM_BOT and TELEGRAM_CHANNEL, save, then run again.",
            CONFIG_FILE,
        )
        print()
        print("=" * 50)
        print("  إعدادات تيليجرام غير مكتملة")
        print("=" * 50)
        print("  1) شغّل: 0 - تعديل الإعدادات.bat")
        print("  2) عدّل TELEGRAM_BOT و TELEGRAM_CHANNEL في register.ini")
        print("  3) احفظ الملف (Ctrl+S) ثم أغلق Notepad")
        print("  4) شغّل: 2 - اختبار تيليجرام.bat للتأكد")
        print("=" * 50)
        sys.exit(1)


def load_config(ini_path: Path | None = None, *, require_telegram: bool = True) -> AppConfig:
    ini_path = Path(ini_path) if ini_path else CONFIG_FILE
    if ini_path == CONFIG_FILE:
        ensure_config_file()

    if not ini_path.exists():
        log.error("Config file not found: %s", ini_path)
        sys.exit(1)

    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding="utf-8")

    telegram_sec = _find_section(parser, ("TELEGRAM",))
    settings_sec = _find_section(parser, ("SETTINGS", "Settings"))
    sections = [telegram_sec, settings_sec]

    if not telegram_sec and not settings_sec:
        log.error("No [TELEGRAM] or [SETTINGS] section in '%s'", ini_path)
        sys.exit(1)

    cfg = AppConfig(
        telegram_bot=_get_option(parser, sections, _BOT_KEYS),
        telegram_channel=normalize_chat_id(
            _get_option(parser, sections, _CHANNEL_KEYS)
        ),
        telegram_view_url=_get_option(
            parser,
            sections,
            _VIEW_URL_KEYS,
            fallback=AppConfig.telegram_view_url,
        ),
        sleep_delay=_get_int(parser, sections, ("SLEEP",), 3),
        cases_folder=str(
            resolve_data_path(
                _get_option(parser, sections, ("CASES_FOLDER",), fallback="register_cases")
            )
        ),
        finished_folder=str(
            resolve_data_path(
                _get_option(parser, sections, ("FINISHED_FOLDER",), fallback="register_finished")
            )
        ),
        error_images_folder=str(
            resolve_data_path(
                _get_option(
                    parser, sections, ("ERROR_IMAGES_FOLDER",), fallback="error_images"
                )
            )
        ),
        threads_count=_get_int(parser, sections, ("THREADS_COUNT",), 4),
        watch_poll_seconds=_get_int(
            parser, sections, ("WATCH_POLL_SECONDS", "POLL_SECONDS"), 3
        ),
        watch_idle_seconds=_get_int(
            parser, sections, ("WATCH_IDLE_SECONDS", "IDLE_SECONDS"), 0
        ),
        ssl_verify=_get_bool(parser, sections, ("SSL_VERIFY",), True),
    )

    log.info("Config file: %s", ini_path.resolve())
    log.info(
        "Telegram: channel=%s | bot=%s",
        cfg.telegram_channel or "(empty)",
        _mask_token(cfg.telegram_bot),
    )
    log.info(
        "Folders: cases='%s' | finished='%s' | errors='%s' | threads=%d",
        cfg.cases_folder,
        cfg.finished_folder,
        cfg.error_images_folder,
        cfg.threads_count,
    )

    if require_telegram:
        validate_telegram(cfg)

    return cfg


def load_telegram_only() -> tuple[str, str, str, bool]:
    """For TestTelegram.exe — bot token, channel id, view URL, ssl_verify."""
    cfg = load_config(require_telegram=True)
    return cfg.telegram_bot, cfg.telegram_channel, cfg.telegram_view_url, cfg.ssl_verify
