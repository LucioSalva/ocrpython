"""
CFDI 4.0 (Mexican electronic invoice) XML parser.

Detects whether an XML root is `cfdi:Comprobante` and extracts the
canonical fields: UUID (from TFD complement), totals, RFC issuer/receiver,
date, serie/folio. The XML is stored verbatim for traceability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from app.logging_config import get_logger

logger = get_logger(__name__)

NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "cfdi3": "http://www.sat.gob.mx/cfd/3",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}

# Hardened parser: no entity resolution (XXE), no network (SSRF),
# no huge tree expansion (billion laughs), no DTD loading.
_SAFE_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=False,
    load_dtd=False,
    dtd_validation=False,
)


class CfdiParseError(Exception):
    """Raised when an XML cannot be parsed as a valid CFDI."""


@dataclass(slots=True)
class CfdiData:
    uuid_sat: str
    rfc_emisor: str | None = None
    rfc_receptor: str | None = None
    total: Decimal | None = None
    subtotal: Decimal | None = None
    total_iva: Decimal | None = None
    fecha: datetime | None = None
    serie: str | None = None
    folio: str | None = None
    raw_xml: str = ""
    text_summary: str = ""
    extra_fields: dict[str, str] = field(default_factory=dict)


def _parse_decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # CFDI 4.0 uses local time without TZ: "yyyy-mm-ddThh:mm:ss"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def is_cfdi_xml(file_path: Path) -> bool:
    """Best-effort detection: parse and check root tag."""
    try:
        tree = etree.parse(str(file_path), parser=_SAFE_PARSER)
    except (etree.XMLSyntaxError, OSError):
        return False
    root = tree.getroot()
    tag = etree.QName(root.tag).localname
    ns = etree.QName(root.tag).namespace
    return tag == "Comprobante" and ns in {NS["cfdi"], NS["cfdi3"]}


def parse_cfdi(file_path: Path) -> CfdiData:
    """Parse a CFDI 4.0 XML file and return structured data."""
    try:
        tree = etree.parse(str(file_path), parser=_SAFE_PARSER)
    except (etree.XMLSyntaxError, OSError) as exc:
        raise CfdiParseError(f"Invalid XML: {exc}") from exc

    root = tree.getroot()
    raw_xml = etree.tostring(tree, encoding="unicode")

    if etree.QName(root.tag).localname != "Comprobante":
        raise CfdiParseError("Root element is not cfdi:Comprobante")

    # Locate Emisor / Receptor / Complemento via local-name() to be tolerant
    # to CFDI 3.3 vs 4.0 namespaces.
    def find(xpath: str) -> etree._Element | None:
        result = root.xpath(xpath, namespaces=NS)
        if isinstance(result, list) and result:
            return result[0]
        return None

    emisor = find(".//*[local-name()='Emisor']")
    receptor = find(".//*[local-name()='Receptor']")
    tfd = find(".//*[local-name()='TimbreFiscalDigital']")

    uuid_sat = tfd.get("UUID") if tfd is not None else None
    if not uuid_sat:
        # Some test CFDIs are not stamped; fall back to a synthetic UUID
        # so we still ingest, but mark error.
        raise CfdiParseError("CFDI missing TimbreFiscalDigital/UUID")

    total = _parse_decimal(root.get("Total"))
    subtotal = _parse_decimal(root.get("SubTotal"))
    fecha = _parse_datetime(root.get("Fecha"))
    serie = root.get("Serie")
    folio = root.get("Folio")
    rfc_emisor = emisor.get("Rfc") if emisor is not None else None
    rfc_receptor = receptor.get("Rfc") if receptor is not None else None

    # IVA: sum of TotalImpuestosTrasladados (CFDI 4.0)
    total_iva: Decimal | None = None
    impuestos = find(".//*[local-name()='Impuestos']")
    if impuestos is not None:
        total_iva = _parse_decimal(impuestos.get("TotalImpuestosTrasladados"))

    name_emisor = emisor.get("Nombre") if emisor is not None else None
    name_receptor = receptor.get("Nombre") if receptor is not None else None

    summary_lines = [
        f"CFDI UUID: {uuid_sat}",
        f"Emisor: {name_emisor or ''} ({rfc_emisor or ''})",
        f"Receptor: {name_receptor or ''} ({rfc_receptor or ''})",
        f"Fecha: {fecha.isoformat() if fecha else ''}",
        f"Serie/Folio: {serie or ''}/{folio or ''}",
        f"SubTotal: {subtotal if subtotal is not None else ''}",
        f"IVA: {total_iva if total_iva is not None else ''}",
        f"Total: {total if total is not None else ''}",
    ]

    logger.info(
        "cfdi_parsed",
        extra={
            "uuid": uuid_sat,
            "rfc_emisor": rfc_emisor,
            "rfc_receptor": rfc_receptor,
            "total": str(total) if total is not None else None,
        },
    )

    return CfdiData(
        uuid_sat=uuid_sat,
        rfc_emisor=rfc_emisor,
        rfc_receptor=rfc_receptor,
        total=total,
        subtotal=subtotal,
        total_iva=total_iva,
        fecha=fecha,
        serie=serie,
        folio=folio,
        raw_xml=raw_xml,
        text_summary="\n".join(summary_lines),
        extra_fields={
            "nombre_emisor": name_emisor or "",
            "nombre_receptor": name_receptor or "",
        },
    )
