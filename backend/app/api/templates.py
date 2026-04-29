"""Template listing endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.template_repo import TemplateRepository
from app.schemas.template import TemplateOut

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)) -> list[TemplateOut]:
    repo = TemplateRepository(db)
    return [TemplateOut.model_validate(t) for t in repo.list_all()]
