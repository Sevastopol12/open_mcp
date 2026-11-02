from urllib.parse import quote

MODELS = "/api/model"
SKILLS = "/api/skill"
SESSIONS = "/api/session"
EXPERIMENTAL_SESSIONS = "/api/experimental/session"
ACTIVE_SESSIONS = "/api/session/active"


def _segment(session_id: str) -> str:
    return quote(session_id, safe="")


def session_prompt(session_id: str) -> str:
    return f"{SESSIONS}/{_segment(session_id)}/prompt"


def session_interrupt(session_id: str) -> str:
    return f"{SESSIONS}/{_segment(session_id)}/interrupt"


def session_wait(session_id: str) -> str:
    return f"{EXPERIMENTAL_SESSIONS}/{_segment(session_id)}/wait"


def session_create() -> str:
    return SESSIONS


def session_get(session_id: str) -> str:
    return f"{SESSIONS}/{_segment(session_id)}"


def session_permissions(session_id: str) -> str:
    return f"{SESSIONS}/{_segment(session_id)}/permission"


def session_permission_reply(session_id: str, request_id: str) -> str:
    return f"{session_permissions(session_id)}/{_segment(request_id)}/reply"


def session_log(session_id: str) -> str:
    return f"{EXPERIMENTAL_SESSIONS}/{_segment(session_id)}/log"
