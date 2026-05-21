@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0KaramaStart.exe" (
    echo.
    echo خطأ: KaramaStart.exe غير موجود.
    echo فك ضغط الـ ZIP كاملاً ثم شغّل من المجلد المُستخرج.
    echo.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   تشغيل برنامج حجز كرامة
echo ==================================================
echo.
echo تأكد من:
echo   - إعدادات تيليجرام في register.ini ^(ملف 0^)
echo   - ملفات .xml داخل مجلد register_cases
echo.
echo للإيقاف أثناء التشغيل: Ctrl+C
echo بعد الانتهاء يُغلق البرنامج تلقائياً.
echo.
echo جاري التشغيل...
echo.

"%~dp0KaramaStart.exe"
set "ERR=%ERRORLEVEL%"

if "%ERR%"=="0" goto :done

echo.
echo ==================================================
echo   توقف البرنامج بخطأ ^(كود %ERR%^)
echo ==================================================
echo.
if "%ERR%"=="1" (
    echo السبب الأغلب: إعدادات تيليجرام غير مكتملة.
    echo   1^) شغّل: 0 - تعديل الإعدادات.bat
    echo   2^) عدّل TELEGRAM_BOT و TELEGRAM_CHANNEL واحفظ
    echo   3^) شغّل: 2 - اختبار تيليجرام.bat
    echo.
)
echo للتفاصيل افتح: automation.log
echo.
pause
exit /b %ERR%

:done
echo.
echo انتهى التشغيل بنجاح.
timeout /t 5 >nul
exit /b 0

