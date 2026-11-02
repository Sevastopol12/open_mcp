from typing import Protocol, runtime_checkable

from open_mcp.contracts.task import TaskSpec, WorkspaceRef
from open_mcp.contracts.workspace import MergeOutcome, WorkspaceDiff


@runtime_checkable
class WorkspaceProvider(Protocol):
    async def prepare(self, spec: TaskSpec, task_id: str) -> WorkspaceRef: ...

    async def snapshot(self, workspace: WorkspaceRef, message: str) -> str | None: ...

    async def collect_diff(self, workspace: WorkspaceRef) -> WorkspaceDiff: ...

    async def merge(
        self, workspace: WorkspaceRef, *, allow_stale_base: bool = False
    ) -> MergeOutcome: ...

    async def cleanup(self, workspace: WorkspaceRef) -> None: ...

    async def discard(self, workspace: WorkspaceRef) -> None: ...
