from typing import Annotated

from pydantic import BaseModel, Field


class SkillInfo(BaseModel):
    id: Annotated[str, Field(description="Skill's identifer")]
    name: Annotated[str, Field(description="Skill name")]
    description: Annotated[str, Field(description="What this skill do")]
    content: Annotated[str, Field(description="Detail about this skill")]
