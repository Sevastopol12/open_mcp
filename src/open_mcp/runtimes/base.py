from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from open_mcp.contracts.model_info import ModelInfo
from open_mcp.contracts.runtime import PermissionRequest, RuntimeStatus
from open_mcp.contracts.skill_info import SkillInfo
from open_mcp.contracts.task import Task, TaskEvent


@runtime_checkable
class RuntimeAdapter(Protocol):
    async def list_models(self, *, free_only: bool = True) -> list[ModelInfo]: ...

    async def list_skills(self) -> list[SkillInfo]: ...

    async def start(self, task: Task, prompt: str) -> str: ...

    async def send(self, session_id: str, text: str) -> None: ...

    async def wait(self, session_id: str, timeout_seconds: float) -> RuntimeStatus: ...

    async def status(self, session_id: str) -> RuntimeStatus: ...

    async def interrupt(self, session_id: str) -> bool: ...

    def events(
        self, session_id: str, *, follow: bool = True
    ) -> AsyncIterator[TaskEvent]: ...

    async def pending_permissions(self, session_id: str) -> list[PermissionRequest]: ...

    async def reply_permission(
        self, session_id: str, request_id: str, *, allow: bool
    ) -> None: ...
