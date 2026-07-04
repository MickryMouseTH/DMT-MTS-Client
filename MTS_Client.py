from concurrent.futures import ThreadPoolExecutor, as_completed
from LogLibrary import Loguru_Logging, Load_Config, script_dir
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta, timezone
import multiprocessing
import pymysql.cursors
import platform
import schedule
import requests
import hashlib
import pymysql
import psutil
import base64
import socket
import struct
import time
import json
import sys
import os

# ----------------------- Configuration Values -----------------------
Program_Name = "MTS_Python"        # Program name for identification and logging.
Program_Version = "3.9"            # Program version used for file naming and logging.
# ---------------------------------------------------------------------

default_config = {
    "url": "",                # API endpoint URL.
    "auth_user": "",          # API authentication username.
    "auth_pass": "",          # API authentication password.
    "tsbId": "",              # Optional identifier; if not provided, log folder size will be used.
    "deviceName": "",         # Device name.
    "folders": [""],          # List of folder paths to process.
    "process": [              # List of processes to monitor.
        {
            "processName": "",   # Display name of the process.
            "processApp": ""     # Actual process name to check if running.
        }
    ],
    "DatabaseConfig":
                {
                    "host":"",
                    "user":"",
                    "password":"",
                    "databaseName":"",
                    "dataCheck":[
                        {"LaneName":"","CheckHours": 1},
                        {"LaneName":"","CheckHours": 1}
                    ]
                },
    "image_path": "",         # Path to the image file for ALPR API.
    "image_url": "",          # URL for the ALPR API endpoint.
    "Global_NTP": "pool.ntp.org",  # Global NTP server address.
    "Local_NTP": "time.google.com",  # Local NTP server address.
    "NTP_Threshold_Seconds": 1,  # Maximum allowed time difference in seconds.
    "Check_ALPR_Enable": 0,   # Set to 1 to enable ALPR check.
    "Check_ALPR_API_Enable": 0,      # Set to 1 to enable ALPR API check.
    "Check_NTP_Enable": 0,   # Set to 1 to enable NTP check.
    "Log_Console": 1,  # Set to "true" to enable console logging.
    "RamOffset": 0,           # Optional RAM offset to subtract from reported usage.
    "TimeSleep": 30,          # Interval (in seconds) between scheduled tasks.
    "log_Level": "DEBUG",
    "log_Backup": 90,         # Log retention **days**.
    "Log_Size": "10 MB",      # Maximum log file size before rotation.
    "http_timeout_sec": 10,
    "http_retries": 2
}

config = Load_Config(default_config, Program_Name)
logger = Loguru_Logging(config, Program_Name, Program_Version)

# Cache the CPU count once and derive an I/O worker cap. Defined at module
# level (not inside __main__) so every function that references MAX_WORKERS_IO
# works even when the module is imported or unit-tested.
CPU_COUNT = os.cpu_count() or 1
MAX_WORKERS_IO = min(CPU_COUNT * 2, 32)

# Resolve once whether DEBUG-level logging is active. Python evaluates the
# f-string argument to logger.debug(...) BEFORE the call, so a debug log in a
# hot loop still pays the string-building cost even when the level is INFO.
# Guarding hot-path debug logs with `if DEBUG_ENABLED` keeps INFO runs fast:
#   - DEBUG: log every step, in full detail.
#   - INFO : only concise summaries; no expensive strings are ever built.
def _debug_enabled():
    try:
        current = logger.level(str(config.get("log_Level", "DEBUG")).strip().upper()).no
        return current <= logger.level("DEBUG").no
    except (ValueError, TypeError):
        return True  # unknown level name -> be safe and keep debug on

DEBUG_ENABLED = _debug_enabled()

EXTRA_PROCESS_STATUS = []

def get_disk_info():
    """
    Retrieve disk usage information for each disk partition, excluding loop devices and virtual filesystems.
    """
    disks_info = []
    # กำหนดประเภทอุปกรณ์/ระบบไฟล์ที่ต้องการกรองออก
    EXCLUDE_FS_TYPES = ['squashfs', 'tmpfs', 'devtmpfs', 'fuse.gvfsd-fuse']
    # กรอง loop devices, CD/DVD drives, และอุปกรณ์เสมือนที่ไม่ได้เมาท์แบบถาวร
    EXCLUDE_PREFIX = ['/dev/loop', '/dev/sr', 'tmpfs', 'udev', 'devpts', 'overlay']

    for part in psutil.disk_partitions():
        # 1. กรองระบบไฟล์เสมือนและประเภทที่ไม่ต้องการออก
        if part.fstype in EXCLUDE_FS_TYPES:
            logger.debug(f"Skipping virtual filesystem: {part.device} ({part.fstype})")
            continue
        
        # 2. กรอง Loop devices และอุปกรณ์เสมือนอื่นๆ ออกจากการตรวจสอบชื่ออุปกรณ์
        if part.device.startswith(tuple(EXCLUDE_PREFIX)):
             logger.debug(f"Skipping loop device/virtual disk: {part.device}")
             continue
        
        # กรอง Mount Point ที่ไม่จำเป็นออก (เช่น Mount Point ที่ไม่ได้เป็นโฟลเดอร์เก็บข้อมูลหลัก)
        if part.mountpoint in ['/dev', '/sys', '/proc']:
             logger.debug(f"Skipping system mount point: {part.mountpoint}")
             continue

        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            free_gb = usage.free / (1024**3)
            percent_used = usage.percent
            
            logger.debug(f"Disk {part.device}: mountpoint={part.mountpoint}, total={total_gb:.2f}GB, used={used_gb:.2f}GB, free={free_gb:.2f}GB, percentUsed={percent_used}")
            
            disks_info.append({
                "disk": part.device,
                "spaceGb": round(total_gb, 2),
                "usageGb": round(used_gb, 2),
                "freeGb":  round(free_gb, 2),
                "percentUsed": int(percent_used)
            })
        except PermissionError as e:
            logger.error(f'PermissionError accessing {part.mountpoint}: {e}')
            continue
        except Exception as e:
            # ดักจับข้อผิดพลาดอื่น ๆ เช่น OSError หาก Mount Point เข้าถึงไม่ได้
            logger.warning(f'Error processing disk partition {part.device} at {part.mountpoint}: {e}')
            continue

    # INFO: concise summary only. Full per-disk data stays at DEBUG (logged above).
    logger.info(f'Disk info collected: {len(disks_info)} partition(s)')
    if DEBUG_ENABLED:
        logger.debug(f'Disk Info (full): {disks_info}')
    return disks_info

def process_directory(directory):
    """
    Process a single directory using os.scandir.
    Returns the cumulative file size (in bytes), file count, and the list of subdirectories found.
    """
    local_size = 0
    local_count = 0
    subdirs = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    try:
                        file_size = entry.stat().st_size
                        local_size += file_size
                        local_count += 1
                    except Exception as e:
                        logger.error(f"Error getting size for file {entry.path}: {e}")
                elif entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                    # Hot path: only build the per-subdirectory message when DEBUG
                    # is actually on, so INFO runs never pay the string cost.
                    if DEBUG_ENABLED:
                        logger.debug(f"Found subdirectory: {entry.path}")
    except Exception as e:
        logger.error(f"Error scanning directory {directory}: {e}")
    return local_size, local_count, subdirs

def get_folder_info(folder_path):
    """
    Retrieve file count and total file size (in kilobytes) for a given folder.

    Walks the whole tree breadth-first using a SINGLE thread pool. Earlier
    versions nested three pools (get_folders_info -> get_folder_info ->
    process_subfolder), which spawned O(workers^3) threads on deep trees; this
    single-level walk keeps concurrency bounded to MAX_WORKERS_IO.
    """
    logger.debug(f"Start processing folder: {folder_path}")
    total_size = 0
    file_count = 0
    total_size_kb = 0.0

    try:
        directories = [folder_path]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_IO) as executor:
            while directories:
                futures = {executor.submit(process_directory, d): d for d in directories}
                directories = []
                for future in as_completed(futures):
                    try:
                        size, count, subdirs = future.result()
                        total_size += size
                        file_count += count
                        directories.extend(subdirs)
                    except Exception as e:
                        logger.error(f"Error processing directory {futures[future]}: {e}")

        total_size_kb = round(total_size / 1024, 2)
        # INFO: one concise summary line per folder (fast to write).
        logger.info(f"Folder '{folder_path}': {file_count} files, {total_size_kb} KB")
    except Exception as e:
        logger.error(f"Error processing folder {folder_path}: {e}")
    logger.debug(f"Finished processing folder: {folder_path}")
    folder_info = {
        "pathFolder": folder_path,
        "fileCount": file_count,
        "fileSiteKilobyte": total_size_kb  # คีย์เดิม (legacy, สะกดผิดไว้เพื่อความเข้ากันได้)
    }
    folder_info["fileSizeKilobyte"] = total_size_kb  # alias ใหม่ เผื่อระบบใหม่
    return folder_info

def snapshot_running_processes():
    """
    Take a one-shot snapshot of running processes.

    Returns a (names, exe_basenames) tuple of lowercased sets. Building this
    once per cycle avoids calling the expensive psutil.process_iter() syscall
    repeatedly — once per configured process — which is what the previous
    per-process check did.
    """
    names = set()
    exe_basenames = set()
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            name = (proc.info.get('name') or "").lower()
            if name:
                names.add(name)
            exe = (proc.info.get('exe') or "").lower()
            if exe:
                exe_basenames.add(os.path.basename(exe))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names, exe_basenames

def is_process_running(process_name, snapshot):
    """
    Check a process against a snapshot from snapshot_running_processes().

    Matching is identical to the original check: an exact match on the process
    name, OR the target appearing as a substring of an executable's basename.
    """
    target = (process_name or "").lower()
    if not target:
        return False
    names, exe_basenames = snapshot
    if target in names:
        return True
    return any(target in basename for basename in exe_basenames)

def check_process_running(process_name):
    """Backward-compatible single-process check (takes its own snapshot)."""
    return is_process_running(process_name, snapshot_running_processes())

def get_folders_info(folder_paths):
    """
    Collect file count and size for each configured folder.

    Folders are processed one at a time; each folder's tree walk is already
    parallelised inside get_folder_info(). Keeping this loop sequential avoids
    nesting thread pools (which previously caused thread-count explosion) while
    still using all workers for the I/O-bound directory walk.
    """
    logger.info(f"Processing folders: {folder_paths}")
    results = []
    for folder_path in folder_paths:
        if not folder_path:
            continue
        try:
            result = get_folder_info(folder_path)
            results.append(result)
            logger.debug(f"Processed folder: {folder_path} with result: {result}")
        except Exception as e:
            logger.error(f"Error processing folder {folder_path}: {e}")
    logger.debug(f"Final folders info: {results}")
    return results

def _path_birth_time(path):
    """
    Return the best available "creation" timestamp for `path`.

    Prefers the real birth time where the platform/filesystem exposes it
    (st_birthtime on Windows/macOS and newer Linux), otherwise falls back to
    the inode-change time (st_ctime) and finally the modification time.
    """
    st = os.stat(path)
    for attr in ("st_birthtime", "st_ctime"):
        ts = getattr(st, attr, None)
        if ts:
            return ts
    return st.st_mtime

def get_os_install_date():
    """
    Best-effort detection of when the OS was (most recently) installed.

    Returned as a compact "YYYYMMDD" string, or "" when it cannot be determined
    (so the caller simply omits it). Detection strategy per platform:
      - Windows: the registry value InstallDate under
        HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion. This is refreshed
        by feature upgrades, so it reflects the LATEST install/upgrade. Falls
        back to the creation time of the Windows directory (%SystemRoot%).
      - macOS  : creation time of /var/db/.AppleSetupDone (written at setup),
        falling back to the root volume's creation time.
      - Linux  : birth/creation time of a stable, install-time path
        (/lost+found is created by mkfs, a good proxy for the install date),
        falling back to /etc or /.
    """
    system = platform.system()
    try:
        if system == "Windows":
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                ) as key:
                    install_ts, _ = winreg.QueryValueEx(key, "InstallDate")
                return datetime.fromtimestamp(int(install_ts)).strftime("%Y%m%d")
            except (OSError, ValueError, ImportError) as e:
                logger.debug(f"Registry InstallDate unavailable ({e}); using Windows dir ctime.")
                win_dir = os.environ.get("SystemRoot", r"C:\Windows")
                return datetime.fromtimestamp(_path_birth_time(win_dir)).strftime("%Y%m%d")

        if system == "Darwin":
            candidates = ("/var/db/.AppleSetupDone", "/private/var/db/.AppleSetupDone", "/")
        else:
            # Linux / other POSIX
            candidates = ("/lost+found", "/etc/hostname", "/etc", "/")

        for marker in candidates:
            if os.path.exists(marker):
                ts = _path_birth_time(marker)
                if ts:
                    return datetime.fromtimestamp(ts).strftime("%Y%m%d")
    except Exception as e:
        logger.warning(f"Could not determine OS install date: {e}")
    return ""

# OS install date does not change while the agent runs, so resolve it once at
# startup instead of on every reporting cycle (keeps the hot path fast).
OS_INSTALL_DATE = get_os_install_date()
logger.debug(f"Detected OS install date: {OS_INSTALL_DATE or 'unknown'}")

def prepare_request_body(config_data, extra_processes=None):
    """
    Assemble the JSON payload with system metrics and folder information for the API.
    """
    try:
        boot_time = psutil.boot_time()
        current_time = datetime.now()
        uptime_seconds = (current_time - datetime.fromtimestamp(boot_time)).total_seconds()
        uptime_minutes = round(uptime_seconds / 60)
        logger.debug(f"Boot time: {boot_time}, Current time: {current_time}, Uptime seconds: {uptime_seconds}, Uptime minutes: {uptime_minutes}")

        # Snapshot running processes ONCE, then check each configured process
        # against it in memory (instead of re-scanning the system per process).
        process_snapshot = snapshot_running_processes()
        processes = [
            {
                "processName": proc["processName"],
                "running": is_process_running(proc["processApp"], process_snapshot)
            }
            for proc in config_data.get("process", [])
        ]
        if extra_processes:
            processes.extend(extra_processes)
        logger.debug(f"Processes info: {processes}")
        app_running = all(proc["running"] for proc in processes)
        logger.debug(f"Overall app_running status: {app_running}")

        cpu_usage = psutil.cpu_percent(interval=1)
        ram_usage = psutil.virtual_memory().percent
        logger.debug(f"CPU usage: {cpu_usage}%, RAM usage: {ram_usage}%")

        disks = get_disk_info()
        logger.debug(f"Disks info collected: {disks}")

        folders_info = get_folders_info(config_data.get("folders", []))
        logger.debug(f"Folders info collected: {folders_info}")

        # Append the OS install date (YYYYMMDD) when known, e.g.
        # "Windows-11-10.0.26200-SP0_20260114". Omitted when undetectable.
        operating_system = platform.platform()
        if OS_INSTALL_DATE:
            operating_system = f"{operating_system}_{OS_INSTALL_DATE}"
        logger.debug(f"Operating system: {operating_system}")

        request_body = {
            "requestId": "MTS" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "requestDatetime": datetime.now().isoformat(),
            "deviceName": config_data.get("deviceName", "Unknown Device"),
            "appRunning": app_running,
            "percentCpuUsage": cpu_usage,
            "percentRamUsage": max(0, min(100, ram_usage - config_data.get("RamOffset", 0))),
            "uptimeMinute": uptime_minutes,
            "disks": disks,
            "folders": folders_info,
            "process": processes,
            "operatingSystem": operating_system
        }

        if config_data.get("tsbId", ""):
            request_body["tsbId"] = config_data["tsbId"]
            logger.debug(f"tsbId provided: {config_data['tsbId']}")
        else:
            # Use an absolute path: logs live next to the script/executable, not
            # in the current working directory (which may differ under a service).
            log_dir = os.path.join(script_dir, "logs")
            log_folder_info = get_folder_info(log_dir)
            request_body["logSizeKilobyte"] = log_folder_info["fileSiteKilobyte"]
            logger.debug(f"No tsbId provided; using log folder size: {log_folder_info['fileSiteKilobyte']} KB")

        # INFO: short, fast-to-write summary of what will be sent.
        logger.info(
            f"Report ready: device={request_body['deviceName']}, "
            f"appRunning={request_body['appRunning']}, cpu={cpu_usage}%, "
            f"ram={request_body['percentRamUsage']}%, uptime={uptime_minutes}m, "
            f"disks={len(disks)}, folders={len(folders_info)}, process={len(processes)}"
        )
        # DEBUG: full payload, only built when debug is actually enabled.
        if DEBUG_ENABLED:
            logger.debug(f"Request Body (full): {request_body}")
    except Exception as e:
        logger.error(f"Error preparing request body: {e}")
        request_body = {}
    return request_body

def send_api_request(url, request_body, auth_user, auth_pass, timeout_sec=10, retries=2):
    headers = {"Content-Type": "application/json"}
    last_err = None
    for attempt in range(retries + 1):
        try:
            logger.debug(f"POST {url} (attempt {attempt + 1}/{retries + 1}, timeout={timeout_sec}s)")
            resp = requests.post(
                url, headers=headers, json=request_body,
                auth=HTTPBasicAuth(auth_user, auth_pass),
                timeout=timeout_sec
            )
            status_code = resp.status_code
            try:
                response_json = resp.json()
            except ValueError:
                response_json = {"error": "Invalid JSON response"}
            return status_code, response_json
        except requests.RequestException as e:
            last_err = e
            logger.warning(f"HTTP request failed (attempt {attempt+1}/{retries+1}): {e}")
            time.sleep(1)
    return None, {"error": str(last_err)}

def check_alpr(config):
    """
    ตรวจสอบสถานะของ ALPR และอัปเดตสถานะในตัวแปร global
    (ใช้ PyMySQL)
    """
    logger.info('Start Check ALPR with PyMySQL')
    global EXTRA_PROCESS_STATUS
    
    db_conn = None
    
    if not config:
        logger.error("Database configuration is missing.")
        return

    try:
        logger.debug("Starting connection to MySQL using PyMySQL")
        db_conn = pymysql.connect(
            host=config.get("host", ""),
            user=config.get("user", ""),
            password=config.get("password", ""),
            database=config.get("databaseName", ""),
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor
        )
        logger.debug("Connected to MySQL successfully with PyMySQL")
        
        with db_conn.cursor() as cursor:
            query = """
                SELECT p.Status_IN_OUT as LaneName,
                       MAX(p.LogDate) as MaxDate
                FROM plate p 
                WHERE p.LogDate >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                GROUP BY p.Status_IN_OUT
            """
            cursor.execute(query)
            db_results = cursor.fetchall()
            logger.debug(f'SQL Data fetched: {len(db_results)} rows')

        lanes_to_check = config.get("dataCheck", [])
        now = datetime.now()
        db_results_map = {row['LaneName']: row for row in db_results}

        for lane_config in lanes_to_check:
            lane_name = lane_config.get("LaneName", "")
            lane_Show = "ALPR " + lane_name
            check_houes = lane_config.get("CheckHours", 1)
            running_status = False

            if lane_name in db_results_map:
                max_date = db_results_map[lane_name]['MaxDate']
                threshold_date = now - timedelta(hours=check_houes)

                if max_date >= threshold_date:
                    logger.info(f"ALPR CHECK OK for Lane: {lane_name}.")
                    running_status = True
                else:
                    logger.error(f"ALPR CHECK FAILED for Lane: {lane_Show}. Last data at {max_date} is too old.")
            else:
                logger.warning(f"ALPR CHECK - Lane: {lane_Show} not found in database results.")
            
            EXTRA_PROCESS_STATUS.append({"processName": lane_Show, "running": running_status})

    except pymysql.Error as e:
        logger.error(f'An error occurred in check_alpr: {e}')
        lanes_to_check = config.get("dataCheck", [])
        for lane_config in lanes_to_check:
             lane_Show = "ALPR " + lane_config.get("LaneName", "")
             EXTRA_PROCESS_STATUS.append({"processName": lane_Show, "running": False})
    finally:
        if db_conn:
            db_conn.close()
            logger.debug("MySQL connection closed.")

    logger.debug(f"Final ALPR Status: {EXTRA_PROCESS_STATUS}")

def Check_alpr_API():
    global EXTRA_PROCESS_STATUS
    logger.info('Start Check ALPR API')
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_IO) as executor:
        future = executor.submit(send_http_request, config.get('image_path', ""), config.get('image_url', ""))
        try:
            response_text = future.result()
            if not response_text:
                logger.error("ALPR API response is None or empty.")
                EXTRA_PROCESS_STATUS.append({"processName": "ALPR API", "running": False})
                return

            result_json = json.loads(response_text)
            status = result_json.get("status", "").upper()
            if status == "OK":
                logger.info('Check ALPR API Status: OK')
                EXTRA_PROCESS_STATUS.append({"processName": "ALPR API", "running": True})
            else:
                logger.warning('ALPR API Status Not OK')
                EXTRA_PROCESS_STATUS.append({"processName": "ALPR API", "running": False})
        except json.JSONDecodeError as e:
            logger.error(f"ALPR API response parse error: {e}")
            EXTRA_PROCESS_STATUS.append({"processName": "ALPR API", "running": False})
        except Exception as e:
            logger.error(f"Unexpected error in Check_alpr_API: {e}")
            EXTRA_PROCESS_STATUS.append({"processName": "ALPR API", "running": False})

def summarize_b64(b64_str: str, max_prefix=128):
    raw = base64.b64decode(b64_str, validate=False)
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "alpr_image_prefix": b64_str[:max_prefix] + ("..." if len(b64_str) > max_prefix else ""),
        "alpr_image_len": len(b64_str),
        "alpr_image_sha256": sha,
        "note": "truncated" if len(b64_str) > max_prefix else "full"
    }

def send_http_request(image_path, url):
    """Create and send an HTTP request."""
    try:
        image_base64 = image_to_base64(image_path)
        if not image_base64:
            logger.error("Failed to convert image to Base64.")
            return None

        payload = {
            "data_type": "alpr_recognition",
            "hw_id": "a1027724-70dd-4b92-85ad-cdb0984ddd62",
            "user_id": "001",
            "os": "Win32NT",
            "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "license_plate_rec": "true",
            "alpr_image": image_base64,
            "latitude": "",
            "longitude": "",
            "country": "th",
            "Place": ""
        }

        headers = {"Content-Type": "application/json"}

        # Log a redacted summary (without the full base64 image) before sending.
        log_payload = dict(payload)
        log_payload["alpr_image_summary"] = summarize_b64(log_payload.pop("alpr_image"))
        logger.debug(f"Sending HTTP request to {url} with payload: {log_payload}")

        timeout_sec = int(config.get("http_timeout_sec", 10))
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"HTTP request failed: {e}")
        return None

def image_to_base64(image_path):
    encoded_string = None
    try:
        logger.debug(f'Convert images Path : {image_path}')
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f'Convert images : {e}')
    return encoded_string

def Check_ntp(config):
    global EXTRA_PROCESS_STATUS
    logger.info('Start Check NTP')
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_IO) as executor:
        try:
            future_global_ntp = executor.submit(get_ntp_time, config.get('Global_NTP', 'pool.ntp.org'))
            future_local_ntp  = executor.submit(get_ntp_time, config.get('Local_NTP', 'time.google.com'))

            global_ntp_time = future_global_ntp.result()
            local_ntp_time  = future_local_ntp.result()

            if global_ntp_time and local_ntp_time:
                delta = abs((local_ntp_time - global_ntp_time).total_seconds())

                if delta < config.get('NTP_Threshold_Seconds', 1):
                    logger.info(f'NTP Status OK. Time difference: {delta:.4f} seconds')
                    EXTRA_PROCESS_STATUS.append({"processName": "Time Sync", "running": True})
                else:
                    logger.warning(f'NTP Status Not OK. Time difference: {delta:.4f} seconds')
                    EXTRA_PROCESS_STATUS.append({"processName": "Time Sync", "running": False})
            else:
                logger.error("NTP Status Not OK: Could not get time from one or both servers.")
                EXTRA_PROCESS_STATUS.append({"processName": "Time Sync", "running": False})

        except Exception as e:
            logger.error(f"NTP Status Not OK. An unexpected error occurred: {e}")
            EXTRA_PROCESS_STATUS.append({"processName": "Time Sync", "running": False})

def get_ntp_time(ntp_server):
    port = 123
    buf = 1024
    address = (ntp_server, port)
    msg = b'\x1b' + 47 * b'\0'
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        client.settimeout(5)
        client.sendto(msg, address)
        msg, _ = client.recvfrom(buf)
        unpacked = struct.unpack("!12I", msg[0:48])
        transmit_timestamp = unpacked[10] + float(unpacked[11]) / 2**32
        # utcfromtimestamp() is deprecated; build a timezone-aware UTC datetime.
        ntp_time = datetime.fromtimestamp(transmit_timestamp - 2208988800, tz=timezone.utc)
        return ntp_time
    except socket.timeout:
        logger.error(f"NTP Server Fail {ntp_server}")
        return None
    except Exception as e:
        logger.error(f"NTP error ({ntp_server}): {e}")
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass

def main():
    """
    Main function that collects system metrics, prepares the JSON payload, and sends the data via API.
    """
    try:
        # 1) ตรวจ config สำคัญก่อน
        url = config.get("url","")
        if not url:
            logger.critical("API URL is not configured. Please check your config.json file.")
            return
        auth_user = config.get("auth_user","")
        if not auth_user:
            logger.critical("API auth_user is not configured. Please check your config.json file.")
            return
        auth_pass = config.get("auth_pass","")
        if not auth_pass:
            logger.critical("API auth_pass is not configured. Please check your config.json file.")
            return
        
        # 2) Run checks once at startup if enabled.
        if config.get("Check_ALPR_Enable", 0) == 1:
            logger.info("ALPR check is enabled. Running check_alpr()")
            check_alpr(config.get("DatabaseConfig"))

        if config.get("Check_ALPR_API_Enable", 0) == 1:
            logger.info("ALPR API check is enabled. Running Check_alpr_API()")
            Check_alpr_API()
        
        if config.get("Check_NTP_Enable", 0) == 1:
            logger.info("NTP check is enabled. Running Check_ntp()")
            Check_ntp(config)

        # 3) สร้าง payload (รวมสถานะจาก EXTRA_PROCESS_STATUS ปัจจุบัน)
        request_body = prepare_request_body(config, extra_processes=EXTRA_PROCESS_STATUS)

        # 4) เคลียร์ EXTRA_PROCESS_STATUS หลัง “เก็บใส่ payload” แล้ว (กันซ้ำรอบหน้า)
        EXTRA_PROCESS_STATUS.clear()

        # 4.1) ถ้าประกอบ payload ไม่สำเร็จ (เกิด exception ภายใน) จะได้ {} — ไม่ส่งเปล่า
        if not request_body:
            logger.error("Skipping send: request body is empty (failed to build payload).")
            return

        # 5) ส่ง API โดยใช้ timeout/retries จาก config (ไม่ log auth_user/auth_pass)
        timeout_sec = int(config.get("http_timeout_sec", 10))
        retries     = int(config.get("http_retries", 2))
        logger.debug(f"Main: sending report to {url} (timeout={timeout_sec}s, retries={retries})")
        status_code, response_json = send_api_request(url, request_body, auth_user, auth_pass, timeout_sec, retries)

        if status_code is None:
            logger.error(f"Send failed after retries: {response_json}")
        else:
            logger.info(f"Report sent: status={status_code}")
            logger.debug(f"Response: {response_json}")
    except Exception as e:
        logger.error(f"Error in main execution: {e}")

def keep_alive():
    """
    Log a keep-alive message to indicate that the system is active.
    """
    logger.info('Keep Alive')

if __name__ == "__main__":

    logger.debug(f"CPU_COUNT = {CPU_COUNT}, MAX_WORKERS_IO = {MAX_WORKERS_IO}")

    logger.info(f"Starting scheduled tasks every {config.get('TimeSleep',360)} seconds")
    
    # For Windows support in frozen executables.
    multiprocessing.freeze_support()

    # Run main() once immediately at startup.
    main()

    # Schedule periodic jobs.
    schedule.every(int(config.get('TimeSleep',360))).seconds.do(main)
    schedule.every(60).seconds.do(keep_alive)

    # Main loop to run pending scheduled tasks. Guard against unexpected errors
    # so a transient failure never terminates this long-running agent.
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
        time.sleep(1)
