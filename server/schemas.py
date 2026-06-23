"""
Pydantic models describing the JSON payload sent by MTS_Client.

The payload shape mirrors `prepare_request_body()` in MTS_Client.py. Notably,
each folder entry carries BOTH `fileSizeKilobyte` (current) and the legacy
misspelled `fileSiteKilobyte` key, so the folder model accepts either.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, AliasChoices


class DiskIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    disk: str = ""
    space_gb: float = Field(0.0, alias="spaceGb")
    usage_gb: float = Field(0.0, alias="usageGb")
    free_gb: float = Field(0.0, alias="freeGb")
    percent_used: int = Field(0, alias="percentUsed")


class FolderIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    path_folder: str = Field("", alias="pathFolder")
    file_count: int = Field(0, alias="fileCount")
    # Accept the current key and the legacy misspelled one ("Site").
    file_size_kilobyte: float = Field(
        0.0,
        validation_alias=AliasChoices("fileSizeKilobyte", "fileSiteKilobyte"),
        serialization_alias="fileSizeKilobyte",
    )


class ProcessIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    process_name: str = Field("", alias="processName")
    running: bool = False


class ReportIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    request_id: str = Field(..., alias="requestId")
    request_datetime: Optional[datetime] = Field(None, alias="requestDatetime")
    device_name: str = Field("Unknown Device", alias="deviceName")
    tsb_id: Optional[str] = Field(None, alias="tsbId")

    app_running: bool = Field(False, alias="appRunning")
    percent_cpu_usage: float = Field(0.0, alias="percentCpuUsage")
    percent_ram_usage: float = Field(0.0, alias="percentRamUsage")
    uptime_minute: int = Field(0, alias="uptimeMinute")
    operating_system: Optional[str] = Field(None, alias="operatingSystem")
    log_size_kilobyte: Optional[float] = Field(None, alias="logSizeKilobyte")

    disks: List[DiskIn] = Field(default_factory=list)
    folders: List[FolderIn] = Field(default_factory=list)
    process: List[ProcessIn] = Field(default_factory=list)


class ReportAccepted(BaseModel):
    status: str = "OK"
    id: int
    requestId: str
    message: str = "Report stored"
