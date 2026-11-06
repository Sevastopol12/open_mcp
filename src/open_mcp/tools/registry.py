import functools
from collections.abc import Awaitable, Callable

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from open_mcp.contracts import OpenMcpError
from open_mcp.tools.describe import discover
from open_mcp.tools.errors import error_text
from open_mcp.tools.handlers import TaskTools


def guarded[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    @functools.wraps(function)
    async def run(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await function(*args, **kwargs)
        except OpenMcpError as exc:
            raise ToolError(error_text(exc)) from exc

    return run


def register_tools(mcp: FastMCP, tools: TaskTools) -> None:
    for name, (handler, description) in discover(tools).items():
        mcp.tool(name=name, description=description)(guarded(handler))
