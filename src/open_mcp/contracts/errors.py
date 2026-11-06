from collections.abc import Mapping


class OpenMcpError(Exception):
    code = "open_mcp_error"

    def __init__(
        self, message: str, *, details: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})

    def to_payload(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ConfigurationError(OpenMcpError):
    code = "configuration_error"


class RuntimeUnavailableError(OpenMcpError):
    code = "runtime_unavailable"


class RuntimeAuthError(OpenMcpError):
    code = "runtime_auth_failed"


class RuntimeNotFoundError(OpenMcpError):
    code = "runtime_not_found"


class RuntimeConflictError(OpenMcpError):
    code = "runtime_conflict"


class RuntimeResponseError(OpenMcpError):
    code = "runtime_bad_response"


class InvalidRequestError(OpenMcpError):
    code = "invalid_request"


class ModelNotAvailableError(OpenMcpError):
    code = "model_not_available"


class TaskNotFoundError(OpenMcpError):
    code = "task_not_found"


class InvalidTransitionError(OpenMcpError):
    code = "invalid_transition"


class TaskStoreError(OpenMcpError):
    code = "task_store_error"


class RuntimeTimeoutError(RuntimeUnavailableError):
    code = "runtime_timeout"


class RuntimeCapabilityError(OpenMcpError):
    code = "runtime_unsupported"


class WorkspaceError(OpenMcpError):
    code = "workspace_error"


class WorkspaceAccessError(WorkspaceError):
    code = "workspace_access_denied"


class WorkspaceDirtyError(WorkspaceError):
    code = "workspace_dirty"


class WorkspaceStaleBaseError(WorkspaceError):
    code = "workspace_stale_base"


class WorkspaceConflictError(WorkspaceError):
    code = "workspace_conflict"
