from open_mcp.contracts.errors import OpenMcpError
from open_mcp.contracts.runtime import RuntimeStatus
from open_mcp.contracts.task import Task, TaskEvent, TaskState
from open_mcp.runtimes.base import RuntimeAdapter
from open_mcp.services.permissions import PermissionGate
from open_mcp.store.base import TaskStore


class EventWatcher:
    def __init__(self, store: TaskStore, runtime: RuntimeAdapter, gate: PermissionGate):
        self._store = store
        self._runtime = runtime
        self._gate = gate

    async def watch(self, task: Task) -> None:
        try:
            await self._follow(task)
        except OpenMcpError as exc:
            await self._fail(task.id, exc)

    async def _fail(self, task_id: str, exc: OpenMcpError) -> None:
        current = await self._store.get(task_id)
        if current.state is not TaskState.RUNNING:
            return
        failed = current.transition(TaskState.FAILED, error=exc.message)
        await self._store.update(failed)
        await self._store.append_event(
            task_id, TaskEvent(kind="task.watcher_failed", data={"code": exc.code})
        )

    async def _follow(self, task: Task) -> None:
        if task.runtime_session_id is None or task.workspace is None:
            return
        async for event in self._runtime.events(task.runtime_session_id):
            await self._store.append_event(task.id, event)
            if "permission" in event.kind.lower() and "ask" in event.kind.lower():
                requests = await self._runtime.pending_permissions(
                    task.runtime_session_id
                )
                for request in requests:
                    decision = await self._gate.decide(task.workspace, request)
                    await self._runtime.reply_permission(
                        task.runtime_session_id, request.id, allow=decision.allow
                    )
                    await self._store.append_event(
                        task.id,
                        TaskEvent(
                            kind="permission.decided",
                            data={
                                "request_id": request.id,
                                "allow": decision.allow,
                                "reason": decision.reason,
                            },
                        ),
                    )
        status = await self._runtime.status(task.runtime_session_id)
        current = await self._store.get(task.id)
        if current.state is not TaskState.RUNNING:
            return
        target = (
            TaskState.FAILED
            if status is RuntimeStatus.FAILED
            else TaskState.AWAITING_REVIEW
        )
        updated = current.transition(target)
        await self._store.update(updated)
        await self._store.append_event(task.id, TaskEvent(kind=f"task.{target.value}"))
