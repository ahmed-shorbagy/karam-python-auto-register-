"""Send one test message using settings from register.ini (no fake link)."""
import asyncio
import sys
from datetime import datetime

import aiohttp

from app_paths import APP_DIR, pause_on_error, setup_runtime
from config_loader import CONFIG_FILE, load_telegram_only
from http_client import format_ssl_help, run_with_http_session
from notify_format import build_success_message
from telegram_utils import send_channel_message, verify_bot_channel_access

setup_runtime()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def main() -> int:
    token, chat_id, view_url, ssl_verify = load_telegram_only()

    print(f"ملف الإعدادات: {CONFIG_FILE}")
    print(f"مجلد البرنامج: {APP_DIR}")
    print(f"CHANNEL = {chat_id}")
    if not ssl_verify:
        print("SSL_VERIFY = 0 (بدون فحص شهادة SSL)")
    print()

    start_time = datetime.now().strftime("%H:%M:%S %d-%m-%Y")
    message = build_success_message(
        start_time=start_time,
        full_name="اختبار النظام",
        ssn="00000000000000",
        phone="01000000000",
        case_type="أمراض مزمنة",
        note="رسالة تجريبية — الرابط يظهر فقط بعد تسجيل حالة حقيقية",
        view_url_template=view_url,
        is_test=True,
    )

    async def operation(session: aiohttp.ClientSession) -> int:
        ok, info = await verify_bot_channel_access(session, token, chat_id)
        print(info)
        print()
        if not ok:
            return 1

        status, body = await send_channel_message(session, token, chat_id, message)
        print(f"HTTP {status}")
        print(body)
        if status == 200:
            print("\nOK: Test message sent using register.ini settings.")
        return 0 if status == 200 else 1

    return await run_with_http_session(
        operation,
        verify_ssl=ssl_verify,
        allow_insecure_fallback=ssl_verify,
    )


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    except SystemExit as exc:
        code = int(exc.code) if exc.code else 1
    except RuntimeError as exc:
        print("ERROR:", exc)
        code = 1
    except Exception as exc:
        print("ERROR:", exc)
        print()
        print(format_ssl_help())
        code = 1
    pause_on_error(code)
    sys.exit(code)
