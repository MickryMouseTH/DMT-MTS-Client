"""Persistence logic: turn a validated ReportIn into ORM rows."""
from sqlalchemy.orm import Session

import models
import schemas


def create_report(db: Session, payload: schemas.ReportIn) -> models.MonitorReport:
    """Insert one monitoring report plus its disks/folders/processes."""
    report = models.MonitorReport(
        request_id=payload.request_id,
        request_datetime=payload.request_datetime,
        device_name=payload.device_name,
        tsb_id=payload.tsb_id,
        app_running=payload.app_running,
        percent_cpu_usage=payload.percent_cpu_usage,
        percent_ram_usage=payload.percent_ram_usage,
        uptime_minute=payload.uptime_minute,
        operating_system=payload.operating_system,
        log_size_kilobyte=payload.log_size_kilobyte,
        disks=[
            models.MonitorDisk(
                disk=d.disk,
                space_gb=d.space_gb,
                usage_gb=d.usage_gb,
                free_gb=d.free_gb,
                percent_used=d.percent_used,
            )
            for d in payload.disks
        ],
        folders=[
            models.MonitorFolder(
                path_folder=f.path_folder,
                file_count=f.file_count,
                file_size_kilobyte=f.file_size_kilobyte,
            )
            for f in payload.folders
        ],
        processes=[
            models.MonitorProcess(
                process_name=p.process_name,
                running=p.running,
            )
            for p in payload.process
        ],
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    return report
