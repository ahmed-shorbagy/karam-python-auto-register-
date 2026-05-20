@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo.
echo Installing Chromium for Playwright...
python -m playwright install chromium
if errorlevel 1 goto fail
echo.
echo Creating folders...
if not exist "register_cases" mkdir "register_cases"
if not exist "register_finished" mkdir "register_finished"
echo.
echo Done. Edit register.ini then run TEST_TELEGRAM.bat
pause
exit /b 0
:fail
echo Installation failed.
pause
exit /b 1
