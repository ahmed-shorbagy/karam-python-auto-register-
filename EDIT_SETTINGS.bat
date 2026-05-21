@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "INI=%~dp0register.ini"
set "TPL=%~dp0register.ini.template"

echo.
echo ==================================================
echo   تعديل إعدادات تيليجرام - register.ini
echo ==================================================
echo.
echo المجلد: %~dp0
echo.

if not exist "%INI%" (
    if exist "%TPL%" (
        copy /Y "%TPL%" "%INI%" >nul
        if errorlevel 1 (
            echo خطأ: تعذر إنشاء register.ini
            echo.
            echo يجب فك ضغط الـ ZIP كاملاً إلى مجلد ^(مثل سطح المكتب^)
            echo ولا تشغّل الملفات من داخل نافذة الـ ZIP.
            echo.
            pause
            exit /b 1
        )
        echo تم إنشاء register.ini من القالب.
    ) else (
        echo خطأ: لم يُعثر على register.ini
        echo.
        echo 1^) فك ضغط KaramaAutomation.zip كاملاً
        echo 2^) افتح المجلد المُستخرج وليس داخل الـ ZIP
        echo 3^) شغّل هذا الملف مرة أخرى
        echo.
        pause
        exit /b 1
    )
)

echo سيفتح Notepad الآن.
echo.
echo عدّل في الملف:
echo   BOT_TOKEN = توكن البوت من BotFather
echo   CHANNEL   = @قناتك أو -100xxxxxxxxxx
echo.
echo ثم احفظ: Ctrl+S  وأغلق Notepad.
echo.
pause

notepad.exe "%INI%"

echo.
if exist "%INI%" (
    echo تم إغلاق Notepad. إذا حفظت الملف، شغّل:
    echo   2 - اختبار تيليجرام.bat
) else (
    echo تحذير: register.ini غير موجود في هذا المجلد.
)
echo.
pause
