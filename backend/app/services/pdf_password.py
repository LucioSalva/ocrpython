"""
Decrypt password-protected PDFs using pikepdf.

Returns the path of an unprotected file written next to the original.
"""
from __future__ import annotations

from pathlib import Path

import pikepdf

from app.logging_config import get_logger

logger = get_logger(__name__)


class PdfPasswordError(Exception):
    """Raised when a PDF cannot be opened with the provided password."""


def decrypt_pdf(encrypted_path: Path, password: str) -> Path:
    """Decrypt `encrypted_path` and return the path of the unlocked copy."""
    target = encrypted_path.with_name(f"{encrypted_path.stem}.decrypted.pdf")
    try:
        with pikepdf.open(encrypted_path, password=password) as pdf:
            pdf.save(target)
    except pikepdf.PasswordError as exc:
        logger.warning("pdf_password_invalid", extra={"path": str(encrypted_path)})
        raise PdfPasswordError("Invalid PDF password") from exc
    except pikepdf.PdfError as exc:
        logger.exception("pdf_decrypt_failed")
        raise PdfPasswordError("Could not decrypt PDF") from exc
    logger.info("pdf_decrypted", extra={"path": str(target)})
    return target
