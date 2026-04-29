"""
Regex-based field extraction per template.

Templates (3 MVP):
  - texto_libre: no extraction, just raw text.
  - factura_generica: RFC, folio, total, IVA.
  - ine: nombre, CURP, vigencia.

Regex are intentionally conservative; precision > recall for an MVP.
"""
from __future__ import annotations

import re
from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)

# --- Regex catalogue ------------------------------------------------

# Mexican RFC: 12 chars (moral) or 13 chars (fisica). Letters + 6 digits + 3 alphanum homoclave.
RFC_RE = re.compile(
    r"\b([A-ZÑ&]{3,4})[\-\s]?(\d{2})(\d{2})(\d{2})[\-\s]?([A-Z\d]{2})([A0-9])\b",
    re.IGNORECASE,
)

# CURP: 18 chars, letters/digits as per RENAPO spec.
CURP_RE = re.compile(
    r"\b([A-Z][AEIOUX][A-Z]{2})(\d{2})(\d{2})(\d{2})([HM])"
    r"(AS|BC|BS|CC|CL|CM|CS|CH|DF|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|OC|PL|QT|QR|SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE)"
    r"([B-DF-HJ-NP-TV-Z]{3})([A-Z\d])(\d)\b",
    re.IGNORECASE,
)

# Folio: pragmatic — "Folio: ABC-12345" or just numeric/alfanumeric runs after the keyword.
FOLIO_RE = re.compile(
    r"folio(?:\s+fiscal|\s+interno)?\s*[:#\-]?\s*([A-Z0-9\-]{3,40})",
    re.IGNORECASE,
)

# Money: $1,234.56 / 1234.56 / 1234,56 / MXN 1,234.56
MONEY_RE = re.compile(
    r"(?:\$|MXN|MN|USD)?\s*([\d]{1,3}(?:[,\.][\d]{3})*(?:[\.,]\d{2}))",
)

# Vigencia / fechas (INE): "VIGENCIA 2025" / "VIGENCIA 2030" / "Vigencia: 12/2030"
VIGENCIA_RE = re.compile(
    r"vigenci[ae]\s*[:#\-]?\s*((?:0?\d|1[0-2])\s*[\/\-]\s*\d{4}|\d{4})",
    re.IGNORECASE,
)

# Nombre INE — heurística: 3 líneas en mayúsculas tras "NOMBRE".
NOMBRE_INE_RE = re.compile(
    r"NOMBRE\s*[:\n]+\s*([A-ZÁÉÍÓÚÑ ]{3,60})\s*\n\s*([A-ZÁÉÍÓÚÑ ]{3,60})\s*\n\s*([A-ZÁÉÍÓÚÑ ]{3,60})",
)


# --- Helpers --------------------------------------------------------

def _normalize_money(raw: str) -> float | None:
    s = raw.strip().replace(" ", "")
    # If both '.' and ',' present, the right-most is the decimal separator.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Spanish locale: 1.234,56 → already removed dots above; here we have commas only.
        # If exactly one comma followed by 2 digits, treat as decimal separator.
        if re.match(r"^\d+,\d{2}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _find_rfcs(text: str) -> list[str]:
    found: list[str] = []
    for match in RFC_RE.finditer(text):
        rfc = "".join(match.groups()).upper()
        if rfc not in found:
            found.append(rfc)
    return found


def _find_curp(text: str) -> str | None:
    match = CURP_RE.search(text)
    if not match:
        return None
    return "".join(match.groups()).upper()


def _find_folio(text: str) -> str | None:
    match = FOLIO_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _find_total_and_iva(text: str) -> tuple[float | None, float | None]:
    """Locate amounts after 'total' and 'iva' keywords."""
    total_val: float | None = None
    iva_val: float | None = None

    # Look for "Total ... <amount>" within ~40 chars window
    for keyword, setter in (
        (r"total(?:\s+a\s+pagar)?", "total"),
        (r"iva(?:\s+\d+%?)?", "iva"),
    ):
        pattern = re.compile(
            rf"{keyword}\s*[:#\-]?\s*\$?\s*([\d]{{1,3}}(?:[,\.][\d]{{3}})*(?:[\.,]\d{{2}}))",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            value = _normalize_money(m.group(1))
            if value is not None:
                if setter == "total" and total_val is None:
                    total_val = value
                elif setter == "iva" and iva_val is None:
                    iva_val = value

    # Fallback: pick the largest money amount as Total
    if total_val is None:
        amounts = [_normalize_money(m.group(1)) for m in MONEY_RE.finditer(text)]
        amounts = [a for a in amounts if a is not None and a > 0]
        if amounts:
            total_val = max(amounts)

    return total_val, iva_val


def _find_vigencia(text: str) -> str | None:
    match = VIGENCIA_RE.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _find_nombre_ine(text: str) -> str | None:
    match = NOMBRE_INE_RE.search(text)
    if not match:
        return None
    parts = [p.strip() for p in match.groups()]
    return " ".join(p for p in parts if p)


# --- Public API -----------------------------------------------------

def extract_fields(template_code: str, text: str) -> dict[str, Any]:
    """Apply the template-specific regex pipeline."""
    if not text:
        return {}

    code = (template_code or "").strip().lower()

    if code == "texto_libre":
        return {}

    if code == "factura_generica":
        rfcs = _find_rfcs(text)
        rfc_emisor = rfcs[0] if rfcs else None
        rfc_receptor = rfcs[1] if len(rfcs) > 1 else None
        total, iva = _find_total_and_iva(text)
        folio = _find_folio(text)
        return {
            "rfc_emisor": rfc_emisor,
            "rfc_receptor": rfc_receptor,
            "folio": folio,
            "total": total,
            "iva": iva,
        }

    if code == "ine":
        return {
            "nombre": _find_nombre_ine(text),
            "curp": _find_curp(text),
            "vigencia": _find_vigencia(text),
        }

    logger.warning("template_unknown", extra={"template": code})
    return {}


# --- Template field metadata (used for seeds) ---------------------------

TEMPLATE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "code": "texto_libre",
        "name": "Texto libre",
        "fields": [],
    },
    {
        "code": "factura_generica",
        "name": "Factura genérica",
        "fields": [
            {"key": "rfc_emisor", "label": "RFC emisor", "type": "string"},
            {"key": "rfc_receptor", "label": "RFC receptor", "type": "string"},
            {"key": "folio", "label": "Folio", "type": "string"},
            {"key": "total", "label": "Total", "type": "number"},
            {"key": "iva", "label": "IVA", "type": "number"},
        ],
    },
    {
        "code": "ine",
        "name": "INE",
        "fields": [
            {"key": "nombre", "label": "Nombre", "type": "string"},
            {"key": "curp", "label": "CURP", "type": "string"},
            {"key": "vigencia", "label": "Vigencia", "type": "string"},
        ],
    },
]
