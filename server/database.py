"""
SQLAlchemy engine / session setup.

A single engine is created from the configured DATABASE_URL. The same ORM
models work across MySQL, PostgreSQL, MSSQL and SQLite because we stick to
portable column types.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL, DB_TYPE, logger

# SQLite needs a special flag when used from a multi-threaded server.
_connect_args = {"check_same_thread": False} if DB_TYPE == "sqlite" else {}

# Hint shown if the driver for the selected backend is not installed.
_DRIVER_HINT = {
    "mysql": "pip install pymysql",
    "postgresql": "pip install psycopg2-binary",
    "mssql": "pip install pyodbc  (and install a system ODBC driver)",
}

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,      # transparently recover from dropped connections
        future=True,
        connect_args=_connect_args,
    )
except ModuleNotFoundError as e:
    # create_engine imports the DBAPI driver eagerly; a missing driver would
    # otherwise surface as a cryptic ModuleNotFoundError deep inside SQLAlchemy.
    hint = _DRIVER_HINT.get(DB_TYPE, "")
    msg = (
        f"Database driver for DB_Type='{DB_TYPE}' is not installed ({e}). "
        + (f"Run: {hint}" if hint else "")
    )
    logger.error(msg)
    raise SystemExit(msg) from e

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they do not already exist."""
    # Import models so they are registered on Base.metadata before create_all.
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.debug("Base.metadata.create_all completed.")
