"""Reliable HTTPS for Telegram API — bundled CA certs + antivirus/proxy fallback."""
from __future__ import annotations

import ssl
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp
import certifi

T = TypeVar("T")

_SSL_ERRORS = (
    aiohttp.ClientConnectorCertificateError,
    aiohttp.ClientSSLError,
    ssl.SSLError,
)


_ssl_fallback_announced = False


def _ssl_context(verify: bool) -> ssl.SSLContext | bool:
    if not verify:
        return False
    return ssl.create_default_context(cafile=certifi.where())


def create_http_session(*, verify_ssl: bool = True) -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(ssl=_ssl_context(verify_ssl))
    return aiohttp.ClientSession(connector=connector)


def is_ssl_certificate_error(exc: BaseException) -> bool:
    if isinstance(exc, _SSL_ERRORS):
        return True
    msg = str(exc).lower()
    return "certificate verify failed" in msg or "sslcertverificationerror" in msg


def format_ssl_help() -> str:
    return (
        "فشل الاتصال الآمن بـ Telegram (SSL).\n"
        "\n"
        "السبب الأغلب على جهاز العميل:\n"
        "  • برنامج حماية (Antivirus) يفحص اتصالات HTTPS\n"
        "  • شبكة شركة أو بروكسي\n"
        "\n"
        "الحل:\n"
        "  1) عطّل «فحص HTTPS / SSL Scanning» في برنامج الحماية\n"
        "  2) أو أضف في register.ini تحت [SETTINGS]:\n"
        "       SSL_VERIFY = 0\n"
        "     ثم احفظ وأعد الاختبار"
    )


async def run_with_http_session(
    operation: Callable[[aiohttp.ClientSession], Awaitable[T]],
    *,
    verify_ssl: bool = True,
    allow_insecure_fallback: bool = True,
) -> T:
    """Run an HTTP operation; retry without SSL verify if antivirus breaks certificates."""
    global _ssl_fallback_announced
    session = create_http_session(verify_ssl=verify_ssl)
    try:
        return await operation(session)
    except Exception as exc:
        if (
            verify_ssl
            and allow_insecure_fallback
            and is_ssl_certificate_error(exc)
        ):
            if not _ssl_fallback_announced:
                print(
                    "\nتنبيه: تم تجاوز فحص SSL تلقائياً "
                    "(برنامج حماية أو شبكة على الجهاز).\n"
                )
                _ssl_fallback_announced = True
            fallback = create_http_session(verify_ssl=False)
            try:
                return await operation(fallback)
            finally:
                await fallback.close()
        if is_ssl_certificate_error(exc):
            raise RuntimeError(format_ssl_help()) from exc
        raise
    finally:
        await session.close()
