from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

T = TypeVar("T")


class StrictModel(BaseModel):
    """Input models: unknown fields are rejected (422), strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=True)


class UpdateModel(StrictModel):
    """PATCH models: at least one field, and no explicit nulls."""

    @model_validator(mode="after")
    def _require_changes(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"fields cannot be null: {', '.join(nulls)}")
        return self


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
