"""Matchning av transaktionstext mot underlagskällor (§4.3).

Mönster matchas som delsträng mot den normaliserade transaktionstexten.
Längre mönster har företräde. Träffar två källor lika långt kopplas raden inte
automatiskt, utan flaggas för manuell koppling.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from .models import Source
from .normalize import normalize_text, now_iso, slugify


def match_source(description: str, sources: Sequence[Source]) -> Tuple[Optional[str], List[str]]:
    """Returnerar ``(source_id, tvetydiga_id)``.

    Vid entydig träff är andra värdet tomt. Vid tvetydig träff är första värdet
    None och andra värdet listan över källor som matchade lika starkt.
    """
    haystack = normalize_text(description)
    if not haystack:
        return None, []

    hits = []  # type: List[Tuple[int, str]]
    for source in sources:
        best = 0
        for pattern in source.normalized_patterns():
            if pattern in haystack and len(pattern) > best:
                best = len(pattern)
        if best:
            hits.append((best, source.id))

    if not hits:
        return None, []
    strongest = max(length for length, _ in hits)
    winners = sorted(source_id for length, source_id in hits if length == strongest)
    if len(winners) > 1:
        return None, winners
    return winners[0], []


def unique_source_id(name: str, existing: Iterable[Source]) -> str:
    """Skapa ett läsbart id som inte krockar med befintliga."""
    base = slugify(name) or "kalla"
    taken = {source.id for source in existing}
    if base not in taken:
        return base
    counter = 2
    while "{}-{}".format(base, counter) in taken:
        counter += 1
    return "{}-{}".format(base, counter)


def new_source(name: str, existing: Sequence[Source], **fields) -> Source:
    source = Source(
        id=unique_source_id(name, existing),
        name=name,
        created_at=now_iso(),
    )
    for key, value in fields.items():
        if hasattr(source, key) and value is not None:
            setattr(source, key, value)
    if not source.filename_tag:
        source.filename_tag = slugify(source.name)
    return source


def suggest_pattern(description: str) -> str:
    """Förslag på match_pattern utifrån en transaktionstext.

    Banker klistrar ofta på ort och referensnummer efter handlarnamnet
    ("ANTHROPIC* CLAUDE SUB SAN FRANCISCO"). Förslaget behåller hela texten —
    användaren får korta ner den — men normaliserad, så att den matchar.
    """
    return normalize_text(description)
