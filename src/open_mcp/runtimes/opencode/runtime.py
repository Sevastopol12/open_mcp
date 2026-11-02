import json
from collections.abc import AsyncIterator

from pydantic import ValidationError

from open_mcp.contracts.errors import (
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
        payload = await self._client.get(paths.SKILLS)
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeResponseError("The skill list had an unexpected shape")
        try:
            return [
                SkillInfo.model_validate(
                    {**item, "description": item.get("description", "")}
                )
                for item in items
            ]
        except (TypeError, ValidationError) as exc:
            raise RuntimeResponseError(
                "Some skills did not match the expected schema"
            ) from exc

    async def start(self, task: Task, prompt: str) -> str:
        workspace = task.workspace
        if workspace is None:
            raise RuntimeResponseError("A workspace is required to start a session")
        payload = await self._client.post(
            paths.session_create(),
            json={
                "title": task.spec.title,
                "model": {
                    "providerID": task.spec.model.provider_id,
                    "id": task.spec.model.model_id,
                },
                "location": {"directory": workspace.ref},
                "permissions": [],
            },
        )
        body = payload.get("data") if isinstance(payload, dict) else None
        session_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeResponseError(
                "The session create response had an unexpected shape"
            )
        await self.send(session_id, prompt)
        return session_id

    async def status(self, session_id: str) -> RuntimeStatus:
        active = await self._client.get(paths.ACTIVE_SESSIONS)
        data = active.get("data") if isinstance(active, dict) else None
        if not isinstance(data, dict):
            raise RuntimeResponseError(
                "The active session response had an unexpected shape"
            )
        if session_id in data:
            return RuntimeStatus.BUSY
        session = await self._client.get(paths.session_get(session_id))
        body = session.get("data") if isinstance(session, dict) else None
        if not isinstance(body, dict):
            raise RuntimeResponseError("The session response had an unexpected shape")
        return (
            RuntimeStatus.FAILED
            if body.get("outcome") in {"failed", "interrupted"}
            else RuntimeStatus.IDLE
        )

    async def events(self, session_id: str) -> AsyncIterator[TaskEvent]:
        async for frame in self._client.stream_sse(
            paths.session_log(session_id), params={"follow": "true"}
        ):
            event = frame.get("event")
            raw_data = frame.get("data")
            try:
                data = json.loads(raw_data) if raw_data is not None else None
            except ValueError as exc:
                raise RuntimeResponseError(
                    "The session event data was not valid JSON"
                ) from exc
            if not isinstance(event, str) or not isinstance(data, dict):
                raise RuntimeResponseError("The session event had an unexpected shape")
            kind = data.get("type", event)
            if not isinstance(kind, str):
                raise RuntimeResponseError("The session event type was unexpected")
            yield TaskEvent(kind=kind, data=data)

    async def pending_permissions(self, session_id: str) -> list[PermissionRequest]:
        payload = await self._client.get(paths.session_permissions(session_id))
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeResponseError("The permission list had an unexpected shape")
        try:
            return [
                PermissionRequest(
                    id=item["id"],
                    session_id=item["sessionID"],
                    kind=item["action"],
                    targets=item.get("resources", []),
                    detail=item.get("message", ""),
                )
                for item in items
            ]
        except (KeyError, TypeError, ValidationError) as exc:
            raise RuntimeResponseError(
                "A permission request had an unexpected shape"
            ) from exc

    async def reply_permission(
        self, session_id: str, request_id: str, *, allow: bool
    ) -> None:
        await self._client.post(
            paths.session_permission_reply(session_id, request_id),
            json={"decision": "once" if allow else "reject"},
        )
