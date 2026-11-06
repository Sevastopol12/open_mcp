from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from open_mcp.lifespan import build_app, create_lifespan
from open_mcp.settings import Settings
from open_mcp.tools.handlers import TaskTools
from open_mcp.tools.instructions import INSTRUCTIONS
from open_mcp.tools.registry import register_tools


def create_server(settings: Settings) -> FastMCP:
    wired = build_app(settings)
    mcp = FastMCP(
        "open-mcp", instructions=INSTRUCTIONS, lifespan=create_lifespan(wired)
    )
    register_tools(mcp, TaskTools(wired.tasks, wired.runtime))
    return mcp


def cors_middleware(settings: Settings) -> list[Middleware]:
    if not settings.cors_allow_origins:
        return []
    return [
        Middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allow_origins),
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    ]


def main() -> None:
    settings = Settings.from_env()
    create_server(settings).run(
        transport="http",
        host=settings.server_host,
        port=settings.server_port,
        middleware=cors_middleware(settings),
    )


if __name__ == "__main__":
    main()
