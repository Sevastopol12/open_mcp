from collections.abc import AsyncIterator

from pydantic import ValidationError

from open_mcp.contracts.errors import (
    RuntimeCapabilityError,
    RuntimeResponseError,
    RuntimeTimeoutError,
)
from open_mcp.contracts.model_info import ModelInfo
from open_mcp.contracts.runtime import PermissionRequest, RuntimeStatus
from open_mcp.contracts.skill_info import SkillInfo
from open_mcp.contracts.task import Task, TaskEvent
from open_mcp.runtimes.opencode import paths
from open_mcp.runtimes.opencode.client import OpencodeClient

MAX_LISTED_INVALID = 500


class OpencodeRuntime:
    def __init__(self, client: OpencodeClient) -> None:
        self._client = client

    async def list_models(self, *, free_only: bool = True) -> list[ModelInfo]:
        payload = await self._client.get(paths.MODELS)
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeResponseError("The model list had an unexpected shape")
        models: list[ModelInfo] = []
        invalid: list[str] = []
        for item in items:
            try:
                models.append(ModelInfo.model_validate(item))
            except ValidationError:
                invalid.append(
                    str(item.get("id", "?")) if isinstance(item, dict) else "?"
                )
        if invalid:
            raise RuntimeResponseError(
                "Some models did not match the expected schema",
                details={"models": ", ".join(invalid)[:MAX_LISTED_INVALID]},
            )
        return [
            model
            for model in models
            if model.enabled and (model.free_tier_available or not free_only)
        ]

    async def send(self, session_id: str, text: str) -> None:
        await self._client.post(paths.session_prompt(session_id), json={"text": text})

    async def wait(self, session_id: str, timeout_seconds: float) -> RuntimeStatus:
        try:
            await self._client.post(
                paths.session_wait(session_id), read_timeout_seconds=timeout_seconds
            )
        except RuntimeTimeoutError:
            return RuntimeStatus.BUSY
        return RuntimeStatus.IDLE

    async def interrupt(self, session_id: str) -> bool:
        payload = await self._client.post(paths.session_interrupt(session_id))
        body = payload.get("data", payload) if isinstance(payload, dict) else None
        interrupted = body.get("interrupted") if isinstance(body, dict) else None
        if not isinstance(interrupted, bool):
            raise RuntimeResponseError("The interrupt response had an unexpected shape")
        return interrupted

    async def list_skills(self) -> list[SkillInfo]:
        raise self._unsupported("list_skills", "G5")

    async def start(self, task: Task, prompt: str) -> str:
        raise self._unsupported("start", "G4, G6")

    async def status(self, session_id: str) -> RuntimeStatus:
        raise self._unsupported("status", "G3, G4")

    async def events(self, session_id: str) -> AsyncIterator[TaskEvent]:
        raise self._unsupported("events", "G3")
        yield

    async def pending_permissions(self, session_id: str) -> list[PermissionRequest]:
        raise self._unsupported("pending_permissions", "G2")

    async def reply_permission(
        self, session_id: str, request_id: str, *, allow: bool
    ) -> None:
        raise self._unsupported("reply_permission", "G2")

    @staticmethod
    def _unsupported(operation: str, gaps: str) -> RuntimeCapabilityError:
        return RuntimeCapabilityError(
            f"{operation} is not implemented yet (opencode contract gaps)",
            details={"operation": operation, "gaps": gaps},
        )
