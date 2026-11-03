import asyncio
from collections.abc import Mapping
from typing import Any, Self

import httpx2

from open_mcp.contracts.errors import (
    RuntimeAuthError,
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeResponseError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
)
from open_mcp.settings import Settings


class OpencodeClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._http = httpx2.AsyncClient(
            base_url=settings.opencode_base_url,
            auth=self._build_auth(settings),
            timeout=self._timeout(settings.request_timeout_seconds),
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        read_timeout_seconds: float | None = None,
    ) -> Any:
        options: dict[str, Any] = {"params": params, "json": json}
        if read_timeout_seconds is not None:
            options["timeout"] = self._timeout(read_timeout_seconds)

        attempt = 0
        while True:
            try:
                response = await self._http.request(method, path, **options)
            except (httpx2.ConnectError, httpx2.ConnectTimeout) as exc:
                if attempt >= self._settings.connect_retries:
                    raise self._unavailable(
                        "Could not connect to the opencode server", method, path
                    ) from exc

                attempt += 1
                await asyncio.sleep(
                    self._settings.retry_backoff_seconds * 2 ** (attempt - 1)
                )
                continue
            except httpx2.TimeoutException as exc:
                raise RuntimeTimeoutError(
                    "The opencode server timed out",
                    details={"method": method, "path": path},
                ) from exc
            except httpx2.TransportError as exc:
                raise self._unavailable(
                    "The opencode server connection failed", method, path
                ) from exc
            return self._parse(method, path, response)

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, **kwargs)

    async def stream_sse(self, path: str, *, params: Mapping[str, Any] | None = None):
        try:
            async with self._http.stream("GET", path, params=params) as response:
                if not 200 <= response.status_code < 300:
                    await response.aread()
                    self._parse("GET", path, response)
                event: dict[str, str] = {}
                async for line in response.aiter_lines():
                    if not line:
                        if "data" in event:
                            yield event
                        event = {}
                        continue
                    if line.startswith(":"):
                        continue
                    key, separator, value = line.partition(":")
                    if separator:
                        event[key] = value.lstrip()
        except httpx2.TimeoutException as exc:
            raise RuntimeTimeoutError(
                "The opencode server timed out",
                details={"method": "GET", "path": path},
            ) from exc
        except httpx2.TransportError as exc:
            raise self._unavailable(
                "The opencode server connection failed", "GET", path
            ) from exc

    def _timeout(self, read_seconds: float) -> httpx2.Timeout:
        return httpx2.Timeout(
            read_seconds, connect=self._settings.connect_timeout_seconds
        )

    @staticmethod
    def _build_auth(settings: Settings) -> httpx2.BasicAuth | None:
        if settings.opencode_auth_id is None or settings.opencode_auth_secret is None:
            return None
        return httpx2.BasicAuth(
            settings.opencode_auth_id,
            settings.opencode_auth_secret.get_secret_value(),
        )

    @staticmethod
    def _unavailable(message: str, method: str, path: str) -> RuntimeUnavailableError:
        return RuntimeUnavailableError(
            message, details={"method": method, "path": path}
        )

    @staticmethod
    def _parse(method: str, path: str, response: httpx2.Response) -> Any:
        status = response.status_code
        details = {"method": method, "path": path, "status": str(status)}
        if 200 <= status < 300:
            if status == 204 or not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeResponseError(
                    "The opencode server returned a body that is not valid JSON",
                    details=details,
                ) from exc

        details["body"] = response.text
        if status in (401, 403):
            raise RuntimeAuthError(
                "The opencode server rejected the credentials", details=details
            )
        if status == 404:
            raise RuntimeNotFoundError(
                "The opencode resource was not found", details=details
            )
        if status == 409:
            raise RuntimeConflictError(
                "The opencode server reported a conflict", details=details
            )
        if status >= 500:
            raise RuntimeUnavailableError(
                "The opencode server is unavailable", details=details
            )
        raise RuntimeResponseError(
            "The opencode server rejected the request", details=details
        )
