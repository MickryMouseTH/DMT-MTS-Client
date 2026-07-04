#!/usr/bin/env bash
#
# Build MTS_Client into a single self-contained executable with PyInstaller.
#
#   ./Build.sh
#
# The result is written to  dist/MTS_Client  (dist/MTS_Client.exe on Windows).
# On first run the program creates, NEXT TO the executable:
#   - MTS_Python_config.json   (edit url / auth_user / auth_pass, then re-run)
#   - MTS_Python.key           (encryption key for secrets — back this up!)
#   - logs/                    (rotating log files)
#
set -euo pipefail

# Always run from the directory containing this script.
cd "$(dirname "$0")"

APP_NAME="MTS_Client"
ENTRY="MTS_Client.py"

# Prefer a local virtualenv if present, else fall back to python3/python.
if [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="$(command -v python3 || command -v python)"
fi
echo "Using Python: $PY"

# Make sure the runtime dependencies and PyInstaller are available.
echo "Installing/updating build dependencies..."
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install --upgrade pyinstaller loguru psutil pymysql schedule requests cryptography

# Clean previous build artifacts for a reproducible build.
rm -rf build "dist/$APP_NAME" "dist/$APP_NAME.exe" "$APP_NAME.spec"

echo "Building $APP_NAME (--onefile)..."
"$PY" -m PyInstaller \
    --onefile \
    --clean \
    --noconfirm \
    --name "$APP_NAME" \
    --hidden-import=pymysql \
    --hidden-import=pymysql.cursors \
    --hidden-import=schedule \
    --collect-submodules=cryptography \
    "$ENTRY"

echo
echo "Done. Executable: dist/$APP_NAME"
echo "Copy it to the target machine and run it once to generate the config, then"
echo "edit MTS_Python_config.json (url / auth_user / auth_pass) and run it again."
