import asyncio
from collections.abc import Collection

from open_mcp.contracts.errors import (
    InvalidTransitionError,
    RuntimeUnavailableError,
    WorkspaceError,
)
from open_mcp.contracts.runtime import RuntimeStatus
from open_mcp.contracts.task import (
    SLOT_STATES,
    Task,
    TaskEvent,
    TaskResult,
    TaskSpec,
    TaskState,
    owned_paths_overlap,
)
from open_mcp.runtimes.base import RuntimeAdapter
from open_mcp.services.permissions import PermissionGate
from open_mcp.services.prompts import build_task_prompt
from open_mcp.services.results import shape_result
from open_mcp.services.watcher import EventWatcher
from open_mcp.settings import Settings
from open_mcp.store.base import ArtifactName, TaskStore
from open_mcp.workspaces.base import WorkspaceProvider


class TaskService:
    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimeAdapter,
        workspace: WorkspaceProvider,
        settings: Settings,
        *,
        gate: PermissionGate | None = None,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._workspace = workspace
        self._settings = settings
        self._gate = gate or PermissionGate()
        self._watcher = EventWatcher(
            store, runtime, self._gate, poll_seconds=settings.permission_poll_seconds
        )
        self._lock = asyncio.Lock()
        self._watchers: dict[str, asyncio.Task[None]] = {}
        self._finished: set[asyncio.Task[None]] = set()

    async def delegate(self, spec: TaskSpec) -> Task:
        async with self._lock:
            tasks = await self._store.list_tasks(states=SLOT_STATES)
            if len(tasks) >= self._settings.max_parallel_tasks:
                raise WorkspaceError("The task concurrency limit has been reached")
            for active in tasks:
                if active.spec.repo == spec.repo and owned_paths_overlap(
                    active.spec.owned_paths, spec.owned_paths
                ):
                    raise WorkspaceError(
                        "Task owned paths overlap",
                        details={
                            "task_id": active.id,
                            "overlap": ",".join(spec.owned_paths),
                        },
                    )
            task = Task.create(spec).transition(TaskState.PREPARING)
            await self._store.create(task)
            await self._store.append_event(task.id, TaskEvent(kind="task.preparing"))
            try:
                workspace = await self._workspace.prepare(spec, task.id)
                task = task.evolve(workspace=workspace)
                await self._store.update(task)
                session_id = await self._runtime.start(task, build_task_prompt(spec))
                task = task.transition(TaskState.RUNNING).evolve(
                    runtime_session_id=session_id
                )
                await self._store.update(task)
                await self._store.append_event(task.id, TaskEvent(kind="task.running"))
                self._spawn_watcher(task)
                return task
            except Exception as exc:
                latest = await self._store.get(task.id)
                if latest.state in (TaskState.PENDING, TaskState.PREPARING):
                    latest = latest.transition(TaskState.FAILED, error=str(exc))
                    await self._store.update(latest)
                if latest.workspace is not None:
                    await self._workspace.discard(latest.workspace)
                raise

    async def list_tasks(
        self, states: Collection[TaskState] | None = None
    ) -> list[Task]:
        return await self._store.list_tasks(states=states)

    async def status(self, task_id: str) -> Task:
        task = await self._store.get(task_id)
        if task.runtime_session_id and task.state in (
            TaskState.RUNNING,
            TaskState.CHANGES_REQUESTED,
        ):
            status = await self._runtime.status(task.runtime_session_id)
            if status is not RuntimeStatus.BUSY and task.state is TaskState.RUNNING:
                target = (
                    TaskState.FAILED
                    if status is RuntimeStatus.FAILED
                    else TaskState.AWAITING_REVIEW
                )
                task = task.transition(target)
                await self._store.update(task)
        return task

    async def wait(self, task_id: str, timeout_seconds: float | None = None) -> Task:
        task = await self._store.get(task_id)
        if task.runtime_session_id is None:
            return task
        bound = min(
            timeout_seconds or self._settings.wait_bound_seconds,
            self._settings.wait_bound_seconds,
        )
        status = await self._runtime.wait(task.runtime_session_id, bound)
        if status is RuntimeStatus.BUSY:
            return task
        return await self.status(task_id)

    async def result(self, task_id: str) -> TaskResult:
        task = await self._store.get(task_id)
        if task.state is not TaskState.AWAITING_REVIEW or task.workspace is None:
            raise InvalidTransitionError("Task result is available only for review")
        await self._workspace.snapshot(task.workspace, f"Snapshot task {task.id}")
        diff = await self._workspace.collect_diff(task.workspace)
        events = await self._store.read_events(task.id, limit=100000)
        result = shape_result(events, diff, owned_paths=task.spec.owned_paths)
        await self._store.write_artifact(task.id, ArtifactName.SUMMARY, result.summary)
        await self._store.write_artifact(task.id, ArtifactName.DIFF, result.diff)
        task = task.evolve(result_fetched=True)
        await self._store.update(task)
        return result

    async def request_changes(self, task_id: str, feedback: str) -> Task:
        task = await self._store.get(task_id)
        if task.runtime_session_id is None:
            raise RuntimeUnavailableError("Task has no runtime session")
        if task.state is not TaskState.CHANGES_REQUESTED:
            task = task.transition(TaskState.CHANGES_REQUESTED)
            await self._store.update(task)
        await self._runtime.send(task.runtime_session_id, feedback)
        task = task.transition(TaskState.RUNNING).evolve(result_fetched=False)
        await self._store.update(task)
        await self._store.append_event(
            task.id,
            TaskEvent(kind="task.changes_requested", data={"feedback": feedback}),
        )
        self._spawn_watcher(task)
        return task

    async def cancel(self, task_id: str) -> Task:
        task = await self._store.get(task_id)
        self._stop_watcher(task.id)
        if task.runtime_session_id:
            await self._runtime.interrupt(task.runtime_session_id)
        if task.state not in (
            TaskState.CANCELLED,
            TaskState.MERGED,
            TaskState.DISCARDED,
        ):
            task = task.transition(TaskState.CANCELLED)
            await self._store.update(task)
        return task

    async def merge(self, task_id: str, *, allow_stale_base: bool = False):
        task = await self._store.get(task_id)
        if (
            task.state is not TaskState.AWAITING_REVIEW
            or not task.result_fetched
            or task.workspace is None
        ):
            raise InvalidTransitionError(
                "Task must be reviewed with task_result before merge"
            )
        outcome = await self._workspace.merge(
            task.workspace, allow_stale_base=allow_stale_base
        )
        task = task.transition(TaskState.MERGED)
        await self._store.update(task)
        await self._workspace.cleanup(task.workspace)
        return outcome

    async def discard(self, task_id: str) -> Task:
        task = await self._store.get(task_id)
        if task.workspace:
            await self._workspace.discard(task.workspace)
        if task.state not in (TaskState.DISCARDED, TaskState.MERGED):
            task = task.transition(TaskState.DISCARDED)
            await self._store.update(task)
        return task

    async def recover(self) -> list[Task]:
        recovered: list[Task] = []
        for task in await self._store.list_tasks(states=SLOT_STATES):
            if task.runtime_session_id is None:
                updated = task.transition(
                    TaskState.FAILED, error="missing runtime session during recovery"
                )
            else:
                status = await self._runtime.status(task.runtime_session_id)
                if status is RuntimeStatus.BUSY:
                    updated = task
                    self._spawn_watcher(task)
                else:
                    target = (
                        TaskState.FAILED
                        if status is RuntimeStatus.FAILED
                        else TaskState.AWAITING_REVIEW
                    )
                    updated = task.transition(target)
            if updated != task:
                await self._store.update(updated)
            recovered.append(updated)
        return recovered

    async def aclose(self) -> None:
        for task_id in list(self._watchers):
            self._stop_watcher(task_id)
        await asyncio.gather(*self._finished, return_exceptions=True)
        self._finished.clear()

    def _spawn_watcher(self, task: Task) -> None:
        self._stop_watcher(task.id)
        watching = asyncio.create_task(self._watcher.watch(task))
        self._watchers[task.id] = watching
        self._finished.add(watching)
        watching.add_done_callback(self._finished.discard)
        watching.add_done_callback(lambda done: self._forget(task.id, done))

    def _stop_watcher(self, task_id: str) -> None:
        watching = self._watchers.pop(task_id, None)
        if watching is not None and not watching.done():
            watching.cancel()

    def _forget(self, task_id: str, done: asyncio.Task[None]) -> None:
        if self._watchers.get(task_id) is done:
            del self._watchers[task_id]
