"""Request bodies for the local API."""

from pydantic import BaseModel, Field, field_validator


class InstructionIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)

    @field_validator("instruction")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Tell Machaa what to look up.")
        return cleaned
