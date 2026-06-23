"""
Configuration for the MTS monitoring API server.

Settings are loaded from a JSON file (`MTS_Server_config.json`) via the shared
`LogLibrary` module — the same mechanism the client uses. The file is created
with sensible defaults on first run and any missing keys are back-filled
automatically. The database backend is selected with `DatabaseConfig.DB_Type`
(one of: ``mysql``, ``postgresql``, ``mssql`` or ``sqlite``).
"""
from urllib.parse import quote_plus

# Uses the LogLibrary copy in THIS directory, so the config file
# (MTS_Server_config.json) and logs/ are created inside server/ — keeping the
# server self-contained and deployable on its own.
from LogLibrary import Load_Config, Loguru_Logging

# ----------------------- Program identity -----------------------
Program_Name = "MTS_Server"
Program_Version = "1.0.0"

# ----------------------- Default configuration -----------------------
default_config = {
    "Host": "0.0.0.0",            # Bind address for the API server.
    "Port": 8000,                 # Listen port.
    "Workers": 1,                 # Number of uvicorn workers.
    "API_Auth_User": "mts",       # HTTP Basic Auth user (must match client).
    "API_Auth_Pass": "change-me", # HTTP Basic Auth password (must match client).
    "API_Path": "/api/monitor",   # Path the client posts to.
    "Auto_Create_Tables": 1,      # 1 = create DB tables on startup.
    "DatabaseConfig": {
        "DB_Type": "sqlite",      # sqlite | mysql | postgresql | mssql
        "host": "localhost",
        "port": "",               # blank -> use the driver default port
        "user": "",
        "password": "",
        "databaseName": "mts_monitor",
        "sqlitePath": "./mts_monitor.db",                 # only for sqlite
        "mssqlOdbcDriver": "ODBC Driver 17 for SQL Server"  # only for mssql
    },
    "log_Level": "INFO",
    "Log_Console": 1,
    "log_Backup": 90,             # Log retention (days).
    "Log_Size": "10 MB"
}

# Load JSON config + initialise the shared loguru logger.
config = Load_Config(default_config, Program_Name)
logger = Loguru_Logging(config, Program_Name, Program_Version)

# ----------------------- Derived settings -----------------------
def _as_int(value, default):
    """Coerce a config value to int, falling back (with a warning) if invalid."""
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(f"Invalid integer config value {value!r}; using default {default}.")
        return default


_db = config.get("DatabaseConfig", {}) or {}

DB_TYPE = str(_db.get("DB_Type", "sqlite")).lower()
API_AUTH_USER = str(config.get("API_Auth_User", "mts"))
API_AUTH_PASS = str(config.get("API_Auth_Pass", "change-me"))
API_PATH = config.get("API_Path", "/api/monitor")
AUTO_CREATE_TABLES = _as_int(config.get("Auto_Create_Tables", 1), 1) == 1
HOST = config.get("Host", "0.0.0.0")
PORT = _as_int(config.get("Port", 8000), 8000)
WORKERS = _as_int(config.get("Workers", 1), 1)

# Default ports per backend, used when "port" is left blank.
_DEFAULT_PORTS = {"mysql": "3306", "postgresql": "5432", "mssql": "1433"}


def build_database_url():
    """
    Build a SQLAlchemy connection URL from the JSON configuration.

    Returns:
        str: a SQLAlchemy-compatible database URL.

    Raises:
        ValueError: if DB_Type is not supported.
    """
    if DB_TYPE == "sqlite":
        return f"sqlite:///{_db.get('sqlitePath', './mts_monitor.db')}"

    if DB_TYPE not in ("mysql", "postgresql", "mssql"):
        raise ValueError(
            f"Unsupported DB_Type '{DB_TYPE}'. "
            "Use one of: mysql, postgresql, mssql, sqlite."
        )

    user = quote_plus(str(_db.get("user", "")))
    password = quote_plus(str(_db.get("password", "")))
    host = _db.get("host", "localhost")
    db_name = _db.get("databaseName", "mts_monitor")
    port = str(_db.get("port", "") or _DEFAULT_PORTS[DB_TYPE])
    auth = f"{user}:{password}@" if user else ""

    if DB_TYPE == "mysql":
        # Requires: pymysql
        return f"mysql+pymysql://{auth}{host}:{port}/{db_name}?charset=utf8mb4"

    if DB_TYPE == "postgresql":
        # Requires: psycopg2-binary
        return f"postgresql+psycopg2://{auth}{host}:{port}/{db_name}"

    # mssql -- requires: pyodbc + an ODBC driver installed on the host
    driver = quote_plus(str(_db.get("mssqlOdbcDriver", "ODBC Driver 17 for SQL Server")))
    return (
        f"mssql+pyodbc://{auth}{host}:{port}/{db_name}"
        f"?driver={driver}&TrustServerCertificate=yes"
    )


DATABASE_URL = build_database_url()
