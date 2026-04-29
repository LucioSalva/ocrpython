"""Template-related Pydantic schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    fields: Any
