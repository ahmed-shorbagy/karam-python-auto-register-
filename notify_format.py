"""Telegram message formatting (shared by main app and test tool)."""
from __future__ import annotations

import re

# Legacy URL from the old working bot (real reqId only — not for tests)
DEFAULT_VIEW_URL = "http://www.smcegy.com/Karama/ViewAll.aspx?reqId={req_id}"

_VALID_REQ_ID = re.compile(r"^\d{4,}$")


def is_valid_request_id(req_id: str | None) -> bool:
    if not req_id:
        return False
    rid = str(req_id).strip()
    if rid in ("0", "OK"):
        return False
    return bool(_VALID_REQ_ID.match(rid))


def format_view_url(req_id: str | None, template: str = DEFAULT_VIEW_URL) -> str:
    """Return view URL only for a real numeric request ID (never for tests or placeholders)."""
    if not is_valid_request_id(req_id):
        return ""
    return template.format(req_id=str(req_id).strip())


def build_success_message(
    *,
    start_time: str,
    full_name: str,
    ssn: str,
    phone: str,
    case_type: str,
    note: str,
    req_id: str | None = None,
    view_url_template: str = DEFAULT_VIEW_URL,
    is_test: bool = False,
) -> str:
    view_url = "" if is_test else format_view_url(req_id, view_url_template)

    lines = [
        "🟢 تم حجز حاله كرامة",
        f"وقت بدا العملية: {start_time}",
        f"الاسم: {full_name}",
        f"رقم البطاقة: {ssn}",
        f"رقم الموبيل: {phone}",
        f"طلب الحاله: {case_type}",
    ]
    if view_url:
        lines.append(view_url)
    lines.append(f"ملاحظه: {note}")
    return "\n".join(lines)
