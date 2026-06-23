# MTS Monitoring API Server

FastAPI server ที่ทำหน้าที่ **รับข้อมูล monitoring** ที่ส่งมาจาก `MTS_Client.py`
แล้วบันทึกลงฐานข้อมูลที่ **เลือกได้** ระหว่าง **MySQL / PostgreSQL / MSSQL**
(และมี **SQLite** ไว้สำหรับทดสอบ/รันเครื่องเดียว)

- ใช้ **SQLAlchemy** เป็นชั้นกลาง → โค้ด/ตารางชุดเดียวใช้ได้กับทุกฐานข้อมูล
  เพียงเปลี่ยน `DatabaseConfig.DB_Type` ใน config
- ใช้ **`LogLibrary.py`** ตัวเดียวกับฝั่ง client → ตั้งค่าผ่าน **ไฟล์ JSON** และ
  log ด้วย **loguru** (rotation + retention + zip)
- มีสคริปต์ **`start.sh` / `stop.sh`** สำหรับรัน/หยุดแบบ background

---

## 1. โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|------|---------|
| `main.py` | FastAPI app, endpoint, HTTP Basic Auth, health check, entrypoint (`python main.py`) |
| `config.py` | โหลด config JSON ผ่าน `LogLibrary.Load_Config` + สร้าง logger + สร้าง SQLAlchemy URL |
| `database.py` | engine / session + `init_db()` (สร้างตารางอัตโนมัติ) |
| `models.py` | ตาราง ORM (`monitor_report` + `monitor_disk` / `monitor_folder` / `monitor_process`) |
| `schemas.py` | Pydantic models ตรวจสอบ payload (รองรับคีย์ legacy `fileSiteKilobyte`) |
| `crud.py` | ตรรกะบันทึกข้อมูลลงตาราง |
| `LogLibrary.py` | สำเนาของไลบรารี logging/config (ทำให้โฟลเดอร์ `server/` ใช้งานได้แบบ standalone) |
| `start.sh` / `stop.sh` | สคริปต์เริ่ม/หยุดเซิร์ฟเวอร์ (เก็บ PID ใน `server.pid`) |
| `requirements.txt` | dependency (driver DB ติดตั้งเฉพาะตัวที่ใช้) |

> **หมายเหตุ:** `server/LogLibrary.py` เป็นสำเนาของไฟล์ที่ project root ทำให้
> `MTS_Server_config.json` และโฟลเดอร์ `logs/` ถูกสร้าง **ภายใน `server/`** เอง
> (แยกจากของ client) หากแก้ไข `LogLibrary.py` ตัวหลัก ควรคัดลอกมาทับตัวนี้ด้วย

---

## 2. โครงสร้างฐานข้อมูล (Schema)

ข้อมูลถูกเก็บแบบ normalized (พอร์ตข้ามฐานข้อมูลได้ และ query ง่าย):

```
monitor_report                       (1 แถว = 1 report ต่อรอบ)
 ├─ id, request_id, request_datetime, received_at
 ├─ device_name, tsb_id
 ├─ app_running, percent_cpu_usage, percent_ram_usage
 ├─ uptime_minute, operating_system, log_size_kilobyte
 │
 ├──< monitor_disk    (disk, space_gb, usage_gb, free_gb, percent_used)
 ├──< monitor_folder  (path_folder, file_count, file_size_kilobyte)
 └──< monitor_process (process_name, running)
```

> ตารางถูกสร้างอัตโนมัติเมื่อ start (เมื่อ `Auto_Create_Tables = 1`) — ตัว
> ฐานข้อมูล (`databaseName`) ต้องถูกสร้างไว้ก่อน

---

## 3. การติดตั้ง

```bash
cd server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# ติดตั้ง driver ตามฐานข้อมูลที่ใช้ (เลือกอย่างใดอย่างหนึ่ง)
pip install pymysql            # MySQL / MariaDB
pip install psycopg2-binary    # PostgreSQL
pip install pyodbc             # MSSQL (ต้องมี ODBC driver ในเครื่องด้วย)
# SQLite ไม่ต้องติดตั้งอะไรเพิ่ม
```

> `start.sh` จะใช้ `venv/bin/python` อัตโนมัติถ้ามีโฟลเดอร์ `venv/` อยู่
> มิฉะนั้นจะใช้ `python3` ในระบบ

---

## 4. การตั้งค่า (`MTS_Server_config.json`)

ไฟล์นี้จะถูก **สร้างอัตโนมัติ** ด้วยค่า default เมื่อรันครั้งแรก (และถ้าไฟล์เดิม
ขาดคีย์ใหม่ ระบบจะเติมให้อัตโนมัติโดยไม่ทับค่าที่แก้ไว้) จากนั้นแก้ค่าตามต้องการ:

```json
{
    "Host": "0.0.0.0",
    "Port": 8000,
    "Workers": 1,
    "API_Auth_User": "mts",
    "API_Auth_Pass": "change-me",
    "API_Path": "/api/monitor",
    "Auto_Create_Tables": 1,
    "DatabaseConfig": {
        "DB_Type": "sqlite",
        "host": "localhost",
        "port": "",
        "user": "",
        "password": "",
        "databaseName": "mts_monitor",
        "sqlitePath": "./mts_monitor.db",
        "mssqlOdbcDriver": "ODBC Driver 17 for SQL Server"
    },
    "log_Level": "INFO",
    "Log_Console": 1,
    "log_Backup": 90,
    "Log_Size": "10 MB"
}
```

| Key | ความหมาย |
|-----|----------|
| `Host`, `Port`, `Workers` | ที่อยู่/พอร์ต/จำนวน worker ของเซิร์ฟเวอร์ |
| `API_Auth_User`, `API_Auth_Pass` | Basic Auth — **ต้องตรงกับ** `auth_user`/`auth_pass` ฝั่ง client |
| `API_Path` | path ที่รับข้อมูล |
| `DatabaseConfig.DB_Type` | `sqlite` \| `mysql` \| `postgresql` \| `mssql` |
| `DatabaseConfig.*` | host/port/user/password/databaseName (เว้น `port` ว่าง = ใช้พอร์ตมาตรฐาน) |
| `sqlitePath` | path ไฟล์ DB (เฉพาะ sqlite, **relative กับโฟลเดอร์ `server/`**) |
| `mssqlOdbcDriver` | ชื่อ ODBC driver (เฉพาะ mssql) |
| `Auto_Create_Tables` | `1` = สร้างตารางอัตโนมัติตอน start |
| `log_*`, `Log_*` | ตั้งค่า log (ระดับ, console, retention, ขนาดหมุนไฟล์) |

---

## 5. การรัน

### ด้วยสคริปต์ (background)
```bash
./start.sh     # อ่าน Host/Port/Workers/DB จาก MTS_Server_config.json
./stop.sh
```
- `start.sh` รันแบบ background, เก็บ PID ใน `server.pid`, log stdout/stderr ไปที่ `server.out`
- `stop.sh` หยุดด้วย SIGTERM (รอ ~10s) แล้ว force-kill ถ้าจำเป็น

### รันตรง (foreground)
```bash
python main.py                                   # อ่านค่าจาก JSON config
# หรือ
uvicorn main:app --host 0.0.0.0 --port 8000
```

- เอกสาร API อัตโนมัติ: `http://<host>:8000/docs`
- Health check: `GET http://<host>:8000/health`

---

## 6. Endpoint

### `POST /api/monitor`  (ต้องมี HTTP Basic Auth)
รับ payload ตามรูปแบบที่ `MTS_Client.prepare_request_body()` ส่งมา

**response (201):**
```json
{ "status": "OK", "id": 12, "requestId": "MTS2026...", "message": "Report stored" }
```

| สถานะ | ความหมาย |
|-------|----------|
| `201` | บันทึกสำเร็จ |
| `401` | auth ไม่ถูกต้อง |
| `422` | payload ไม่ถูกต้อง (เช่น ขาด `requestId`) |
| `503` | ฐานข้อมูลมีปัญหา |

### `GET /health`
ตรวจสอบสถานะเซิร์ฟเวอร์ + การเชื่อมต่อ DB

---

## 7. การเชื่อมกับ MTS_Client

ในไฟล์ `MTS_Python_config.json` ฝั่ง client ตั้งค่า:

```json
{
  "url": "http://<server-ip>:8000/api/monitor",
  "auth_user": "mts",
  "auth_pass": "<ตรงกับ API_Auth_Pass>"
}
```

Client จะ POST ข้อมูลมาตามรอบ `TimeSleep` โดยอัตโนมัติ

---

## 8. ทดสอบด้วย curl

```bash
curl -u mts:change-me -X POST http://localhost:8000/api/monitor \
  -H "Content-Type: application/json" \
  -d '{
    "requestId":"MTS-test-1","requestDatetime":"2026-06-23T07:30:00",
    "deviceName":"LANE-01","appRunning":true,
    "percentCpuUsage":12.5,"percentRamUsage":47,"uptimeMinute":1440,
    "disks":[{"disk":"C:","spaceGb":100,"usageGb":60,"freeGb":40,"percentUsed":60}],
    "folders":[{"pathFolder":"/data","fileCount":1200,"fileSizeKilobyte":345.6}],
    "process":[{"processName":"ALPR","running":true}],
    "operatingSystem":"Windows-10"
  }'
```
