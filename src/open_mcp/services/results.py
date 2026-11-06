from collections.abc import Sequence

from open_mcp.contracts.task import TaskEvent, TaskResult, paths_outside
from open_mcp.contracts.workspace import WorkspaceDiff

MAX_RESULT_LINES = 300


def shape_result(
    events: list[TaskEvent],
    workspace_diff: WorkspaceDiff,
    summary: str | None = None,
    *,
    owned_paths: Sequence[str] = (),
) -> TaskResult:
    if summary is None:
        summary = (
            _last_assistant_text(events)
            or "Task completed. Review the diff for details."
        )
    bounded_summary, summary_truncated = _bound(summary)
    bounded_diff, diff_truncated = _bound(workspace_diff.diff)
    return TaskResult(
        summary=bounded_summary,
        diff=bounded_diff,
        changed_files=workspace_diff.changed_files,
        outside_owned_paths=paths_outside(owned_paths, workspace_diff.changed_files)
        if owned_paths
        else [],
        summary_truncated=summary_truncated,
        diff_truncated=diff_truncated,
    )


def _last_assistant_text(events: list[TaskEvent]) -> str | None:
    for event in reversed(events):
        if "assistant" in event.kind.lower():
            for key in ("text", "message", "summary"):
                value = event.data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _bound(value: str) -> tuple[str, bool]:
    lines = value.splitlines()
    if len(lines) <= MAX_RESULT_LINES:
        return value, False
    return "\n".join(
        lines[: MAX_RESULT_LINES - 1] + ["[truncated; full result is stored on disk]"]
    ), True
