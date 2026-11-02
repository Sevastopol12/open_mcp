from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str
    prompt: str
    timeout: int = 60
    model_id: str | None
    provider_id: str | None
