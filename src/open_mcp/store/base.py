from collections.abc import Collection
from enum import StrEnum
from typing import Protocol

from open_mcp.contracts.task import Task, TaskEvent, TaskState


class ArtifactName(StrEnum):
    SUMMARY = "summary.md"
    DIFF = "diff.patch"


class TaskStore(Protocol):
    async def create(self, task: Task) -> None: ...

    async def get(self, task_id: str) -> Task: ...

    async def update(self, task: Task) -> None: ...

    async def list_tasks(
        self, *, states: Collection[TaskState] | None = None
    ) -> list[Task]: ...

    async def append_event(self, task_id: str, event: TaskEvent) -> None: ...

    async def read_events(
        self, task_id: str, *, offset: int = 0, limit: int = 100
    ) -> list[TaskEvent]: ...

    async def write_artifact(
        self, task_id: str, name: ArtifactName, content: str
    ) -> None: ...

    async def read_artifact(self, task_id: str, name: ArtifactName) -> str | None: ...
