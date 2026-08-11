"""CSV-import enligt profil."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from ..normalize import ParseError, parse_amount, parse_date
from . import FORMAT_CSV, ImportError_, ImportResult, RowError
from .profiles import Profile

# Fallbackkedjan från §6.2. iso-8859-1 sist eftersom den aldrig misslyckas och
# därför skulle dölja alla andra kandidater om den provades tidigare.
ENCODING_FALLBACKS = ("utf-8-sig", "cp1252", "iso-8859-1")


def decode(data: bytes, encoding: Optional[str] = None) -> Tuple[str, str]:
    """Avkoda filen. Returnerar ``(text, använd_kodning)``."""
    candidates = []
    if encoding:
        candidates.append(encoding)
    candidates.extend(e for e in ENCODING_FALLBACKS if e != encoding)
    for candidate in candidates:
        try:
            return data.decode(candidate), candidate
        except (UnicodeDecodeError, LookupError):
            continue
    raise ImportError_("Filens teckenkodning gick inte att tolka.")


def sniff_delimiter(sample: str, default: str = ",") -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return default


def read_header(data: bytes, profile: Profile) -> Tuple[List[str], str]:
    """Läs kolumnrubrikerna utan att tolka resten av filen."""
    text, encoding = decode(data, profile.encoding)
    lines = text.splitlines()
    if len(lines) <= profile.skip_rows:
        return [], encoding
    reader = csv.reader(
        io.StringIO("\n".join(lines[profile.skip_rows : profile.skip_rows + 1])),
        delimiter=profile.delimiter,
        quotechar=profile.quotechar,
    )
    for row in reader:
        return [cell.strip() for cell in row], encoding
    return [], encoding


def parse(data: bytes, profile: Profile) -> ImportResult:
    """Tolka en CSV-fil enligt profilen.

    Rader som inte går att tolka samlas i ``errors`` med radnummer och orsak.
    De kastas aldrig tyst.
    """
    text, encoding = decode(data, profile.encoding)
    lines = text.splitlines()
    if len(lines) <= profile.skip_rows:
        raise ImportError_("Filen innehåller inga rader efter skip_rows.")

    body = "\n".join(lines[profile.skip_rows :])
    reader = csv.DictReader(
        io.StringIO(body), delimiter=profile.delimiter, quotechar=profile.quotechar
    )
    header = [name.strip() for name in (reader.fieldnames or [])]
    reader.fieldnames = header

    missing = profile.missing_columns(header)
    if missing:
        raise ImportError_(
            "Profilen '{}' passar inte filen. Saknade kolumner: {}. Filens kolumner: {}.".format(
                profile.name, ", ".join(missing), ", ".join(header) or "(inga)"
            )
        )

    result = ImportResult(format=FORMAT_CSV, profile_id=profile.id, encoding=encoding)
    # Radnumret som visas ska peka i originalfilen: skippade rader + rubrikrad.
    offset = profile.skip_rows + 1

    for index, raw_row in enumerate(reader, start=1):
        line_number = offset + index
        raw_row = {k: v for k, v in raw_row.items() if k is not None}
        if not any((value or "").strip() for value in raw_row.values()):
            continue
        try:
            result.rows.append(_build_row(raw_row, profile))
        except ParseError as error:
            result.errors.append(
                RowError(line=line_number, reason=str(error), raw=_preview(raw_row))
            )
        except Exception as error:  # oväntat men ska aldrig stoppa importen
            result.errors.append(
                RowError(
                    line=line_number,
                    reason="oväntat fel: {}".format(error),
                    raw=_preview(raw_row),
                )
            )
    return result


def _build_row(raw_row: Dict[str, str], profile: Profile) -> Dict[str, Any]:
    date = parse_date(profile.value("date", raw_row), profile.date_format)
    amount = parse_amount(
        profile.value("amount", raw_row),
        profile.decimal_separator,
        profile.thousands_separator,
    )
    balance = None
    raw_balance = profile.value("balance", raw_row)
    if raw_balance:
        try:
            balance = parse_amount(
                raw_balance, profile.decimal_separator, profile.thousands_separator
            )
        except ParseError:
            balance = None  # saldo är trevligt men inte nödvändigt

    return {
        "date": date,
        "amount": amount,
        "currency": (profile.value("currency", raw_row) or "SEK").upper(),
        "description": profile.value("description", raw_row) or "",
        "transaction_type": profile.value("type", raw_row) or "",
        "account": profile.value("account", raw_row) or "",
        "balance": balance,
        "bank_id": profile.value("transaction_id", raw_row) or "",
    }


def _preview(raw_row: Dict[str, str], limit: int = 160) -> str:
    text = " | ".join("{}".format(v).strip() for v in raw_row.values() if v)
    return text[:limit]
