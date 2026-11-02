from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class RuntimeStatus(StrEnum):
    BUSY = "busy"
    IDLE = "idle"
    FAILED = "failed"


class PermissionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: Annotated[str, Field(min_length=1)]
    session_id: Annotated[str, Field(min_length=1)]
    kind: Annotated[str, Field(min_length=1)]
    targets: list[str] = Field(default_factory=list)
    detail: str = ""
