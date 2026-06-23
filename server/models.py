"""
ORM models for the monitoring data.

The payload sent by MTS_Client is stored in a normalised set of tables (rather
than JSON columns) so the schema is portable across MySQL, PostgreSQL and
MSSQL and is easy to query/report on:

    monitor_report (1) --< monitor_disk    (many)
                   (1) --< monitor_folder  (many)
                   (1) --< monitor_process (many)
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Index
)
from sqlalchemy.orm import relationship

from database import Base


class MonitorReport(Base):
    __tablename__ = "monitor_report"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), index=True)
    request_datetime = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow, index=True)

    device_name = Column(String(255), index=True)
    tsb_id = Column(String(64), nullable=True, index=True)

    app_running = Column(Boolean, default=False)
    percent_cpu_usage = Column(Float, default=0.0)
    percent_ram_usage = Column(Float, default=0.0)
    uptime_minute = Column(Integer, default=0)
    operating_system = Column(String(255), nullable=True)
    log_size_kilobyte = Column(Float, nullable=True)

    disks = relationship(
        "MonitorDisk", back_populates="report",
        cascade="all, delete-orphan",
    )
    folders = relationship(
        "MonitorFolder", back_populates="report",
        cascade="all, delete-orphan",
    )
    processes = relationship(
        "MonitorProcess", back_populates="report",
        cascade="all, delete-orphan",
    )


# Composite index to speed up "latest report per device" style queries.
Index("ix_report_device_received", MonitorReport.device_name, MonitorReport.received_at)


class MonitorDisk(Base):
    __tablename__ = "monitor_disk"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("monitor_report.id", ondelete="CASCADE"), index=True)

    disk = Column(String(255))
    space_gb = Column(Float, default=0.0)
    usage_gb = Column(Float, default=0.0)
    free_gb = Column(Float, default=0.0)
    percent_used = Column(Integer, default=0)

    report = relationship("MonitorReport", back_populates="disks")


class MonitorFolder(Base):
    __tablename__ = "monitor_folder"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("monitor_report.id", ondelete="CASCADE"), index=True)

    path_folder = Column(String(1024))
    file_count = Column(Integer, default=0)
    file_size_kilobyte = Column(Float, default=0.0)

    report = relationship("MonitorReport", back_populates="folders")


class MonitorProcess(Base):
    __tablename__ = "monitor_process"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("monitor_report.id", ondelete="CASCADE"), index=True)

    process_name = Column(String(255))
    running = Column(Boolean, default=False)

    report = relationship("MonitorReport", back_populates="processes")
