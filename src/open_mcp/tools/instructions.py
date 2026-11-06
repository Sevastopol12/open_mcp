INSTRUCTIONS = """\
open_mcp lets you delegate building work to sub-agents so you can focus on
discussing with the user, planning, and validating.

Workflow:
1. Plan. Discuss with the user. Publish a plan of NON-OVERLAPPING tasks, each with
   the repo-relative paths it owns, so tasks can run in parallel.
2. Delegate. Call available_models (free models) once, then delegate_task once per
   task. Each task gets its own git worktree and branch. Use the repo directory the
   user named. Tools return quickly: poll with task_status or wait_for_task.
3. Validate and correct. When a task is awaiting_review, call task_result and read
   the summary and diff. Check that outside_owned_paths is empty, that the code is
   correct, and that it follows the codebase's patterns and conventions. If not, call
   request_changes with concrete corrections and review again. merge_task is refused
   until the latest result has been read. After you merge one task, the other tasks
   of the same plan have a stale base: merge them with allow_stale_base=true once
   their diff is reviewed. A conflicting merge is aborted and reported, never forced.
4. Report. When everything is in line, report to the user in 200-300 lines and ask
   them to verify manually.

Never run git yourself. Use discard_task or cancel_task to abandon work.
"""
