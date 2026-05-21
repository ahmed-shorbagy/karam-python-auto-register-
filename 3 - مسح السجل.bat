@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==================================================
echo   مسح سجل الحالات (processed_state.json)
echo ==================================================
echo.
echo يستخدم إذا أردت إعادة محاولة حالة سبق تسجيلها.
echo.

if exist "%~dp0processed_state.json" (
    del /f "%~dp0processed_state.json"
    echo تم مسح السجل.
) else (
    echo لا يوجد سجل — لا شيء للمسح.
)

echo.
pause
