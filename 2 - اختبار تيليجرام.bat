@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0TestTelegram.exe" (
    echo.
    echo خطأ: TestTelegram.exe غير موجود. فك ضغط الـ ZIP أولاً.
    echo.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   اختبار إرسال تيليجرام
echo ==================================================
echo.

"%~dp0TestTelegram.exe"
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
    echo.
    echo فشل الاختبار. عدّل register.ini عبر: 0 - تعديل الإعدادات.bat
    echo.
    pause
    exit /b %ERR%
)

echo.
echo نجح الاختبار.
pause
exit /b 0
