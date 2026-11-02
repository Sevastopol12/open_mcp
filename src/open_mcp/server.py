from fastmcp import FastMCP

mcp = FastMCP("open-mcp")


def main() -> None:
    mcp.run(transport="http", host="127.0.0.1", port=8000)
