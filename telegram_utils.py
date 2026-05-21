"""Telegram API helpers — normalize chat IDs and verify bot access before send."""
from __future__ import annotations

import re

import aiohttp

_GET_ME = "https://api.telegram.org/bot{token}/getMe"
_GET_CHAT = "https://api.telegram.org/bot{token}/getChat"
_SEND = "https://api.telegram.org/bot{token}/sendMessage"

_MINUS_CHARS = ("\u2212", "\u2013", "\u2014", "\u2010", "\u2011", "\uFE63", "\uFF0D")


def normalize_chat_id(raw: str) -> str:
    """Clean channel/group IDs pasted from Telegram or Notepad."""
    value = raw.strip()
    for ch in _MINUS_CHARS:
        value = value.replace(ch, "-")
    value = value.replace(" ", "").replace("\u200e", "").replace("\u200f", "")
    if not value or value.startswith("@"):
        return value

    digits = value.lstrip("-")
    if not digits.isdigit():
        return value

    if value.startswith("-100"):
        return value

    # Common mistake: pasted id without -100 prefix (e.g. 2425490930)
    if not value.startswith("-"):
        return f"-100{digits}"

    # Legacy group id -2425490930 → supergroup/channel -1002425490930
    if re.fullmatch(r"-\d{9,11}", value):
        return f"-100{digits}"

    return value


async def verify_bot_channel_access(
    session: aiohttp.ClientSession,
    bot_token: str,
    chat_id: str,
) -> tuple[bool, str]:
    """Return (ok, message) — checks token and that this bot can see the channel."""
    chat_id = normalize_chat_id(chat_id)

    async with session.get(_GET_ME.format(token=bot_token)) as resp:
        me_body = await resp.json(content_type=None)
    if not me_body.get("ok"):
        desc = me_body.get("description", "unknown error")
        return False, f"توكن البوت غير صحيح: {desc}"

    bot_user = me_body["result"].get("username") or "?"
    bot_label = f"@{bot_user}" if bot_user != "?" else me_body["result"].get("first_name", "البوت")

    async with session.post(
        _GET_CHAT.format(token=bot_token),
        json={"chat_id": chat_id},
    ) as resp:
        chat_body = await resp.json(content_type=None)

    if chat_body.get("ok"):
        title = chat_body["result"].get("title") or chat_id
        return True, f"البوت {bot_label} متصل بالقناة «{title}» ({chat_id})"

    desc = str(chat_body.get("description", "")).lower()
    if "chat not found" in desc:
        return False, (
            f"البوت {bot_label} لا يرى القناة {chat_id}.\n"
            "\n"
            "السبب الأغلب: BOT_TOKEN و CHANNEL لا ينتميان لنفس الإعداد:\n"
            "  • BOT_TOKEN = توكن بوت مُضاف كمشرف على القناة\n"
            "  • CHANNEL = معرف نفس القناة (للخاصة: -100...)\n"
            "\n"
            "لا تخلط توكن بوتك مع معرف قناة عميل آخر.\n"
            "أضف هذا البوت مشرفاً على القناة ثم أعد الاختبار."
        )

    return False, f"خطأ Telegram ({chat_body.get('error_code', '?')}): {chat_body.get('description', desc)}"


async def send_channel_message(
    session: aiohttp.ClientSession,
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    disable_web_page_preview: bool = True,
) -> tuple[int, str]:
    chat_id = normalize_chat_id(chat_id)
    async with session.post(
        _SEND.format(token=bot_token),
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        },
    ) as resp:
        return resp.status, await resp.text()
