"""Conservative text cleaning. Does NOT autocorrect words (official docs)."""
from __future__ import annotations

import re

# Lines that contain only punctuation/symbols (no alphanumeric) get dropped.
_ALNUM_RE = re.compile(r"[A-Za-z0-9À-ſ]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def clean(text: str) -> str:
    if not text:
        return ""
    out_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        # Collapse repeated horizontal whitespace.
        line = _MULTI_SPACE_RE.sub(" ", line)
        if line.strip() == "":
            out_lines.append("")
            continue
        # Drop lines that have NO alphanumeric character (pure symbol noise).
        if not _ALNUM_RE.search(line):
            continue
        out_lines.append(line)
    joined = "\n".join(out_lines)
    # Squash 3+ blank lines into 2.
    joined = _MULTI_BLANK_RE.sub("\n\n", joined)
    return joined.strip()
