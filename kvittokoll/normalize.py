"""Normalisering av text, belopp och datum.

Allt som handlar om att göra bankernas olika stavningar jämförbara samlas här,
så att dubblettnyckeln och källmatchningen använder exakt samma regler.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

_WHITESPACE = re.compile(r"\s+")
_NON_KEY_CHARS = re.compile(r"[^A-Z0-9 ]")
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")

# Blanksteg som banker gärna använder i tusentalsavgränsare.
_SPACE_LIKE = "    "


class ParseError(ValueError):
    """Ett fält kunde inte tolkas. Meddelandet visas för användaren."""


def strip_diacritics(text: str) -> str:
    """Å/Ä→A, Ö→O, É→E. Behåller övriga tecken."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(text) -> str:
    """Versaler, borttagna specialtecken, kollapsade mellanslag.

    Används både för dubblettnyckeln och för källmatchningen. Att båda kör
    samma normalisering är poängen: mönstret "GOOGLE *WORKSPACE" ska träffa
    banktexten "Google Workspace_ab Dublin" utan att användaren behöver
    gissa hur just den banken skriver skiljetecken.
    """
    if not text:
        return ""
    result = strip_diacritics(str(text)).upper()
    result = _NON_KEY_CHARS.sub(" ", result)
    return _WHITESPACE.sub(" ", result).strip()


def slugify(text, max_length: int = 40) -> str:
    """Gemener, bindestreck, inga å/ä/ö. För filnamn och käll-id."""
    result = _NON_SLUG_CHARS.sub("-", strip_diacritics(str(text or "")).lower())
    result = result.strip("-")
    if max_length and len(result) > max_length:
        result = result[:max_length]
    return result.strip("-")


def format_amount(amount: float) -> str:
    """Kanoniskt beloppsformat för nycklar och jämförelser: -1256.09"""
    text = "{:.2f}".format(round(float(amount) + 0.0, 2))
    return "0.00" if text == "-0.00" else text


def parse_amount(raw, decimal_separator: str = ".", thousands_separator: str = "") -> float:
    """Tolkar ett belopp enligt profilens separatorer.

    Hanterar de tre skrivsätten för negativa tal som förekommer i praktiken:
    ledande minus, efterställt minus (``123,45-``) och parenteser (``(123,45)``).
    """
    if raw is None:
        raise ParseError("belopp saknas")
    text = str(raw).strip()
    for space in _SPACE_LIKE:
        text = text.replace(space, " ")
    if not text:
        raise ParseError("belopp saknas")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    if text.endswith("-"):
        negative = True
        text = text[:-1].strip()
    if text.startswith("-"):
        negative = True
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()

    if thousands_separator:
        text = text.replace(thousands_separator, "")
    # Blanksteg är alltid tusentalsavgränsare i ett belopp, oavsett profil.
    text = text.replace(" ", "")
    if decimal_separator and decimal_separator != ".":
        text = text.replace(decimal_separator, ".")

    if not re.fullmatch(r"\d*\.?\d*", text) or not text.strip("."):
        raise ParseError("otolkbart belopp: {!r}".format(raw))

    value = float(text)
    return -value if negative else value


def parse_date(raw, date_format: str = "%Y-%m-%d") -> str:
    """Tolkar ett datum och returnerar det som ISO-sträng."""
    if raw is None or str(raw).strip() == "":
        raise ParseError("datum saknas")
    text = str(raw).strip()
    try:
        return datetime.strptime(text, date_format).date().isoformat()
    except ValueError:
        pass
    # Fallback: ISO-datum accepteras alltid, även om profilen säger annat.
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ParseError(
            "otolkbart datum: {!r} (förväntade formatet {})".format(raw, date_format)
        )


def now_iso() -> str:
    """Lokal tid med tidszonsoffset, sekundupplösning."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def month_of(iso_date: str) -> str:
    """'2026-08-11' -> '2026-08'"""
    return iso_date[:7]
