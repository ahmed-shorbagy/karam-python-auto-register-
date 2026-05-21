"""
Build customer ZIP package (no Python required on customer PC).

Run once on your development machine:
    pip install -r requirements.txt
    pip install pyinstaller
    python -m playwright install chromium
    python build_release.py

Output:
    release/KaramaAutomation/   — folder to zip and deliver
    release/KaramaAutomation.zip
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELEASE_DIR = ROOT / "release"
PACKAGE_DIR = RELEASE_DIR / "KaramaAutomation"
DIST_DIR = ROOT / "dist" / "KaramaAutomation"

# Arabic shortcuts only (no duplicate English copies)
CUSTOMER_BATS = [
    ("EDIT_SETTINGS.bat", "0 - تعديل الإعدادات.bat"),
    ("1 - تشغيل البرنامج.bat", "1 - تشغيل البرنامج.bat"),
    ("2 - اختبار تيليجرام.bat", "2 - اختبار تيليجرام.bat"),
    ("3 - مسح السجل.bat", "3 - مسح السجل.bat"),
]


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def copy_chromium_browsers(target: Path) -> None:
    local_app = os.environ.get("LOCALAPPDATA", "")
    if not local_app:
        raise RuntimeError("LOCALAPPDATA not set — cannot find Playwright browsers")

    src_root = Path(local_app) / "ms-playwright"
    if not src_root.is_dir():
        raise RuntimeError(
            "Playwright browsers not installed. Run: python -m playwright install chromium"
        )

    dest = target / "browsers"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    copied = 0
    for item in src_root.iterdir():
        if item.is_dir() and item.name.startswith("chromium"):
            shutil.copytree(item, dest / item.name)
            copied += 1
            print(f"Copied browser: {item.name}")

    if copied == 0:
        raise RuntimeError(f"No chromium folder found in {src_root}")


def write_customer_files(target: Path) -> None:
    folder_notes = {
        "register_cases": (
            "_اقرأني.txt",
            "مجلد ملفات الحالات\r\n"
            "==================\r\n\r\n"
            "• ضع كل ملفات .xml هنا (ملف واحد لكل شخص)\r\n"
            "• لا تضع sample_case.txt هنا — هو مثال فقط في المجلد الرئيسي\r\n"
            "• شغّل: 1 - تشغيل البرنامج.bat\r\n"
            "• بعد النجاح ينتقل الملف إلى register_finished\r\n",
        ),
        "register_finished": (
            "_اقرأني.txt",
            "مجلد الحالات المنتهية\r\n"
            "====================\r\n\r\n"
            "• الملفات تنتقل هنا تلقائياً بعد الحجز الناجح\r\n"
            "• لا تحذف هذا المجلد\r\n",
        ),
        "error_images": (
            "_اقرأني.txt",
            "مجلد صور الأخطاء\r\n"
            "=================\r\n\r\n"
            "• عند فشل حالة تُحفظ صورة الخطأ هنا\r\n"
            "• الملف الأصلي يبقى في register_cases لإعادة المحاولة\r\n",
        ),
    }

    for folder, (note_name, note_text) in folder_notes.items():
        folder_path = target / folder
        folder_path.mkdir(exist_ok=True)
        (folder_path / note_name).write_text(note_text, encoding="utf-8")

    shutil.copy2(ROOT / "register.ini.template", target / "register.ini.template")
    customer_ini = ROOT / "register_customer.ini"
    if customer_ini.exists():
        shutil.copy2(customer_ini, target / "register.ini")
    else:
        shutil.copy2(ROOT / "register.ini.template", target / "register.ini")
    shutil.copy2(ROOT / "sample_case.txt", target / "sample_case.txt")
    shutil.copy2(ROOT / "دليل_المستخدم.txt", target / "دليل_المستخدم.txt")
    shutil.copy2(ROOT / "فك_الضغط_أولاً.txt", target / "فك_الضغط_أولاً.txt")
    vbs = ROOT / "OPEN_REGISTER_INI.vbs"
    if vbs.exists():
        shutil.copy2(vbs, target / "0 - تعديل الإعدادات.vbs")

    for src_name, dest_name in CUSTOMER_BATS:
        src = ROOT / src_name
        if src.exists():
            shutil.copy2(src, target / dest_name)

    readme = target / "اقرأني.txt"
    readme.write_text(
        "برنامج حجز كرامة\n"
        "================\n\n"
        "⚠️ فك ضغط الـ ZIP كاملاً إلى مجلد قبل أي تشغيل!\n"
        "   (اقرأ: فك_الضغط_أولاً.txt)\n\n"
        "✓ register.ini جاهز بإعدادات تيليجرام — لا تحتاج تعديلاً إلا إذا غيّرت البوت أو القناة.\n\n"
        "المجلدات:\n"
        "  register_cases     ← ضع ملفات .xml هنا\n"
        "  register_finished  ← الملفات بعد الحجز الناجح\n"
        "  error_images       ← صور الأخطاء\n\n"
        "1) 2 - اختبار تيليجرام.bat   → تأكد أن الإشعار يصل\n"
        "2) ضع ملفات .xml في: register_cases\n"
        "3) 1 - تشغيل البرنامج.bat    → بدء الحجز\n\n"
        "لتعديل الإعدادات: 0 - تعديل الإعدادات.bat\n\n"
        "ملفات داخلية (لا تحذف):\n"
        "  KaramaStart.exe, TestTelegram.exe, browsers, _internal\n\n"
        "لا تحذف مجلد browsers\n",
        encoding="utf-8",
    )


def make_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            rel = path.relative_to(source_dir.parent)
            if path.is_file():
                zf.write(path, rel)
            elif path.is_dir():
                # Preserve empty folders in the ZIP
                zf.writestr(str(rel).replace("\\", "/") + "/", "")
    size_mb = zip_path.stat().st_size // (1024 * 1024)
    print(f"ZIP created: {zip_path} ({size_mb} MB approx)")


def main() -> None:
    print("=== Building Karama customer package ===\n")

    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "karama.spec"])
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "TestTelegram",
        "--hidden-import", "app_paths",
        "--hidden-import", "notify_format",
        "--hidden-import", "config_loader",
        "--hidden-import", "telegram_utils",
        "--hidden-import", "http_client",
        "--hidden-import", "certifi",
        "test_telegram.py",
    ])

    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    shutil.copytree(DIST_DIR, PACKAGE_DIR)

    test_exe = ROOT / "dist" / "TestTelegram.exe"
    if test_exe.exists():
        shutil.copy2(test_exe, PACKAGE_DIR / "TestTelegram.exe")

    print("\nCopying Chromium (may take a minute)...")
    copy_chromium_browsers(PACKAGE_DIR)

    print("\nAdding customer files...")
    write_customer_files(PACKAGE_DIR)

    RELEASE_DIR.mkdir(exist_ok=True)
    zip_path = RELEASE_DIR / "KaramaAutomation.zip"
    make_zip(PACKAGE_DIR, zip_path)

    print("\n=== DONE ===")
    print(f"Deliver to customer: {zip_path}")
    print(f"Or folder: {PACKAGE_DIR}")


if __name__ == "__main__":
    main()
