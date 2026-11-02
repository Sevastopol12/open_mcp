import asyncio
import os
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from open_mcp.contracts.errors import (
    WorkspaceAccessError,
    WorkspaceConflictError,
    WorkspaceDirtyError,
    WorkspaceError,
    WorkspaceStaleBaseError,
)
from open_mcp.contracts.task import TASK_ID_PATTERN, TaskSpec, WorkspaceRef
from open_mcp.contracts.workspace import MergeOutcome, WorkspaceDiff

KIND = "local-git"
STDERR_CHARS = 500
COMMAND_CHARS = 200
FALLBACK_IDENTITY = {"user.name": "open_mcp", "user.email": "open_mcp@localhost"}


@dataclass(frozen=True)
class GitResult:
    code: int
    stdout: str
    stderr: str


async def run_git(*args: str, cwd: Path) -> GitResult:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise WorkspaceError("The git executable was not found") from exc
    stdout, stderr = await process.communicate()
    return GitResult(
        code=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


async def git(*args: str, cwd: Path) -> str:
    result = await run_git(*args, cwd=cwd)
    if result.code != 0:
        raise WorkspaceError(
            "A git command failed",
            details={
                "command": " ".join(args)[:COMMAND_CHARS],
                "stderr": result.stderr.strip()[:STDERR_CHARS],
            },
        )
    return result.stdout


class LocalGitWorktree:
    def __init__(self, worktrees_dir: Path, allowed_roots: Sequence[Path]) -> None:
        self._worktrees_dir = Path(worktrees_dir)
        self._roots = tuple(Path(root).resolve() for root in allowed_roots)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def prepare(self, spec: TaskSpec, task_id: str) -> WorkspaceRef:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise WorkspaceError("Invalid task id", details={"task_id": task_id})
        if spec.base_ref.startswith("-"):
            raise WorkspaceError("base_ref must not start with '-'")
        requested = self._resolve_repo(spec.repo)
        self._require_allowed(requested)
        reported = (await git("rev-parse", "--show-toplevel", cwd=requested)).strip()
        top_level = await asyncio.to_thread(self._resolve_path, reported)
        self._require_allowed(top_level)
        branch = f"task/{task_id}"
        path = self._worktrees_dir / task_id
        async with self._locks[str(top_level)]:
            base_commit = (
                await git(
                    "rev-parse",
                    "--verify",
                    "--end-of-options",
                    f"{spec.base_ref}^{{commit}}",
                    cwd=top_level,
                )
            ).strip()
            if path.exists():
                raise WorkspaceError(
                    "A worktree for this task already exists",
                    details={"task_id": task_id},
                )
            self._worktrees_dir.mkdir(parents=True, exist_ok=True)
            await git(
                "worktree", "add", "-b", branch, str(path), base_commit, cwd=top_level
            )
        return WorkspaceRef(
            kind=KIND,
            origin=str(top_level),
            ref=str(path.resolve()),
            branch=branch,
            base_commit=base_commit,
        )

    async def snapshot(self, workspace: WorkspaceRef, message: str) -> str | None:
        path = self._worktree_path(workspace)
        if not (await git("status", "--porcelain", cwd=path)).strip():
            return None
        await git("add", "-A", cwd=path)
        identity = await self._commit_options(path)
        await git(*identity, "commit", "--no-verify", "-m", message, cwd=path)
        return (await git("rev-parse", "HEAD", cwd=path)).strip()

    async def collect_diff(self, workspace: WorkspaceRef) -> WorkspaceDiff:
        path = self._worktree_path(workspace)
        range_args = (workspace.base_commit, workspace.branch, "--")
        diff = await git(
            "diff", "--no-color", "--no-ext-diff", "--no-renames", *range_args, cwd=path
        )
        names = await git(
            "diff", "--name-only", "-z", "--no-renames", *range_args, cwd=path
        )
        dirty = bool((await git("status", "--porcelain", cwd=path)).strip())
        return WorkspaceDiff(
            diff=diff,
            changed_files=sorted({name for name in names.split("\0") if name}),
            has_uncommitted_changes=dirty,
        )

    async def merge(
        self, workspace: WorkspaceRef, *, allow_stale_base: bool = False
    ) -> MergeOutcome:
        path = self._worktree_path(workspace)
        repo = self._origin(workspace)
        async with self._locks[str(repo)]:
            if (await git("status", "--porcelain", cwd=path)).strip():
                raise WorkspaceDirtyError(
                    "The task worktree has uncommitted changes; snapshot it first",
                    details={"branch": workspace.branch},
                )
            task_tip = (await git("rev-parse", workspace.branch, cwd=repo)).strip()
            if task_tip == workspace.base_commit:
                raise WorkspaceError(
                    "The task has no changes to merge",
                    details={"branch": workspace.branch},
                )
            if (
                await git("status", "--porcelain", "--untracked-files=no", cwd=repo)
            ).strip():
                raise WorkspaceDirtyError(
                    "The target repository has uncommitted changes",
                    details={"repo": str(repo)},
                )
            head = await run_git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=repo)
            if head.code != 0:
                raise WorkspaceError("The target repository HEAD is detached")
            target = head.stdout.strip()
            target_tip = (await git("rev-parse", "HEAD", cwd=repo)).strip()
            stale = target_tip != workspace.base_commit
            if stale:
                ancestry = await run_git(
                    "merge-base",
                    "--is-ancestor",
                    workspace.base_commit,
                    target_tip,
                    cwd=repo,
                )
                if ancestry.code != 0:
                    raise WorkspaceError(
                        "The target branch does not contain the task base commit",
                        details={"target": target, "base": workspace.base_commit},
                    )
                if not allow_stale_base:
                    raise WorkspaceStaleBaseError(
                        "The target branch moved since the task started",
                        details={
                            "target": target,
                            "base": workspace.base_commit,
                            "tip": target_tip,
                        },
                    )
            options = await self._commit_options(repo)
            result = await run_git(
                *options,
                "merge",
                "--no-ff",
                "--no-verify",
                "-m",
                f"Merge {workspace.branch}",
                workspace.branch,
                cwd=repo,
            )
            if result.code != 0:
                await self._abort_merge(repo, result)
            commit = (await git("rev-parse", "HEAD", cwd=repo)).strip()
        return MergeOutcome(commit=commit, target_branch=target, stale_base=stale)

    async def cleanup(self, workspace: WorkspaceRef) -> None:
        path = self._worktree_path(workspace)
        repo = self._origin(workspace)
        async with self._locks[str(repo)]:
            if (await git("status", "--porcelain", cwd=path)).strip():
                raise WorkspaceDirtyError(
                    "The task worktree has uncommitted changes; use discard",
                    details={"branch": workspace.branch},
                )
            merged = await run_git(
                "merge-base", "--is-ancestor", workspace.branch, "HEAD", cwd=repo
            )
            if merged.code != 0:
                raise WorkspaceError(
                    "The task branch is not merged; use discard to drop it",
                    details={"branch": workspace.branch},
                )
            await git("worktree", "remove", "--force", str(path), cwd=repo)
            await git("branch", "-d", workspace.branch, cwd=repo)

    async def discard(self, workspace: WorkspaceRef) -> None:
        path = self._worktree_path(workspace, must_exist=False)
        repo = self._origin(workspace)
        async with self._locks[str(repo)]:
            if path.exists():
                await git("worktree", "remove", "--force", str(path), cwd=repo)
            await git("worktree", "prune", cwd=repo)
            known = await run_git(
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{workspace.branch}",
                cwd=repo,
            )
            if known.code == 0:
                await git("branch", "-D", workspace.branch, cwd=repo)

    @staticmethod
    def _resolve_path(value: str) -> Path:
        return Path(value).resolve()

    def _resolve_repo(self, repo: str) -> Path:
        try:
            return Path(repo).expanduser().resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as exc:
            raise WorkspaceError(
                "The repository path does not exist", details={"repo": repo}
            ) from exc

    def _require_allowed(self, path: Path) -> None:
        if not self._roots:
            raise WorkspaceAccessError(
                "No workspace roots are configured", details={"path": str(path)}
            )
        if not any(path == root or path.is_relative_to(root) for root in self._roots):
            raise WorkspaceAccessError(
                "The path is outside the allowed workspace roots",
                details={"path": str(path)},
            )

    def _origin(self, workspace: WorkspaceRef) -> Path:
        self._require_kind(workspace)
        origin = Path(workspace.origin).resolve()
        self._require_allowed(origin)
        return origin

    def _worktree_path(
        self, workspace: WorkspaceRef, *, must_exist: bool = True
    ) -> Path:
        self._require_kind(workspace)
        path = Path(workspace.ref).resolve()
        if path.parent != self._worktrees_dir.resolve():
            raise WorkspaceAccessError(
                "The worktree is outside the managed worktrees directory",
                details={"path": str(path)},
            )
        if must_exist and not path.is_dir():
            raise WorkspaceError(
                "The task worktree is missing", details={"path": str(path)}
            )
        return path

    @staticmethod
    def _require_kind(workspace: WorkspaceRef) -> None:
        if workspace.kind != KIND:
            raise WorkspaceError(
                "This provider cannot handle that workspace",
                details={"kind": workspace.kind},
            )

    @staticmethod
    async def _commit_options(cwd: Path) -> list[str]:
        options = ["-c", "commit.gpgsign=false"]
        for key, fallback in FALLBACK_IDENTITY.items():
            configured = await run_git("config", "--get", key, cwd=cwd)
            if not configured.stdout.strip():
                options += ["-c", f"{key}={fallback}"]
        return options

    @staticmethod
    async def _abort_merge(repo: Path, result: GitResult) -> None:
        unmerged = await run_git(
            "diff", "--name-only", "--diff-filter=U", "-z", cwd=repo
        )
        await run_git("merge", "--abort", cwd=repo)
        files = [name for name in unmerged.stdout.split("\0") if name]
        if files:
            raise WorkspaceConflictError(
                "The merge conflicts with the target branch",
                details={"files": ", ".join(files)[:STDERR_CHARS]},
            )
        raise WorkspaceError(
            "The merge failed",
            details={"stderr": result.stderr.strip()[:STDERR_CHARS]},
        )
