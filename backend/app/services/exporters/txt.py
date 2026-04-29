"""TXT export."""
from __future__ import annotations

from pathlib import Path


def export_txt(text: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text or "", encoding="utf-8")
    return output_path
