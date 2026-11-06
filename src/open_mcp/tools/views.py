from typing import Self

from pydantic import BaseModel, ConfigDict

from open_mcp.contracts import (
    MergeOutcome,
    ModelInfo,
    SkillInfo,
    Task,
    TaskResult,
)


class TaskView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    spec_title: str
    spec_state: str
    spec_model: str
    spec_repo: str
    spec_base_ref: str
    spec_owned_paths: list[str]
    workspace_branch: str | None
    workspace_base_commit: str | None
    result_fetched: bool
    error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, task: Task) -> Self:
        workspace = task.workspace
        return cls(
            id=task.id,
            spec_title=task.spec.title,
            spec_state=task.state.value,
            spec_model=f"{task.spec.model.provider_id}/{task.spec.model.model_id}",
            spec_repo=task.spec.repo,
            spec_base_ref=task.spec.base_ref,
            spec_owned_paths=list(task.spec.owned_paths),
            workspace_branch=workspace.branch if workspace else None,
            workspace_base_commit=workspace.base_commit if workspace else None,
            result_fetched=task.result_fetched,
            error=task.error,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat(),
        )


class ResultView(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    summary: str
    diff: str
    changed_files: list[str]
    outside_owned_paths: list[str]
    summary_truncated: bool
    diff_truncated: bool

    @classmethod
    def of(cls, task_id: str, result: TaskResult) -> Self:
        return cls(task_id=task_id, **result.model_dump())


class MergeView(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    commit: str
    target_branch: str
    stale_base: bool

    @classmethod
    def of(cls, task_id: str, outcome: MergeOutcome) -> Self:
        return cls(task_id=task_id, **outcome.model_dump())


class ModelSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    model_id: str
    name: str
    free: bool
    supports_tools: bool
    context_tokens: int
    output_tokens: int

    @classmethod
    def of(cls, model: ModelInfo) -> Self:
        return cls(
            provider_id=model.providerID,
            model_id=model.modelID,
            name=model.name,
            free=model.free_tier_available,
            supports_tools=model.capabilities.tools,
            context_tokens=model.limit.context,
            output_tokens=model.limit.output,
        )


class SkillSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str

    @classmethod
    def of(cls, skill: SkillInfo) -> Self:
        return cls(id=skill.id, name=skill.name, description=skill.description)
