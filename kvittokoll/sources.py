"""Matchning av transaktionstext mot underlagskällor (§4.3).

Varje mönster har ett läge — ``contains``, ``starts_with`` eller
``ends_with`` — som kompileras till ett reguljärt uttryck. Mönstret och
transaktionstexten normaliseras först på samma sätt (versaler, borttagna
skiljetecken, kollapsade mellanslag), så att ``GOOGLE *WORKSPACE`` träffar
banktexten ``Google Workspace_ab Dublin``, och så att en förankring som
``^HYRA`` faktiskt sitter i början av texten och inte efter ett skiljetecken.

Vid flera träffar vinner det längsta mönstret, enligt kravspecen. Är två
mönster lika långa vinner det förankrade — ``börjar med HYRA`` är mer
specifikt än ``innehåller HYRA``. Är även det lika kopplas raden inte
automatiskt, utan flaggas för manuell koppling.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence, Tuple

from .models import (
    MATCH_CONTAINS,
    MATCH_ENDS_WITH,
    MATCH_MODES,
    MATCH_STARTS_WITH,
    MatchPattern,
    Source,
)
from .normalize import normalize_text, now_iso, slugify

MODE_LABELS = {
    MATCH_CONTAINS: "innehåller",
    MATCH_STARTS_WITH: "börjar med",
    MATCH_ENDS_WITH: "slutar med",
}


@lru_cache(maxsize=1024)
def compile_pattern(pattern: str, mode: str = MATCH_CONTAINS):
    """Kompilera ett mönster till regex. Returnerar None för tomma mönster.

    Mönstret escapas — användaren skriver text, inte reguljära uttryck.
    Läget avgör förankringen.
    """
    text = normalize_text(pattern)
    if not text:
        return None
    expression = re.escape(text)
    if mode == MATCH_STARTS_WITH:
        expression = r"\A" + expression
    elif mode == MATCH_ENDS_WITH:
        expression = expression + r"\Z"
    return re.compile(expression)


def _score(pattern: MatchPattern, haystack: str) -> Optional[Tuple[int, int]]:
    """Hur starkt ett mönster träffar: (längd, förankrat). None = ingen träff."""
    mode = pattern.mode if pattern.mode in MATCH_MODES else MATCH_CONTAINS
    regex = compile_pattern(pattern.pattern, mode)
    if regex is None or not regex.search(haystack):
        return None
    return (len(normalize_text(pattern.pattern)), 0 if mode == MATCH_CONTAINS else 1)


def match_source(description: str, sources: Sequence[Source]) -> Tuple[Optional[str], List[str]]:
    """Returnerar ``(source_id, tvetydiga_id)``.

    Vid entydig träff är andra värdet tomt. Vid tvetydig träff är första värdet
    None och andra värdet listan över källor som matchade lika starkt.
    """
    haystack = normalize_text(description)
    if not haystack:
        return None, []

    hits = []  # type: List[Tuple[Tuple[int, int], str]]
    for source in sources:
        best = None  # type: Optional[Tuple[int, int]]
        for pattern in source.match_patterns:
            score = _score(pattern, haystack)
            if score is not None and (best is None or score > best):
                best = score
        if best is not None:
            hits.append((best, source.id))

    if not hits:
        return None, []
    strongest = max(score for score, _ in hits)
    winners = sorted(source_id for score, source_id in hits if score == strongest)
    if len(winners) > 1:
        return None, winners
    return winners[0], []


def explain_match(description: str, source: Source) -> Optional[str]:
    """Läsbar förklaring till varför en källa matchade. För felsökning."""
    haystack = normalize_text(description)
    best = None
    for pattern in source.match_patterns:
        score = _score(pattern, haystack)
        if score is not None and (best is None or score > best[0]):
            best = (score, pattern)
    if best is None:
        return None
    pattern = best[1]
    return "{} {!r}".format(MODE_LABELS.get(pattern.mode, pattern.mode), pattern.pattern)


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
    source.match_patterns = [MatchPattern.from_any(p) for p in source.match_patterns]
    if not source.filename_tag:
        source.filename_tag = slugify(source.name)
    return source


def suggest_pattern(description: str) -> str:
    """Förslag på mönstertext utifrån en transaktionstext.

    Banker klistrar ofta på ort och referensnummer efter handlarnamnet
    ("ANTHROPIC* CLAUDE SUB SAN FRANCISCO"). Förslaget behåller hela texten —
    användaren kortar ner den och väljer läge — men normaliserad, så att den
    matchar.
    """
    return normalize_text(description)
