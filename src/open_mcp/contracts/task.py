import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)

from open_mcp.contracts.errors import InvalidTransitionError

TASK_ID_REGEX = r"^[0-9]{14}-[0-9a-f]{6}$"
TASK_ID_PATTERN = re.compile(TASK_ID_REGEX)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_task_id(now: datetime | None = None) -> str:
    moment = now or utc_now()
    return f"{moment:%Y%m%d%H%M%S}-{secrets.token_hex(3)}"


def normalize_owned_path(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or "\\" in cleaned:
        raise ValueError("owned path must be a non-empty POSIX relative path")
    posix = PurePosixPath(cleaned)
    if posix.is_absolute() or PureWindowsPath(cleaned).drive or ".." in posix.parts:
        raise ValueError("owned path must stay inside the repository")
    return posix.as_posix()


def owned_paths_overlap(first: Sequence[str], second: Sequence[str]) -> bool:
    first_parts = [PurePosixPath(path).parts for path in first]
    second_parts = [PurePosixPath(path).parts for path in second]
    return any(
        _is_prefix(left, right) or _is_prefix(right, left)
        for left in first_parts
        for right in second_parts
    )


def paths_outside(owned_paths: Sequence[str], files: Sequence[str]) -> list[str]:
    owned = [PurePosixPath(path).parts for path in owned_paths]
    return [
        file
        for file in files
        if not any(_is_prefix(prefix, PurePosixPath(file).parts) for prefix in owned)
    ]


def _is_prefix(prefix: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    return parts[: len(prefix)] == prefix


class TaskState(StrEnum):
    PENDING = "pending"
    PREPARING = "preparing"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    CHANGES_REQUESTED = "changes_requested"
    MERGED = "merged"
    DISCARDED = "discarded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: Mapping[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset(
        {TaskState.PREPARING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.PREPARING: frozenset(
        {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.RUNNING: frozenset(
        {TaskState.AWAITING_REVIEW, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.AWAITING_REVIEW: frozenset(
        {
            TaskState.CHANGES_REQUESTED,
            TaskState.MERGED,
            TaskState.DISCARDED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.CHANGES_REQUESTED: frozenset(
        {
            TaskState.RUNNING,
            TaskState.DISCARDED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.FAILED: frozenset({TaskState.DISCARDED}),
    TaskState.CANCELLED: frozenset({TaskState.DISCARDED}),
    TaskState.MERGED: frozenset(),
    TaskState.DISCARDED: frozenset(),
}

FINAL_STATES = frozenset({TaskState.MERGED, TaskState.DISCARDED})
SLOT_STATES = frozenset({TaskState.PREPARING, TaskState.RUNNING})

OwnedPath = Annotated[str, AfterValidator(normalize_owned_path)]


class ModelRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: Annotated[str, Field(min_length=1)]
    model_id: Annotated[str, Field(min_length=1)]


class WorkspaceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Annotated[str, Field(min_length=1)]
    origin: Annotated[str, Field(min_length=1)]
    ref: Annotated[str, Field(min_length=1)]
    branch: Annotated[str, Field(min_length=1)]
    base_commit: Annotated[str, Field(min_length=1)]


class TaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: Annotated[str, Field(min_length=1, max_length=120)]
    prompt: Annotated[str, Field(min_length=1)]
    repo: Annotated[str, Field(min_length=1)]
    base_ref: Annotated[str, Field(min_length=1)] = "HEAD"
    model: ModelRef
    skill: str | None = None
    owned_paths: Annotated[list[OwnedPath], Field(min_length=1)]

    @field_validator("owned_paths")
    @classmethod
    def _deduplicate(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class Task(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: Annotated[str, Field(pattern=TASK_ID_REGEX)]
    spec: TaskSpec
    state: TaskState = TaskState.PENDING
    created_at: AwareDatetime
    updated_at: AwareDatetime
    runtime_session_id: str | None = None
    workspace: WorkspaceRef | None = None
    error: str | None = None
    result_fetched: bool = False

    @classmethod
    def create(cls, spec: TaskSpec, *, now: datetime | None = None) -> Self:
        moment = now or utc_now()
        return cls(
            id=new_task_id(moment),
            spec=spec,
            created_at=moment,
            updated_at=moment,
        )

    def evolve(self, *, now: datetime | None = None, **changes: object) -> Self:
        merged = {**self.model_dump(), **changes, "updated_at": now or utc_now()}
        return type(self).model_validate(merged)

    def transition(
        self,
        target: TaskState,
        *,
        error: str | None = None,
        now: datetime | None = None,
    ) -> Self:
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransitionError(
                f"Task {self.id} cannot move from {self.state} to {target}",
                details={
                    "task_id": self.id,
                    "from": self.state.value,
                    "to": target.value,
                },
            )
        return self.evolve(state=target, error=error, now=now)


class TaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    diff: str
    changed_files: list[str] = Field(default_factory=list)
    outside_owned_paths: list[str] = Field(default_factory=list)
    summary_truncated: bool = False
    diff_truncated: bool = False


class TaskEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: AwareDatetime = Field(default_factory=utc_now)
    kind: Annotated[str, Field(min_length=1)]
    data: dict[str, JsonValue] = Field(default_factory=dict)


class PermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allow: bool
    reason: Annotated[str, Field(min_length=1)]
