from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import FastMCP

from open_mcp.runtimes.base import RuntimeAdapter
from open_mcp.runtimes.opencode import OpencodeClient, OpencodeRuntime
from open_mcp.services import TaskService
from open_mcp.settings import Settings
from open_mcp.store import FileTaskStore
from open_mcp.workspaces import LocalGitWorktree


@dataclass(frozen=True)
class App:
    settings: Settings
    runtime: RuntimeAdapter
    tasks: TaskService
    client: OpencodeClient | None = None


def build_app(settings: Settings) -> App:
    client = OpencodeClient(settings)
    runtime = OpencodeRuntime(client)
    store = FileTaskStore(settings.context_dir)
    workspace = LocalGitWorktree(
        settings.context_dir / "worktrees", settings.workspace_roots
    )
    tasks = TaskService(store, runtime, workspace, settings)
    return App(settings=settings, runtime=runtime, tasks=tasks, client=client)


def create_lifespan(app: App):
    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[App]:
        await app.tasks.recover()
        try:
            yield app
        finally:
            await app.tasks.aclose()
            if app.client is not None:
                await app.client.aclose()

    return lifespan
