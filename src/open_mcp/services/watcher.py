import asyncio

from open_mcp.contracts.errors import OpenMcpError
from open_mcp.contracts.runtime import RuntimeStatus
from open_mcp.contracts.task import Task, TaskEvent, TaskState
from open_mcp.runtimes.base import RuntimeAdapter
from open_mcp.services.permissions import PermissionGate
from open_mcp.store.base import TaskStore

TERMINAL_EVENTS = {
    "session.idle": RuntimeStatus.IDLE,
    "session.failed": RuntimeStatus.FAILED,
    "session.interrupted": RuntimeStatus.FAILED,
}


class _Decisions:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.seen: set[str] = set()


class EventWatcher:
    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimeAdapter,
        gate: PermissionGate,
        *,
        poll_seconds: float = 0.5,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._gate = gate
        self._poll_seconds = poll_seconds

    async def watch(self, task: Task) -> None:
        if task.runtime_session_id is None or task.workspace is None:
            return
        outcome: RuntimeStatus | None = None
        failure: BaseException | None = None
        try:
            outcome = await self._run(task)
        except* OpenMcpError as errors:
            failure = errors.exceptions[0]
        if isinstance(failure, OpenMcpError):
            await self._fail(task.id, failure)
        elif outcome is not None:
            await self._settle(task.id, outcome)

    async def _run(self, task: Task) -> RuntimeStatus:
        decisions = _Decisions()
        async with asyncio.TaskGroup() as group:
            poller = group.create_task(self._poll_permissions(task, decisions))
            try:
                return await self._follow(task, decisions)
            finally:
                poller.cancel()

    async def _follow(self, task: Task, decisions: _Decisions) -> RuntimeStatus:
        session_id = self._session(task)
        while True:
            terminal = await self._consume(task, decisions, follow=True)
            if terminal is not None:
                return terminal
            status = await self._runtime.status(session_id)
            if status is not RuntimeStatus.BUSY:
                drained = await self._consume(task, decisions, follow=False)
                return drained or status
            await asyncio.sleep(self._poll_seconds)

    async def _consume(
        self, task: Task, decisions: _Decisions, *, follow: bool
    ) -> RuntimeStatus | None:
        async for event in self._runtime.events(self._session(task), follow=follow):
            await self._store.append_event(task.id, event)
            kind = event.kind.lower()
            if "permission" in kind and "ask" in kind:
                await self._decide_pending(task, decisions)
            if event.kind in TERMINAL_EVENTS:
                return TERMINAL_EVENTS[event.kind]
        return None

    async def _poll_permissions(self, task: Task, decisions: _Decisions) -> None:
        while True:
            await self._decide_pending(task, decisions)
            await asyncio.sleep(self._poll_seconds)

    async def _decide_pending(self, task: Task, decisions: _Decisions) -> None:
        session_id = self._session(task)
        workspace = task.workspace
        if workspace is None:
            return
        async with decisions.lock:
            for request in await self._runtime.pending_permissions(session_id):
                if request.id in decisions.seen:
                    continue
                decisions.seen.add(request.id)
                decision = await self._gate.decide(workspace, request)
                await self._runtime.reply_permission(
                    session_id, request.id, allow=decision.allow
                )
                await self._store.append_event(
                    task.id,
                    TaskEvent(
                        kind="permission.decided",
                        data={
                            "request_id": request.id,
                            "action": request.kind,
                            "targets": request.targets,
                            "allow": decision.allow,
                            "reason": decision.reason,
                        },
                    ),
                )

    async def _settle(self, task_id: str, outcome: RuntimeStatus) -> None:
        current = await self._store.get(task_id)
        if current.state is not TaskState.RUNNING:
            return
        target = (
            TaskState.FAILED
            if outcome is RuntimeStatus.FAILED
            else TaskState.AWAITING_REVIEW
        )
        await self._store.update(current.transition(target))
        await self._store.append_event(task_id, TaskEvent(kind=f"task.{target.value}"))

    async def _fail(self, task_id: str, exc: OpenMcpError) -> None:
        current = await self._store.get(task_id)
        if current.state is not TaskState.RUNNING:
            return
        failed = current.transition(TaskState.FAILED, error=exc.message)
        await self._store.update(failed)
        await self._store.append_event(
            task_id, TaskEvent(kind="task.watcher_failed", data={"code": exc.code})
        )

    @staticmethod
    def _session(task: Task) -> str:
        if task.runtime_session_id is None:
            raise RuntimeError("A watched task must have a runtime session")
        return task.runtime_session_id
