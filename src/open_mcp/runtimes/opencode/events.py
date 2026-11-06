from dataclasses import dataclass

from pydantic import JsonValue

from open_mcp.contracts.task import TaskEvent


@dataclass(frozen=True)
class Event:
    TEXT_ENDED = "session.text.ended"
    EXECUTION_SUCCEEDED = "session.execution.succeeded"
    EXECUTION_FAILED = "session.execution.failed"
    EXECUTION_INTERRUPTED = "session.execution.interrupted"

    ASSISTANT_MESSAGE = "assistant.message"
    SESSION_IDLE = "session.idle"
    SESSION_FAILED = "session.failed"
    SESSION_INTERRUPTED = "session.interrupted"

    TERMINAL_KINDS = frozenset({SESSION_IDLE, SESSION_FAILED, SESSION_INTERRUPTED})



def event_sequence(frame: dict[str, JsonValue]) -> int | None:
    durable = frame.get("durable")
    if not isinstance(durable, dict):
        return None
    seq = durable.get("seq")
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else None


def normalize(kind: str, frame: dict[str, JsonValue]) -> TaskEvent:
    payload = frame.get("data")
    body: dict[str, JsonValue] = payload if isinstance(payload, dict) else {}
    if kind == Event.TEXT_ENDED:
        text = body.get("text")
        return TaskEvent(
            kind=Event.ASSISTANT_MESSAGE,
            data={"text": text if isinstance(text, str) else "", "source": kind},
        )
    if kind == Event.EXECUTION_SUCCEEDED:
        return TaskEvent(kind=Event.SESSION_IDLE, data={"source": kind})
    if kind == Event.EXECUTION_FAILED:
        return TaskEvent(
            kind=Event.SESSION_FAILED, data={"source": kind, "error": body.get("error")}
        )
    if kind == Event.EXECUTION_INTERRUPTED:
        return TaskEvent(
            kind=Event.SESSION_INTERRUPTED,
            data={"source": kind, "reason": body.get("reason")},
        )
    return TaskEvent(kind=kind, data=frame)
