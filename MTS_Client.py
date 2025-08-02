from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.auth import HTTPBasicAuth
from datetime import datetime,timedelta
from loguru import logger
import multiprocessing
import pymysql.cursors
import platform
import schedule
import requests
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
Program_Version = "3.2"            # Program version used for file naming and logging.
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
    "Check_ALPR_Enable": 0,   # Set to 1 to enable ALPR check.
    "Check_ALPR_API_Enable": 0,      # Set to 1 to enable ALPR API check.
    "Check_NTP_Enable": 0,   # Set to 1 to enable NTP check.
    "Log_Console_Enable": 1,  # Set to "true" to enable console logging.
    "RamOffset": 0,           # Optional RAM offset to subtract from reported usage.
    "TimeSleep": 30,          # Interval (in seconds) between scheduled tasks.
    "log_Level": "DEBUG",
    "log_Backup": 90,         # Log retention duration (number of backup files).
    "Log_Size": "10 MB"       # Maximum log file size before rotation.
}

EXTRA_PROCESS_STATUS = []

def Load_Config(default_config,Program_Name):
    # Define the configuration file path.
    config_file_path = f'{Program_Name}.config.json'

    # Create config file with default values if it does not exist.
    if not os.path.exists(config_file_path):
        default_config = default_config 
        with open(config_file_path, 'w') as new_config_file:
            json.dump(default_config, new_config_file, indent=4)

    # Load configuration
    with open(config_file_path, 'r') as config_file:
        config = json.load(config_file)
    
    return config

# ----------------------- Loguru Logging Setup -----------------------
def Loguru_Logging(config,Program_Name,Program_Version):
    logger.remove()

    log_Backup = int(config.get('log_Backup', 90))  # Default to 90 days if not set
    if log_Backup < 1:  # Ensure log retention is at least 1 day
        log_Backup = 1
    Log_Size = config.get('Log_Size', '10 MB')  # Default to 10 MB if not set
    log_Level = config.get('log_Level', 'DEBUG').upper()  # Default to DEBUG if not set

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    log_file_name = f'{Program_Name}_{Program_Version}.log'
    log_file = os.path.join(log_dir, log_file_name)

    if config.get('Log_Console_Enable',0) == 1:
        logger.add(
            sys.stdout, 
            level=log_Level, 
            format="<green>{time}</green> | <blue>{level}</blue> | <cyan>{thread.id}</cyan> | <magenta>{function}</magenta> | {message}"
        )

    logger.add(
        log_file,
        format="{time} | {level} | {thread.id} | {function} | {message}",
        level=log_Level,
        rotation=Log_Size,
        retention=log_Backup,
        compression="zip"
    )

    logger.info('-' * 117)
    logger.info(f"Start {Program_Name} Version {Program_Version}")
    logger.info('-' * 117)

    return logger

def get_disk_info():
    """
    Retrieve disk usage information for each disk partition.

    Returns:
        A list of dictionaries, each containing:
            - disk: Full device name (e.g., /dev/sda1).
            - spaceGb: Total disk space in gigabytes.
            - usageGb: Used disk space in gigabytes.
            - freeGb: Free disk space in gigabytes.
            - percentUsed: Percentage of disk space used.
    """
    disks_info = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_gb = round(usage.total / (1024**3), 2)
            used_gb = round(usage.used / (1024**3), 2)
            free_gb = round(usage.free / (1024**3), 2)
            percent_used = usage.percent
            logger.debug(f"Disk {part.device}: mountpoint={part.mountpoint}, total={total_gb}GB, used={used_gb}GB, free={free_gb}GB, percentUsed={percent_used}")
            disks_info.append({
                "disk": part.device,
                "spaceGb": int(total_gb),
                "usageGb": int(used_gb),
                "freeGb": int(free_gb),
                "percentUsed": int(percent_used)
            })
        except PermissionError as e:
            # Log error if permission is denied for a partition.
            logger.error(f'PermissionError accessing {part.mountpoint}: {e}')
            continue
    logger.info(f'Disk Info: {disks_info}')
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
                        logger.debug(f"File: {entry.path} size: {file_size} bytes")
                    except Exception as e:
                        logger.error(f"Error getting size for file {entry.path}: {e}")
                elif entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                    logger.debug(f"Found subdirectory: {entry.path}")
    except Exception as e:
        logger.error(f"Error scanning directory {directory}: {e}")
    return local_size, local_count, subdirs

def process_subfolder(subfolder_path):
    """
    Concurrently process a subfolder using breadth-first search.
    ใช้ ThreadPoolExecutor สแกนทุกโฟลเดอร์ในระดับเดียวกันพร้อมกัน
    แล้วรวมผลลัพธ์ (ขนาดไฟล์และจำนวนไฟล์) จากทุกระดับของ subdirectories
    """
    total_size = 0
    total_count = 0
    # เริ่มต้นจาก subfolder_path เป็นรายการแรกในการสแกน
    directories = [subfolder_path]
    
    with ThreadPoolExecutor(max_workers=CPU_COUNT) as executor:
        while directories:
            # ส่งงานสแกนสำหรับทุก directory ในระดับปัจจุบัน
            futures = {executor.submit(process_directory, d): d for d in directories}
            directories = []  # เตรียมรับรายการของ subdirectories จากรอบถัดไป
            for future in as_completed(futures):
                try:
                    size, count, subdirs = future.result()
                    total_size += size
                    total_count += count
                    directories.extend(subdirs)
                except Exception as e:
                    logger.error(f"Error processing subfolder {futures[future]}: {e}")
    logger.debug(f"Finished processing subfolder (optimized): {subfolder_path} with total size: {total_size} bytes and file count: {total_count}")
    return {"size": total_size, "count": total_count}

def get_folder_info(folder_path):
    """
    Retrieve file count and total file size (in kilobytes) for a given folder.
    Processes files in the folder and its subdirectories concurrently.
    """
    logger.debug(f"Start processing folder: {folder_path}")
    total_size = 0
    file_count = 0

    subfolders = []
    try:
        # สแกนไฟล์ในระดับแรกของ folder_path
        with os.scandir(folder_path) as it:
            for entry in it:
                if entry.is_file():
                    file_count += 1
                    try:
                        file_size = entry.stat().st_size
                        total_size += file_size
                        logger.debug(f"File: {entry.path} size: {file_size} bytes")
                    except Exception as e:
                        logger.error(f"Error getting size for file {entry.path}: {e}")
                elif entry.is_dir():
                    subfolders.append(entry.path)
                    logger.debug(f"Found directory: {entry.path}")

        # ประมวลผล subfolders แบบคู่ขนาน
        with ThreadPoolExecutor(max_workers=CPU_COUNT) as executor:
            future_to_subfolder = {executor.submit(process_subfolder, subfolder): subfolder for subfolder in subfolders}
            for future in as_completed(future_to_subfolder):
                try:
                    result = future.result()
                    total_size += result["size"]
                    file_count += result["count"]
                    logger.debug(f"Processed subfolder: {future_to_subfolder[future]} with result: {result}")
                except Exception as e:
                    logger.error(f"Error processing subfolder {future_to_subfolder[future]}: {e}")
        total_size_kb = round(total_size / 1024, 2)
        logger.info(f"Folder Path: {folder_path}")
        logger.info(f"File Count: {file_count}")
        logger.info(f"Total File Size (KB): {total_size_kb}")
    except Exception as e:
        logger.error(f"Error processing folder {folder_path}: {e}")
    logger.debug(f"Finished processing folder: {folder_path}")
    return {
        "pathFolder": folder_path,
        "fileCount": file_count,
        "fileSiteKilobyte": total_size_kb
    }

def check_process_running(process_name):
    """
    Check whether a process with the specified name is currently running.
    
    Args:
        process_name (str): The name of the process to search for.
    
    Returns:
        bool: True if the process is running, False otherwise.
    """
    result = any(proc.info['name'] == process_name for proc in psutil.process_iter(['name']))
    logger.debug(f"Check process running for '{process_name}': {result}")
    return result

def get_folders_info(folder_paths):
    """
    Process a list of folders concurrently to collect file count and size for each folder.
    """
    logger.info(f"Processing folders: {folder_paths}")
    max_workers = min(len(folder_paths), CPU_COUNT)
    logger.info(f"Using max_workers: {max_workers}")
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_folder = {executor.submit(get_folder_info, folder): folder for folder in folder_paths}
        for future in as_completed(future_to_folder):
            folder_path = future_to_folder[future]
            try:
                result = future.result()
                results.append(result)
                logger.info(f"Processed folder: {folder_path} with result: {result}")
            except Exception as e:
                logger.error(f"Error processing folder {folder_path}: {e}")
    logger.debug(f"Final folders info: {results}")
    return results

def prepare_request_body(config_data, extra_processes=None):
    """
    Assemble the JSON payload with system metrics and folder information for the API.
    """
    try:
        # Compute system uptime in minutes.
        boot_time = psutil.boot_time()
        current_time = datetime.now()
        uptime_seconds = (current_time - datetime.fromtimestamp(boot_time)).total_seconds()
        uptime_minutes = round(uptime_seconds / 60)
        logger.debug(f"Boot time: {boot_time}, Current time: {current_time}, Uptime seconds: {uptime_seconds}, Uptime minutes: {uptime_minutes}")

        # Gather process status information from the configuration.
        processes = [
            {
                "processName": proc["processName"],
                "running": check_process_running(proc["processApp"])
            }
            for proc in config_data.get("process", [])
        ]
        if extra_processes:
            processes.extend(extra_processes)
        logger.debug(f"Processes info: {processes}")
        app_running = all(proc["running"] for proc in processes)
        logger.debug(f"Overall app_running status: {app_running}")

        # Measure CPU and memory usage.
        cpu_usage = psutil.cpu_percent(interval=1)
        ram_usage = psutil.virtual_memory().percent
        logger.debug(f"CPU usage: {cpu_usage}%, RAM usage: {ram_usage}%")

        # Gather disks information.
        disks = get_disk_info()
        logger.debug(f"Disks info collected: {disks}")

        # Gather folders information.
        folders_info = get_folders_info(config_data.get("folders", []))
        logger.debug(f"Folders info collected: {folders_info}")

        # Operating system information.
        operating_system = platform.system() + " " + platform.release()
        logger.debug(f"Operating system: {operating_system}")

        # Build the request payload with all gathered system metrics.
        request_body = {
            "requestId": "MTS" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "requestDatetime": datetime.now().isoformat(),
            "deviceName": config_data.get("deviceName", "Unknown Device"),
            "appRunning": app_running,
            "percentCpuUsage": cpu_usage,
            "percentRamUsage": ram_usage - config.get("RamOffset", 0),  # Subtract any overhead if specified.
            "uptimeMinute": uptime_minutes,
            "disks": disks,
            "folders": folders_info,
            "process": processes,
            "operatingSystem": operating_system
        }
        logger.debug(f"Initial request_body: {request_body}")

        # Add an identifier if provided; otherwise, include log folder size.
        if config_data.get("tsbId", ""):
            request_body["tsbId"] = config_data["tsbId"]
            logger.debug(f"tsbId provided: {config_data['tsbId']}")
        else:
            log_folder_info = get_folder_info("logs")
            request_body["logSizeKilobyte"] = log_folder_info["fileSiteKilobyte"]
            logger.debug(f"No tsbId provided; using log folder size: {log_folder_info['fileSiteKilobyte']} KB")

        logger.info(f"Request Body: {request_body}")
    except Exception as e:
        logger.error(f"Error preparing request body: {e}")
        request_body = {}
    return request_body

def send_api_request(url, request_body, auth_user, auth_pass):
    """
    Send a POST request to the specified API endpoint using basic authentication.
    """
    headers = {"Content-Type": "application/json"}
    logger.debug(f"Sending API request to {url} with payload: {request_body} and auth_user: {auth_user}")
    try:
        response = requests.post(url, headers=headers, json=request_body,
                                 auth=HTTPBasicAuth(auth_user, auth_pass))
        status_code = response.status_code
        logger.debug(f"Received response with status code: {status_code}")
        try:
            response_json = response.json()
            logger.debug(f"Response JSON: {response_json}")
        except ValueError:
            response_json = {"error": "Invalid JSON response"}
            logger.error("Invalid JSON response received from API")
        return status_code, response_json
    except requests.RequestException as e:
        logger.error(f"HTTP request failed: {e}")
        return None, {"error": str(e)}

def check_alpr(config):
    """
    ตรวจสอบสถานะของ ALPR และอัปเดตสถานะในตัวแปร global
    (แก้ไขให้ใช้ PyMySQL)
    """
    logger.info('Start Check ALPR with PyMySQL')
    global EXTRA_PROCESS_STATUS
    
    db_conn = None
    
    if not config:
        logger.error("Database configuration is missing.")
        return

    try:
        logger.info("Starting connection to MySQL using PyMySQL")
        # --- แก้ไข: ใช้ pymysql.connect() ---
        db_conn = pymysql.connect(
            host=config["host"],
            user=config["user"],
            password=config["password"],
            database=config["databaseName"], # ตรวจสอบให้แน่ใจว่า key นี้มีใน config.json
            cursorclass=pymysql.cursors.DictCursor  # <-- ทำให้ผลลัพธ์เป็น Dictionary
        )
        logger.info("Connected to MySQL successfully with PyMySQL")
        
        # ใช้ with ... as ... เพื่อให้ cursor ปิดตัวเองอัตโนมัติ
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
            lane_name = lane_config["LaneName"]
            lane_Show = "ALPR " + lane_name # ใช้ lane_Show ในการแสดงผล Log
            check_houes = lane_config["CheckHours"]
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

    except pymysql.Error as e: # <-- แก้ไข: ดักจับ Error ของ PyMySQL
        logger.error(f'An error occurred in check_alpr: {e}')
        # หากเกิดข้อผิดพลาด ให้กำหนดสถานะทุกเลนเป็น False
        lanes_to_check = config.get("dataCheck", [])
        for lane_config in lanes_to_check:
             lane_Show = "ALPR " + lane_config["LaneName"]
             EXTRA_PROCESS_STATUS.append({"processName": lane_Show, "running": False})
    finally:
        # ปิดการเชื่อมต่อเสมอไม่ว่าจะสำเร็จหรือล้มเหลว
        if db_conn:
            db_conn.close()
            logger.info("MySQL connection closed.")
    
    logger.debug(f"Final ALPR Status: {EXTRA_PROCESS_STATUS}")

def Check_alpr_API():
    global EXTRA_PROCESS_STATUS
    logger.info('Start Check ALPR API')
    with ThreadPoolExecutor(max_workers=1) as executor:
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

def send_http_request(image_path, url):
    """Create and send an HTTP request."""
    try:
        # Convert image to Base64
        image_base64 = image_to_base64(image_path)
        if not image_base64:
            logger.error("Failed to convert image to Base64.")
            return None

        # Create JSON payload
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
        logger.debug(f"Sending HTTP request to {url} with payload: {payload}")

        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        return response.text
    except requests.RequestException as e:
        logger.error(f"HTTP request failed: {e}")
        return None

def image_to_base64(image_path):

    try:
        logger.debug(f'Convert images Path : {image_path}')
        """แปลงรูปภาพเป็น Base64"""
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f'Convert images : {e}')
    return encoded_string

def Check_ntp(config):
    global EXTRA_PROCESS_STATUS
    logger.info('Start Check NTP')
    with ThreadPoolExecutor(max_workers=2) as executor: # เพิ่ม workers เป็น 2 เพื่อให้ทำงานพร้อมกันได้
        try:
            # ส่งงานไปให้ Thread และเก็บ Future object ไว้
            future_global_ntp = executor.submit(get_ntp_time, config.get('Global_NTP', 'pool.ntp.org'))
            future_local_ntp = executor.submit(get_ntp_time, config.get('Local_NTP', 'time.google.com'))

            # เรียก .result() เพื่อรอและดึงผลลัพธ์ที่แท้จริง
            global_ntp_time = future_global_ntp.result()
            local_ntp_time = future_local_ntp.result()

            # ตรวจสอบว่าได้ค่าเวลามาครบทั้งสองค่าหรือไม่ (กรณี timeout จะเป็น None)
            if global_ntp_time and local_ntp_time:
                # ตอนนี้สามารถนำ datetime object มาคำนวณได้แล้ว
                delta = abs((local_ntp_time - global_ntp_time).total_seconds())

                if delta < 0.1 and delta > -0.1:
                    logger.info(f'NTP Status OK. Time difference: {delta:.4f} seconds')
                    EXTRA_PROCESS_STATUS.append({"processName": "Time Sync", "running": True})
                else:
                    logger.warning(f'NTP Status Not OK. Time difference: {delta:.4f} seconds')
                    EXTRA_PROCESS_STATUS.append({"processName": "Time Sync", "running": False})
            else:
                # กรณีมี NTP server ตัวใดตัวหนึ่งไม่ตอบสนอง
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

    try:
        # สร้าง socket UDP
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(5)
        client.sendto(msg, address)
        msg, address = client.recvfrom(buf)
    except socket.timeout:
        logger.error(f"NTP Server Fail {ntp_server}")
        return None

    # วิเคราะห์ค่าที่ได้
    unpacked = struct.unpack("!12I", msg[0:48])
    transmit_timestamp = unpacked[10] + float(unpacked[11]) / 2**32
    ntp_time = datetime.utcfromtimestamp(transmit_timestamp - 2208988800)
    return ntp_time

def main():
    """
    Main function that collects system metrics, prepares the JSON payload, and sends the data via API.
    """
    try:
        request_body = prepare_request_body(config, extra_processes=EXTRA_PROCESS_STATUS)
        url = config.get("url","")  # Default to empty string if not specified.
        if  not url:
            logger.error("API URL is not configured. Please check your config.json file.")
            return
        auth_user = config.get("auth_user", "")  # Default to empty string if not specified.
        if not auth_user:       
            logger.error("API auth_user is not configured. Please check your config.json file.")
            return
        auth_pass = config.get("auth_pass", "")  # Default to empty string if not specified.
        if not auth_pass:
            logger.error("API auth_pass is not configured. Please check your config.json file.")
            return
        EXTRA_PROCESS_STATUS.clear()
        logger.debug(f"Main function: Using URL: {url}, auth_user: {auth_user}")
        status_code, response_json = send_api_request(url, request_body, auth_user, auth_pass)
        logger.info(f"Status Code: {status_code}")
        logger.info(f"Response: {response_json}")
    except Exception as e:
        logger.error(f"Error in main execution: {e}")

def keep_alive():
    """
    Log a keep-alive message to indicate that the system is active.
    """
    logger.info('Keep Alive')

if __name__ == "__main__":
    # Load configuration and initialize logging.
    config = Load_Config(default_config,Program_Name)
    logger = Loguru_Logging(config, Program_Name, Program_Version)
    logger.debug("Loaded configuration: {}", config)

    # Cache the CPU count to avoid repeated calls.
    CPU_COUNT = os.cpu_count() or 1
    logger.debug(f"CPU_COUNT = {CPU_COUNT}")

    logger.info(f"Starting scheduled tasks every {config.get('TimeSleep',360)} seconds")
    
    # For Windows support in frozen executables.
    multiprocessing.freeze_support()

    # Run main() once immediately at startup.
    if config.get("Check_ALPR_Enable", 0) == 1:
        logger.info("ALPR check is enabled. Running check_alpr()")
        check_alpr(config.get("DatabaseConfig"))
        schedule.every(1).hours.do(check_alpr,config.get("DatabaseConfig"))

    if config.get("Check_ALPR_API_Enable", 0) == 1:
        logger.info("ALPR API check is enabled. Running Check_alpr_API()")
        Check_alpr_API()
        schedule.every(1).hours.do(Check_alpr_API)
    
    # Check NTP status at startup.
    if config.get("Check_NTP_Enable", 0) == 1:
        logger.info("NTP check is enabled. Running Check_ntp()")
        Check_ntp(config)
        schedule.every(1).hours.do(Check_ntp, config)

    # Run main() once immediately at startup.
    main()

    # Schedule main() to run every TimeSleep seconds.
    schedule.every(int(config.get('TimeSleep',360))).seconds.do(main)
    # Schedule keep_alive() to run every 60 seconds.
    schedule.every(60).seconds.do(keep_alive)

    # Main loop to run pending scheduled tasks.
    while True:
        schedule.run_pending()
        time.sleep(10)
