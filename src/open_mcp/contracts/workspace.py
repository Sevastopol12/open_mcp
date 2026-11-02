from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    diff: str
    changed_files: list[str] = Field(default_factory=list)
    has_uncommitted_changes: bool = False


class MergeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    commit: Annotated[str, Field(min_length=1)]
    target_branch: Annotated[str, Field(min_length=1)]
    stale_base: bool = False
