import asyncio
import os
import secrets
from collections.abc import Callable, Collection
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError

from open_mcp.contracts.errors import TaskNotFoundError, TaskStoreError
from open_mcp.contracts.task import TASK_ID_PATTERN, Task, TaskEvent, TaskState
from open_mcp.store.base import ArtifactName

TASK_FILE = "task.json"
EVENTS_FILE = "events.jsonl"


def atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


class FileTaskStore:
    def __init__(self, root: Path) -> None:
        self._tasks_dir = Path(root) / "tasks"
        self._lock = asyncio.Lock()

    async def create(self, task: Task) -> None:
        await self._run(self._create, task)

    async def get(self, task_id: str) -> Task:
        return await self._run(self._read, task_id)

    async def update(self, task: Task) -> None:
        await self._run(self._update, task)

    async def list_tasks(
        self, *, states: Collection[TaskState] | None = None
    ) -> list[Task]:
        wanted = None if states is None else frozenset(states)
        tasks = await self._run(self._list)
        if wanted is None:
            return tasks
        return [task for task in tasks if task.state in wanted]

    async def append_event(self, task_id: str, event: TaskEvent) -> None:
        await self._run(self._append_event, task_id, event)

    async def read_events(
        self, task_id: str, *, offset: int = 0, limit: int = 100
    ) -> list[TaskEvent]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be >= 0 and limit must be >= 1")
        return await self._run(self._read_events, task_id, offset, limit)

    async def write_artifact(
        self, task_id: str, name: ArtifactName, content: str
    ) -> None:
        await self._run(self._write_artifact, task_id, name, content)

    async def read_artifact(self, task_id: str, name: ArtifactName) -> str | None:
        return await self._run(self._read_artifact, task_id, name)

    async def _run[**P, T](
        self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        async with self._lock:
            try:
                return await asyncio.to_thread(function, *args, **kwargs)
            except OSError as exc:
                raise TaskStoreError(f"Task store I/O failed: {exc}") from exc

    def _directory(self, task_id: str) -> Path:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise TaskNotFoundError(
                f"Task {task_id!r} not found", details={"task_id": task_id}
            )
        return self._tasks_dir / task_id

    def _existing_directory(self, task_id: str) -> Path:
        directory = self._directory(task_id)
        if not (directory / TASK_FILE).is_file():
            raise TaskNotFoundError(
                f"Task {task_id!r} not found", details={"task_id": task_id}
            )
        return directory

    def _create(self, task: Task) -> None:
        directory = self._directory(task.id)
        if directory.exists():
            raise TaskStoreError(
                f"Task {task.id} already exists", details={"task_id": task.id}
            )
        directory.mkdir(parents=True)
        atomic_write_text(directory / TASK_FILE, task.model_dump_json(indent=2))

    def _read(self, task_id: str) -> Task:
        path = self._existing_directory(task_id) / TASK_FILE
        try:
            return Task.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise TaskStoreError(
                f"Task record {task_id} is corrupt",
                details={"task_id": task_id, "path": str(path)},
            ) from exc

    def _update(self, task: Task) -> None:
        directory = self._existing_directory(task.id)
        atomic_write_text(directory / TASK_FILE, task.model_dump_json(indent=2))

    def _list(self) -> list[Task]:
        if not self._tasks_dir.is_dir():
            return []
        tasks = [
            self._read(entry.name)
            for entry in self._tasks_dir.iterdir()
            if TASK_ID_PATTERN.fullmatch(entry.name) and (entry / TASK_FILE).is_file()
        ]
        return sorted(tasks, key=lambda task: (task.created_at, task.id))

    def _append_event(self, task_id: str, event: TaskEvent) -> None:
        directory = self._existing_directory(task_id)
        line = event.model_dump_json() + "\n"
        with (directory / EVENTS_FILE).open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _read_events(self, task_id: str, offset: int, limit: int) -> list[TaskEvent]:
        directory = self._existing_directory(task_id)
        path = directory / EVENTS_FILE
        if not path.is_file():
            return []
        *complete, tail = path.read_text(encoding="utf-8").split("\n")
        events = [self._parse_event(task_id, line) for line in complete]
        if tail.strip():
            with suppress(ValidationError):
                events.append(TaskEvent.model_validate_json(tail))
        return events[offset : offset + limit]

    @staticmethod
    def _parse_event(task_id: str, line: str) -> TaskEvent:
        try:
            return TaskEvent.model_validate_json(line)
        except ValidationError as exc:
            raise TaskStoreError(
                f"Event log of task {task_id} is corrupt",
                details={"task_id": task_id},
            ) from exc

    def _write_artifact(self, task_id: str, name: ArtifactName, content: str) -> None:
        directory = self._existing_directory(task_id)
        atomic_write_text(directory / name.value, content)

    def _read_artifact(self, task_id: str, name: ArtifactName) -> str | None:
        directory = self._existing_directory(task_id)
        path = directory / name.value
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
