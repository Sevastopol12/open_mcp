from urllib.parse import quote

MODELS = "/api/model"
SESSIONS = "/api/session"
EXPERIMENTAL_SESSIONS = "/api/experimental/session"


def _segment(session_id: str) -> str:
    return quote(session_id, safe="")


def session_prompt(session_id: str) -> str:
    return f"{SESSIONS}/{_segment(session_id)}/prompt"


def session_interrupt(session_id: str) -> str:
    return f"{SESSIONS}/{_segment(session_id)}/interrupt"


def session_wait(session_id: str) -> str:
    return f"{EXPERIMENTAL_SESSIONS}/{_segment(session_id)}/wait"
