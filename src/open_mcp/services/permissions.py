from pathlib import Path

from open_mcp.contracts.runtime import PermissionRequest
from open_mcp.contracts.task import PermissionDecision, WorkspaceRef


class PermissionGate:
    async def decide(
        self, workspace: WorkspaceRef, request: PermissionRequest
    ) -> PermissionDecision:
        root = Path(workspace.ref).resolve()
        if not request.targets:
            return PermissionDecision(
                allow=False, reason="request has no scoped targets"
            )
        for target in request.targets:
            path = Path(target)
            if not path.is_absolute():
                path = root / path
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                return PermissionDecision(
                    allow=False, reason=f"target is outside task workspace: {target}"
                )
        return PermissionDecision(
            allow=True, reason="all targets are inside task workspace"
        )
