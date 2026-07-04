@echo off
REM ==========================================================================
REM  Build MTS_Client into a single self-contained .exe with PyInstaller.
REM
REM      Build.bat
REM
REM  The result is written to  dist\MTS_Client.exe
REM  On first run the program creates, NEXT TO the executable:
REM    - MTS_Python_config.json  (edit url / auth_user / auth_pass, then re-run)
REM    - MTS_Python.key          (encryption key for secrets - back this up!)
REM    - logs\                   (rotating log files)
REM ==========================================================================
setlocal enabledelayedexpansion

REM Always run from the directory containing this script.
cd /d "%~dp0"

set "APP_NAME=MTS_Client"
set "ENTRY=MTS_Client.py"

REM Prefer a local virtualenv if present, else fall back to python on PATH.
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
echo Using Python: %PY%

echo Installing/updating build dependencies...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install --upgrade pyinstaller loguru psutil pymysql schedule requests cryptography
if errorlevel 1 goto :error

REM Clean previous build artifacts for a reproducible build.
if exist build rmdir /s /q build
if exist "dist\%APP_NAME%.exe" del /q "dist\%APP_NAME%.exe"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo Building %APP_NAME% (--onefile)...
"%PY%" -m PyInstaller ^
    --onefile ^
    --clean ^
    --noconfirm ^
    --name "%APP_NAME%" ^
    --hidden-import=pymysql ^
    --hidden-import=pymysql.cursors ^
    --hidden-import=schedule ^
    --collect-submodules=cryptography ^
    "%ENTRY%"
if errorlevel 1 goto :error

echo.
echo Done. Executable: dist\%APP_NAME%.exe
echo Copy it to the target machine and run it once to generate the config, then
echo edit MTS_Python_config.json (url / auth_user / auth_pass) and run it again.
goto :eof

:error
echo.
echo BUILD FAILED. See the messages above.
exit /b 1
