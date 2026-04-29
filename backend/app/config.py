"""
Application configuration loaded from environment variables.

All settings are read once at startup; the resulting object is imported
across the app via `from app.config import settings`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the OCR backend."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://ocr:ocr@db:5432/ocr",
        description="SQLAlchemy DSN (psycopg v3 driver).",
    )

    # --- OCR ---
    OCR_ENGINE: str = Field(default="tesseract")
    OCR_LANGUAGES: str = Field(
        default="spa+eng",
        description="Tesseract language codes joined by '+'.",
    )

    # --- Storage / uploads ---
    STORAGE_PATH: str = Field(default="/storage")
    MAX_UPLOAD_MB: int = Field(default=20, ge=1, le=200)

    # --- CORS ---
    CORS_ORIGINS: str = Field(default="http://localhost:8080")

    # --- Concurrency ---
    MAX_CONCURRENT_JOBS: int | None = Field(
        default=None,
        description="Override the auto-derived semaphore size.",
    )

    # --- Logging ---
    LOG_LEVEL: str = Field(default="INFO")

    # --- Feature flags ---
    STORE_PAGES: bool = Field(default=False)

    # --- Derived helpers ---
    @field_validator("OCR_ENGINE")
    @classmethod
    def _normalize_engine(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_PATH)

    @property
    def originals_dir(self) -> Path:
        return self.storage_path / "originals"

    @property
    def exports_dir(self) -> Path:
        return self.storage_path / "exports"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def effective_concurrency(self) -> int:
        if self.MAX_CONCURRENT_JOBS and self.MAX_CONCURRENT_JOBS > 0:
            return self.MAX_CONCURRENT_JOBS
        cpu = os.cpu_count() or 2
        return max(1, min(2, cpu - 1))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
