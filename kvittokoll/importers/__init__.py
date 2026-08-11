"""Import av banktransaktioner.

Två spår: ISO 20022 camt.053 (XML, profilfritt) och CSV (kräver profil).
Båda returnerar samma ``ImportResult`` så att resten av verktyget slipper veta
vilket format filen hade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

FORMAT_CAMT053 = "camt053"
FORMAT_CSV = "csv"


@dataclass
class RowError:
    """En rad som inte kunde tolkas. Kastas aldrig tyst (§6.4)."""

    line: int
    reason: str
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"line": self.line, "reason": self.reason, "raw": self.raw}


@dataclass
class ImportResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[RowError] = field(default_factory=list)
    format: str = ""
    profile_id: Optional[str] = None
    encoding: Optional[str] = None


class ImportError_(Exception):
    """Filen gick inte att läsa alls — fel format, fel profil, trasig XML."""


def detect_format(filename: str, data: bytes) -> str:
    """Gissa format utifrån filnamn och innehåll."""
    head = data[:4096].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<"):
        return FORMAT_CAMT053
    if filename.lower().endswith(".xml"):
        return FORMAT_CAMT053
    return FORMAT_CSV
