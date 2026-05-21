"""Send one test message using settings from register.ini (no fake link)."""
import asyncio
import sys
from datetime import datetime

import aiohttp

from app_paths import pause_on_error, setup_runtime
from config_loader import load_telegram_only
from notify_format import build_success_message

setup_runtime()


async def main() -> int:
    token, chat_id, view_url = load_telegram_only()

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

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
        ) as resp:
            body = await resp.text()
            print(f"HTTP {resp.status}")
            print(body)
            if resp.status == 200:
                print("\nOK: Test message sent using register.ini [TELEGRAM] settings.")
            return 0 if resp.status == 200 else 1


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    except SystemExit as exc:
        code = int(exc.code) if exc.code else 1
    except Exception as exc:
        print("ERROR:", exc)
        code = 1
    pause_on_error(code)
    sys.exit(code)
