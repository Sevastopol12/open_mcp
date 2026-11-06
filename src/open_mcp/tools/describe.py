import inspect
from collections.abc import Awaitable, Callable

ATTRIBUTE = "tool_description"

type Handler = Callable[..., Awaitable[object]]


def describe[F: Callable[..., object]](text: str) -> Callable[[F], F]:
    def mark(function: F) -> F:
        setattr(function, ATTRIBUTE, text)
        return function

    return mark


def description_of(function: Callable[..., object]) -> str | None:
    value = getattr(function, ATTRIBUTE, None)
    return value if isinstance(value, str) else None


def discover(owner: object) -> dict[str, tuple[Handler, str]]:
    found: dict[str, tuple[Handler, str]] = {}
    for name, method in inspect.getmembers(owner, predicate=inspect.ismethod):
        description = description_of(method)
        if description is not None:
            found[name] = (method, description)
    return found
