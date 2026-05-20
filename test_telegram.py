"""Send one test message using settings from register.ini (no fake link)."""
import asyncio
import configparser
import sys
from datetime import datetime

import aiohttp

from app_paths import app_path, is_frozen, setup_runtime
from notify_format import build_success_message

setup_runtime()


def load_telegram_settings():
    parser = configparser.ConfigParser()
    parser.read(app_path("register.ini"), encoding="utf-8")
    section = next(s for s in parser.sections() if s.upper() == "SETTINGS")
    return (
        parser.get(section, "TELEGRAM_BOT").strip(),
        parser.get(section, "TELEGRAM_CHANNEL").strip(),
    )


async def main() -> int:
    token, chat_id = load_telegram_settings()
    if not token or "YOUR_BOT" in token:
        print("ERROR: Set TELEGRAM_BOT in register.ini")
        return 1
    if not chat_id or "YOUR_CHANNEL" in chat_id:
        print("ERROR: Set TELEGRAM_CHANNEL in register.ini")
        return 1

    start_time = datetime.now().strftime("%H:%M:%S %d-%m-%Y")
    message = build_success_message(
        start_time=start_time,
        full_name="اختبار النظام",
        ssn="00000000000000",
        phone="01000000000",
        case_type="أمراض مزمنة",
        note="رسالة تجريبية — الرابط يظهر فقط بعد تسجيل حالة حقيقية",
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
                print("\nOK: Test message sent (no link line — avoids 404 on fake reqId).")
            return 0 if resp.status == 200 else 1


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    except Exception as exc:
        print("ERROR:", exc)
    if is_frozen():
        print()
        input("Press Enter to close... ")
    sys.exit(code)
