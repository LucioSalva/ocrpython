"""
FastAPI shared dependencies.

- `get_db()` — request-scoped SQLAlchemy session (re-exported from app.database).
- `get_semaphore()` — global asyncio.Semaphore that throttles the
  CPU-heavy OCR pipeline. The Semaphore is created on app startup and
  attached to `app.state.semaphore`.
"""
from __future__ import annotations

import asyncio

from fastapi import Request

from app.database import get_db  # re-exported

__all__ = ["get_db", "get_semaphore"]


def get_semaphore(request: Request) -> asyncio.Semaphore:
    sem: asyncio.Semaphore | None = getattr(request.app.state, "semaphore", None)
    if sem is None:  # defensive — should be set in lifespan
        sem = asyncio.Semaphore(2)
        request.app.state.semaphore = sem
    return sem
