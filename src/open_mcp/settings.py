import os
from pathlib import Path
from typing import Annotated, Self

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from open_mcp.contracts.errors import ConfigurationError


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    opencode_base_url: str
    opencode_auth_id: str | None = None
    opencode_auth_secret: SecretStr | None = None
    context_dir: Path = Path("context")
    server_host: Annotated[str, Field(min_length=1)]
    server_port: Annotated[int, Field(ge=1, le=65535)]
    cors_allow_origins: tuple[str, ...] = ()
    workspace_roots: tuple[Path, ...] = ()
    permission_poll_seconds: Annotated[float, Field(gt=0)] = 0.5
    max_parallel_tasks: Annotated[int, Field(ge=1, le=32)] = 3
    connect_timeout_seconds: Annotated[float, Field(gt=0)] = 5.0
    request_timeout_seconds: Annotated[float, Field(gt=0)] = 60.0
    wait_bound_seconds: Annotated[float, Field(gt=0)] = 30.0
    connect_retries: Annotated[int, Field(ge=0, le=5)] = 2
    retry_backoff_seconds: Annotated[float, Field(ge=0)] = 0.2

    @field_validator("workspace_roots", mode="before")
    @classmethod
    def _split_roots(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part for part in value.split(os.pathsep) if part.strip())
        return value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("opencode_base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return cleaned

    @model_validator(mode="after")
    def _auth_is_complete(self) -> Self:
        if (self.opencode_auth_id is None) != (self.opencode_auth_secret is None):
            raise ValueError(
                "opencode_auth_id and opencode_auth_secret must be set together"
            )
        return self

    @classmethod
    def from_env(cls) -> Self:
        load_dotenv()
        values = {name: os.getenv(name.upper()) for name in cls.model_fields}
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            problems = {
                ".".join(str(part) for part in error["loc"]) or "settings": error["msg"]
                for error in exc.errors()
            }
            raise ConfigurationError("Invalid configuration", details=problems) from exc
