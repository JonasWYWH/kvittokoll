"""Importprofiler för CSV.

En profil beskriver hur just den bankens export ser ut: avgränsare, kodning,
datumformat, decimaltecken och vilka kolumner som betyder vad.

Kolumnmappningen tar antingen ett kolumnnamn (``"Belopp"``) eller en mall med
platshållare (``"{Produkt} {Clnr}-{Kontonr}"``). Mallen finns för att
verkligheten sällan lägger ett fält i exakt en kolumn — Swedbank delar upp
kontot i clearingnummer, kontonummer och produktnamn.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")

FIELDS = (
    "date",
    "description",
    "type",
    "amount",
    "balance",
    "currency",
    "account",
    "transaction_id",
)

DEFAULT_PROFILE: Dict[str, Any] = {
    "name": "Namnlös profil",
    "delimiter": ",",
    "encoding": None,
    "skip_rows": 0,
    "date_format": "%Y-%m-%d",
    "decimal_separator": ".",
    "thousands_separator": "",
    "quotechar": '"',
    "columns": {field: None for field in FIELDS},
}


class Profile:
    def __init__(self, data: Dict[str, Any], profile_id: str = "") -> None:
        merged = dict(DEFAULT_PROFILE)
        merged.update({k: v for k, v in data.items() if k != "columns"})
        columns = dict(DEFAULT_PROFILE["columns"])
        columns.update(data.get("columns") or {})
        merged["columns"] = columns

        self.id = profile_id or data.get("id") or ""
        self.name = merged["name"]
        self.delimiter = merged["delimiter"] or ","
        self.encoding = merged["encoding"]
        self.skip_rows = int(merged["skip_rows"] or 0)
        self.date_format = merged["date_format"] or "%Y-%m-%d"
        self.decimal_separator = merged["decimal_separator"]
        self.thousands_separator = merged["thousands_separator"] or ""
        self.quotechar = merged["quotechar"] or '"'
        self.columns = columns
        self.note = data.get("note", "")

    def column(self, field: str) -> Optional[str]:
        return self.columns.get(field)

    def value(self, field: str, row: Dict[str, str]) -> Optional[str]:
        """Hämta ett fälts värde ur en CSV-rad, via kolumnnamn eller mall."""
        spec = self.columns.get(field)
        if not spec:
            return None
        if "{" in spec:
            def replace(match):
                return (row.get(match.group(1)) or "").strip()

            return _PLACEHOLDER.sub(replace, spec).strip()
        if spec not in row:
            return None
        value = row.get(spec)
        return value.strip() if isinstance(value, str) else value

    def required_columns(self) -> List[str]:
        """Kolumnnamn som måste finnas i filen för att profilen ska passa."""
        needed = []
        for field in ("date", "description", "amount"):
            spec = self.columns.get(field)
            if not spec:
                continue
            if "{" in spec:
                needed.extend(_PLACEHOLDER.findall(spec))
            else:
                needed.append(spec)
        return needed

    def missing_columns(self, header: List[str]) -> List[str]:
        present = set(header or [])
        return [name for name in self.required_columns() if name not in present]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "skip_rows": self.skip_rows,
            "date_format": self.date_format,
            "decimal_separator": self.decimal_separator,
            "thousands_separator": self.thousands_separator,
            "quotechar": self.quotechar,
            "columns": self.columns,
            "note": self.note,
        }


def load_profiles(profiles_dir) -> List[Profile]:
    directory = Path(profiles_dir)
    if not directory.exists():
        return []
    profiles = []
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            continue
        profiles.append(Profile(data, profile_id=path.stem))
    return profiles


def find_profile(profiles: List[Profile], profile_id: str) -> Optional[Profile]:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    return None


def save_profile(profiles_dir, profile: Profile) -> Path:
    from ..storage import write_json_atomic

    directory = Path(profiles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "{}.json".format(profile.id)
    write_json_atomic(path, profile.to_dict())
    return path
