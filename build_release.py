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
    for folder in ("register_cases", "register_finished"):
        (target / folder).mkdir(exist_ok=True)

    ini_src = ROOT / "register.ini"
    if ini_src.exists():
        shutil.copy2(ini_src, target / "register.ini")
    else:
        shutil.copy2(ROOT / "register.ini.template", target / "register.ini")

    shutil.copy2(ROOT / "sample_case.txt", target / "sample_case.txt")
    shutil.copy2(ROOT / "دليل_المستخدم.txt", target / "دليل_المستخدم.txt")

    readme = target / "اقرأني.txt"
    readme.write_text(
        "برنامج حجز كرامة\n"
        "================\n\n"
        "1) افتح ملف: دليل_المستخدم.txt\n"
        "2) ضع ملفات الحالات في مجلد: register_cases\n"
        "3) شغّل: KaramaStart.exe\n"
        "4) لاختبار تيليجرام فقط: TestTelegram.exe\n\n"
        "لا تحذف مجلد browsers\n",
        encoding="utf-8",
    )

    start = target / "KaramaStart.exe"
    test = target / "TestTelegram.exe"
    if start.exists():
        shutil.copy2(start, target / "1 - تشغيل البرنامج.exe")
    if test.exists():
        shutil.copy2(test, target / "2 - اختبار تيليجرام.exe")


def make_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(source_dir.rglob("*")):
            if file.is_file():
                arcname = file.relative_to(source_dir.parent)
                zf.write(file, arcname)
    print(f"ZIP created: {zip_path} ({zip_path.stat().st_size // (1024 * 1024)} MB approx)")


def main() -> None:
    print("=== Building Karama customer package ===\n")

    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "karama.spec"])
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "TestTelegram",
        "--hidden-import", "app_paths",
        "--hidden-import", "notify_format",
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
