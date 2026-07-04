# DMT-MTS-Client (MTS_Python)

โปรแกรม **Monitoring Agent** สำหรับเครื่อง Client ที่ทำหน้าที่เก็บข้อมูลสุขภาพของเครื่อง
(CPU, RAM, Disk, Uptime, ขนาดโฟลเดอร์, สถานะ Process) รวมถึงตรวจสอบระบบ ALPR
(License Plate Recognition) และการ Sync เวลา (NTP) แล้วส่งข้อมูลทั้งหมดไปยัง Server
ผ่าน HTTP API ตามรอบเวลาที่กำหนด

- **Version:** 4.0
- **ภาษา:** Python 3 (ทดสอบบน Python 3.13)
- **ไฟล์หลัก:** `MTS_Client.py`, `LogLibrary.py`

---

## 1. โครงสร้างโปรเจกต์

| ไฟล์ | หน้าที่ |
|------|---------|
| `MTS_Client.py` | โปรแกรมหลัก — เก็บ metric, ตรวจสอบ ALPR/NTP, สร้าง payload และส่ง API ตามรอบ |
| `LogLibrary.py` | โหลด/สร้างไฟล์ config (JSON) และตั้งค่า logger (Loguru) แบบ rotation + retention |
| `MTS_Python_config.json` | ไฟล์ตั้งค่า (สร้างอัตโนมัติครั้งแรกที่รัน) |
| `logs/` | โฟลเดอร์เก็บ log (สร้างอัตโนมัติ) |

---

## 2. การทำงานโดยรวม (Flow)

```
เริ่มโปรแกรม
   │
   ├─ Load_Config()  → โหลด/สร้าง MTS_Python_config.json (+ back-fill คีย์ที่ขาด)
   ├─ Loguru_Logging() → ตั้งค่า log console + ไฟล์ (rotation/retention/zip)
   │
   ├─ main() (รันทันที 1 ครั้ง)
   │     ├─ ตรวจ config สำคัญ (url, auth_user, auth_pass)
   │     ├─ (option) check_alpr()      → query MySQL ดูว่ามีข้อมูลป้ายล่าสุดไหม
   │     ├─ (option) Check_alpr_API()  → ยิงรูปไป ALPR API เช็คสถานะ
   │     ├─ (option) Check_ntp()       → เทียบเวลา Global vs Local NTP
   │     ├─ prepare_request_body()     → รวบรวม CPU/RAM/Disk/Folder/Process
   │     ├─ เคลียร์ EXTRA_PROCESS_STATUS
   │     └─ send_api_request()         → POST ไป Server (มี retry)
   │
   └─ schedule loop
         ├─ main()        ทุก TimeSleep วินาที
         └─ keep_alive()  ทุก 60 วินาที
```

### ฟังก์ชันสำคัญ
- **`get_disk_info()`** — อ่านการใช้ disk ทุก partition (กรอง loop device / virtual fs ออก)
- **`get_folder_info()` / `get_folders_info()`** — นับจำนวนไฟล์และขนาดรวมของโฟลเดอร์ (เดินทรีแบบ BFS แบบขนาน)
- **`check_process_running()`** — เช็คว่า process ที่ระบุกำลังรันอยู่หรือไม่ (เทียบ name/exe)
- **`prepare_request_body()`** — ประกอบ JSON payload ทั้งหมด
- **`send_api_request()`** — POST ข้อมูลไป Server พร้อม Basic Auth + retry
- **`check_alpr()` / `Check_alpr_API()` / `Check_ntp()`** — การตรวจสอบเสริม (เปิด/ปิดได้ผ่าน config)

---

## 3. การตั้งค่า (Config)

ไฟล์ `MTS_Python_config.json` จะถูกสร้างอัตโนมัติด้วยค่า default ในการรันครั้งแรก
คีย์สำคัญ:

| Key | ความหมาย |
|-----|----------|
| `url`, `auth_user`, `auth_pass` | ปลายทาง API + Basic Auth (จำเป็น) |
| `deviceName`, `tsbId` | ชื่อ/รหัสอุปกรณ์ |
| `folders` | รายการโฟลเดอร์ที่ต้องวัดขนาด |
| `process` | รายการ process ที่ต้องเฝ้าดู (`processName`, `processApp`) |
| `DatabaseConfig` | ค่าเชื่อมต่อ MySQL สำหรับ ALPR + `dataCheck` (LaneName/CheckHours) |
| `image_path`, `image_url` | รูปและ endpoint สำหรับ ALPR API |
| `Global_NTP`, `Local_NTP`, `NTP_Threshold_Seconds` | ค่าตรวจ NTP |
| `Check_ALPR_Enable`, `Check_ALPR_API_Enable`, `Check_NTP_Enable` | เปิด/ปิดการตรวจ (1/0) |
| `TimeSleep` | รอบเวลาส่งข้อมูล (วินาที) |
| `RamOffset` | ค่าหักลบ % RAM ที่รายงาน |
| `log_Level`, `log_Backup`, `Log_Size`, `Log_Console` | ตั้งค่า log |
| `http_timeout_sec`, `http_retries` | timeout และจำนวน retry ของ HTTP |

> ตั้งแต่เวอร์ชันนี้ ถ้าไฟล์ config เดิมขาดคีย์ใหม่ ระบบจะ **เติมค่า default ให้อัตโนมัติ**
> (โดยไม่ทับค่าที่ผู้ใช้แก้ไว้) แล้วบันทึกกลับลงไฟล์

---

## 4. การติดตั้งและรัน

```bash
pip install loguru psutil pymysql schedule requests
python3 MTS_Client.py
```

ครั้งแรกจะสร้าง `MTS_Python_config.json` ให้ — แก้ค่า `url`, `auth_user`, `auth_pass`
และอื่น ๆ แล้วรันใหม่อีกครั้ง

---

## 5. Bug ที่พบและแก้ไข

> ปรับปรุงในรอบนี้ — แก้ทั้งที่ `MTS_Client.py` และ `LogLibrary.py`

### 🔴 5.1 Thread pool ซ้อนกัน 3 ชั้น (Thread Explosion) — *ผลกระทบสูง*
**เดิม:** `get_folders_info()` เปิด pool → เรียก `get_folder_info()` ที่เปิด pool อีก →
เรียก `process_subfolder()` ที่เปิด pool อีกชั้น ทำให้จำนวน thread พุ่งเป็น
~`O(MAX_WORKERS³)` บนทรีที่ลึก เสี่ยงใช้ทรัพยากรจนเครื่องค้าง

**แก้:** ยุบเหลือ **pool เดียว** — `get_folder_info()` เดินทรีแบบ BFS ด้วย pool เดียว,
ลบ `process_subfolder()` ทิ้ง, และให้ `get_folders_info()` วนทีละโฟลเดอร์ (sequential)
จำนวน thread จึงถูกจำกัดที่ `MAX_WORKERS_IO` เสมอ พร้อมยังคงความขนานของงาน I/O ไว้

### 🟠 5.2 พาธ `"logs"` แบบ relative (ขึ้นกับ CWD)
**เดิม:** `get_folder_info("logs")` ใช้พาธสัมพัทธ์ — ถ้ารันเป็น service ที่ CWD ต่างออกไป
จะหาโฟลเดอร์ log ไม่เจอ (log จริงอยู่ที่ `script_dir/logs`)
**แก้:** เปลี่ยนไปใช้ `os.path.join(script_dir, "logs")` (พาธสมบูรณ์)

### 🟠 5.3 `datetime.utcfromtimestamp()` ถูก deprecated
**เดิม:** ใช้ใน `get_ntp_time()` — แจ้งเตือน deprecation บน Python 3.12+ และจะถูกถอดในอนาคต
**แก้:** เปลี่ยนเป็น `datetime.fromtimestamp(ts, tz=timezone.utc)` (timezone-aware)
ผลลัพธ์ delta เวลายังเท่าเดิม

### 🟠 5.4 `MAX_WORKERS_IO` ถูกประกาศใน `__main__` เท่านั้น
**เดิม:** หลายฟังก์ชันอ้างถึง `MAX_WORKERS_IO` เป็น global แต่ตัวแปรถูกสร้างในบล็อก
`if __name__ == "__main__":` ทำให้เปราะมาก (พังทันทีถ้า import โมดูลมาใช้/ทดสอบ)
**แก้:** ย้าย `CPU_COUNT` / `MAX_WORKERS_IO` ขึ้นมาเป็น module-level

### 🟡 5.5 เข้าถึง key ของ config ด้วย `[]` ตรง ๆ → เสี่ยง `KeyError`
**เดิม:** `check_alpr()` ใช้ `config["host"]`, `lane_config["LaneName"]`, `lane_config["CheckHours"]`
ถ้า config ไม่ครบจะ crash
**แก้:** เปลี่ยนเป็น `.get(key, default)` ทั้งหมด + เพิ่ม `connect_timeout=10` ให้ MySQL

### 🟡 5.6 Config ไม่ถูก merge กับ default
**เดิม:** ถ้าไฟล์ config เดิมขาดคีย์ใหม่ (เพิ่มในเวอร์ชันใหม่) จะไม่มีคีย์นั้น
**แก้:** `Load_Config()` ทำ deep-merge เติมคีย์ที่ขาด (ไม่ทับค่าผู้ใช้) แล้วบันทึกกลับ
พร้อมจับกรณีไฟล์ config เสีย/อ่านไม่ได้ ให้ fallback เป็น default แทนการ crash

### 🟡 5.7 Log ของ `send_http_request()` ทำให้เข้าใจผิด + timeout hardcode
**เดิม:** debug log "Sending HTTP request..." ถูกพิมพ์ **หลัง** request ถูกส่งไปแล้ว
และ timeout ถูก hardcode เป็น 10 วินาที
**แก้:** ย้าย log ไปก่อนส่งจริง (พร้อม redact base64 รูปออกจาก log) และใช้
`http_timeout_sec` จาก config

### 🟠 5.8 `check_process_running()` สแกน process ทั้งระบบซ้ำทุก process ที่ config — *ผลกระทบสูง (perf)*
**เดิม:** ทุกครั้งที่เช็ค 1 process ใน config จะเรียก `psutil.process_iter()` (syscall แพง)
ใหม่ทั้งหมด → ถ้ามี N process ที่เฝ้าดู ก็สแกน process list ทั้งระบบ N รอบ
**แก้:** เพิ่ม `snapshot_running_processes()` ที่ snapshot รายชื่อ process **ครั้งเดียวต่อรอบ**
แล้ว `is_process_running()` เช็คใน memory (คงตรรกะ match เดิมเป๊ะ: ตรงชื่อ หรือ
substring ใน basename ของ exe) — ลดจาก O(N × จำนวน process ทั้งระบบ) เหลือสแกนระบบครั้งเดียว

### 🟡 5.9 Main scheduler loop ไม่มีการดักจับ exception
**เดิม:** `while True: schedule.run_pending()` ไม่มี try/except — ถ้า `run_pending()`
โยน exception ขึ้นมา โปรแกรมที่ควรรันยาว ๆ จะตายทันที
**แก้:** ครอบ `run_pending()` ด้วย try/except + log error เพื่อให้ agent ทำงานต่อได้

---

## 6. หมายเหตุ / ข้อควรระวังที่ยังคงไว้โดยตั้งใจ

- **คีย์ `fileSiteKilobyte`** (สะกดผิด "Site") ถูกคงไว้เพื่อความเข้ากันได้กับ Server เดิม
  และเพิ่ม alias `fileSizeKilobyte` (สะกดถูก) ควบคู่ไว้ให้ระบบใหม่
- **`psutil.cpu_percent(interval=1)`** จะ block 1 วินาทีต่อรอบ (ตั้งใจให้สุ่มค่าแบบ blocking)
- **Scheduler เป็น single-thread** — ถ้า `main()` ใช้เวลานานกว่า `TimeSleep` รอบถัดไปจะเลื่อน
  ออกไป ไม่เกิดการทำงานทับซ้อน

## 7. ข้อเสนอแนะเพิ่มเติม (อนาคต)

- พิจารณาไม่ log `request_body`/`auth_user` เต็ม ๆ ที่ระดับ INFO เพื่อลดข้อมูลอ่อนไหวใน log
- เพิ่ม `requirements.txt` ระบุเวอร์ชันไลบรารีให้ชัดเจน
- เพิ่มชุดทดสอบ (unit test) สำหรับฟังก์ชันเดินทรีโฟลเดอร์และการ merge config
