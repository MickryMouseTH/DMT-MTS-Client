# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Two cooperating Python programs for machine-health monitoring of ALPR (License Plate Recognition) client machines:

- **Client** (repo root): `MTS_Client.py` — a long-running monitoring agent. Every `TimeSleep` seconds it collects CPU/RAM/disk/uptime/folder-size/process-status metrics (plus optional ALPR-DB, ALPR-API and NTP checks), builds a JSON payload, and POSTs it to the server over HTTP Basic Auth.
- **Server** (`server/`): a FastAPI app that receives those reports and stores them in a configurable SQL backend (SQLite/MySQL/PostgreSQL/MSSQL) via SQLAlchemy.

Both sides share `LogLibrary.py` (config loading + logging). Documentation in `README.md` and `server/README.md` is written in Thai; most code comments mix Thai and English.

## Commands

### Client
```bash
pip install loguru psutil pymysql schedule requests cryptography
python3 MTS_Client.py          # first run creates MTS_Python_config.json, then re-run after editing
```

### Server
```bash
cd server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install pymysql            # add ONLY the driver for your DB_Type (or none for sqlite)

./start.sh                     # background; PID -> server.pid, stdout -> server.out
./stop.sh                      # SIGTERM then force-kill
python main.py                 # foreground; reads Host/Port/Workers from JSON config
uvicorn main:app --host 0.0.0.0 --port 8000   # alternative foreground run
```
- API docs: `http://<host>:<port>/docs`  ·  Health: `GET /health` (returns 503 if DB unreachable)
- Manual test payload: see the `curl` example in `server/README.md` §8.

There is **no test suite, linter, or build step** configured. When editing, mirror the existing style rather than introducing tooling.

## Configuration model (important)

Config is JSON-file based, not env-based. `LogLibrary.Load_Config(default_config, Program_Name)` drives it for both programs:

- The file is `<Program_Name>_config.json` (`MTS_Python_config.json` for the client, `MTS_Server_config.json` for the server), created next to the script on first run.
- On every load it **deep-merges the file over `default_config`**, so adding a new key to a `default_config` dict automatically back-fills existing config files without overwriting user edits. **To add a config option, add it to the relevant `default_config`** (`MTS_Client.py` top, `server/config.py`).
- A corrupt/unreadable config file is backed up to `.bak` and defaults are used — the app never crashes on bad config.
- **Secrets**: any config key whose name *contains* `"pass"` (case-insensitive, e.g. `auth_pass`, `API_Auth_Pass`, `password`) is auto-encrypted on disk as `ENC:...` using Fernet. The key comes from the `LOGLIB_KEY` env var; if unset, one is generated and printed once to stderr — it **must** be exported (`export LOGLIB_KEY=<key>`) or secrets become undecryptable on the next run. At runtime `config[...]` always holds decrypted plaintext. Requires the `cryptography` package (falls back to plaintext with a warning if absent).

`script_dir` (in `LogLibrary.py`) is the anchor for all config/log paths and is PyInstaller-aware (`sys.frozen`), so config and `logs/` sit next to the frozen executable when packaged. Always resolve paths against `script_dir`, not the CWD (a service may run with a different CWD).

## Architecture notes

### Client (`MTS_Client.py`)
- Entry point runs `main()` once immediately, then uses the `schedule` library: `main()` every `TimeSleep`s and `keep_alive()` every 60s, in a single-threaded `while True: schedule.run_pending()` loop wrapped in try/except so a transient error never kills the agent. Because it's single-threaded, if `main()` runs longer than `TimeSleep` the next cycle simply slips (no overlap).
- `prepare_request_body()` assembles the payload. Process liveness uses `snapshot_running_processes()` **once per cycle** — match is exact process-name OR substring-of-exe-basename. Folder walking uses a **single** `ThreadPoolExecutor` (bounded by module-level `MAX_WORKERS_IO`) doing a BFS; do **not** nest pools (a prior bug caused O(workers³) thread explosion).
- Optional checks are gated by config flags (`Check_ALPR_Enable`, `Check_ALPR_API_Enable`, `Check_NTP_Enable`) and append to the module-global `EXTRA_PROCESS_STATUS`, which is folded into the payload and then cleared each cycle.
- **Legacy compatibility**: folder payloads intentionally carry both the misspelled `fileSiteKilobyte` (kept for the old server) and correct `fileSizeKilobyte`. Preserve both.
- If `tsbId` is empty, the client reports its own `logs/` folder size as `logSizeKilobyte` instead.

### Server (`server/`)
Layered, one responsibility per module:
- `config.py` — loads JSON config, builds the SQLAlchemy `DATABASE_URL` from `DatabaseConfig.DB_Type` (blank port → per-driver default).
- `database.py` — single engine (`pool_pre_ping=True`); a missing DB driver is turned into a clear `SystemExit` with a pip hint. `get_db()` is the FastAPI session dependency.
- `models.py` — ORM: one `monitor_report` parent with child `monitor_disk` / `monitor_folder` / `monitor_process` rows (normalized, portable column types so the same schema works on all four backends).
- `schemas.py` — Pydantic v2 validation of the incoming payload; uses field aliases (camelCase wire format) and `AliasChoices` to accept both `fileSizeKilobyte` and legacy `fileSiteKilobyte`.
- `crud.py` — turns a validated `ReportIn` into ORM rows in one transaction.
- `main.py` — FastAPI app: `verify_credentials()` (constant-time Basic Auth on UTF-8 bytes), `POST {API_Path}` (201/401/422/503), `GET /health`. Tables are auto-created on startup when `Auto_Create_Tables=1` (the **database itself** must already exist).

### Shared LogLibrary
`server/LogLibrary.py` is a **copy** of the root `LogLibrary.py` so `server/` is self-contained (its own config + `logs/`). **If you change the root `LogLibrary.py`, copy it over the server one too**, or the two will drift.

### Client ↔ server contract
The client's `url`/`auth_user`/`auth_pass` must point at the server's `API_Path` with credentials matching `API_Auth_User`/`API_Auth_Pass`. The payload shape produced by `prepare_request_body()` is the single source of truth for `schemas.py` — changing one requires updating the other.
