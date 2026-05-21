"""Parse Karama server response text from lblMsg and post-submit page banners."""
from __future__ import annotations

import re

REQUEST_ID_PATTERN = re.compile(r"(\d{4,})")

_FAILURE = ("خطأ", "غير صحيح", "فشل")
_ALREADY = ("مسجل", "موجود", "طلب مسجل", "انتظار تحديد موعد")
_SUCCESS = (
    "تم",
    "نجاح",
    "بنجاح",
    "حفظ",
    "طباعة الاستمارات",
    "الاستمارات",
    "الموعد المحدد",
    "الالتزام بالموعد",
    "تجهيز الابحاث",
    "الابحاث المطلوبه",
    "الابحاث المطلوبة",
)

# Red banner after successful booking — often NOT written to lblMsg.
POST_SUBMIT_SUCCESS_MARKERS = (
    "يجب طباعة الاستمارات",
    "تجهيز الابحاث المطلوب",
    "الالتزام بالموعد المحدد",
)


def detect_post_submit_success(text: str) -> bool:
    """True when the page shows the post-registration instruction banner."""
    msg = text or ""
    if "يجب طباعة الاستمارات" in msg:
        return True
    if "تجهيز الابحاث" in msg and "الموعد المحدد" in msg:
        return True
    return False


def parse_server_message(text: str) -> str | None:
    """
    Return request id, 'OK', 'ALREADY_REGISTERED', or None if failed/unknown.

    None means the automation should treat the submission as failed unless
    the caller re-checks the full page body.
    """
    msg = (text or "").strip()
    if not msg:
        return None

    if any(kw in msg for kw in _FAILURE):
        return None

    if any(kw in msg for kw in _ALREADY):
        return "ALREADY_REGISTERED"

    match = REQUEST_ID_PATTERN.search(msg)
    if match:
        return match.group(1)

    if detect_post_submit_success(msg):
        return "OK"

    if any(kw in msg for kw in _SUCCESS):
        return "OK"

    return None
