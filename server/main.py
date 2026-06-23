"""
MTS Monitoring API server (FastAPI).

Receives monitoring reports posted by MTS_Client and stores them in the
configured database (MySQL / PostgreSQL / MSSQL / SQLite).

Config is read from `MTS_Server_config.json` via the shared LogLibrary module.

Run:
    python main.py                      # uses Host/Port/Workers from the JSON config
    uvicorn main:app --host 0.0.0.0 --port 8000
"""
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import config
import crud
import schemas
from config import logger
from database import engine, get_db, init_db

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Validate HTTP Basic Auth using constant-time comparison.

    Compare UTF-8 bytes (not str): secrets.compare_digest raises TypeError on
    non-ASCII strings, so comparing str directly would turn a non-ASCII
    password into a 500 error instead of a clean 401.
    """
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), config.API_AUTH_USER.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), config.API_AUTH_PASS.encode("utf-8")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.AUTO_CREATE_TABLES:
        try:
            init_db()
            logger.info(f"Database tables ensured (DB_Type={config.DB_TYPE}).")
        except Exception as e:
            logger.error(f"Failed to initialise database: {e}")
            raise
    yield


app = FastAPI(
    title="MTS Monitoring API",
    version=config.Program_Version,
    description="Receives MTS_Client monitoring reports and stores them in a database.",
    lifespan=lifespan,
)


@app.get("/health")
def health(response: Response):
    """Liveness + DB connectivity probe. Returns 503 if the DB is unreachable."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_ok = False
        logger.warning(f"Health check DB error: {e}")
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if db_ok else "degraded",
        "db_type": config.DB_TYPE,
        "db_connected": db_ok,
    }


@app.post(
    config.API_PATH,
    response_model=schemas.ReportAccepted,
    status_code=status.HTTP_201_CREATED,
)
def receive_report(
    payload: schemas.ReportIn,
    db: Session = Depends(get_db),
    _user: str = Depends(verify_credentials),
):
    """Accept a monitoring report and persist it."""
    try:
        report = crud.create_report(db, payload)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"DB error while storing report {payload.request_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to store report",
        )

    logger.info(
        f"Stored report id={report.id} requestId={report.request_id} "
        f"device={report.device_name} appRunning={report.app_running}"
    )
    return schemas.ReportAccepted(id=report.id, requestId=report.request_id)


if __name__ == "__main__":
    import uvicorn

    logger.info(
        f"Starting {config.Program_Name} {config.Program_Version} on "
        f"{config.HOST}:{config.PORT} (workers={config.WORKERS}, DB={config.DB_TYPE})"
    )
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        workers=config.WORKERS,
        log_config=None,   # keep our loguru logging, don't let uvicorn override it
    )
