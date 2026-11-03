from typing import Annotated

from pydantic import Field, ValidationError

from open_mcp.contracts import (
    InvalidRequestError,
    ModelNotAvailableError,
    ModelRef,
    TaskSpec,
    TaskState,
)
from open_mcp.runtimes.base import RuntimeAdapter
from open_mcp.services import TaskService
from open_mcp.tools.views import (
    MergeView,
    ModelSummary,
    ResultView,
    SkillSummary,
    TaskView,
)

TaskId = Annotated[str, Field(description="Id returned by delegate_task.")]


class TaskTools:
    def __init__(self, tasks: TaskService, runtime: RuntimeAdapter) -> None:
        self._tasks = tasks
        self._runtime = runtime

    async def available_models(
        self,
        free_only: Annotated[
            bool, Field(description="Only models with no cost. Keep true by default.")
        ] = True,
    ) -> list[ModelSummary]:
        models = await self._runtime.list_models(free_only=free_only)
        return [ModelSummary.of(model) for model in models]

    async def available_skills(self) -> list[SkillSummary]:
        return [SkillSummary.of(skill) for skill in await self._runtime.list_skills()]

    async def delegate_task(
        self,
        title: Annotated[str, Field(description="Short title, at most 120 chars.")],
        prompt: Annotated[
            str, Field(description="Complete, self-contained instructions.")
        ],
        repo: Annotated[
            str,
            Field(
                description="Absolute path of the repository directory the user named."
            ),
        ],
        owned_paths: Annotated[
            list[str],
            Field(
                description=(
                    "Repo-relative files or folders this task may change. "
                    "Must not overlap with any other active task."
                )
            ),
        ],
        provider_id: Annotated[
            str, Field(description="Provider id from available_models.")
        ],
        model_id: Annotated[str, Field(description="Model id from available_models.")],
        base_ref: Annotated[
            str, Field(description="Branch, tag or commit to start from.")
        ] = "HEAD",
        skill: Annotated[
            str | None, Field(description="Optional skill name from available_skills.")
        ] = None,
        allow_paid: Annotated[
            bool, Field(description="Allow a model that is not free. Default false.")
        ] = False,
    ) -> TaskView:
        await self._require_model(provider_id, model_id, allow_paid=allow_paid)
        try:
            spec = TaskSpec(
                title=title,
                prompt=prompt,
                repo=repo,
                base_ref=base_ref,
                model=ModelRef(provider_id=provider_id, model_id=model_id),
                skill=skill,
                owned_paths=owned_paths,
            )
        except ValidationError as exc:
            raise _invalid(exc) from exc
        return TaskView.of(await self._tasks.delegate(spec))

    async def task_status(self, task_id: TaskId) -> TaskView:
        return TaskView.of(await self._tasks.status(task_id))

    async def list_tasks(
        self,
        state: Annotated[
            str | None,
            Field(
                description=(
                    "Only tasks in this state: "
                    + ", ".join(item.value for item in TaskState)
                    + "."
                )
            ),
        ] = None,
    ) -> list[TaskView]:
        wanted = None if state is None else {_parse_state(state)}
        return [TaskView.of(task) for task in await self._tasks.list_tasks(wanted)]

    async def wait_for_task(
        self,
        task_id: TaskId,
        timeout_seconds: Annotated[
            float,
            Field(gt=0, description="Wait at most this long; the server caps it."),
        ] = 25.0,
    ) -> TaskView:
        return TaskView.of(await self._tasks.wait(task_id, timeout_seconds))

    async def task_result(self, task_id: TaskId) -> ResultView:
        return ResultView.of(task_id, await self._tasks.result(task_id))

    async def request_changes(
        self,
        task_id: TaskId,
        feedback: Annotated[
            str, Field(min_length=1, description="Concrete corrections to apply.")
        ],
    ) -> TaskView:
        return TaskView.of(await self._tasks.request_changes(task_id, feedback))

    async def cancel_task(self, task_id: TaskId) -> TaskView:
        return TaskView.of(await self._tasks.cancel(task_id))

    async def merge_task(
        self,
        task_id: TaskId,
        allow_stale_base: Annotated[
            bool,
            Field(description="Merge even if the repository moved past the task base."),
        ] = False,
    ) -> MergeView:
        outcome = await self._tasks.merge(task_id, allow_stale_base=allow_stale_base)
        return MergeView.of(task_id, outcome)

    async def discard_task(self, task_id: TaskId) -> TaskView:
        return TaskView.of(await self._tasks.discard(task_id))

    async def _require_model(
        self, provider_id: str, model_id: str, *, allow_paid: bool
    ) -> None:
        models = await self._runtime.list_models(free_only=(not allow_paid))
        if not any(
            model.providerID == provider_id and model.modelID == model_id
            for model in models
        ):
            raise ModelNotAvailableError(
                "The model is not available"
                + ("" if allow_paid else " as a free model"),
                details={"provider_id": provider_id, "model_id": model_id},
            )


def _parse_state(value: str) -> TaskState:
    try:
        return TaskState(value)
    except ValueError as exc:
        raise InvalidRequestError(
            "Unknown task state",
            details={"state": value, "allowed": ", ".join(s.value for s in TaskState)},
        ) from exc


def _invalid(exc: ValidationError) -> InvalidRequestError:
    problems = {
        ".".join(str(part) for part in error["loc"]) or "request": error["msg"]
        for error in exc.errors()
    }
    return InvalidRequestError("The task request is invalid", details=problems)
