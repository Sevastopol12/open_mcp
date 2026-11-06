import json

from open_mcp.contracts import OpenMcpError


def error_text(exc: OpenMcpError) -> str:
    return json.dumps(exc.to_payload(), sort_keys=True)
