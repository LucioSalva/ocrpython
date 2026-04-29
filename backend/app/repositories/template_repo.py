"""Template repository."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.template import Template


class TemplateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[Template]:
        return list(self.db.execute(select(Template).order_by(Template.id)).scalars())

    def get_by_code(self, code: str) -> Template | None:
        return self.db.execute(
            select(Template).where(Template.code == code)
        ).scalar_one_or_none()

    def get_by_id(self, template_id: int) -> Template | None:
        return self.db.get(Template, template_id)
